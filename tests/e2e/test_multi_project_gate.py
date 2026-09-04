"""The multi-project gate: isolation, failure containment, and survival across a restart.

These are end-to-end properties of the running host rather than route contracts. Two
projects are opened through the real control plane, and every assertion is about what one
project can see of another - or about what survives the process that served them. Task 13
extends this file; the fixtures it needs live in `tests/contract/protocol/multi_fixtures.py`.
"""

from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import httpx
from starlette.testclient import TestClient

from research_harness.domain.base import utc_now
from tests.contract.protocol import multi_fixtures
from tests.contract.protocol.conftest import CLAIM
from tests.contract.protocol.multi_fixtures import (
    GATE_TIMEOUT,
    LEFT,
    LEFT_STATEMENT,
    NOTE_CAPABILITY,
    RIGHT,
    RIGHT_STATEMENT,
    GatedProjects,
    MultiHarness,
    TwoProjects,
    authenticate,
    build_multi_app,
    finish_run,
)

# The same fixtures the contract tests use, bound the same way (see that module's note).
multi_harness = multi_fixtures.multi_harness
multi_client = multi_fixtures.multi_client
authenticated_multi_client = multi_fixtures.authenticated_multi_client
two_projects = multi_fixtures.two_projects
two_projects_client = multi_fixtures.two_projects_client
left_run_id = multi_fixtures.left_run_id
gated_projects = multi_fixtures.gated_projects

BLOCKED_WINDOW = 0.5
"""How long a call that must still be waiting is given to prove it is not waiting."""

CROSS_PROJECT_WINDOW = 2.0
"""How long a write in the other project may take while a first project holds its gate."""

THIRD_PROJECT = "prj_0000000000000003"
"""The id a restarted host hands the next project; the first two are already on disk."""


def third_project_id() -> str:
    """The id factory a restarted host gets, since `prj_...0001` and `...0002` exist."""
    return THIRD_PROJECT


def post_note(client: TestClient, project_id: str, text: str) -> httpx.Response:
    """One accepted-state mutation in one project: the smallest write there is."""
    return client.post(
        f"/api/projects/{project_id}/capabilities/{NOTE_CAPABILITY}", json={"text": text}
    )


def captured_notes(root: Path) -> list[str]:
    """Every note text the workspace journal recorded, in the order it recorded them."""
    lines = (root / "events" / "research.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
    return [event["payload"]["text"] for event in events if event["event"] == "note.captured"]


def test_the_same_object_id_is_resolved_inside_the_selected_project(
    two_projects_client: TestClient,
) -> None:
    left = two_projects_client.get(f"/api/projects/{LEFT}/objects/{CLAIM}").json()
    right = two_projects_client.get(f"/api/projects/{RIGHT}/objects/{CLAIM}").json()
    assert left["object"]["statement"] == LEFT_STATEMENT
    assert right["object"]["statement"] == RIGHT_STATEMENT


def test_a_run_cannot_be_read_through_another_project(
    two_projects_client: TestClient, left_run_id: str
) -> None:
    assert two_projects_client.get(f"/api/projects/{RIGHT}/runs/{left_run_id}").status_code == 404


def test_two_projects_never_share_a_runtime_or_a_mutation_gate(
    two_projects_client: TestClient, two_projects: TwoProjects
) -> None:
    assert two_projects_client.get(f"/api/projects/{LEFT}/health").status_code == 200
    assert two_projects_client.get(f"/api/projects/{RIGHT}/health").status_code == 200
    left, right = (two_projects.harness.pool.get(LEFT), two_projects.harness.pool.get(RIGHT))
    assert left is not right
    assert left.mutation_gate is not right.mutation_gate
    assert left.root != right.root


def test_one_unusable_project_leaves_the_others_and_project_home_working(
    two_projects_client: TestClient, two_projects: TwoProjects, tmp_path: Path
) -> None:
    shutil.move(str(two_projects.left_root), str(tmp_path / "carried-away"))

    assert two_projects_client.get(f"/api/projects/{LEFT}/health").status_code == 422
    assert two_projects_client.get(f"/api/projects/{RIGHT}/health").status_code == 200

    listed = two_projects_client.get("/api/projects").json()["projects"]
    availability = {item["project_id"]: item["availability"] for item in listed}
    assert availability[LEFT] == "unavailable"
    assert availability[RIGHT] == "available"


def test_projects_and_durable_runs_survive_a_restart_of_the_host(
    two_projects: TwoProjects, left_run_id: str
) -> None:
    """A second host over the same data directory shares nothing but the files on disk."""
    before = two_projects.client.get("/api/projects").json()["projects"]
    two_projects.client.close()

    restarted = build_multi_app(two_projects.harness.data_dir)
    assert restarted.manager is not two_projects.harness.manager
    assert restarted.pool is not two_projects.harness.pool

    with TestClient(restarted.app) as client:
        authenticate(client)
        after = client.get("/api/projects").json()["projects"]
        assert [item["project_id"] for item in after] == [item["project_id"] for item in before]
        assert [Path(item["path"]) for item in after] == [Path(item["path"]) for item in before]

        run = client.get(f"/api/projects/{LEFT}/runs/{left_run_id}")
        assert run.status_code == 200
        assert run.json()["status"] == "running"
        claim = client.get(f"/api/projects/{RIGHT}/objects/{CLAIM}").json()
        assert claim["object"]["statement"] == RIGHT_STATEMENT


# -- concurrent writes -------------------------------------------------------


def test_a_write_held_open_in_one_project_never_blocks_a_write_in_another(
    gated_projects: GatedProjects,
) -> None:
    """Two projects, two mutation gates: one researcher's slow write is nobody else's wait."""
    started, release = gated_projects.gates.gate("left-held")
    client = gated_projects.client
    with ThreadPoolExecutor(max_workers=2) as workers:
        left = workers.submit(post_note, client, LEFT, "left-held")
        assert started.wait(timeout=GATE_TIMEOUT), "the held write never reached the gate"

        right = workers.submit(post_note, client, RIGHT, "right-free")
        assert right.result(timeout=CROSS_PROJECT_WINDOW).status_code == 200

        release.set()
        assert left.result(timeout=GATE_TIMEOUT).status_code == 200

    assert captured_notes(gated_projects.left_root) == ["left-held"]
    assert captured_notes(gated_projects.right_root) == ["right-free"]


def test_two_writes_to_the_same_project_are_serialized_by_its_own_gate(
    gated_projects: GatedProjects,
) -> None:
    """One workspace still writes one mutation at a time; the second waits for the first."""
    first_started, first_release = gated_projects.gates.gate("first")
    second_started, second_release = gated_projects.gates.gate("second")
    client = gated_projects.client
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(post_note, client, LEFT, "first")
        assert first_started.wait(timeout=GATE_TIMEOUT)

        second = workers.submit(post_note, client, LEFT, "second")
        assert not second_started.wait(timeout=BLOCKED_WINDOW), (
            "the second write entered the capability while the first still held the gate"
        )

        first_release.set()
        assert first.result(timeout=GATE_TIMEOUT).status_code == 200
        assert second_started.wait(timeout=GATE_TIMEOUT), "the gate was never handed over"
        second_release.set()
        assert second.result(timeout=GATE_TIMEOUT).status_code == 200

    assert captured_notes(gated_projects.left_root) == ["first", "second"]
    assert captured_notes(gated_projects.right_root) == []


# -- idle eviction -----------------------------------------------------------


def test_evicting_an_idle_runtime_changes_nothing_a_client_can_see(
    two_projects_client: TestClient, two_projects: TwoProjects
) -> None:
    """A runtime is a cache: dropping it costs one rebuild and no observable difference."""
    pool = two_projects.harness.pool
    before = two_projects_client.get(f"/api/projects/{LEFT}/objects/{CLAIM}")
    assert before.status_code == 200
    assert pool.status(LEFT).loaded is True

    assert LEFT in pool.evict_idle(utc_now() + timedelta(seconds=1))
    assert pool.status(LEFT).loaded is False

    after = two_projects_client.get(f"/api/projects/{LEFT}/objects/{CLAIM}")
    assert after.status_code == 200
    assert after.json() == before.json()
    assert pool.status(LEFT).loaded is True


def test_a_runtime_serving_an_active_run_is_never_evicted_as_idle(
    two_projects_client: TestClient, two_projects: TwoProjects, left_run_id: str
) -> None:
    assert left_run_id
    assert two_projects_client.get(f"/api/projects/{LEFT}/health").status_code == 200
    assert two_projects_client.get(f"/api/projects/{RIGHT}/health").status_code == 200
    evicted = two_projects.harness.pool.evict_idle(utc_now() + timedelta(seconds=1))
    assert LEFT not in evicted
    assert RIGHT in evicted


# -- restart -----------------------------------------------------------------


def test_a_run_left_behind_by_the_previous_process_still_reports_busy_and_blocks_forget(
    two_projects: TwoProjects, left_run_id: str
) -> None:
    """Run state lives on disk, so a fresh host inherits it - and Forget still refuses."""
    two_projects.client.close()
    restarted = build_multi_app(two_projects.harness.data_dir)
    assert restarted.registry is not two_projects.harness.registry
    assert restarted.manager is not two_projects.harness.manager
    assert restarted.pool is not two_projects.harness.pool

    with TestClient(restarted.app) as client:
        authenticate(client)
        listed = {
            item["project_id"]: item for item in client.get("/api/projects").json()["projects"]
        }
        assert listed[LEFT]["availability"] == "busy"
        assert listed[LEFT]["active_runs"] == 1
        assert listed[RIGHT]["availability"] == "available"
        assert listed[RIGHT]["active_runs"] == 0

        refused = client.delete(f"/api/projects/{LEFT}")
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "project_active_runs"

        finish_run(two_projects.left_root, left_run_id)
        assert (
            client.get(f"/api/projects/{LEFT}/runs/{left_run_id}").json()["status"] == "succeeded"
        )
        assert client.delete(f"/api/projects/{LEFT}").status_code == 204
        assert [item["project_id"] for item in client.get("/api/projects").json()["projects"]] == [
            RIGHT
        ]
        assert two_projects.left_root.is_dir()
        assert (two_projects.left_root / "research.yaml").is_file()


def test_a_restarted_host_reads_the_registry_from_disk_and_not_from_the_old_process(
    two_projects: TwoProjects, tmp_path: Path
) -> None:
    """The only thing two hosts over one data directory share is `projects.json`."""
    third_root = multi_fixtures.populated_workspace(tmp_path / "third", "third", "third claim")
    two_projects.client.close()

    restarted: MultiHarness = build_multi_app(
        two_projects.harness.data_dir, id_factory=third_project_id
    )
    with TestClient(restarted.app) as client:
        authenticate(client)
        opened = client.post("/api/projects/open", json={"path": str(third_root)})
        assert opened.status_code == 200, opened.text
        third = opened.json()["project_id"]
        listed = [item["project_id"] for item in client.get("/api/projects").json()["projects"]]
        assert listed == [third, RIGHT, LEFT]

    again = build_multi_app(two_projects.harness.data_dir, id_factory=third_project_id)
    with TestClient(again.app) as client:
        authenticate(client)
        assert [item["project_id"] for item in client.get("/api/projects").json()["projects"]] == [
            third,
            RIGHT,
            LEFT,
        ]
        served = client.get(f"/api/projects/{third}/objects/{CLAIM}")
        assert served.json()["object"]["statement"] == "third claim"

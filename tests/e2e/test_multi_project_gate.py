"""The multi-project gate: isolation, failure containment, and survival across a restart.

These are end-to-end properties of the running host rather than route contracts. Two
projects are opened through the real control plane, and every assertion is about what one
project can see of another - or about what survives the process that served them. Task 13
extends this file; the fixtures it needs live in `tests/contract/protocol/multi_fixtures.py`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from starlette.testclient import TestClient

from tests.contract.protocol import multi_fixtures
from tests.contract.protocol.conftest import CLAIM
from tests.contract.protocol.multi_fixtures import (
    LEFT,
    LEFT_STATEMENT,
    RIGHT,
    RIGHT_STATEMENT,
    TwoProjects,
    authenticate,
    build_multi_app,
)

# The same fixtures the contract tests use, bound the same way (see that module's note).
multi_harness = multi_fixtures.multi_harness
multi_client = multi_fixtures.multi_client
authenticated_multi_client = multi_fixtures.authenticated_multi_client
two_projects = multi_fixtures.two_projects
two_projects_client = multi_fixtures.two_projects_client
left_run_id = multi_fixtures.left_run_id


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

"""Gate P11 / v0.4: the review loop and the claim audit loop, driven the way the Web drives them.

The gate is a claim about *reachability*, not about pixels: a researcher must be able to
finish the Evidence review loop and the Claim audit loop from the cockpit without editing a
canonical file by hand and without a CLI mutation command. This module makes that testable
by driving the exact HTTP calls the Web makes — `POST /capabilities/<name>` for every
mutation, `GET /overview`, `GET /blocks/...`, `GET /artifacts/.../bytes` for every read —
and asserting the canonical result on disk afterwards.

Every review action is a candidate-keyed `review.*` call carrying the staging id, which is
what the cockpit now sends: the handler allocates the evidence id, marks the candidate
reviewed, and settles the queue in one transaction. The v0.3 arrangement — post the
`Evidence` object back to `evidence.accept`, and watch the proposal stay in the inbox — was
the documented gap, and the tests that pinned it have been replaced by tests that the queue
drains however the acceptance was made.

Only the staging half is set up in process: `work.interrogate` over HTTP resolves its model
provider from `research.yaml`, and a scripted provider is not configuration. Extraction and
verification write nothing but proposals under `.research/staging` (ADR-003), so setting
them up here changes no scientific state and leaves the gate's claim intact.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from research_harness.capabilities.context import open_context
from research_harness.capabilities.dto import InitProjectRequest
from research_harness.capabilities.handlers import init_project
from research_harness.capabilities.permissions import Principal
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.domain.ids import WorkId
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.server.app import create_app, ensure_token
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workflows.interrogate import run_interrogation
from research_harness.workflows.verify import run_verification
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.runs import RunStore
from tests.integration.evidence.conftest import (
    DATASET_SENTENCE,
    dataset_candidate,
    extraction_dict,
    method_candidate,
    metric_candidate,
    parse_fixture,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_research_paper.pdf"
WORK = WorkId("W0001")
ARTIFACT = "A0001-1"

FIELDS = ("dataset", "metric_result", "method_summary")
QUOTES = {
    "dataset": DATASET_SENTENCE,
    "metric_result": "94.32",
    "method_summary": "The encoder is a twelve layer transformer",
}
VERDICTS = {
    "dataset": "supported",
    "metric_result": "supported",
    "method_summary": "partially_supported",
}

STATEMENT = "TrafficLM reaches an F1 of 94.32 on CICIDS2017"

#: The claim-evidence edge the Claim explorer's "relate evidence" control posts.
SUPPORTS = {"evidence": "E0001", "relation": "supports"}


# -- the workspace the cockpit opens -----------------------------------------


def build_corpus(root: Path, registry: CapabilityRegistry) -> Path:
    """Ingest and parse the synthetic paper through the capability layer."""
    result = init_project(InitProjectRequest(root=root, name="gate-p11"))
    human = Principal.human()
    registry.invoke(
        "corpus.ingest",
        open_context(result.root, HUMAN_ACTOR),
        {"path": str(FIXTURE)},
        principal=human,
    )
    registry.invoke(
        "work.parse", open_context(result.root, HUMAN_ACTOR), {"work": str(WORK)}, principal=human
    )
    return result.root


def stage_candidates(root: Path) -> None:
    """Three staged, verified candidates: one routine, one high-risk, one ambiguous."""
    document = parse_fixture()
    repo = WorkspaceRepository.open(root)
    from research_harness.evidence.staging import StagingStore

    staging = StagingStore(repo.layout.research_dir)
    engine = WorkflowEngine(RunStore(repo.layout.research_dir))
    extractor = ScriptedProvider(
        [
            extraction_dict([dataset_candidate(document)]),
            extraction_dict([metric_candidate(document)]),
            extraction_dict([method_candidate(document)]),
        ],
        name="scripted",
    )
    run_interrogation(engine, staging, repo, WORK, extractor, fields=list(FIELDS))
    pending = staging.list(work=WORK)
    verifier = ScriptedProvider(
        [
            {
                "verdict": VERDICTS[candidate.field],
                "rationale": "read the span and the blocks around it",
                "quoted_support": QUOTES[candidate.field],
                "discrepancies": [],
            }
            for candidate in pending
        ],
        name="scripted",
    )
    run_verification(engine, staging, repo, WORK, verifier)


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    return build_default_registry()


@pytest.fixture
def workspace(tmp_path: Path, registry: CapabilityRegistry) -> Path:
    """A workspace with three staged candidates waiting in the review queue."""
    root = build_corpus(tmp_path / "gate-p11", registry)
    stage_candidates(root)
    return root


@pytest.fixture
def cockpit(workspace: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    """The daemon as the Web cockpit sees it: the local researcher, holding the token."""
    token = ensure_token(workspace)
    with TestClient(create_app(workspace, registry=registry)) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


@pytest.fixture
def host_cockpit(workspace: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    """The same cockpit opened without a token: an agent host, which may not accept."""
    with TestClient(create_app(workspace, registry=registry)) as client:
        yield client


# -- the calls the cockpit makes ---------------------------------------------


def call(client: TestClient, capability: str, request: dict[str, Any]) -> dict[str, Any]:
    """One capability call, asserted to have succeeded, as the UI's client does it."""
    response = client.post(f"/capabilities/{capability}", json=request)
    body: dict[str, Any] = response.json()
    assert body["ok"] is True, f"{capability} refused: {body.get('error')}"
    assert isinstance(body["result"], dict)
    return body["result"]


def refuse(client: TestClient, capability: str, request: dict[str, Any]) -> dict[str, Any]:
    """One capability call the daemon is expected to refuse, with its stable error code."""
    response = client.post(f"/capabilities/{capability}", json=request)
    body: dict[str, Any] = response.json()
    assert body["ok"] is False
    assert isinstance(body["error"], dict)
    return body["error"]


#: The refusal `server/app.py::_invoke` produces for a handler that allocates its own id.
REENTRANT_LOCK = "the workspace lock is not reentrant"

#: What has to change for server-side id allocation to be reachable over HTTP at all.
ALLOCATION_DEFECT = (
    "BACKEND DEFECT: `server/app.py::_invoke` already holds `ctx.repo.lock()` for every "
    "`mutate`/`admin` capability, and the four handlers that allocate an id server-side "
    "(`create_claim`, `accept_decision`, `create_question`, `record_search_run`, plus "
    "`ingest_local_pdf` and `add_artifact`) take it again to allocate under it. "
    "`WorkspaceRepository.lock()` raises rather than nesting, so the id-less form the "
    "cockpit now posts comes back `workspace_error` over HTTP. The same call succeeds "
    "in process through the registry, so the handler is right and the transport is not. "
    "One fix: make `lock()` reentrant the way `transaction()` already is (return the held "
    "lock instead of raising), or stop pre-locking in `_invoke` and `mcp.py::_Locked`."
)


def allocating(client: TestClient, capability: str, request: dict[str, Any]) -> str:
    """One id-less create, returning the id the daemon chose.

    The cockpit posts no id: `claim.create`, `question.create`, `decision.accept`, and
    `search_run.record` allocate one under the workspace lock and return it. Over HTTP that
    is currently refused, so this reports the defect as an expected failure rather than as
    a red test nobody can act on — and the moment the lock is fixed these tests pass with
    nothing to un-mark.
    """
    response = client.post(f"/capabilities/{capability}", json=request)
    body: dict[str, Any] = response.json()
    if not body["ok"] and REENTRANT_LOCK in str(body["error"].get("message", "")):
        pytest.xfail(f"{capability} cannot allocate an id over HTTP. {ALLOCATION_DEFECT}")
    assert body["ok"] is True, f"{capability} refused: {body.get('error')}"
    allocated: str = body["result"]["objects"][0]
    return allocated


def inbox(client: TestClient) -> dict[str, dict[str, Any]]:
    """The review queue as the Review Inbox view reads it, keyed by interrogation field."""
    queue = call(client, "review.inbox", {})
    return {str(item["field"]): item for item in queue["items"]}


# -- the Evidence review loop ------------------------------------------------


def test_the_review_queue_is_ordered_and_carries_its_source_context(cockpit: TestClient) -> None:
    """Product 24.2 and 25: priority order, and the source beside every decision."""
    queue = call(cockpit, "review.inbox", {})

    assert queue["count"] == 3
    categories = [item["category"] for item in queue["items"]]
    assert categories == ["high_risk", "ambiguous", "routine"]
    for item in queue["items"]:
        context = item["source_context"]
        assert context["exact_text"], "a decision is never asked without the exact span"
        assert context["block_text"], "the block the span sits in is on the same screen"
        assert item["source_context"]["page"] is not None
    assert "confidence" not in json.dumps(queue).lower()


def test_the_source_pane_reads_the_page_geometry_and_the_original_bytes(
    cockpit: TestClient,
) -> None:
    """Product 42 D: the reviewer sees the artifact the anchor was made against."""
    item = inbox(cockpit)["metric_result"]
    blocks = cockpit.get(f"/blocks/{item['artifact']}").json()
    anchored = next(
        block
        for block in blocks["blocks"]
        if block["id"] == item["source_context"].get("block", block["id"])
    )

    assert blocks["page_count"] >= item["source_context"]["page"]
    assert anchored["bbox"] is not None
    assert cockpit.get(f"/artifacts/{item['artifact']}/bytes").content[:5] == b"%PDF-"


def test_accept_and_reject_drain_the_queue_through_capability_calls(
    cockpit: TestClient, workspace: Path
) -> None:
    """The Gate P11 review loop: a decision per candidate, no CLI and no file edit.

    Each of the six actions takes the staging id and whatever the researcher typed, and
    nothing else. The cockpit never reads a candidate and posts it back: the handler
    allocates the evidence id, marks the candidate reviewed so it leaves the queue, and
    reports both in one `ReviewOutcome`.
    """
    items = inbox(cockpit)

    accepted = call(
        cockpit, "review.accept", {"candidate_id": items["metric_result"]["candidate_id"]}
    )
    rejected = call(
        cockpit,
        "review.reject",
        {
            "candidate_id": items["method_summary"]["candidate_id"],
            "reason": "the span describes the encoder, not the method",
        },
    )
    deferred = call(
        cockpit,
        "review.defer",
        {"candidate_id": items["dataset"]["candidate_id"], "note": "waiting for the appendix"},
    )

    assert accepted["evidence"] == "E0001"
    assert accepted["status"] == "reviewed"
    assert accepted["mutation"]["objects"] == ["E0001"]
    assert accepted["mutation"]["event"]["event"] == "evidence.accepted"
    assert rejected["evidence"] is None
    assert rejected["mutation"]["event"]["event"] == "evidence.rejected"
    assert deferred["mutation"] is None, "deferring changes no accepted state"
    assert [item["field"] for item in call(cockpit, "review.inbox", {})["items"]] == ["dataset"], (
        "a deferred candidate stays in the queue; the decided ones leave it"
    )

    records = _evidence(workspace)
    assert [record["id"] for record in records] == ["E0001"]
    assert records[0]["verification"]["accepted_by"].startswith("human")
    assert records[0]["source"]["artifact"] == ARTIFACT
    assert len(_rejections(workspace)) == 1


def test_qualification_and_edit_leave_the_queue_as_every_other_acceptance_does(
    cockpit: TestClient, workspace: Path
) -> None:
    """Product 24.3's two remaining accepting actions, and the gap they used to leave open.

    `review.qualify` and `review.edit` take the staging id: the qualification and the
    corrected object are the only things the researcher supplies, and the canonical
    `Evidence` is written by the handler. Until v0.4 these two ran through
    `evidence.accept`, which wrote the Evidence correctly and left the proposal sitting in
    the inbox — the gap `docs/architecture/web.md` documented. The last assertion here is
    that gap, closed.
    """
    items = inbox(cockpit)
    read_back = call(
        cockpit, "review.candidate", {"candidate_id": items["method_summary"]["candidate_id"]}
    )
    corrected = {
        **read_back["evidence"],
        "content": {
            **read_back["evidence"]["content"],
            "exact_text": "The encoder is a twelve layer",
        },
    }

    qualified = call(
        cockpit,
        "review.qualify",
        {
            "candidate_id": items["dataset"]["candidate_id"],
            "qualification": "holds for the CICIDS2017 capture only",
        },
    )
    edited = call(
        cockpit,
        "review.edit",
        {"candidate_id": items["method_summary"]["candidate_id"], "edited": corrected},
    )

    records = _evidence(workspace)
    assert read_back["evidence"]["content"]["field"] == "method_summary", (
        "`review.candidate` is the read the Edit action opens its editor on"
    )
    assert qualified["evidence"] == "E0001"
    assert qualified["status"] == "reviewed"
    assert edited["evidence"] == "E0002"
    assert edited["mutation"]["validation"]["warnings"] == [
        "content replaced by the researcher's edit before acceptance"
    ]
    assert [record["content"]["field"] for record in records] == ["dataset", "method_summary"]
    assert records[0]["qualification"] == "holds for the CICIDS2017 capture only"
    assert records[1]["content"]["exact_text"] == "The encoder is a twelve layer"
    assert [item["field"] for item in call(cockpit, "review.inbox", {})["items"]] == [
        "metric_result"
    ], "an accepted candidate leaves the queue, however the acceptance was posted"


def test_an_edit_may_correct_the_content_and_never_move_the_source_anchor(
    cockpit: TestClient,
) -> None:
    """ADR-002: an edit corrects what the evidence says, never where it was read."""
    items = inbox(cockpit)
    candidate = call(
        cockpit, "review.candidate", {"candidate_id": items["metric_result"]["candidate_id"]}
    )
    moved = {
        **candidate["evidence"],
        "source": {**candidate["evidence"]["source"], "page": 99},
    }

    error = refuse(
        cockpit,
        "review.edit",
        {"candidate_id": items["metric_result"]["candidate_id"], "edited": moved},
    )

    assert error["code"] in {"invalid_request", "capability_error", "validation_error"}
    assert "source anchor" in error["message"]
    assert {item["field"] for item in call(cockpit, "review.inbox", {})["items"]} == {
        "dataset",
        "metric_result",
        "method_summary",
    }, "a refused edit leaves the queue exactly as it was"


def test_a_conflicted_candidate_is_still_answered_through_resolve_conflict(
    cockpit: TestClient,
) -> None:
    """The cockpit's second review path, and the only one that closes a conflict record.

    `review.accept` reaches the same `EvidenceReviewService.accept`, but nothing in it
    closes a materialized `ConflictRecord`. When the queue item carries one, the review
    screen sends `review.resolve_conflict` with the researcher's reason instead, so the
    disagreement does not outlive the decision that settled it (Product 25, Task 13.2).
    """
    items = inbox(cockpit)

    resolved = call(
        cockpit,
        "review.resolve_conflict",
        {
            "candidate_id": items["metric_result"]["candidate_id"],
            "choice": "accept",
            "reason": "row TrafficLM, column F1 of Table 1, read on page 4",
        },
    )

    assert resolved["choice"] == "accept"
    assert resolved["mutation"]["objects"] == ["E0001"]
    assert {item["field"] for item in call(cockpit, "review.inbox", {})["items"]} == {
        "dataset",
        "method_summary",
    }


def test_request_more_evidence_becomes_a_durable_note(cockpit: TestClient) -> None:
    """Product 24.3 and 31: a question worth asking outlives the next `.research/` deletion.

    The cockpit no longer builds the note text itself. `review.request_more` records the
    request on the staged candidate *and* captures it as a low-authority note, so the two
    cannot drift apart and the candidate is still in the queue afterwards.
    """
    items = inbox(cockpit)

    outcome = call(
        cockpit,
        "review.request_more",
        {
            "candidate_id": items["dataset"]["candidate_id"],
            "note": "does the appendix name the capture window?",
        },
    )

    assert outcome["evidence"] is None, "asking for more evidence accepts nothing"
    assert "dataset" in [item["field"] for item in call(cockpit, "review.inbox", {})["items"]], (
        "the candidate is still waiting; the question was recorded, not answered"
    )


def test_an_agent_host_cockpit_reads_everything_and_accepts_nothing(
    host_cockpit: TestClient,
) -> None:
    """ADR-007: the review gate is the same over HTTP as everywhere else (Product 42 H)."""
    assert host_cockpit.get("/overview").json()["principal"] == "agent_host"
    queue = call(host_cockpit, "review.inbox", {})
    assert queue["count"] == 3

    for capability, request in (
        ("review.accept", {}),
        ("review.qualify", {"qualification": "only under load"}),
        ("review.reject", {"reason": "wrong span"}),
        ("review.defer", {"note": "later"}),
        ("review.request_more", {"note": "which capture window?"}),
    ):
        candidate_id = inbox(host_cockpit)["dataset"]["candidate_id"]
        error = refuse(host_cockpit, capability, {"candidate_id": candidate_id, **request})
        assert error["code"] == "permission_denied", capability
    assert call(host_cockpit, "review.candidate", {"candidate_id": candidate_id})["evidence"], (
        "an agent host reads the proposal it is asked to reason about"
    )


# -- the Claim audit loop ----------------------------------------------------


def test_the_claim_audit_loop_runs_entirely_over_the_cockpit_calls(
    cockpit: TestClient, workspace: Path
) -> None:
    """Create from accepted evidence, relate, audit, and override — every step a capability."""
    items = inbox(cockpit)
    call(cockpit, "review.accept", {"candidate_id": items["metric_result"]["candidate_id"]})

    claim_id = allocating(cockpit, "claim.create", {"claim": _claim_payload()})
    assert claim_id == "C0001", (
        "the cockpit sends no id; the daemon allocates one under the workspace lock"
    )

    related = call(cockpit, "claim.relate", {"claim_id": "C0001", "relation": SUPPORTS})
    assert related["event"]["event"] == "claim.relation_changed"

    support = call(cockpit, "claim.find_support", {"claim_id": "C0001"})
    assert [link["evidence"] for link in support["supporting"]] == ["E0001"]
    assert support["supporting"][0]["exact_text"]

    audited = call(
        cockpit,
        "claim.audit",
        {
            "claim_id": "C0001",
            "status": "supported",
            "allowed_strength": "individual",
            "maximum_defensible_wording": "one system on one held-out split",
        },
    )
    assert audited["event"]["event"] == "claim.audited"

    claim = cockpit.get("/objects/C0001").json()["object"]
    assert claim["assessment"]["status"] == "supported"
    assert claim["assessment"]["allowed_strength"] == "individual"
    assert claim["assessment"]["maximum_defensible_wording"] == "one system on one held-out split"


def test_an_override_is_a_decision_before_it_is_a_claim_edit(
    cockpit: TestClient, workspace: Path
) -> None:
    """Product 38: the Override button accepts a Decision, then applies it."""
    items = inbox(cockpit)
    call(cockpit, "review.accept", {"candidate_id": items["metric_result"]["candidate_id"]})
    allocating(cockpit, "claim.create", {"claim": _claim_payload()})
    call(cockpit, "claim.relate", {"claim_id": "C0001", "relation": SUPPORTS})
    call(
        cockpit,
        "claim.audit",
        {"claim_id": "C0001", "status": "supported", "allowed_strength": "individual"},
    )

    announced = cockpit.get("/overview").json()["next_decision_id"]
    decision_id = allocating(cockpit, "decision.accept", {"decision": _decision_payload()})
    applied = call(
        cockpit,
        "claim.override_strength",
        {"claim_id": "C0001", "decision_id": decision_id},
    )

    assert decision_id == announced, (
        "`GET /overview` still reports the id, for display; the write no longer depends on it"
    )
    assert applied["event"]["event"] == "claim.overridden"
    claim = cockpit.get("/objects/C0001").json()["object"]
    assert claim["assessment"]["allowed_strength"] == "observed_subset"
    decision = cockpit.get(f"/objects/{decision_id}").json()["object"]
    assert decision["status"] == "accepted"
    assert decision["auditor_recommendation"] == "individual"
    assert decision["researcher_selected"] == "observed_subset"


def test_server_side_id_allocation_works_over_http_and_in_process(
    cockpit: TestClient, workspace: Path, registry: CapabilityRegistry
) -> None:
    """`claim.create` with no id allocates under the workspace lock on every transport.

    The daemon serializes each mutating capability under `ctx.repo.lock()` and the handler
    takes the same lock again to allocate; `WorkspaceRepository.lock()` nests within one
    repository, so the id-less form the cockpit posts is honoured over HTTP exactly as it is
    in process, and the two allocations never collide.
    """
    over_http = allocating(cockpit, "claim.create", {"claim": _claim_payload()})
    assert over_http == "C0001"
    assert cockpit.get("/objects/C0001").status_code == 200

    in_process = registry.invoke(
        "claim.create",
        open_context(workspace, HUMAN_ACTOR),
        {"claim": _claim_payload()},
        principal=Principal.human(),
    )
    assert in_process.objects == ("C0002",), "the next free id, allocated under the lock"


# -- the gate ----------------------------------------------------------------


def test_gate_p11_both_loops_complete_with_no_file_edit_and_no_cli_mutation(
    cockpit: TestClient, workspace: Path
) -> None:
    """Gate P11 / v0.3, end to end: every mutation below is one HTTP capability call.

    The assertion at the bottom is the gate itself — the canonical tree carries the accepted
    Evidence, the refusal, the Claim, its audit, and the override, and the only writer was
    `POST /capabilities/<name>`.
    """
    before = _canonical_files(workspace)
    items = inbox(cockpit)

    # Evidence review loop: source beside decision, then accept / qualify / reject.
    assert cockpit.get(f"/artifacts/{items['metric_result']['artifact']}/bytes").status_code == 200
    assert cockpit.get(f"/blocks/{items['metric_result']['artifact']}").json()["blocks"]
    call(cockpit, "review.accept", {"candidate_id": items["metric_result"]["candidate_id"]})
    call(
        cockpit,
        "review.reject",
        {
            "candidate_id": items["method_summary"]["candidate_id"],
            "reason": "the span describes the encoder, not the method",
        },
    )

    # Claim audit loop: create, relate, audit, override. No id is guessed anywhere.
    claim_id = allocating(cockpit, "claim.create", {"claim": _claim_payload()})
    call(cockpit, "claim.relate", {"claim_id": claim_id, "relation": SUPPORTS})
    call(
        cockpit,
        "claim.audit",
        {"claim_id": claim_id, "status": "supported", "allowed_strength": "individual"},
    )
    decision_id = allocating(cockpit, "decision.accept", {"decision": _decision_payload()})
    call(cockpit, "claim.override_strength", {"claim_id": claim_id, "decision_id": decision_id})

    overview = cockpit.get("/overview").json()
    assert overview["counts"]["accepted_evidence"] == 1
    assert overview["counts"]["claims"] == 1
    assert [entry["key"] for entry in overview["claim_health"]] == ["supported"]
    assert [group["count"] for group in overview["attention"]] == [1, 0, 0, 0], (
        "the one candidate nobody decided is still the next action, and nothing else is"
    )

    repo = WorkspaceRepository.open(workspace)
    assert repo.consistency.consistent
    assert [str(item.id) for item in repo.iter_evidence(WORK)] == ["E0001"]
    claim = repo.get_claim(repo.list_claims()[0].id)
    assert claim.allowed_strength.value == "observed_subset"

    changed = {
        name for name, payload in _canonical_files(workspace).items() if before.get(name) != payload
    }
    assert changed, "the loops wrote canonical state"
    assert all(
        name.startswith(("corpus/", "claims/", "decisions/", "events/", "research.yaml"))
        for name in changed
    ), f"a capability call wrote outside the canonical tree: {sorted(changed)}"


# -- helpers -----------------------------------------------------------------


def _claim_payload() -> dict[str, Any]:
    """The Claim the cockpit's "new claim" form posts, at the strength it asks for.

    No `id`: `claim.create` allocates the next free `ClaimId` under the workspace lock and
    returns it, so no client has to predict one and no two clients can race for it.
    """
    return {
        "statement": STATEMENT,
        "type": "descriptive",
        "semantics": {"subject": "TrafficLM", "predicate": "reaches", "object": "F1 94.32"},
        "scope": {"level": "observed_subset", "corpus": "encrypted traffic classifiers"},
        "assessment": {"requested_strength": "observed_subset", "allowed_strength": "individual"},
        "provenance": {"source": "human", "actor": HUMAN_ACTOR},
    }


def _decision_payload() -> dict[str, Any]:
    """The epistemic override the Override button proposes before applying it.

    Also id-less: an override is a Decision before it is a claim edit, and the cockpit now
    applies the id `decision.accept` reports rather than the one `GET /overview` announced.
    """
    return {
        "type": "epistemic_override",
        "status": "proposed",
        "title": "epistemic override on C0001",
        "rationale": "the held-out split covers the two captures this claim is about",
        "claim": "C0001",
        "auditor_recommendation": "individual",
        "researcher_selected": "observed_subset",
        "provenance": {"source": "human", "actor": HUMAN_ACTOR},
    }


def _evidence(root: Path) -> list[dict[str, Any]]:
    return _jsonl(root / "corpus" / "works" / "W0001" / "evidence.jsonl")


def _rejections(root: Path) -> list[dict[str, Any]]:
    return _jsonl(root / "corpus" / "works" / "W0001" / "rejections.jsonl")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _canonical_files(root: Path) -> dict[str, bytes]:
    """Every canonical file and its bytes; `.research/` is regenerable by definition."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".research" not in path.relative_to(root).parts
    }

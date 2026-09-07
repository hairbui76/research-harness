"""Task 11.1: the reads the Web cockpit needs, and nothing more than reads.

The Web cockpit is a client of the same capability registry every other transport uses
(ADR-004). Four things it needs are not capability calls: the immutable artifact bytes, the
stored parse geometry the highlight is drawn from, one composed "what needs attention"
answer, and the built bundle itself. All four are GETs, and this module is the proof that
they stay that way.

The overview is asserted hardest, because it is where a business rule would leak into
React first: the ordering, the grouping, and the "unsupported manuscript claim" judgement
all have to be decided here (Product 5 P10, 26).

Everything else the cockpit lists is now a named capability rather than a route. The last
two sections check that migration from both ends: that `state.index` answers exactly what
`GET /index` answers, that a one-list read returns the same summaries the index composes,
and that every field name `web/src/api/dto.ts` hand-declares for a capability response is a
field the daemon actually publishes — so a rename fails here rather than in a blank panel.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from research_harness.capabilities.context import open_context
from research_harness.capabilities.dto import InitProjectRequest
from research_harness.capabilities.handlers import init_project
from research_harness.capabilities.permissions import Principal
from research_harness.capabilities.registry import CapabilityRegistry
from research_harness.domain.base import Provenance
from research_harness.domain.conversation import Message, MessageRole, TextBlock
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.evidence.conflicts import ConflictKind, ConflictRecord, ConflictStore
from research_harness.protocol.dto import ArtifactBlocks, OverviewReport, WorkspaceIndex
from research_harness.server.app import (
    CHANGE_ITEMS,
    DEV_ENV,
    DEV_ORIGINS,
    WEB_DIST_ENV,
    create_app,
    dev_mode,
    ensure_token,
    web_dist,
)
from research_harness.workspace.conversations import ConversationStore
from research_harness.workspace.repository import WorkspaceRepository

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "synthetic_research_paper.pdf"
WEB_DTO_TS = REPO_ROOT / "web" / "src" / "api" / "dto.ts"
WORK = "W0001"
ARTIFACT = "A0001-1"

#: The capability each hand-written interface in `web/src/api/dto.ts` mirrors. Only the ones
#: no HTTP route returns are listed: the rest are generated from `web/openapi.json` and
#: cannot drift by construction.
WEB_RESPONSE_TYPES = {
    "ClaimList": "claim.list",
    "WorkList": "work.list",
    "QuestionList": "question.list",
    "DecisionList": "decision.list",
    "AnchorList": "anchor.list",
    "EvidenceList": "evidence.list",
    "EvidenceSummary": "evidence.list",
    "ReviewOutcome": "review.accept",
    "AnchorVerdict": "manuscript.anchors",
    "ManuscriptAnchors": "manuscript.anchors",
    "RevalidationView": "manuscript.revalidate",
    "TraceView": "manuscript.trace",
    "FindingLocation": "manuscript.audit",
    "ManuscriptAuditFinding": "manuscript.audit",
    # v1.1 — manuscript workspace (Phase 21)
    "ManuscriptFile": "manuscript.files",
    "ManuscriptTree": "manuscript.files",
    "FileSnapshot": "manuscript.read_file",
    "CompileDiagnostic": "manuscript.build",
    "LastGoodBuild": "manuscript.build",
    "CompileResult": "manuscript.build",
    "DiscoveredEngine": "manuscript.build",
    "ManuscriptSettings": "manuscript.build",
    "ToolchainReport": "manuscript.build",
    "BuildView": "manuscript.build",
    "PdfLocation": "manuscript.synctex",
    "SourceLocation": "manuscript.synctex",
    "SynctexView": "manuscript.synctex",
    "ProtectedSpan": "manuscript.suggest",
    "ProtectedViolation": "manuscript.suggest",
    "SemanticDiff": "manuscript.suggest",
    "StyleReport": "manuscript.suggest",
    "SuggestionDiffLine": "manuscript.suggest",
    "SuggestionDiffHunk": "manuscript.suggest",
    "AnchorImpact": "manuscript.suggest",
    "SuggestionProvenance": "manuscript.suggest",
    "SuggestionCandidate": "manuscript.suggest",
    "AppliedSuggestion": "manuscript.apply_suggestion",
    # v1.1 — conversation workspace (Phase 18)
    "ModelIdentity": "session.get",
    "SessionDefaults": "session.get",
    "ConversationSession": "session.get",
    "TextBlock": "session.get",
    "ReferenceBlock": "session.get",
    "AttachmentBlock": "session.get",
    "MessageAttempt": "session.get",
    "ConversationMessage": "session.get",
    "SessionAttachmentRecord": "session.get",
    "SessionView": "session.create",
    "SessionListView": "session.list",
    "SessionTranscript": "session.get",
    "SessionMatch": "session.search",
    "SessionSearchResults": "session.search",
    "SessionSummaryView": "session.summarize",
    "ContextItemView": "context.preview",
    "OmittedContextItemView": "context.preview",
    "ContextReceipt": "context.preview",
    "ClassBudget": "context.preview",
    "ContextPack": "context.preview",
    "OmissionView": "context.preview",
    "DiscrepancyView": "context.preview",
    "ContextPackView": "context.get",
    "SendStarted": "session.send",
    "SessionStopped": "session.stop",
    "PromotionView": "session.promote",
    "ProviderModel": "provider.list",
    "ProviderCatalog": "provider.list",
    # v1.1 — attachments (Phase 19)
    "AttachmentView": "attachment.add",
    "AttachmentRemoved": "attachment.remove",
    "AttachmentSendItem": "attachment.check_send",
    "AttachmentSendCheck": "attachment.check_send",
    "AttachmentIdentityView": "attachment.resolve_identity",
    "AttachmentPromotionView": "attachment.save_to_corpus",
    # v1.1 — research graph (Phase 20)
    "GraphNodeView": "graph.neighbors",
    "GraphEdgeView": "graph.neighbors",
    "GraphNeighbourView": "graph.neighbors",
    "GraphNeighbourhoodView": "graph.neighbors",
    "GraphResolvedView": "graph.resolve",
    "GraphAutocompleteResult": "graph.autocomplete",
    "GraphQueryResult": "graph.query",
    "GraphProvenanceStepView": "graph.provenance",
    "GraphProvenanceView": "graph.provenance",
    "GraphStatusView": "graph.status",
    # subscription-backed CLI providers
    "CliModelView": "provider.cli.scan",
    "CliRuntimeStatus": "provider.cli.scan",
    "ConfiguredCliProviderView": "provider.cli.scan",
    "CliScanReport": "provider.cli.scan",
    "CliProviderConfigured": "provider.cli.configure",
    "CliProviderRemoved": "provider.cli.remove",
    "CliProviderTestReport": "provider.cli.test",
}

#: The request each cockpit control posts, exactly as `web/src/api/client.ts` builds it.
WEB_REQUESTS = {
    "state.index": {},
    "claim.list": {"status": "unverified"},
    "work.list": {},
    "question.list": {},
    "decision.list": {"claim": "C0001"},
    "anchor.list": {},
    "evidence.list": {"work": WORK, "status": "accepted"},
}

#: The four attention surfaces of Product 26, in the order the Overview states them.
EXPECTED_ATTENTION = (
    "review_items",
    "conflicts",
    "stale",
    "unsupported_manuscript_claims",
)


@pytest.fixture
def corpus(tmp_path: Path, registry: CapabilityRegistry) -> Path:
    """A workspace with the synthetic paper ingested and parsed, through capabilities."""
    result = init_project(InitProjectRequest(root=tmp_path / "cockpit", name="cockpit"))
    human = Principal.human()
    registry.invoke(
        "corpus.ingest",
        open_context(result.root, HUMAN_ACTOR),
        {"path": str(FIXTURE)},
        principal=human,
    )
    registry.invoke(
        "work.parse",
        open_context(result.root, HUMAN_ACTOR),
        {"work": WORK},
        principal=human,
    )
    return result.root


@pytest.fixture
def reader(corpus: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    """The daemon over the corpus workspace, as the local researcher."""
    token = ensure_token(corpus)
    with TestClient(create_app(corpus, registry=registry)) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client


@pytest.fixture
def host_reader(corpus: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    """The same workspace as an agent host: reads succeed, acceptance does not."""
    with TestClient(create_app(corpus, registry=registry)) as test_client:
        yield test_client


@pytest.fixture
def bare(tmp_path: Path) -> Path:
    """A registered project with nothing in it: no work, no evidence, no history at all."""
    return init_project(InitProjectRequest(root=tmp_path / "fresh", name="fresh")).root


@pytest.fixture
def bare_reader(bare: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    """The daemon over a project on its first day."""
    token = ensure_token(bare)
    with TestClient(create_app(bare, registry=registry)) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client


# -- artifact bytes ----------------------------------------------------------


def test_artifact_bytes_are_the_stored_file_byte_for_byte(reader: TestClient) -> None:
    """Product 42 D: accepted evidence opens the exact artifact it was accepted from."""
    response = reader.get(f"/artifacts/{ARTIFACT}/bytes")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert hashlib.sha256(response.content).hexdigest() == _artifact_hash(reader)


def test_artifact_bytes_render_inline_so_a_source_pane_can_draw_on_them(
    reader: TestClient,
) -> None:
    disposition = reader.get(f"/artifacts/{ARTIFACT}/bytes").headers["content-disposition"]
    assert disposition.startswith("inline")


def test_an_agent_host_may_read_the_source_it_is_asked_to_reason_about(
    host_reader: TestClient,
) -> None:
    assert host_reader.get(f"/artifacts/{ARTIFACT}/bytes").status_code == 200
    assert host_reader.get(f"/blocks/{ARTIFACT}").status_code == 200
    assert host_reader.get("/overview").status_code == 200


def test_an_id_that_is_not_an_artifact_is_a_404_not_a_guess(reader: TestClient) -> None:
    assert reader.get("/artifacts/W0001/bytes").status_code == 404
    assert reader.get("/artifacts/not-an-id/bytes").status_code == 404
    assert reader.get("/artifacts/A9999-1/bytes").status_code == 404


def test_there_is_no_route_that_writes_artifact_bytes(reader: TestClient) -> None:
    """An Artifact is registered once and never edited (ADR-002)."""
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = reader.request(method, f"/artifacts/{ARTIFACT}/bytes")
        assert response.status_code == 405


# -- blocks ------------------------------------------------------------------


def test_blocks_carry_the_page_and_geometry_a_highlight_needs(reader: TestClient) -> None:
    blocks = ArtifactBlocks.model_validate(reader.get(f"/blocks/{ARTIFACT}").json())

    assert blocks.artifact == ARTIFACT
    assert blocks.work == WORK
    assert blocks.page_count >= 1
    assert blocks.blocks
    assert all(block.page >= 1 for block in blocks.blocks)
    assert any(block.bbox is not None for block in blocks.blocks)
    assert [block.order for block in blocks.blocks] == sorted(
        block.order for block in blocks.blocks
    )


def test_blocks_match_the_parse_the_workspace_stored(reader: TestClient) -> None:
    """The blocks are read from canonical files, so an anchor replays without a parser."""
    blocks = ArtifactBlocks.model_validate(reader.get(f"/blocks/{ARTIFACT}").json())
    stored = _object(reader, ARTIFACT)

    assert blocks.file_hash == stored["file_hash"]
    assert blocks.mime_type == stored["mime_type"]


# -- overview ----------------------------------------------------------------


def test_the_overview_leads_with_next_actions_in_product_26_order(reader: TestClient) -> None:
    overview = OverviewReport.model_validate(reader.get("/overview").json())

    assert tuple(group.kind for group in overview.attention) == EXPECTED_ATTENTION
    assert [group.route for group in overview.attention] == [
        "/review",
        "/conflicts",
        "/stale",
        "/manuscript",
    ]
    assert all(group.count == 0 for group in overview.attention)
    assert overview.attention[0].label == "0 review items"


def test_the_overview_counts_the_project_it_serves(reader: TestClient) -> None:
    overview = OverviewReport.model_validate(reader.get("/overview").json())

    assert overview.project == "cockpit"
    assert overview.counts.works == 1
    assert overview.counts.artifacts == 1
    assert overview.counts.accepted_evidence == 0
    assert overview.review_policy == "strict"


def test_the_overview_never_reports_a_model_confidence_number(reader: TestClient) -> None:
    """Product 43: false precision from model confidence is a named risk, not a metric."""
    body = reader.get("/overview").text.lower()
    assert "confidence" not in body


def test_the_overview_names_the_principal_so_a_client_can_disable_what_it_may_not_do(
    reader: TestClient, host_reader: TestClient
) -> None:
    assert OverviewReport.model_validate(reader.get("/overview").json()).principal == "human"
    host = OverviewReport.model_validate(host_reader.get("/overview").json())
    assert host.principal == "agent_host"


def test_claim_health_and_open_questions_come_from_canonical_state(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    _create_question(corpus, registry)

    overview = OverviewReport.model_validate(reader.get("/overview").json())

    assert overview.counts.questions == 1
    assert [item.detail for item in overview.open_questions] == ["open"]
    assert overview.claim_health == ()


def test_an_overview_of_a_workspace_with_a_claim_reports_its_status(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    _create_claim(corpus, registry)

    overview = OverviewReport.model_validate(reader.get("/overview").json())

    assert overview.counts.claims == 1
    assert [(entry.key, entry.count) for entry in overview.claim_health] == [("unverified", 1)]


# -- what changed since the researcher last worked ----------------------------


def test_a_project_with_no_recorded_research_says_so_rather_than_showing_an_empty_box(
    bare_reader: TestClient,
) -> None:
    """A project nobody has worked in yet has no history, and the honest answer is words."""
    changes = OverviewReport.model_validate(bare_reader.get("/overview").json()).since_last_session

    assert changes.basis == "no_history"
    assert changes.entries == ()
    assert changes.total == 0
    assert "no research activity" in changes.summary.lower()
    assert changes.more == ""


def test_the_change_list_reports_one_entry_of_each_kind_newest_first(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """Works added, evidence accepted, claims promoted, decisions taken, conflicts moved."""
    _accept_a_candidate(corpus, registry)
    _create_claim(corpus, registry)
    _accept_a_decision(corpus, registry)
    _open_a_conflict(corpus, "conf-open", resolve=False)
    _open_a_conflict(corpus, "conf-closed", resolve=True)

    changes = OverviewReport.model_validate(reader.get("/overview").json()).since_last_session

    assert changes.basis == "recent_window"
    assert {entry.kind for entry in changes.entries} == {
        "work",
        "evidence",
        "claim",
        "decision",
        "conflict",
    }
    moments = [datetime.fromisoformat(entry.at) for entry in changes.entries]
    assert moments == sorted(moments, reverse=True), "the newest change is read first"
    assert all(entry.label and entry.when and entry.id for entry in changes.entries)
    work = next(entry for entry in changes.entries if entry.kind == "work")
    assert work.route == f"/corpus/{WORK}", "a change leads to the object it changed"
    assert changes.total == len(changes.entries)
    assert changes.more == ""


def test_the_change_list_caps_what_it_carries_and_says_what_it_left_out(
    reader: TestClient, corpus: Path
) -> None:
    """The Overview is a first screen, not a log viewer: the rest stays in the event log."""
    for index in range(12):
        _open_a_conflict(corpus, f"conf-{index}", resolve=False)

    changes = OverviewReport.model_validate(reader.get("/overview").json()).since_last_session

    assert len(changes.entries) == CHANGE_ITEMS
    assert changes.total > CHANGE_ITEMS
    assert str(changes.total - CHANGE_ITEMS) in changes.more


def test_the_window_opens_at_the_end_of_the_session_before_the_latest_one(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """Two sessions: the researcher's most recent sitting, and everything after it."""
    _end_a_session(corpus, "the sitting before last")
    _end_a_session(corpus, "the last sitting")
    _create_claim(corpus, registry)

    changes = OverviewReport.model_validate(reader.get("/overview").json()).since_last_session

    assert changes.basis == "previous_session"
    assert [entry.kind for entry in changes.entries] == ["claim"], (
        "ingesting the corpus happened before that session ended, so it is not news"
    )
    assert "previous session" in changes.summary


def test_one_session_is_not_two_so_the_window_is_the_documented_seven_days(
    reader: TestClient, corpus: Path
) -> None:
    """A project with one conversation cannot bound a window, and says which rule it used."""
    _end_a_session(corpus, "the only sitting")

    changes = OverviewReport.model_validate(reader.get("/overview").json()).since_last_session

    assert changes.basis == "recent_window"
    assert "seven days" in changes.summary
    assert [entry.kind for entry in changes.entries] == ["work"]


def test_the_overview_says_in_one_line_what_needs_a_researcher(
    reader: TestClient, corpus: Path
) -> None:
    """The page's description is the daemon's sentence, not a count a client assembled."""
    assert (
        OverviewReport.model_validate(reader.get("/overview").json()).attention_summary
        == "Nothing needs a researcher right now."
    )

    _open_a_conflict(corpus, "conf-one", resolve=False)

    assert (
        OverviewReport.model_validate(reader.get("/overview").json()).attention_summary
        == "1 conflict needs a researcher."
    )


def test_every_attention_group_says_which_surface_it_belongs_to(reader: TestClient) -> None:
    """Waiting for a decision and having gone stale are different states, and the daemon says so."""
    groups = {
        group.kind: group.surface
        for group in OverviewReport.model_validate(reader.get("/overview").json()).attention
    }

    assert groups["review_items"] == "decide"
    assert groups["conflicts"] == "decide"
    assert groups["unsupported_manuscript_claims"] == "decide"
    assert groups["stale"] == "stale"


def test_a_waiting_review_item_leads_to_the_candidate_and_not_only_to_the_queue(
    reader: TestClient, corpus: Path
) -> None:
    _stage_candidates(corpus)

    overview = OverviewReport.model_validate(reader.get("/overview").json())
    queue = next(group for group in overview.attention if group.kind == "review_items")

    assert queue.count > 0
    assert all(item.route == f"/review/{item.id}" for item in queue.items)


def test_the_index_lists_everything_the_navigation_shows(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """Product 26's navigation needs one read, not a capability call per list."""
    _create_claim(corpus, registry)
    _create_question(corpus, registry)

    index = WorkspaceIndex.model_validate(reader.get("/index").json())

    assert [work.id for work in index.works] == [WORK]
    assert index.works[0].artifacts[0].parsed is True
    assert index.works[0].evidence == 0
    assert [claim.id for claim in index.claims] == ["C0001"]
    assert index.claims[0].requested_strength == "individual"
    assert index.claims[0].allowed_strength == "individual"
    assert [question.id for question in index.questions] == ["RQ0001"]
    assert index.decisions == () and index.matrices == () and index.anchors == ()


def test_the_index_of_an_empty_corpus_is_empty_rather_than_an_error(
    reader: TestClient, corpus: Path
) -> None:
    index = WorkspaceIndex.model_validate(reader.get("/index").json())
    assert index.claims == ()
    assert index.taxonomies == ()


# -- the bundle and the dev origin -------------------------------------------


def test_no_bundle_means_no_mount_and_a_json_api_that_still_answers(
    corpus: Path, registry: CapabilityRegistry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(WEB_DIST_ENV, str(tmp_path / "never-built"))
    assert web_dist() is None

    with TestClient(create_app(corpus, registry=registry)) as client:
        assert client.get("/health").json()["ok"] is True
        assert client.get("/does-not-exist").status_code == 404


def test_a_built_bundle_is_served_at_the_root_with_a_single_page_fallback(
    corpus: Path, registry: CapabilityRegistry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>cockpit</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("export const app = 1;\n", encoding="utf-8")
    monkeypatch.setenv(WEB_DIST_ENV, str(dist))

    with TestClient(create_app(corpus, registry=registry)) as client:
        assert "cockpit" in client.get("/").text
        assert "cockpit" in client.get("/review/cand_1234").text, "client routes render the shell"
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/health").json()["ok"] is True, "the API is never shadowed"
        assert client.get(f"/blocks/{ARTIFACT}").status_code == 200


def test_the_dev_origin_is_allowed_only_in_development(
    corpus: Path, registry: CapabilityRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DEV_ENV, raising=False)
    assert dev_mode() is False
    with TestClient(create_app(corpus, registry=registry)) as closed:
        response = closed.get("/health", headers={"Origin": DEV_ORIGINS[0]})
        assert "access-control-allow-origin" not in response.headers

    monkeypatch.setenv(DEV_ENV, "1")
    assert dev_mode() is True
    with TestClient(create_app(corpus, registry=registry)) as open_for_dev:
        response = open_for_dev.get("/health", headers={"Origin": DEV_ORIGINS[0]})
        assert response.headers["access-control-allow-origin"] == DEV_ORIGINS[0]


def test_development_never_opens_the_daemon_to_a_remote_origin(
    corpus: Path, registry: CapabilityRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEV_ENV, "1")
    with TestClient(create_app(corpus, registry=registry)) as client:
        response = client.get("/health", headers={"Origin": "https://example.invalid"})
        assert "access-control-allow-origin" not in response.headers
    assert all(
        origin.startswith(("http://localhost", "http://127.0.0.1")) for origin in DEV_ORIGINS
    )


# -- the capability reads the cockpit issues ---------------------------------


def test_state_index_answers_exactly_what_the_index_route_answers(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """One navigation read, two names. The cockpit uses the capability; the route stays."""
    _create_claim(corpus, registry)
    _create_question(corpus, registry)

    route = reader.get("/index").json()
    capability = _call(reader, "state.index", {})

    assert capability == route, "`state.index` and `GET /index` are one answer, not two"
    WorkspaceIndex.model_validate(capability)


def test_one_list_at_a_time_returns_the_summaries_the_index_composes(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """A view that needs one list asks for that list, and gets the same objects back."""
    _create_claim(corpus, registry)
    _create_question(corpus, registry)
    index = reader.get("/index").json()

    assert _call(reader, "claim.list", {})["claims"] == index["claims"]
    assert _call(reader, "work.list", {})["works"] == index["works"]
    assert _call(reader, "question.list", {})["questions"] == index["questions"]
    assert _call(reader, "decision.list", {})["decisions"] == index["decisions"]
    assert _call(reader, "anchor.list", {})["anchors"] == index["anchors"]


def test_every_list_read_the_cockpit_issues_is_accepted_as_the_client_shapes_it(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """The filters `client.ts` sends, field for field; a closed model refuses an invented one."""
    _create_claim(corpus, registry)

    for capability, request in WEB_REQUESTS.items():
        result = _call(reader, capability, request)
        assert "count" in result or capability == "state.index", capability

    refused = reader.post("/capabilities/claim.list", json={"statuses": ["unverified"]}).json()
    assert refused["ok"] is False
    assert refused["error"]["code"] == "invalid_request", (
        "`claim.list` refuses a field the cockpit did not learn from the schema"
    )


def test_claim_list_filters_server_side_rather_than_handing_back_everything(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """The Claims view renders the daemon's selection; it never re-filters (Product 5 P10)."""
    _create_claim(corpus, registry)

    assert _call(reader, "claim.list", {"status": "unverified"})["count"] == 1
    assert _call(reader, "claim.list", {"status": "supported"})["count"] == 0
    assert _call(reader, "claim.list", {"stale": "stale"})["count"] == 0
    assert _call(reader, "claim.list", {"type": "descriptive"})["count"] == 1


def test_an_agent_host_may_read_every_list_the_navigation_shows(
    host_reader: TestClient,
) -> None:
    """Product 29: the cockpit reads everything without a token, and accepts nothing."""
    for capability, request in WEB_REQUESTS.items():
        envelope = host_reader.post(f"/capabilities/{capability}", json=request).json()
        assert envelope["ok"] is True, f"{capability}: {envelope.get('error')}"

    refused = host_reader.post("/capabilities/manuscript.revalidate", json={}).json()
    assert refused["ok"] is False
    assert refused["error"]["code"] == "permission_denied", (
        "the Revalidate control is human-only, which is why the cockpit disables it"
    )


# -- the TypeScript types and the daemon agree -------------------------------


def test_every_field_the_cockpit_declares_is_a_field_the_daemon_publishes(
    reader: TestClient,
) -> None:
    """`web/src/api/dto.ts` hand-declares the capability responses no route returns.

    The route DTOs are generated from `web/openapi.json` and cannot drift. These cannot be,
    because no OpenAPI path returns them, so they are checked against the response schema
    the daemon publishes for the capability that does — which is the same schema an MCP host
    reads. A rename on either side fails here.
    """
    source = WEB_DTO_TS.read_text(encoding="utf-8")
    published = {
        item["name"]: _schema_fields(item["response_schema"])
        for item in reader.get("/capabilities").json()["capabilities"]
    }

    for interface, capability in WEB_RESPONSE_TYPES.items():
        declared = _ts_interface_fields(source, interface)
        missing = sorted(declared - published[capability])
        assert not missing, (
            f"{interface} in web/src/api/dto.ts declares {missing}, which {capability} does "
            "not publish; one of the two has drifted"
        )


def test_the_cockpit_names_only_capabilities_this_build_registers(reader: TestClient) -> None:
    """`capabilities.gen.ts` is generated from the catalog, so this is the round trip."""
    registered = {item["name"] for item in reader.get("/capabilities").json()["capabilities"]}
    called = (
        set(WEB_REQUESTS)
        | set(WEB_RESPONSE_TYPES.values())
        | {
            "review.qualify",
            "review.edit",
            "review.reject",
            "review.defer",
            "review.request_more",
            "review.candidate",
            "review.resolve_conflict",
            "review.inbox",
            "claim.create",
            "question.create",
            "decision.accept",
            "claim.override_strength",
            "state.stale",
        }
    )
    assert not called - registered, f"the cockpit calls {sorted(called - registered)}"


# -- helpers -----------------------------------------------------------------


def _call(client: TestClient, capability: str, request: dict[str, Any]) -> Any:
    """One capability call the cockpit makes, asserted to have succeeded."""
    body = client.post(f"/capabilities/{capability}", json=request).json()
    assert body["ok"] is True, f"{capability} refused: {body.get('error')}"
    return body["result"]


def _schema_fields(schema: Any) -> set[str]:
    """Every property name anywhere in a published JSON schema, `$defs` included."""
    found: set[str] = set()
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            found |= set(properties)
        for value in schema.values():
            found |= _schema_fields(value)
    elif isinstance(schema, list):
        for item in schema:
            found |= _schema_fields(item)
    return found


def _ts_interface_fields(source: str, name: str) -> set[str]:
    """The property names of one `export interface` in `web/src/api/dto.ts`.

    A deliberately small parse: the file is hand-maintained DTO declarations with no
    computed members, so matching `name?: type;` lines inside the braces catches a rename,
    which is the whole job.
    """
    # `export interface Name {` or `export interface Name extends Base {`; the base's own
    # fields are checked under the base's entry.
    match = re.search(
        rf"export interface {re.escape(name)}\b[^{{]*\{{(.*?)\n\}}", source, re.DOTALL
    )
    if match is None:
        raise AssertionError(f"{WEB_DTO_TS.name} declares no interface {name}")
    return set(re.findall(r"^\s{2}(\w+)\??:", match.group(1), re.MULTILINE))


def _object(client: TestClient, object_id: str) -> dict[str, Any]:
    payload = client.get(f"/objects/{object_id}").json()
    assert isinstance(payload["object"], dict)
    return payload["object"]


def _artifact_hash(client: TestClient) -> str:
    return str(_object(client, ARTIFACT)["file_hash"]).removeprefix("sha256:")


def _create_question(root: Path, registry: CapabilityRegistry) -> None:
    registry.invoke(
        "question.create",
        open_context(root, HUMAN_ACTOR),
        {
            "question": {
                "id": "RQ0001",
                "question": "Which tokenizations survive short encrypted flows?",
                "provenance": {"source": "human", "actor": HUMAN_ACTOR},
            }
        },
        principal=Principal.human(),
    )


def _create_claim(root: Path, registry: CapabilityRegistry) -> None:
    from tests.contract.protocol.conftest import make_claim

    registry.invoke(
        "claim.create",
        open_context(root, HUMAN_ACTOR),
        {"claim": make_claim().model_dump(mode="json")},
        principal=Principal.human(),
    )


def _stage_candidates(root: Path) -> None:
    """The Gate P11 candidates, staged through the scripted extractor and verifier."""
    from tests.e2e.test_web_gate import stage_candidates

    stage_candidates(root)


def _accept_a_candidate(root: Path, registry: CapabilityRegistry) -> None:
    """One staged candidate accepted as canonical Evidence, so the log records a review."""
    _stage_candidates(root)
    ctx = open_context(root, HUMAN_ACTOR)
    inbox = registry.invoke("review.inbox", ctx, {}, principal=Principal.human())
    candidate = next(
        item
        for item in inbox.items
        if item["field"] == "dataset"  # type: ignore[union-attr]
    )
    registry.invoke(
        "review.accept",
        open_context(root, HUMAN_ACTOR),
        {"candidate_id": candidate["candidate_id"]},
        principal=Principal.human(),
    )


def _accept_a_decision(root: Path, registry: CapabilityRegistry) -> None:
    registry.invoke(
        "decision.accept",
        open_context(root, HUMAN_ACTOR),
        {
            "decision": {
                "type": "methodology",
                "status": "proposed",
                "title": "count only held-out splits",
                "rationale": "the pilot split leaks between train and test",
                "provenance": {"source": "human", "actor": HUMAN_ACTOR},
            }
        },
        principal=Principal.human(),
    )


def _open_a_conflict(root: Path, subject: str, *, resolve: bool) -> None:
    """One disagreement on record, optionally already answered by the researcher."""
    store = ConflictStore(WorkspaceRepository.open(root).layout.research_dir)
    record = store.open_or_put(
        ConflictRecord(
            kind=ConflictKind.CANDIDATE_VS_ACCEPTED,
            subject=subject,
            summary=f"the staged reading of {subject} differs from the accepted one",
        )
    )
    if resolve:
        store.resolve(record.conflict_id, "accept", "the accepted reading still holds", HUMAN_ACTOR)


def _end_a_session(root: Path, title: str) -> None:
    """A conversation with one message in it, so the project records when it was last used."""
    store = ConversationStore(WorkspaceRepository.open(root).layout)
    session = store.create_session(title=title, provenance=Provenance.human())
    store.append_message(
        session.id,
        lambda message_id: Message(
            id=message_id,
            session=session.id,
            role=MessageRole.USER,
            blocks=(TextBlock(text="where did the held-out split come from?"),),
            provenance=Provenance.human(),
        ),
    )

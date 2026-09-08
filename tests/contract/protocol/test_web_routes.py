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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from research_harness.capabilities.context import open_context
from research_harness.capabilities.dto import InitProjectRequest
from research_harness.capabilities.handlers import init_project
from research_harness.capabilities.permissions import Principal
from research_harness.capabilities.reads import (
    ArtifactSummary,
    ClaimRef,
    EvidenceSummary,
    WorkSummary,
    corpus_attention,
    evidence_attention,
    evidence_questions,
)
from research_harness.capabilities.registry import CapabilityRegistry
from research_harness.domain.base import Provenance
from research_harness.domain.conversation import Message, MessageRole, TextBlock
from research_harness.domain.ids import ClaimId, WorkId
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.evidence.conflicts import ConflictKind, ConflictRecord, ConflictStore
from research_harness.projection.rows import manuscript_anchor_key
from research_harness.protocol.dto import ArtifactBlocks, OverviewReport, WorkspaceIndex
from research_harness.server.app import (
    CHANGE_ITEMS,
    DEV_ENV,
    DEV_ORIGINS,
    WEB_DIST_ENV,
    _ObjectNames,
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
    "ClaimGroup": "claim.list",
    "ClaimList": "claim.list",
    "WorkList": "work.list",
    "QuestionGroup": "question.list",
    "CorpusAttentionGroup": "work.list",
    "CorpusAttentionItem": "work.list",
    "CorpusQuestion": "work.list",
    "EvidenceAttentionGroup": "evidence.list",
    "EvidenceAttentionItem": "evidence.list",
    "EvidenceQuestion": "evidence.list",
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


def test_every_kind_of_object_a_page_names_has_one_title_composed_here(
    corpus: Path, registry: CapabilityRegistry
) -> None:
    """Naming an object is a judgement about the workspace, so the daemon makes it once.

    The Stale page, the Overview's "Gone stale" group and the Conflicts page all show
    objects the daemon reports by id. Which field of a record is its name — a Work's
    title, a Claim's statement, a Decision's title or, when it has none, the rationale it
    was taken for, the field and work an Evidence object was accepted under — is decided
    here, and every one of those surfaces reads the same answer (Product 5 P10).
    """
    _accept_a_candidate(corpus, registry)
    _create_claim(corpus, registry)
    _create_question(corpus, registry)
    _accept_a_decision(corpus, registry)
    _attach_a_sentence(corpus)
    repo = WorkspaceRepository.open(corpus)
    names = _ObjectNames(repo)
    evidence = next(str(record.id) for record in repo.iter_evidence(WorkId(WORK)))
    anchor = next(
        manuscript_anchor_key(record.file, record.sentence_fingerprint)
        for record in repo.iter_anchors()
    )

    assert names.title(WORK) == "Deep Representations for Encrypted Network Traffic"
    assert names.title("C0001") == (
        "Byte-level tokenization improves recall on short encrypted flows."
    )
    assert names.title("RQ0001") == "Which tokenizations survive short encrypted flows?"
    assert names.title("D0001") == "count only held-out splits"
    assert names.title(evidence) == ("dataset · Deep Representations for Encrypted Network Traffic")
    assert names.title(anchor) == "Existing systems disagree about byte-level tokenization."
    assert names.title("W0404") == "", "an id nothing in this workspace answers to names nothing"


def test_a_stale_object_the_overview_reports_carries_its_name_and_keeps_its_id(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """The Overview's "Gone stale" group is the Stale page's items, titles included."""
    _accept_a_candidate(corpus, registry)
    _create_claim(corpus, registry)
    _make_the_claim_stale(corpus, registry)

    overview = OverviewReport.model_validate(reader.get("/overview").json())
    stale = next(group for group in overview.attention if group.surface == "stale")

    assert [item.label for item in stale.items] == ["C0001"]
    assert stale.items[0].title == (
        "Byte-level tokenization improves recall on short encrypted flows."
    )
    assert "E0001" not in stale.items[0].detail, "the evidence that moved is named, not coded"
    assert stale.items[0].detail.startswith("upstream evidence “dataset · ")


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


def test_each_change_says_whether_the_researcher_or_the_daemon_recorded_it(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """A returning researcher has to tell her own decisions from what ran without her.

    The attribution is read off the record and nowhere else: the event log stores the actor
    of every mutation it describes, and a resolved conflict stores the researcher who
    answered it. Nothing here is inferred from the kind of change.
    """
    _accept_a_candidate(corpus, registry)
    _accept_a_decision(corpus, registry)
    _open_a_conflict(corpus, "conf-closed", resolve=True)

    changes = OverviewReport.model_validate(reader.get("/overview").json()).since_last_session

    recorded = {entry.kind: entry.by for entry in changes.entries}
    assert recorded["work"] == "researcher", "the corpus was ingested by the researcher"
    assert recorded["evidence"] == "researcher", "only a researcher accepts evidence"
    assert recorded["decision"] == "researcher"
    answered = next(entry for entry in changes.entries if "resolved a conflict" in entry.label)
    assert answered.by == "researcher", "a conflict is answered by the researcher who resolved it"


def test_a_change_the_researcher_did_not_make_is_attributed_to_the_daemon(
    reader: TestClient, corpus: Path
) -> None:
    """The log's actor decides, so an event no researcher recorded says the daemon.

    Every capability that writes one of these events requires human authority today, so the
    only way to put a non-human actor in the log is to write the line the way the log stores
    it. That is the point: the Overview reads the actor it was given rather than assuming
    the researcher was behind every change.
    """
    from research_harness.domain.enums import ResearchEventType
    from research_harness.domain.research import ResearchEvent
    from research_harness.workspace.serialization import dump_jsonl_line

    layout = WorkspaceRepository.open(corpus).layout
    with layout.events_file.open("a", encoding="utf-8") as stream:
        stream.write(
            dump_jsonl_line(
                ResearchEvent(
                    event=ResearchEventType.WORK_INGESTED,
                    subjects=(WorkId("W0002"),),
                    actor="model:scripted-extractor",
                    summary="registered W0002 from a discovery run",
                )
            )
        )

    changes = OverviewReport.model_validate(reader.get("/overview").json()).since_last_session

    proposed = next(entry for entry in changes.entries if entry.detail == "W0002")
    assert proposed.by == "daemon"


def test_a_conflict_nothing_attributes_is_left_unattributed_rather_than_guessed(
    reader: TestClient, corpus: Path
) -> None:
    """The conflict store records no actor for an opening, so the entry claims none.

    A conflict that names the run it came out of was opened by that run — the daemon — and
    says so. One that names nothing is left unattributed: inventing an actor for it would be
    the cockpit deciding what the record does not say.
    """
    _open_a_conflict(corpus, "conf-anonymous", resolve=False)
    _open_a_conflict(corpus, "conf-from-a-run", resolve=False, run="run_0001")

    changes = OverviewReport.model_validate(reader.get("/overview").json()).since_last_session
    opened = {
        entry.detail: entry
        for entry in changes.entries
        if entry.kind == "conflict" and "opened" in entry.label
    }

    assert opened["conf-anonymous"].by == ""
    assert opened["conf-from-a-run"].by == "daemon"

    # And the sentence stands up without the subject a client would otherwise lead it with.
    # An attributed change is verb-initial, because the client writes "The daemon" in front
    # of it; an unattributed one has no such word coming, so the daemon writes the passive
    # rather than handing the client an imperative — "opened a conflict:" reads as an order.
    assert opened["conf-from-a-run"].label.startswith("opened a conflict:")
    assert opened["conf-anonymous"].label.startswith("a conflict was opened:")


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


def test_the_overview_groups_the_open_conflicts_by_the_kind_of_disagreement(
    reader: TestClient, corpus: Path
) -> None:
    """The Conflicts page reads its grouping; it never decides from `kind` which is which."""
    _open_a_conflict(corpus, "C0001", resolve=False)
    _open_a_conflict(corpus, "cand_44c1f007fc0db0b2", resolve=False)

    overview = OverviewReport.model_validate(reader.get("/overview").json())
    groups = overview.conflict_groups

    assert [group.kind for group in groups] == ["candidate_vs_accepted"]
    assert groups[0].count == 2
    assert groups[0].label == "2 conflicts"
    assert groups[0].surface == "conflict"
    assert overview.conflict_summary.startswith("2 conflicts are open")


def test_an_open_conflict_leads_to_where_that_disagreement_is_decided(
    reader: TestClient, corpus: Path
) -> None:
    """A candidate is decided in the review screen; a Claim on its own page; nothing else links."""
    _open_a_conflict(corpus, "cand_44c1f007fc0db0b2", resolve=False)
    _open_a_conflict(corpus, "C0001", resolve=False)
    _open_a_conflict(corpus, "table-1", resolve=False)

    routes = {
        item.label: item.route
        for group in OverviewReport.model_validate(reader.get("/overview").json()).conflict_groups
        for item in group.items
    }

    assert routes["cand_44c1f007fc0db0b2"] == "/review/cand_44c1f007fc0db0b2"
    assert routes["C0001"] == "/claims/C0001"
    assert routes["table-1"] == ""


def test_a_conflict_over_a_staged_candidate_is_named_the_way_the_queue_names_it(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """A `cand_<16 hex>` id is where the record lives, never what the disagreement is about.

    The candidate is called `<field> · <work>` in the review inbox, on the review screen
    and in the palette, so a conflict over it is called that too — and the Overview's own
    list of conflicts composes the subject with the same function, so one disagreement
    never carries two names (Product 5 P10).
    """
    candidate = _staged_candidate(corpus, registry, "metric_result")
    _open_a_conflict(corpus, candidate, resolve=False)

    overview = OverviewReport.model_validate(reader.get("/overview").json())
    disputed = overview.conflict_groups[0].items[0]
    listed = next(group for group in overview.attention if group.kind == "conflicts").items[0]

    assert disputed.label == "metric_result · W0001"
    assert disputed.route == f"/review/{candidate}", "the id is in the route, not in the label"
    assert listed.label == "candidate_vs_accepted · metric_result · W0001"


def test_a_conflict_over_a_claim_is_named_by_the_claim_it_is_about(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """The Claims page calls C0001 by its statement, so the Conflicts page does too."""
    _create_claim(corpus, registry)
    _open_a_conflict(corpus, "C0001", resolve=False)

    overview = OverviewReport.model_validate(reader.get("/overview").json())
    disputed = overview.conflict_groups[0].items[0]

    assert disputed.label == "Byte-level tokenization improves recall on short encrypted flows."
    assert disputed.route == "/claims/C0001"


def test_a_subject_this_workspace_cannot_name_keeps_the_text_the_record_holds(
    reader: TestClient, corpus: Path
) -> None:
    """Inventing a name for a subject nothing answers to would be worse than the record."""
    _open_a_conflict(corpus, "table-1", resolve=False)

    overview = OverviewReport.model_validate(reader.get("/overview").json())

    assert overview.conflict_groups[0].items[0].label == "table-1"


def test_a_project_with_nothing_in_dispute_says_so_in_its_own_sentence(
    bare_reader: TestClient,
) -> None:
    overview = OverviewReport.model_validate(bare_reader.get("/overview").json())

    assert overview.conflict_groups == ()
    assert overview.conflict_summary == "Nothing in this project is in dispute."


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


# -- what in the corpus needs a researcher -----------------------------------


def _work(work_id: str, **overrides: Any) -> WorkSummary:
    """One `work.list` row, as the daemon composes it, with one thing changed."""
    fields: dict[str, Any] = {
        "id": work_id,
        "title": f"study {work_id}",
        "screening": "included",
        "evidence": 1,
        "artifacts": (
            ArtifactSummary(
                id=f"A{work_id[1:]}-1",
                version=f"V{work_id[1:]}-1",
                kind="pdf",
                mime_type="application/pdf",
                original_filename=f"{work_id}.pdf",
                size_bytes=1024,
                parsed=True,
            ),
        ),
    }
    fields.update(overrides)
    return WorkSummary(**fields)


def test_work_list_names_the_sources_that_need_a_researcher(reader: TestClient) -> None:
    """The Corpus page opens with this, so `work.list` has to answer it (Product 5 P10).

    The fixture workspace holds one Work, ingested and parsed, with nothing accepted from
    it yet - so the one thing it asks for is a reader, and the daemon says so in the
    sentence the page prints.
    """
    result = _call(reader, "work.list", {})

    assert [group["kind"] for group in result["attention"]] == ["unread"], (
        "a parsed Work nothing has been accepted from is the corpus's own open work"
    )
    group = result["attention"][0]
    assert group["label"] == "1 work has nothing accepted from it yet"
    assert group["count"] == 1
    assert group["more"] == "", "nothing was left out, so nothing says it was"
    assert [item["id"] for item in group["items"]] == [WORK]
    assert group["items"][0]["route"] == f"/corpus/{WORK}", (
        "the daemon says where one Work lives, exactly as `GET /overview` does"
    )


def test_an_unparsed_source_is_named_before_one_nothing_was_accepted_from(
    tmp_path: Path, registry: CapabilityRegistry
) -> None:
    """A file with no stored parse cannot have a span anchored in it at all (Product 16).

    Asking a researcher to read from it would be asking for the wrong thing, so the group
    it belongs in is the earlier one, and the sentence names the file rather than the work.
    """
    root = init_project(InitProjectRequest(root=tmp_path / "unparsed", name="unparsed")).root
    registry.invoke(
        "corpus.ingest",
        open_context(root, HUMAN_ACTOR),
        {"path": str(FIXTURE)},
        principal=Principal.human(),
    )
    token = ensure_token(root)
    with TestClient(create_app(root, registry=registry)) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        result = _call(client, "work.list", {})

    assert [group["kind"] for group in result["attention"]] == ["unparsed"]
    assert result["attention"][0]["label"] == "1 work has no readable text yet"
    # Nothing to add: the group's own line already said it, and a detail repeating it under
    # every work in the group is the same sentence printed three times.
    assert result["attention"][0]["items"][0]["detail"] == ""


def test_a_source_is_named_by_the_first_thing_missing_from_it() -> None:
    """Screening, then a file, then a parse, then a reading: the order it is acquired in.

    Two of these states no capability can reach - nothing screens a Work or unregisters its
    file - so the judgement is exercised where it lives, over the rows `work.list` builds.
    """
    unparsed = _work("W0003").artifacts[0].model_copy(update={"parsed": False})
    groups = corpus_attention(
        (
            _work("W0001", screening="screened", artifacts=(), evidence=0),
            _work("W0002", artifacts=(), evidence=0),
            _work("W0003", artifacts=(unparsed,), evidence=0),
            _work("W0004", evidence=0),
            _work("W0005"),
            _work("W0006", screening="excluded", artifacts=(), evidence=0),
        )
    )

    assert [(group.kind, group.count) for group in groups] == [
        ("screening", 1),
        ("no_file", 1),
        ("unparsed", 1),
        ("unread", 1),
    ], "a Work already read from, and one screened out, ask for nothing"
    assert groups[0].items[0].id == "W0001"
    assert groups[2].items[0].detail == "", "one unreadable file is what the group line says"


def test_the_state_every_work_is_ingested_in_is_not_an_open_decision() -> None:
    """`discovered` is the field's default and nothing in the cockpit moves it.

    Counting it would put every source a project ever ingested into one group with no next
    step in it, which is the opposite of naming what needs a researcher.
    """
    groups = corpus_attention((_work("W0001", screening="discovered"),))

    assert groups == (), "a Work that has been read from asks for nothing, however it is screened"


def test_a_group_larger_than_the_page_shows_says_what_it_left_out() -> None:
    """The cap is the page's, and the sentence that admits it is the daemon's."""
    groups = corpus_attention(tuple(_work(f"W{index:04d}", evidence=0) for index in range(1, 12)))

    assert groups[0].count == 11
    assert groups[0].label == "11 works have nothing accepted from them yet"
    assert len(groups[0].items) == 8
    assert groups[0].more == "3 more are in the list below."


def test_a_group_the_page_can_hold_names_every_work_rather_than_a_sentence() -> None:
    """A cap sentence is neither a work nor a link, so a group that fits does not need one.

    "1 more is in the list below" leaves a reader to go and find that work themselves. Up
    to the cap the group names every work it counts, each of them a link to itself, and the
    sentence disappears because there is nothing it would be standing in for.
    """
    groups = corpus_attention(tuple(_work(f"W{index:04d}", evidence=0) for index in range(1, 7)))

    assert groups[0].count == 6
    assert len(groups[0].items) == 6
    assert groups[0].more == ""


def test_a_corpus_every_source_of_which_can_be_read_names_nothing() -> None:
    """Four lines of zero are not an answer; the page's own empty state is."""
    assert corpus_attention((_work("W0001"), _work("W0002"))) == ()


# -- the evidence index composes its own lead and its own questions ----------


def _evidence(evidence_id: str, **overrides: Any) -> EvidenceSummary:
    """One `evidence.list` row, as the daemon composes it, with one thing changed."""
    fields: dict[str, Any] = {
        "id": evidence_id,
        "work": "W0001",
        "work_title": "Structured traffic representations",
        "artifact": "A0001-1",
        "field": "dataset",
        "status": "accepted",
        "origin": "source_observed",
        "evidence_type": "experimental_setup",
        "strength": "direct",
        "review_tier": 1,
        "exact_text": "We evaluate on CICIDS2017 and report macro F1.",
        "stale": "fresh",
        "claims": (ClaimRef(id="C0001", title="a claim that rests on it"),),
        "accepted": "8 September 2026",
        "accepted_at": datetime.now(UTC).isoformat(),
    }
    fields.update(overrides)
    return EvidenceSummary(**fields)


def test_accepted_evidence_is_named_by_the_first_thing_wrong_with_it() -> None:
    """Decay first, then the disagreement that stands, then what landed nowhere.

    A stale span is also uncited more often than not, so the groups are disjoint and take
    the first thing wrong: counting one absence twice would offer two controls that lead to
    the same row, which is the rule the corpus already keeps.
    """
    groups = evidence_attention(
        (
            _evidence("E0001", stale="stale", status="stale", claims=()),
            _evidence("E0002", status="superseded"),
            _evidence("E0003", verdict="contradicted"),
            _evidence("E0004", verdict="insufficient_evidence", claims=()),
            _evidence("E0005", claims=()),
            _evidence("E0006"),
        )
    )

    assert [(group.kind, group.count) for group in groups] == [
        ("stale", 1),
        ("superseded", 1),
        ("contradicted", 2),
        ("uncited", 1),
    ], "a fresh, supported, cited piece of evidence asks for nothing"
    assert groups[0].label == "1 piece of evidence went stale when its source changed"
    assert groups[3].label == "1 piece of evidence is cited by no claim"
    # The row's own name, not its id: an index of two hundred `E0007`s is unreadable.
    assert groups[0].items[0].label == "Dataset · Structured traffic representations"
    assert groups[0].items[0].route == "/evidence/E0001"
    # A verifier that contradicted a reading and one that found it insufficient are two
    # different pieces of news, and the group's own line states neither.
    assert [item.detail for item in groups[2].items] == [
        "the verifier contradicted it",
        "the verifier found the evidence insufficient",
    ]
    # Nothing to add where the group's line already said it.
    assert groups[0].items[0].detail == ""


def test_an_evidence_group_larger_than_the_page_shows_says_what_it_left_out() -> None:
    """The cap is the page's, and the sentence that admits it is the daemon's."""
    groups = evidence_attention(
        tuple(_evidence(f"E{index:04d}", claims=()) for index in range(1, 12))
    )

    assert groups[0].count == 11
    assert groups[0].label == "11 pieces of evidence are cited by no claim"
    assert len(groups[0].items) == 8
    assert groups[0].more == "3 more are in the list below."


def test_a_record_with_nothing_wrong_in_it_names_nothing() -> None:
    """Four lines of zero are not an answer; the page's own empty state is."""
    assert evidence_attention((_evidence("E0001"), _evidence("E0002"))) == ()


def test_the_evidence_index_offers_only_the_questions_something_answers() -> None:
    """A control that narrows a list to nothing is a dead end wearing a count of zero."""
    now = datetime.now(UTC)
    questions = evidence_questions(
        (
            _evidence("E0001", strength="derived"),
            _evidence("E0002", origin="researcher_inferred", claims=()),
            _evidence("E0003", accepted_at="2020-01-01T00:00:00+00:00"),
        ),
        now=now,
    )
    asked = {question.kind: question for question in questions}

    # No stale, superseded or contradicted evidence in this record, so none of the three is
    # offered as a control at all.
    assert set(asked) == {"uncited", "derived", "interpretive", "recent"}
    assert asked["derived"].label == "Derived, not direct"
    assert asked["derived"].count == 1
    assert asked["derived"].summary == (
        "1 of 3 pieces of evidence is derived rather than read directly from a source."
    )
    # Two of the three were accepted just now; the third was accepted years ago.
    assert asked["recent"].count == 2
    assert asked["recent"].summary == (
        "2 of 3 pieces of evidence were accepted in the last 7 days."
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


def test_claim_list_groups_the_claims_whose_evidence_cannot_carry_them(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """Product 42 G: a claim asking for more than its evidence allows is the failure state.

    Which claims those are is the same judgement the summaries already record, so the list
    draws the line and orders the groups; the Claims page reads them (Product 5 P10).
    """
    _create_claim(corpus, registry)
    _create_overreaching_claim(corpus, registry)

    result = _call(reader, "claim.list", {})

    assert [group["kind"] for group in result["groups"]] == ["overreaching"]
    assert result["groups"][0]["label"] == "1 claim asks for more than its evidence allows"
    assert result["groups"][0]["claims"] == ["C0002"]
    assert result["summary"] == "1 claim asks for more than its evidence allows."


def test_claim_list_says_the_work_is_done_rather_than_reporting_its_size(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """The page's first sentence names work. A project with none says that, not "1 claim"."""
    assert _call(reader, "claim.list", {})["summary"] == (
        "This project has registered no claims yet."
    )

    _create_claim(corpus, registry)

    assert _call(reader, "claim.list", {})["groups"] == []
    assert _call(reader, "claim.list", {})["summary"] == (
        "Every registered claim stands where its evidence puts it."
    )


def test_question_list_groups_what_is_still_open_and_reads_the_oldest_first(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """Product 31: a question stays open until a researcher resolves it, so age is the order."""
    _create_question(corpus, registry)
    _create_question(corpus, registry, question_id="RQ0002", text="Which metrics are comparable?")
    _create_question(corpus, registry, question_id="RQ0003", text="What did the pilot split leak?")
    _answer_question(corpus, registry, "RQ0002")

    result = _call(reader, "question.list", {})
    groups = {group["kind"]: group for group in result["groups"]}

    assert [group["kind"] for group in result["groups"]] == ["unanswered", "answered"]
    assert groups["unanswered"]["surface"] == "waiting"
    assert groups["answered"]["surface"] == "settled"
    assert groups["unanswered"]["questions"] == ["RQ0001", "RQ0003"]
    assert groups["answered"]["questions"] == ["RQ0002"]
    assert groups["unanswered"]["label"] == "2 questions are still open"
    assert result["summary"] == "2 questions are still open."


def test_a_question_group_states_the_one_status_its_own_line_already_says(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """So a row badges its status only where the status is what the row has to add.

    "1 question is still open" says `open` about every row under it, and a badge repeating
    that beside each question would be the group's name said twice. Which status a group
    states is part of composing the grouping, so the daemon says it.
    """
    _create_question(corpus, registry)
    _create_question(
        corpus, registry, question_id="RQ0002", text="Which captures re-encrypt a flow?"
    )
    _answer_question(corpus, registry, "RQ0002")

    groups = {
        group["kind"]: group["status"] for group in _call(reader, "question.list", {})["groups"]
    }

    assert groups == {"unanswered": "open", "answered": "answered"}


def test_question_list_says_when_every_question_it_holds_has_been_answered(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    assert _call(reader, "question.list", {})["summary"] == (
        "This project has registered no questions yet."
    )

    _create_question(corpus, registry)
    _answer_question(corpus, registry, "RQ0001")

    assert _call(reader, "question.list", {})["summary"] == (
        "Every question this project registered has been answered."
    )


def test_a_question_carries_the_claims_that_bear_on_it_by_what_they_assert(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """ "Bearing on it: C0001" is a code; the Claims page calls C0001 by its statement.

    The statement is the Claim's own name, so the daemon carries it beside the id rather
    than leaving each page to look it up and risk two accounts of what C0001 says.
    """
    _create_claim(corpus, registry)
    _create_question(corpus, registry)
    registry.invoke(
        "question.update",
        open_context(corpus, HUMAN_ACTOR),
        {"question_id": "RQ0001", "claims": ["C0001"]},
        principal=Principal.human(),
    )

    question = _call(reader, "question.list", {})["questions"][0]

    assert question["claims"] == ["C0001"], "the ids stay, for every reader written on them"
    assert question["bearing"] == [
        {
            "id": "C0001",
            "title": "Byte-level tokenization improves recall on short encrypted flows.",
        }
    ]


def test_a_question_says_when_it_was_registered_so_the_oldest_is_visible(
    reader: TestClient, corpus: Path, registry: CapabilityRegistry
) -> None:
    """The order alone does not say "longest"; the date each row carries does."""
    _create_question(corpus, registry)

    opened = _call(reader, "question.list", {})["questions"][0]["opened"]

    assert opened == datetime.now(UTC).date().isoformat()


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


def _create_question(
    root: Path,
    registry: CapabilityRegistry,
    question_id: str = "RQ0001",
    text: str = "Which tokenizations survive short encrypted flows?",
) -> None:
    registry.invoke(
        "question.create",
        open_context(root, HUMAN_ACTOR),
        {
            "question": {
                "id": question_id,
                "question": text,
                "provenance": {"source": "human", "actor": HUMAN_ACTOR},
            }
        },
        principal=Principal.human(),
    )


def _create_overreaching_claim(root: Path, registry: CapabilityRegistry) -> None:
    """A claim asking for L3 on evidence that allows L0: the state Product 42 G forbids."""
    from tests.contract.protocol.conftest import make_claim

    claim = make_claim(claim_id=ClaimId("C0002"), statement="Existing systems generally agree")
    payload = claim.model_dump(mode="json")
    payload["assessment"]["requested_strength"] = "field_generalization"
    payload["assessment"]["allowed_strength"] = "individual"
    registry.invoke(
        "claim.create",
        open_context(root, HUMAN_ACTOR),
        {"claim": payload},
        principal=Principal.human(),
    )


def _answer_question(root: Path, registry: CapabilityRegistry, question: str) -> None:
    """One question resolved, so the list has a settled group as well as a waiting one."""
    registry.invoke(
        "question.update",
        open_context(root, HUMAN_ACTOR),
        {"question_id": question, "status": "answered"},
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


def _staged_candidate(root: Path, registry: CapabilityRegistry, field: str) -> str:
    """The id of one staged candidate, so a conflict can be opened against it."""
    _stage_candidates(root)
    inbox = registry.invoke(
        "review.inbox", open_context(root, HUMAN_ACTOR), {}, principal=Principal.human()
    )
    return str(
        next(
            item["candidate_id"]
            for item in inbox.items  # type: ignore[union-attr]
            if item["field"] == field
        )
    )


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


def _attach_a_sentence(root: Path) -> None:
    """One manuscript anchor on record, appended the way the workspace stores them.

    The daemon names an anchor by the sentence it holds, and nothing else in this file
    writes one; going through the manuscript workspace to get a single line into
    `manuscript/anchors.jsonl` would test the editor rather than the naming.
    """
    from research_harness.domain.manuscript import ManuscriptAnchor
    from research_harness.workspace.serialization import dump_jsonl_line

    layout = WorkspaceRepository.open(root).layout
    layout.anchors_file.parent.mkdir(parents=True, exist_ok=True)
    anchor = ManuscriptAnchor(
        file="main.tex",
        line_start=17,
        line_end=17,
        sentence="Existing systems disagree about byte-level tokenization.",
        sentence_fingerprint=f"sha256:{'b' * 64}",
        claim=ClaimId("C0001"),
        provenance=Provenance.human(HUMAN_ACTOR),
    )
    with layout.anchors_file.open("a", encoding="utf-8") as stream:
        stream.write(dump_jsonl_line(anchor))


def _make_the_claim_stale(root: Path, registry: CapabilityRegistry) -> None:
    """Real decay under the Claim: the evidence it rests on is declared changed.

    Nothing asks for a stale mark. The Claim is related to the accepted Evidence, the
    projection is rebuilt, and the daemon's own invalidation hook runs over that Evidence
    — which is what a mutation touching it would have done (Product 37, ADR-008).
    """
    from research_harness.capabilities.invalidation import DependencyInvalidation
    from research_harness.projection.rebuild import rebuild_workspace

    repo = WorkspaceRepository.open(root)
    evidence = [str(record.id) for record in repo.iter_evidence(WorkId(WORK))]
    for identifier in evidence:
        registry.invoke(
            "claim.relate",
            open_context(root, HUMAN_ACTOR),
            {"claim_id": "C0001", "relation": {"evidence": identifier, "relation": "supports"}},
            principal=Principal.human(),
        )
    repo = WorkspaceRepository.open(root)
    rebuild_workspace(repo)
    DependencyInvalidation().invalidate(repo, evidence)


def _open_a_conflict(root: Path, subject: str, *, resolve: bool, run: str | None = None) -> None:
    """One disagreement on record, optionally already answered by the researcher.

    `run` is the run that produced it, which is the only thing the store keeps about who
    opened a conflict; a record without one is a conflict nothing in the workspace attributes.
    """
    store = ConflictStore(WorkspaceRepository.open(root).layout.research_dir)
    record = store.open_or_put(
        ConflictRecord(
            kind=ConflictKind.CANDIDATE_VS_ACCEPTED,
            subject=subject,
            summary=f"the staged reading of {subject} differs from the accepted one",
            run_id=run,
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

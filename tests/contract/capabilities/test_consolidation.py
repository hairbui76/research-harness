"""Follow-ups the module authors asked for, each stated as the rule it defends.

Five separate things are checked here, and they share a fixture rather than a subject:

* `manuscript.attach_claim` is a human act, exactly like `evidence.accept`;
* `decision.supersede` logs `decision.superseded`, whatever kind of decision it retires;
* `note.discard` records the researcher's reason, and `note.add` records where a capture
  came from as provenance rather than as note text;
* `evidence.accept` allocates the real `EvidenceId` itself, so a transport that posts a
  staged candidate verbatim gets a correct id;
* the registry and `CAPABILITY_HANDLERS` name the same set of capabilities.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.claims_ext import CLAIM_EXTENSION_HANDLERS
from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import (
    AcceptDecisionRequest,
    AcceptEvidenceRequest,
    AddNoteRequest,
    AttachManuscriptAnchorRequest,
)
from research_harness.capabilities.extra_handlers import (
    EXTRA_CAPABILITY_HANDLERS,
    DiscardNoteRequest,
    SupersedeDecisionRequest,
    discard_note_mutation,
    supersede_decision,
)
from research_harness.capabilities.handlers import (
    CAPABILITY_HANDLERS,
    PROVISIONAL_EVIDENCE_ID,
    accept_decision,
    accept_evidence,
    add_note,
    attach_manuscript_anchor,
    next_evidence_id,
)
from research_harness.capabilities.permissions import Permission, Principal
from research_harness.capabilities.registry import build_default_registry
from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    DecisionStatus,
    DecisionType,
    EvidenceStatus,
    NoteStatus,
    ProvenanceSource,
    ResearchEventType,
    VerificationVerdict,
)
from research_harness.domain.errors import AuthorityError
from research_harness.domain.ids import ClaimId, DecisionId, EvidenceId
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.domain.research import Decision
from research_harness.evidence.staging import PROVISIONAL_EVIDENCE_ID as STAGED_ID
from research_harness.workspace.repository import WorkspaceRepository

from .conftest import MODEL_ACTOR, Registered, make_evidence

VERDICT = VerificationVerdict.SUPPORTED


@pytest.fixture
def model_project(project: CapabilityContext) -> Iterator[CapabilityContext]:
    """The same workspace, acting as a model rather than as the researcher."""
    yield open_context(project.root, MODEL_ACTOR)


def anchor_for(claim: ClaimId) -> ManuscriptAnchor:
    """A manuscript anchor binding one sentence to ``claim``."""
    return ManuscriptAnchor(
        claim=claim,
        file="main.tex",
        line_start=12,
        line_end=12,
        sentence="TrafficLM reaches an F1 of 94.32 on CICIDS2017.",
        sentence_fingerprint=f"sha256:{'a' * 64}",
        provenance=Provenance.human(),
    )


# -- 1. the human gate on manuscript attachment ------------------------------


def test_attaching_a_manuscript_sentence_needs_a_human_actor(
    model_project: CapabilityContext, registered: Registered
) -> None:
    """An anchor makes a sentence auditable; binding one is the researcher's act."""
    with pytest.raises(AuthorityError) as refused:
        attach_manuscript_anchor(
            model_project,
            AttachManuscriptAnchorRequest(anchor=anchor_for(ClaimId("C0001"))),
        )
    assert "only a human actor" in str(refused.value)
    assert not list(model_project.repo.iter_anchors())


def test_the_manuscript_gate_reads_the_same_as_the_evidence_gate(
    model_project: CapabilityContext, registered: Registered
) -> None:
    """Both refusals are `AuthorityError` and neither writes anything (ADR-007)."""
    interpretive = make_evidence(registered).touch(id=EvidenceId("E0001"))
    with pytest.raises(AuthorityError):
        accept_evidence(
            model_project,
            AcceptEvidenceRequest(candidate=interpretive, verdict=VERDICT),
        )
    with pytest.raises(AuthorityError):
        attach_manuscript_anchor(
            model_project,
            AttachManuscriptAnchorRequest(anchor=anchor_for(ClaimId("C0001"))),
        )


def test_manuscript_attach_is_human_only_in_the_registry() -> None:
    spec = build_default_registry().get("manuscript.attach_claim")
    assert spec.human_only
    assert spec.permission is Permission.MUTATE
    assert spec.descriptor().human_only


# -- 2. `decision.superseded` ------------------------------------------------


def accepted_decision(ctx: CapabilityContext, kind: DecisionType) -> Decision:
    """One accepted Decision of ``kind``, written through `decision.accept`."""
    number = len(ctx.repo.list_decisions()) + 1
    decision = Decision(
        id=DecisionId(f"D{number:04d}"),
        type=kind,
        status=DecisionStatus.PROPOSED,
        title=f"a {kind.value} decision",
        rationale="because the record needs the reason",
        taxonomy_terms=("raw_sequential",) if kind is DecisionType.TAXONOMY_REVISION else (),
        provenance=Provenance.human(),
    )
    accept_decision(ctx, AcceptDecisionRequest(decision=decision))
    return ctx.repo.get_decision(decision.id)


@pytest.mark.parametrize("kind", [DecisionType.TAXONOMY_REVISION, DecisionType.METHODOLOGY])
def test_superseding_a_decision_logs_decision_superseded(
    project: CapabilityContext, kind: DecisionType
) -> None:
    """`taxonomy.revised` names a vocabulary change; retiring a decision is its own fact."""
    decision = accepted_decision(project, kind)
    response = supersede_decision(
        project,
        SupersedeDecisionRequest(decision_id=decision.id, reason="a better term list exists"),
    )
    assert response.event.event is ResearchEventType.DECISION_SUPERSEDED
    assert response.event.payload["reason"] == "a better term list exists"
    assert project.repo.get_decision(decision.id).status is DecisionStatus.SUPERSEDED


def test_decision_superseded_is_a_named_event_type() -> None:
    assert ResearchEventType.DECISION_SUPERSEDED.value == "decision.superseded"


# -- 3. `note.discard` reason, and `note.add` source -------------------------


def test_discarding_a_note_records_the_reason_in_its_event(project: CapabilityContext) -> None:
    added = add_note(project, AddNoteRequest(text="byte-level tokenization keeps showing up"))
    key = str(added.event.payload["note"])

    result = discard_note_mutation(
        project, DiscardNoteRequest(note_key=key, reason="answered by E0004")
    )

    assert result.event.event is ResearchEventType.NOTE_DISCARDED
    assert result.event.payload["reason"] == "answered by E0004"
    stored = next(note for note in project.repo.iter_notes() if note.key == key)
    assert stored.status is NoteStatus.DISCARDED


def test_a_discard_without_a_reason_is_still_allowed(project: CapabilityContext) -> None:
    """A note carries no authority to withdraw, so a reason is a courtesy, not a rule."""
    added = add_note(project, AddNoteRequest(text="worth a second look"))
    key = str(added.event.payload["note"])
    result = discard_note_mutation(project, DiscardNoteRequest(note_key=key))
    assert "reason" not in result.event.payload


def test_a_capture_source_lands_in_provenance_and_never_in_the_note_text(
    project: CapabilityContext,
) -> None:
    """Where a note was typed is provenance; the scientific record keeps what was said."""
    result = add_note(project, AddNoteRequest(text="check the ablation", source="cli"))
    key = str(result.event.payload["note"])
    note = next(item for item in project.repo.iter_notes() if item.key == key)

    assert note.text == "check the ablation"
    assert note.provenance.note == "captured via cli"
    assert note.provenance.source is ProvenanceSource.HUMAN
    # And nowhere else: the same `note.add` over the CLI and over HTTP journals the same
    # event, so the capture host must not reach the payload (Task 10.4 parity).
    assert "source" not in result.event.payload


def test_a_capture_without_a_source_carries_no_capture_note(
    project: CapabilityContext,
) -> None:
    result = add_note(project, AddNoteRequest(text="no host recorded"))
    key = str(result.event.payload["note"])
    note = next(item for item in project.repo.iter_notes() if item.key == key)
    assert note.provenance.note is None


# -- 4. the handler allocates the evidence id --------------------------------


def test_accept_allocates_the_real_id_for_a_staged_candidate(
    project: CapabilityContext, registered: Registered
) -> None:
    """A transport that posts the staged candidate verbatim must not store `E0000`."""
    candidate = make_evidence(registered).touch(id=PROVISIONAL_EVIDENCE_ID)
    assert candidate.id == STAGED_ID

    result = accept_evidence(project, AcceptEvidenceRequest(candidate=candidate, verdict=VERDICT))

    assert result.objects == ("E0001",)
    accepted = list(project.repo.iter_evidence(registered.work))
    assert [str(item.id) for item in accepted] == ["E0001"]
    assert accepted[0].status is EvidenceStatus.ACCEPTED


def test_a_real_id_is_never_reallocated(project: CapabilityContext, registered: Registered) -> None:
    """`evidence/service.py` allocates before it calls; the handler must not do it twice."""
    first = accept_evidence(
        project,
        AcceptEvidenceRequest(
            candidate=make_evidence(registered).touch(id=PROVISIONAL_EVIDENCE_ID),
            verdict=VERDICT,
        ),
    )
    assert first.objects == ("E0001",)

    allocated = next_evidence_id(project.repo)
    assert str(allocated) == "E0002"
    second = accept_evidence(
        project,
        AcceptEvidenceRequest(
            candidate=make_evidence(registered, text="A second measured span.").touch(id=allocated),
            verdict=VERDICT,
        ),
    )
    assert second.objects == ("E0002",)
    assert [str(item.id) for item in project.repo.iter_evidence(registered.work)] == [
        "E0001",
        "E0002",
    ]


def test_the_registry_path_allocates_the_same_id(
    project: CapabilityContext, registered: Registered
) -> None:
    """`CapabilityRegistry.invoke` is the HTTP and MCP path; it must not differ."""
    registry = build_default_registry()
    response = registry.invoke(
        "evidence.accept",
        project,
        AcceptEvidenceRequest(
            candidate=make_evidence(registered).touch(id=PROVISIONAL_EVIDENCE_ID),
            verdict=VERDICT,
        ),
        principal=Principal.human(),
    )
    assert response.objects == ("E0001",)
    assert [str(item.id) for item in project.repo.iter_evidence(registered.work)] == ["E0001"]


def test_the_provisional_id_matches_the_staging_constant() -> None:
    """`capabilities/` spells the value out to stay parser-free; it may not drift."""
    assert PROVISIONAL_EVIDENCE_ID == STAGED_ID
    assert PROVISIONAL_EVIDENCE_ID.number == 0


def test_next_evidence_id_reads_canonical_evidence(
    project: CapabilityContext, registered: Registered
) -> None:
    assert str(next_evidence_id(project.repo)) == "E0001"
    accept_evidence(
        project,
        AcceptEvidenceRequest(
            candidate=make_evidence(registered).touch(id=PROVISIONAL_EVIDENCE_ID),
            verdict=VERDICT,
        ),
    )
    assert str(next_evidence_id(WorkspaceRepository.open(project.root))) == "E0002"


# -- 5. registry and handler table agree -------------------------------------


def test_every_registered_capability_has_a_handler_in_the_table() -> None:
    registry = build_default_registry()
    missing = sorted(name for name in registry.names() if name not in CAPABILITY_HANDLERS)
    assert missing == []


def test_every_handler_in_the_table_is_registered() -> None:
    """The other direction: a handler nobody can call is dead weight, not a capability.

    `project.init` is the documented exception and is deliberately not in the table: it has
    no workspace to run in, so it is registered apart as `handlers.PROJECT_INIT`.
    """
    registry = build_default_registry()
    extra = sorted(name for name in CAPABILITY_HANDLERS if name not in registry)
    assert extra == []


def test_the_table_carries_the_extension_modules() -> None:
    """Merged lazily, so the entries must be there however the caller reached the module."""
    assert set(EXTRA_CAPABILITY_HANDLERS) <= set(CAPABILITY_HANDLERS)
    assert set(CLAIM_EXTENSION_HANDLERS) <= set(CAPABILITY_HANDLERS)
    for name in ("claim.relate", "claim.unrelate", "claim.supersede", "note.discard"):
        assert name in CAPABILITY_HANDLERS


def test_the_extra_handler_table_matches_the_specs_it_registers() -> None:
    """The declared table is what the coherence test reads; it may not drift from the specs."""
    registry = build_default_registry()
    for name, handler in EXTRA_CAPABILITY_HANDLERS.items():
        assert name in registry, name
        assert registry.get(name).handler is handler, name


def test_a_core_name_wins_a_collision_in_the_table() -> None:
    """`corpus.ingest` and `work.parse` keep the raw handler they always had."""
    from research_harness.capabilities.handlers import ingest_local_pdf, parse_work

    assert CAPABILITY_HANDLERS["corpus.ingest"] is ingest_local_pdf
    assert CAPABILITY_HANDLERS["work.parse"] is parse_work


# -- research/ opens no transaction of its own -------------------------------


def test_nothing_in_research_opens_a_workspace_transaction() -> None:
    """ADR-004: `capabilities/` is the only surface that may write canonical state."""
    package = Path(__file__).resolve().parents[3] / "src" / "research_harness" / "research"
    offenders = [
        path.name
        for path in sorted(package.glob("*.py"))
        if "repo.transaction(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []

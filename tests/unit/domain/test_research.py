"""Questions, decisions, taxonomy, search runs, matrices, notes, and semantic events."""

from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

from research_harness.domain import (
    Claim,
    ClaimId,
    ClaimScope,
    Decision,
    DecisionId,
    DecisionStatus,
    DecisionType,
    Evidence,
    EvidenceId,
    IdentityResolutionOutcome,
    MatrixCell,
    NoteStatus,
    QuestionId,
    QuestionStatus,
    ResearchEvent,
    ResearchEventType,
    ResearchNote,
    ScreeningState,
    SearchCandidate,
    SearchResultCounts,
    SearchRunId,
    SourceCursor,
    SourceFailure,
    SynthesisId,
    SynthesisMatrix,
    Taxonomy,
    TaxonomyTerm,
    WorkCandidate,
    WorkId,
)
from research_harness.domain.research import (
    MAX_EVENT_PAYLOAD_KEYS,
    MAX_EVENT_PAYLOAD_VALUE_CHARS,
)
from tests.unit.domain import strategies as sty


def test_a_question_links_claims_searches_and_both_sides_of_the_evidence() -> None:
    question = sty.make_question(
        claims=(ClaimId("C0041"),),
        search_runs=(SearchRunId("SR0019"),),
        supporting_evidence=(EvidenceId("E0132"),),
        counter_evidence=(EvidenceId("E0180"),),
        remaining_uncertainty="No evidence yet for encrypted traffic.",
    )
    assert question.status is QuestionStatus.OPEN
    assert question.counter_evidence == ("E0180",)
    assert question.remaining_uncertainty


def test_an_epistemic_override_decision_needs_a_claim_and_both_scopes() -> None:
    with pytest.raises(ValidationError, match="must reference a claim"):
        Decision(
            id=DecisionId("D0027"),
            type=DecisionType.EPISTEMIC_OVERRIDE,
            rationale="because",
            auditor_recommendation=ClaimScope.CORPUS_PATTERN,
            researcher_selected=ClaimScope.FIELD_GENERALIZATION,
            provenance=sty.HUMAN,
        )
    with pytest.raises(ValidationError, match="auditor_recommendation"):
        Decision(
            id=DecisionId("D0027"),
            type=DecisionType.EPISTEMIC_OVERRIDE,
            claim=ClaimId("C0041"),
            rationale="because",
            provenance=sty.HUMAN,
        )


def test_scope_fields_belong_only_to_an_epistemic_override() -> None:
    with pytest.raises(ValidationError, match="belong to epistemic_override"):
        Decision(
            id=DecisionId("D0028"),
            type=DecisionType.INCLUSION,
            rationale="include this work",
            researcher_selected=ClaimScope.CORPUS_PATTERN,
            provenance=sty.HUMAN,
        )


def test_a_taxonomy_revision_names_its_terms() -> None:
    with pytest.raises(ValidationError, match="taxonomy terms"):
        Decision(
            id=DecisionId("D0012"),
            type=DecisionType.TAXONOMY_REVISION,
            rationale="split the category",
            provenance=sty.HUMAN,
        )
    decision = Decision(
        id=DecisionId("D0012"),
        type=DecisionType.TAXONOMY_REVISION,
        rationale="split the category",
        taxonomy_terms=("field_based", "behavior_aware"),
        provenance=sty.HUMAN,
    )
    assert decision.status is DecisionStatus.PROPOSED


def test_taxonomy_terms_record_the_decision_that_approved_them() -> None:
    taxonomy = Taxonomy(
        name="representation",
        terms=(
            TaxonomyTerm(term="raw_sequential", decision=DecisionId("D0012")),
            TaxonomyTerm(term="field_based", parent="raw_sequential", definition="protocol fields"),
        ),
        provenance=sty.HUMAN,
    )
    assert taxonomy.terms[0].decision == "D0012"
    assert taxonomy.terms[1].parent == "raw_sequential"


def test_taxonomy_rejects_duplicates_and_unknown_parents() -> None:
    with pytest.raises(ValidationError, match="unique"):
        Taxonomy(
            name="representation",
            terms=(TaxonomyTerm(term="a"), TaxonomyTerm(term="a")),
            provenance=sty.HUMAN,
        )
    with pytest.raises(ValidationError, match="unknown parent"):
        Taxonomy(
            name="representation",
            terms=(TaxonomyTerm(term="a", parent="missing"),),
            provenance=sty.HUMAN,
        )


def test_a_search_run_records_reproducible_discovery_provenance() -> None:
    run = sty.make_search_run(
        research_question=QuestionId("RQ0003"),
        filters={"year_from": "2020"},
        results=SearchResultCounts(discovered=143, screened=38, included=11),
        cutoff=datetime.date(2026, 8, 31),
        cursors=(SourceCursor(source="openalex", last_cursor="page-3", pages_fetched=3),),
        failures=(SourceFailure(source="dblp", reason="rate limited", incomplete=True),),
        unresolved_identities=("10.1000/unknown",),
        unavailable_full_text=(WorkId("W0021"),),
    )
    assert run.results.discovered == 143
    assert run.cursors[0].exhausted is False
    assert run.failures[0].incomplete is True
    assert run.unavailable_full_text == ("W0021",)
    assert run.executed_at.tzinfo is not None


def test_a_failed_source_query_is_not_a_zero_result_search() -> None:
    """Roadmap 12.1: provider errors stay distinct from an empty but successful search."""
    empty = sty.make_search_run(results=SearchResultCounts(discovered=0))
    failed = sty.make_search_run(
        results=SearchResultCounts(discovered=0),
        failures=(SourceFailure(source="dblp", reason="HTTP 503"),),
    )
    assert empty.failures == ()
    assert failed.failures[0].reason == "HTTP 503"


def candidate(key: str, **overrides: object) -> SearchCandidate:
    """A discovered candidate on a search run; nothing here is corpus state yet."""
    fields: dict[str, object] = {
        "key": key,
        "candidate": WorkCandidate(provenance=sty.SYSTEM),
        "sources": ("openalex",),
        "ranks": {"openalex": 1},
    }
    return SearchCandidate(**{**fields, **overrides})


def screened(key: str, state: ScreeningState, **overrides: object) -> SearchCandidate:
    """A candidate carrying a screening decision, author and timestamp included."""
    return candidate(
        key,
        screening=state,
        screened_by="human",
        screened_at=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
        **overrides,
    )


def test_a_search_candidate_keeps_every_source_that_reported_it() -> None:
    """Product 17: two sources reporting one work is corroboration, not a duplicate."""
    entry = candidate("doi:10.1000/x", sources=("openalex", "crossref"), ranks={"openalex": 3})

    assert entry.sources == ("openalex", "crossref")
    assert entry.ranks == {"openalex": 3}
    assert entry.screening is ScreeningState.DISCOVERED
    assert entry.screened is False and entry.included is False


def test_a_candidate_rank_must_name_a_source_that_reported_it() -> None:
    with pytest.raises(ValidationError, match="ranks name sources"):
        candidate("doi:10.1000/x", sources=("openalex",), ranks={"dblp": 1})


def test_an_excluded_candidate_persists_its_reason() -> None:
    """Product 14: exclusion reasons are persisted, and only for excluded candidates."""
    with pytest.raises(ValidationError, match="must persist a reason"):
        screened("doi:10.1000/x", ScreeningState.EXCLUDED)
    with pytest.raises(ValidationError, match="only valid for excluded"):
        screened("doi:10.1000/x", ScreeningState.INCLUDED, exclusion_reason="why")

    entry = screened("doi:10.1000/x", ScreeningState.EXCLUDED, exclusion_reason="out of scope")
    assert entry.exclusion_reason == "out of scope"
    assert entry.reason == "out of scope"


def test_an_inclusion_can_record_why_it_was_included() -> None:
    """Dogfood F9: PRISMA needs both halves, and inclusion is the one asked about."""
    entry = screened(
        "doi:10.1000/x",
        ScreeningState.INCLUDED,
        screening_reason="pre-trained transformer over raw traffic",
    )
    assert entry.screening_reason == "pre-trained transformer over raw traffic"
    assert entry.reason == "pre-trained transformer over raw traffic"
    assert entry.exclusion_reason is None

    excluded = screened(
        "doi:10.1000/y", ScreeningState.EXCLUDED, screening_reason="a digital-health survey"
    )
    assert excluded.reason == "a digital-health survey"

    with pytest.raises(ValidationError, match="has no screening reason"):
        candidate("doi:10.1000/z", screening_reason="never screened")


def test_a_screening_decision_records_who_made_it_and_when() -> None:
    with pytest.raises(ValidationError, match="screened_by and screened_at"):
        candidate("doi:10.1000/x", screening=ScreeningState.INCLUDED)


def test_a_matched_identity_must_name_the_work_it_matched() -> None:
    with pytest.raises(ValidationError, match="requires matched_work"):
        candidate("doi:10.1000/x", identity=IdentityResolutionOutcome.SAME_WORK)

    entry = candidate(
        "doi:10.1000/x",
        identity=IdentityResolutionOutcome.SAME_WORK,
        matched_work=WorkId("W0017"),
    )
    assert entry.matched_work == "W0017"


def test_run_counts_are_the_candidates_not_a_number_typed_beside_them() -> None:
    entries = (
        candidate("doi:10.1000/a"),
        screened("doi:10.1000/b", ScreeningState.INCLUDED),
        screened("doi:10.1000/c", ScreeningState.EXCLUDED, exclusion_reason="wrong field"),
    )

    run = sty.make_search_run(
        candidates=entries, results=SearchResultCounts(discovered=3, screened=2, included=1)
    )
    assert run.candidate("doi:10.1000/b") is not None
    assert [entry.key for entry in run.included_candidates()] == ["doi:10.1000/b"]

    with pytest.raises(ValidationError, match="do not match the recorded candidates"):
        sty.make_search_run(
            candidates=entries, results=SearchResultCounts(discovered=3, screened=3, included=1)
        )


def test_a_run_never_records_one_candidate_twice() -> None:
    with pytest.raises(ValidationError, match="same candidate key twice"):
        sty.make_search_run(
            candidates=(candidate("doi:10.1000/a"), candidate("doi:10.1000/a")),
            results=SearchResultCounts(discovered=2),
        )


def test_two_candidates_may_resolve_to_one_work_and_stay_two_records() -> None:
    """ADR-002: work-level dedup never merges the Version and Artifact records behind it."""
    entries = (
        candidate(
            "doi:10.1000/a",
            identity=IdentityResolutionOutcome.SAME_WORK,
            matched_work=WorkId("W0017"),
        ),
        candidate(
            "arxiv:2101.00001",
            identity=IdentityResolutionOutcome.SAME_VERSION,
            matched_work=WorkId("W0017"),
        ),
    )

    run = sty.make_search_run(candidates=entries, results=SearchResultCounts(discovered=2))

    assert len(run.candidates) == 2
    assert {entry.matched_work for entry in run.candidates} == {"W0017"}


def test_unresolved_and_full_text_keys_name_candidates_the_run_recorded() -> None:
    entries = (candidate("doi:10.1000/a"),)
    run = sty.make_search_run(
        candidates=entries,
        results=SearchResultCounts(discovered=1),
        unresolved_keys=("doi:10.1000/a",),
        full_text_unavailable_keys=("doi:10.1000/a",),
    )
    assert run.unresolved_keys == ("doi:10.1000/a",)

    with pytest.raises(ValidationError, match="names candidates this run did not record"):
        sty.make_search_run(
            candidates=entries,
            results=SearchResultCounts(discovered=1),
            unresolved_keys=("doi:10.1000/missing",),
        )


def test_a_rerun_records_the_run_it_reproduces_and_never_itself() -> None:
    run = sty.make_search_run(id=SearchRunId("SR0020"), reproduces=SearchRunId("SR0019"))
    assert run.reproduces == "SR0019"

    with pytest.raises(ValidationError, match="cannot reproduce itself"):
        sty.make_search_run(id=SearchRunId("SR0019"), reproduces=SearchRunId("SR0019"))


def matrix(**overrides: object) -> SynthesisMatrix:
    fields: dict[str, object] = {
        "id": SynthesisId("S0002"),
        "name": "representation comparison",
        "taxonomy": "representation",
        "works": (WorkId("W0017"), WorkId("W0018")),
        "fields": ("traffic_unit", "tokenization"),
        "cells": (
            MatrixCell(
                work=WorkId("W0017"),
                field="traffic_unit",
                labels=("packet", "flow"),
                evidence=(EvidenceId("E0132"),),
            ),
        ),
        "provenance": sty.SYSTEM,
    }
    return SynthesisMatrix(**{**fields, **overrides})


def test_matrix_cells_are_multi_label_and_evidence_backed() -> None:
    built = matrix()
    assert built.cells[0].labels == ("packet", "flow")
    assert built.cells[0].evidence == ("E0132",)


def test_matrix_cells_must_reference_declared_rows_and_fields() -> None:
    with pytest.raises(ValidationError, match="undeclared work"):
        matrix(cells=(MatrixCell(work=WorkId("W0099"), field="traffic_unit"),))
    with pytest.raises(ValidationError, match="undeclared field"):
        matrix(cells=(MatrixCell(work=WorkId("W0017"), field="unknown"),))
    with pytest.raises(ValidationError, match="duplicate matrix cell"):
        matrix(
            cells=(
                MatrixCell(work=WorkId("W0017"), field="traffic_unit"),
                MatrixCell(work=WorkId("W0017"), field="traffic_unit"),
            )
        )


def test_notes_have_lower_authority_than_claims_and_decisions() -> None:
    """Product 31: a note is capture, not knowledge; it cannot be cited as support."""
    note_fields = set(ResearchNote.model_fields)
    assert "id" not in note_fields
    assert not note_fields & {
        "relations",
        "evidence",
        "assessment",
        "verification",
        "coverage",
        "accepted_by",
    }
    assert {"id", "assessment", "relations"} <= set(Claim.model_fields)
    assert {"id", "status", "rationale"} <= set(Decision.model_fields)
    assert "verification" in set(Evidence.model_fields)


def test_a_note_starts_captured_and_records_its_promotion_target() -> None:
    note = sty.make_note()
    assert note.status is NoteStatus.CAPTURED
    assert note.promoted_to is None
    with pytest.raises(ValidationError, match="promoted note"):
        sty.make_note(status=NoteStatus.PROMOTED)
    with pytest.raises(ValidationError, match="only valid for promoted"):
        sty.make_note(promoted_to=ClaimId("C0041"))


@pytest.mark.parametrize("target", [ClaimId("C0041"), QuestionId("RQ0003"), DecisionId("D0027")])
def test_notes_may_be_promoted_to_a_claim_question_or_decision(target: str) -> None:
    note = sty.make_note(status=NoteStatus.PROMOTED, promoted_to=target)
    assert note.promoted_to == target


def event(**overrides: object) -> ResearchEvent:
    fields: dict[str, object] = {
        "event": ResearchEventType.EVIDENCE_ACCEPTED,
        "subjects": (EvidenceId("E0482"), WorkId("W0017")),
        "actor": "human",
        "summary": "Accepted dataset evidence for W0017.",
        "payload": {"review_action": "accept", "tier": 1},
    }
    return ResearchEvent(**{**fields, **overrides})


def test_events_carry_semantic_subjects_and_a_small_payload() -> None:
    record = event()
    assert record.event is ResearchEventType.EVIDENCE_ACCEPTED
    assert record.subjects == ("E0482", "W0017")
    assert record.payload["tier"] == 1
    assert record.occurred_at.tzinfo is not None


def test_events_refuse_prompts_and_hidden_reasoning() -> None:
    """Product 19.3: traces belong in disposable .research/traces/, not the event log."""
    for forbidden in ("prompt", "Reasoning", "chain_of_thought", "messages", "tool_output"):
        with pytest.raises(ValidationError, match="traces"):
            event(payload={forbidden: "..."})


def test_event_payloads_stay_small() -> None:
    with pytest.raises(ValidationError, match="at most"):
        event(payload={f"k{index}": index for index in range(MAX_EVENT_PAYLOAD_KEYS + 1)})
    with pytest.raises(ValidationError, match="characters"):
        event(payload={"note": "x" * (MAX_EVENT_PAYLOAD_VALUE_CHARS + 1)})


def test_event_payload_values_are_scalars() -> None:
    with pytest.raises(ValidationError):
        event(payload={"ids": ["E0482", "E0483"]})


def test_event_subjects_parse_into_typed_ids() -> None:
    record = ResearchEvent.model_validate(
        {
            "event": "claim.audited",
            "subjects": ["C0041", "SR0019"],
            "actor": "auditor",
            "summary": "Audited C0041.",
        }
    )
    assert isinstance(record.subjects[0], ClaimId)
    assert isinstance(record.subjects[1], SearchRunId)

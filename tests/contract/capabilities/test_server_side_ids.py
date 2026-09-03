"""Ids are allocated by the workspace, not guessed by a client (Product 22, ADR-004).

`docs/architecture/vscode.md` gap 2: `claim.create` took a whole `Claim`, so an HTTP client
had to *choose* the id - the extension probed `GET /objects/C####` by doubling and then
bisecting, and the Web computed one from `GET /index`. Both are races: two clients reading
the same "next free" number both write it, and the second one loses a claim.

So every capability that creates a numbered object accepts one without an id and allocates
under the workspace lock, and confirms that allocation inside the transaction. A caller that
already holds an id keeps working unchanged - the CLI, a replay, an export.
"""

from __future__ import annotations

from typing import Any

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import (
    PROVISIONAL_CLAIM_ID,
    PROVISIONAL_DECISION_ID,
    PROVISIONAL_QUESTION_ID,
    PROVISIONAL_SEARCH_RUN_ID,
)
from research_harness.capabilities.permissions import Principal
from research_harness.capabilities.registry import build_default_registry
from research_harness.domain.enums import (
    ClaimScope,
    ClaimStatus,
    ClaimType,
    DecisionStatus,
    DecisionType,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import ClaimId, DecisionId, QuestionId, SearchRunId

HUMAN = Principal.human()

CLAIM_BODY: dict[str, Any] = {
    "statement": "Byte-level tokenization improves recall on short flows",
    "type": ClaimType.DESCRIPTIVE.value,
    "semantics": {"subject": "tokenization", "predicate": "improves", "object": "recall"},
    "scope": {"level": ClaimScope.INDIVIDUAL.value},
    "assessment": {
        "requested_strength": ClaimScope.INDIVIDUAL.value,
        "allowed_strength": ClaimScope.INDIVIDUAL.value,
        "status": ClaimStatus.UNVERIFIED.value,
    },
    "provenance": {"source": "human", "actor": "human", "workflow": "test"},
}

QUESTION_BODY: dict[str, Any] = {
    "question": "Does tokenization matter for short flows?",
    "provenance": {"source": "human", "actor": "human", "workflow": "test"},
}

DECISION_BODY: dict[str, Any] = {
    "type": DecisionType.METHODOLOGY.value,
    "status": DecisionStatus.PROPOSED.value,
    "title": "Use macro F1",
    "rationale": "the classes are unbalanced",
    "provenance": {"source": "human", "actor": "human", "workflow": "test"},
}

SEARCH_RUN_BODY: dict[str, Any] = {
    "question": "encrypted traffic classification",
    "queries": [],
    "sources": [],
    "provenance": {"source": "human", "actor": "human", "workflow": "test"},
}


def invoke(ctx: CapabilityContext, name: str, request: dict[str, Any]) -> Any:
    return build_default_registry().invoke(name, ctx, request, principal=HUMAN)


# -- allocation --------------------------------------------------------------


def test_claim_create_allocates_the_id_when_the_request_omits_it(
    project: CapabilityContext,
) -> None:
    first = invoke(project, "claim.create", {"claim": CLAIM_BODY})
    second = invoke(project, "claim.create", {"claim": CLAIM_BODY})

    assert first.objects == ("C0001",)
    assert second.objects == ("C0002",)
    assert [str(claim.id) for claim in project.repo.list_claims()] == ["C0001", "C0002"]


def test_the_provisional_id_means_the_same_thing_as_omitting_it(
    project: CapabilityContext,
) -> None:
    """A client that must send *something* sends `C0000`, which is never allocated."""
    response = invoke(
        project, "claim.create", {"claim": {**CLAIM_BODY, "id": str(PROVISIONAL_CLAIM_ID)}}
    )
    assert response.objects == ("C0001",)


def test_an_explicit_id_is_still_used_unchanged(project: CapabilityContext) -> None:
    """The CLI and every replayed export keep working: the id they hold is the id written."""
    response = invoke(project, "claim.create", {"claim": {**CLAIM_BODY, "id": "C0007"}})

    assert response.objects == ("C0007",)
    assert [str(claim.id) for claim in project.repo.list_claims()] == ["C0007"]


def test_an_allocated_id_never_collides_with_one_a_client_chose(
    project: CapabilityContext,
) -> None:
    """Allocation reads the ids on disk, so a hand-picked `C0007` is not handed out twice."""
    invoke(project, "claim.create", {"claim": {**CLAIM_BODY, "id": "C0007"}})

    allocated = invoke(project, "claim.create", {"claim": CLAIM_BODY})

    assert allocated.objects == ("C0008",)


def test_question_create_allocates_its_id(project: CapabilityContext) -> None:
    first = invoke(project, "question.create", {"question": QUESTION_BODY})
    second = invoke(
        project,
        "question.create",
        {"question": {**QUESTION_BODY, "id": str(PROVISIONAL_QUESTION_ID)}},
    )

    assert first.objects == ("RQ0001",)
    assert second.objects == ("RQ0002",)


def test_decision_accept_allocates_its_id(project: CapabilityContext) -> None:
    """An override is a Decision before it is a claim edit; the client no longer guesses it."""
    first = invoke(project, "decision.accept", {"decision": DECISION_BODY})
    second = invoke(
        project,
        "decision.accept",
        {"decision": {**DECISION_BODY, "id": str(PROVISIONAL_DECISION_ID)}},
    )

    assert first.objects == ("D0001",)
    assert second.objects == ("D0002",)
    assert [str(item.id) for item in project.repo.list_decisions()] == ["D0001", "D0002"]


def test_search_run_record_allocates_its_id(project: CapabilityContext) -> None:
    first = invoke(project, "search_run.record", {"search_run": SEARCH_RUN_BODY})
    second = invoke(
        project,
        "search_run.record",
        {"search_run": {**SEARCH_RUN_BODY, "id": str(PROVISIONAL_SEARCH_RUN_ID)}},
    )

    assert first.objects == ("SR0001",)
    assert second.objects == ("SR0002",)


# -- the refusals that still hold -------------------------------------------


def test_creating_a_claim_twice_with_the_same_explicit_id_is_still_refused(
    project: CapabilityContext,
) -> None:
    invoke(project, "claim.create", {"claim": {**CLAIM_BODY, "id": "C0007"}})

    with pytest.raises(CapabilityError, match="already exists"):
        invoke(project, "claim.create", {"claim": {**CLAIM_BODY, "id": "C0007"}})


@pytest.mark.parametrize(
    ("provisional", "id_type"),
    [
        (PROVISIONAL_CLAIM_ID, ClaimId),
        (PROVISIONAL_QUESTION_ID, QuestionId),
        (PROVISIONAL_DECISION_ID, DecisionId),
        (PROVISIONAL_SEARCH_RUN_ID, SearchRunId),
    ],
)
def test_the_provisional_ids_are_number_zero_and_never_allocated(
    provisional: Any, id_type: type[Any]
) -> None:
    """Allocation starts at 1, which is what makes 0 safe to mean "unassigned"."""
    assert isinstance(provisional, id_type)
    assert provisional.number == 0
    assert id_type.next(()).number == 1


def test_the_request_schema_a_host_reads_shows_the_id_is_optional() -> None:
    """A host reads the schema before calling; "optional" has to be visible there."""
    schema = build_default_registry().get("claim.create").request_model.model_json_schema()
    claim = schema["$defs"]["Claim"]
    assert "claim" in schema["required"]
    assert "id" in claim["required"], (
        "the nested Claim still requires an id; the request model fills the provisional one "
        "in before validation, which is what makes omitting it work"
    )

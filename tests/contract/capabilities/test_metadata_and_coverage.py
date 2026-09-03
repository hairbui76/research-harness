"""`work.update_metadata` and `claim.update_coverage`: two dogfood defects, one rule each.

**F5** — discovery found the right authors and venue for a Work the corpus already held and
threw them away, leaving `work.yaml` with the parser's mojibake. Filling an empty or
undecodable field is safe; overwriting a decodable one is a judgement. Both are done here,
and *neither* is done silently: every disagreement reaches the response and the event.

**F2** — `research coverage` computed a PRISMA funnel that never reached the Claim, so
`claim audit` read `0 of 0 relevant works` and capped every literature-wide claim at L1.
`claim.update_coverage` is where that funnel is written, and it refuses a record naming a
search run this workspace does not hold, because coverage that cannot be reproduced from
its runs is not coverage.
"""

from __future__ import annotations

from typing import Any

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import CreateClaimRequest
from research_harness.capabilities.handlers import create_claim
from research_harness.capabilities.permissions import Permission, PermissionDenied, Principal
from research_harness.capabilities.registry import build_default_registry
from research_harness.domain.enums import (
    ClaimScope,
    ClaimStatus,
    ClaimType,
    OverturnRisk,
    ProvenanceSource,
    ResearchEventType,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import ClaimId, WorkId

from .conftest import MODEL_ACTOR, Registered

HUMAN = Principal.human()

#: What a broken ToUnicode CMap leaves behind: `parsing.quality` calls the third undecodable.
MOJIBAKE_AUTHORS = ("anced traffic data for accurate classification", "ORVH\x10GRPDLQ")
REAL_AUTHORS = ("Xinjie Lin", "Gang Xiong", "Gaopeng Gou")

CLAIM_BODY: dict[str, Any] = {
    "id": "C0001",
    "statement": "No reviewed system reports per-flow latency",
    "type": ClaimType.DESCRIPTIVE.value,
    "semantics": {"subject": "systems", "predicate": "report", "object": "latency"},
    "scope": {"level": ClaimScope.INDIVIDUAL.value},
    "assessment": {
        "requested_strength": ClaimScope.INDIVIDUAL.value,
        "allowed_strength": ClaimScope.INDIVIDUAL.value,
        "status": ClaimStatus.UNVERIFIED.value,
    },
    "provenance": {"source": "human", "actor": "human", "workflow": "test"},
}

SEARCH_RUN_BODY: dict[str, Any] = {
    "question": "per-flow latency reporting",
    "sources": ["arxiv", "openalex"],
    "provenance": {"source": "human", "actor": "human", "workflow": "test"},
}


def invoke(ctx: CapabilityContext, name: str, request: dict[str, Any]) -> Any:
    return build_default_registry().invoke(name, ctx, request, principal=HUMAN)


def field(value: str) -> dict[str, Any]:
    """One `IdentifierField` as a discovery source would report it."""
    return {"value": value, "source": ProvenanceSource.EXTERNAL_METADATA.value}


# -- work.update_metadata ----------------------------------------------------


def test_updating_metadata_is_a_researcher_act() -> None:
    spec = build_default_registry().get("work.update_metadata")
    assert spec.permission is Permission.MUTATE
    assert spec.human_only


def test_an_agent_host_may_not_update_metadata(
    project: CapabilityContext, registered: Registered
) -> None:
    with pytest.raises(PermissionDenied):
        build_default_registry().invoke(
            "work.update_metadata",
            project,
            {"work": str(registered.work), "venue": field("WWW 2022")},
            principal=Principal.agent_host("some-host"),
        )


def test_an_empty_field_is_filled(project: CapabilityContext, registered: Registered) -> None:
    """The corpus records no venue; discovery found one. Filling is safe."""
    response = invoke(
        project,
        "work.update_metadata",
        {"work": str(registered.work), "venue": field("Proceedings of the ACM Web Conference")},
    )

    assert response.updated == ("venue",)
    assert response.conflicts == ()
    assert project.repo.get_work(registered.work).venue == ("Proceedings of the ACM Web Conference")
    assert response.mutation is not None
    assert response.mutation.event.event is ResearchEventType.WORK_METADATA_UPDATED


def test_an_undecodable_field_is_replaced(
    project: CapabilityContext, registered: Registered
) -> None:
    """dogfood F5: mojibake authors are a font artefact, not a record worth defending."""
    with project.repo.transaction(_event(project), project.actor) as tx:
        tx.put(project.repo.get_work(registered.work).touch(authors=MOJIBAKE_AUTHORS))

    response = invoke(
        project,
        "work.update_metadata",
        {
            "work": str(registered.work),
            "authors": [field(name) for name in REAL_AUTHORS],
        },
    )

    assert response.updated == ("authors",)
    assert response.conflicts == ()
    assert project.repo.get_work(registered.work).authors == REAL_AUTHORS


def test_a_decodable_disagreement_is_recorded_and_not_overwritten(
    project: CapabilityContext, registered: Registered
) -> None:
    """Never discarded, never silently taken: the disagreement itself is the record."""
    before = project.repo.get_work(registered.work).title

    response = invoke(
        project,
        "work.update_metadata",
        {"work": str(registered.work), "title": field("A Completely Different Title")},
    )

    assert response.updated == ()
    assert response.mutation is None, "nothing to write means nothing is written"
    assert [item.field for item in response.conflicts] == ["title"]
    assert response.conflicts[0].current == before
    assert response.conflicts[0].proposed == "A Completely Different Title"
    assert response.conflicts[0].applied is False
    assert project.repo.get_work(registered.work).title == before


def test_overwrite_takes_the_value_and_still_records_the_conflict(
    project: CapabilityContext, registered: Registered
) -> None:
    response = invoke(
        project,
        "work.update_metadata",
        {
            "work": str(registered.work),
            "title": field("A Completely Different Title"),
            "overwrite": True,
        },
    )

    assert response.updated == ("title",)
    assert response.conflicts[0].applied is True
    assert project.repo.get_work(registered.work).title == "A Completely Different Title"
    assert response.mutation is not None
    assert "disagrees with" in " ".join(response.mutation.validation.warnings)
    assert "title" in str(response.mutation.event.payload["conflicts"])


def test_an_agreeing_value_changes_nothing(
    project: CapabilityContext, registered: Registered
) -> None:
    current = project.repo.get_work(registered.work).title

    response = invoke(
        project, "work.update_metadata", {"work": str(registered.work), "title": field(current)}
    )

    assert response.updated == ()
    assert response.unchanged == ("title",)
    assert response.conflicts == ()


def test_an_identifier_the_work_lacks_is_added_and_a_conflicting_one_is_reported(
    project: CapabilityContext, registered: Registered
) -> None:
    response = invoke(
        project,
        "work.update_metadata",
        {
            "work": str(registered.work),
            "identifiers": {
                "arxiv": field("2202.06335"),
                "doi": field("10.9999/not-the-recorded-one"),
            },
        },
    )

    stored = project.repo.get_work(registered.work).identifiers
    assert stored.arxiv is not None
    assert stored.arxiv.value == "2202.06335"
    assert stored.doi is not None
    assert stored.doi.value == "10.1234/gate-p1", "the recorded identifier is kept"
    assert [item.field for item in response.conflicts] == ["identifiers.doi"]


def test_a_year_that_is_not_a_year_is_refused_by_name(
    project: CapabilityContext, registered: Registered
) -> None:
    with pytest.raises(CapabilityError, match="not a publication year"):
        invoke(
            project,
            "work.update_metadata",
            {"work": str(registered.work), "year": field("last spring")},
        )


def test_a_model_actor_is_refused_in_the_handler_not_only_in_the_registry(
    project: CapabilityContext, registered: Registered
) -> None:
    """`discovery.apply_enrichments` calls this handler by name, so the gate lives in it."""
    from research_harness.capabilities.extra_handlers import (
        UpdateWorkMetadataRequest,
        update_work_metadata,
    )
    from research_harness.domain.errors import AuthorityError

    as_model = open_context(project.root, MODEL_ACTOR)
    before = project.repo.get_work(registered.work).venue

    with pytest.raises(AuthorityError, match="only a human actor"):
        update_work_metadata(
            as_model,
            UpdateWorkMetadataRequest.model_validate(
                {"work": str(registered.work), "venue": field("WWW 2022")}
            ),
        )
    assert project.repo.get_work(registered.work).venue == before


def test_a_work_that_is_not_there_is_refused_by_name(project: CapabilityContext) -> None:
    with pytest.raises(CapabilityError, match="no Work W0404"):
        invoke(project, "work.update_metadata", {"work": str(WorkId("W0404")), "venue": field("x")})


# -- claim.update_coverage ---------------------------------------------------


def test_coverage_is_written_onto_the_claim(project: CapabilityContext) -> None:
    """dogfood F2: the funnel `research coverage` computes now reaches the Claim."""
    create_claim(project, CreateClaimRequest(claim=_claim()))
    run = invoke(project, "search_run.record", {"search_run": SEARCH_RUN_BODY})
    run_id = run.objects[0]

    response = invoke(
        project,
        "claim.update_coverage",
        {
            "claim_id": "C0001",
            "coverage": {
                "relevant_works": 5,
                "examined_works": 5,
                "unresolved_works": 0,
                "overturn_risk": OverturnRisk.LOW.value,
                "search_runs": [run_id],
                "cutoff": "2025-08-31",
            },
        },
    )

    stored = project.repo.get_claim(ClaimId("C0001")).coverage
    assert response.event.event is ResearchEventType.CLAIM_COVERAGE_RECORDED
    assert stored.relevant_works == 5
    assert stored.examined_works == 5
    assert [str(item) for item in stored.search_runs] == [run_id]
    assert response.event.payload["examined_works"] == 5


def test_coverage_naming_a_run_that_is_not_recorded_is_refused(
    project: CapabilityContext,
) -> None:
    """Coverage that cannot be reproduced from its runs is not a coverage record."""
    create_claim(project, CreateClaimRequest(claim=_claim()))

    with pytest.raises(CapabilityError, match="no search run SR0009"):
        invoke(
            project,
            "claim.update_coverage",
            {
                "claim_id": "C0001",
                "coverage": {"relevant_works": 1, "search_runs": ["SR0009"]},
            },
        )
    assert project.repo.get_claim(ClaimId("C0001")).coverage.relevant_works == 0


def test_recording_coverage_needs_a_human_and_a_claim(project: CapabilityContext) -> None:
    spec = build_default_registry().get("claim.update_coverage")
    assert spec.permission is Permission.MUTATE

    with pytest.raises(PermissionDenied):
        build_default_registry().invoke(
            "claim.update_coverage",
            open_context(project.root, MODEL_ACTOR),
            {"claim_id": "C0001", "coverage": {}},
            principal=Principal.human(),
        )


# -- helpers -----------------------------------------------------------------


def _claim() -> Any:
    from research_harness.domain.claim import Claim

    return Claim.model_validate(CLAIM_BODY)


def _event(ctx: CapabilityContext) -> Any:
    from research_harness.domain.research import ResearchEvent

    return ResearchEvent(
        event=ResearchEventType.WORK_METADATA_UPDATED,
        subjects=(),
        actor=ctx.actor,
        occurred_at=ctx.now(),
        summary="test fixture: replace the recorded authors with mojibake",
    )

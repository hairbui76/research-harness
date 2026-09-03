"""Hand-built claim state and fake providers for the Gate P7 audit.

Every object here is built in the test, not ingested: the audit reads accepted state and
computes, so a fixture is a claim, its evidence, the works behind it, and a search run. The
providers are in-memory and answer with the exact structured output the test hands them,
which is what keeps the run offline and deterministic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from research_harness.claims.audit import ClaimAuditInput, RetrievalCandidate
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    Coverage,
)
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimType,
    EvidenceStatus,
    EvidenceType,
    OverturnRisk,
)
from research_harness.domain.evidence import Evidence, EvidenceContent, VerificationRecord
from research_harness.domain.ids import ArtifactId, EvidenceId, VersionId, WorkId
from research_harness.domain.research import SearchRun
from research_harness.domain.work import Work
from research_harness.providers.models.base import (
    EgressDeclaration,
    ModelProvider,
    ModelRequest,
    ProviderCapabilities,
    ProviderError,
    RawCompletion,
    Usage,
)
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workspace.runs import RunStore
from tests.unit.domain import strategies as sty

ACCEPTED = VerificationRecord(status=EvidenceStatus.ACCEPTED, accepted_by="human:alice")
DATASET = "CICIDS2017"
OTHER_DATASET = "UNSW-NB15"
CLAIM_ID = "C0041"


# ------------------------------------------------------------------------ hand-built state


def make_evidence(
    number: int,
    work: int,
    version: int = 1,
    *,
    dataset: str = DATASET,
    metric: str = "F1",
    text: str | None = None,
) -> Evidence:
    """Accepted, source-observed numeric evidence anchored in one version of one work."""
    return sty.make_evidence(
        id=EvidenceId.make(number),
        source=sty.make_anchor(
            work=WorkId.make(work),
            version=VersionId.make(work, version),
            artifact=ArtifactId.make(work, version),
        ),
        content=EvidenceContent(
            exact_text=text or f"We report {metric} of 94.3 on {dataset}.",
            numeric=sty.make_numeric(dataset=dataset, metric=metric),
        ),
        evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
        verification=ACCEPTED,
    )


def gate_p7_claim() -> Claim:
    """A prevalence claim deliberately requested at L3 with corpus-level evidence."""
    return sty.make_claim(
        type=ClaimType.PREVALENCE,
        scope=ClaimScopeSpec(
            level=ClaimScope.CORPUS_PATTERN,
            corpus="structured-traffic-llm",
            publication_until="2026-08",
        ),
        relations=(
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0001"), relation=ClaimEvidenceRelationType.SUPPORTS
            ),
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0002"), relation=ClaimEvidenceRelationType.SUPPORTS
            ),
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0003"), relation=ClaimEvidenceRelationType.SUPPORTS
            ),
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0004"), relation=ClaimEvidenceRelationType.SUPPORTS
            ),
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0009"),
                relation=ClaimEvidenceRelationType.CONTRADICTS,
                note="reports a lower score",
            ),
        ),
        coverage=Coverage(
            relevant_works=10,
            examined_works=8,
            unresolved_works=0,
            overturn_risk=OverturnRisk.LOW_MODERATE,
            search_runs=(sty.make_search_run().id,),
            cutoff=sty.make_search_run().executed_at.date(),
        ),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.FIELD_GENERALIZATION,
            allowed_strength=ClaimScope.INDIVIDUAL,
        ),
    )


def gate_p7_evidence() -> dict[EvidenceId, Evidence]:
    """Four supports across three works — two of them versions of one — and one outsider.

    E0001 and E0002 are read from two versions of W0001, so they are one unit of support.
    E0009 is measured on another dataset, which makes it incomparable rather than opposed.
    """
    items = [
        make_evidence(1, work=1, version=1),
        make_evidence(2, work=1, version=2),
        make_evidence(3, work=2),
        make_evidence(4, work=3),
        make_evidence(9, work=4, dataset=OTHER_DATASET),
    ]
    return {item.id: item for item in items}


def gate_p7_works() -> dict[WorkId, Work]:
    """Four works with disjoint author lists, so nothing merges by author overlap."""
    names = ["A. First", "B. Second", "C. Third", "D. Fourth"]
    return {
        WorkId.make(number): sty.make_work(
            id=WorkId.make(number), title=f"Paper {number}", authors=(names[number - 1],)
        )
        for number in range(1, 5)
    }


def gate_p7_search_runs() -> list[SearchRun]:
    return [sty.make_search_run()]


class FakeCounterFinder:
    """Retrieval that offers one place to look for a counter-example. Never Evidence."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def find_counter_evidence(self, claim: Claim, *, limit: int) -> list[RetrievalCandidate]:
        self.calls.append(limit)
        return [
            RetrievalCandidate(
                ref="B0142",
                work=WorkId.make(5),
                text="Under a byte-level tokenizer the same pipeline loses 8 F1 points.",
                score=0.68,
                source="semantic_index",
                location="block B0142, page 6",
            )
        ][:limit]


# ------------------------------------------------------------------------- fake providers


class FakeModel(ModelProvider):
    """Answers with a canned structured output, or raises the error it was built with."""

    def __init__(
        self,
        name: str,
        answer: dict[str, Any] | None = None,
        *,
        model: str = "fake-1",
        error: ProviderError | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._answer = answer or {}
        self._error = error
        self.calls: list[ModelRequest[Any]] = []

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            structured_output=True,
            max_context_tokens=1_000_000,
            reasoning_levels={"low", "medium", "high"},
            vision=False,
            egress=EgressDeclaration(
                endpoint_host=f"{self.name}.invalid",
                sends_source_text=False,
                sends_identifiers=False,
                description="fake provider used in tests; nothing leaves the process",
            ),
        )

    def _execute(self, request: ModelRequest[Any], schema_json: dict[str, Any]) -> RawCompletion:
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        return RawCompletion(
            text=json.dumps(self._answer),
            usage=Usage(input_tokens=1, output_tokens=1),
            model=self.model,
            stop_reason="stop",
        )


def skeptic_answer(**overrides: Any) -> dict[str, Any]:
    """A Skeptic that found one anchored counter candidate and one qualifier."""
    payload: dict[str, Any] = {
        "counter_candidates": [
            {
                "exact_text": "On UNSW-NB15 the same tokenizer performs worse.",
                "page": 6,
                "block": "B0142",
                "char_start": 100,
                "char_end": 148,
                "origin": "source_observed",
                "evidence_type": "experimental_result",
                "strength": "direct",
                "field": "tokenization",
                "numeric": None,
                "negative_state": None,
                "rationale": None,
            }
        ],
        "qualifiers": [
            {"text": "holds only for flow-level inputs", "evidence_refs": ["E0003"]},
        ],
        "incomparability_notes": [
            "E0009 is measured on another dataset and is not a counter-example",
        ],
        "rationale": "Searched the supplied corpus for lower scores under the same metric.",
    }
    return {**payload, **overrides}


def auditor_answer(
    scope: ClaimScope = ClaimScope.CORPUS_PATTERN, **overrides: Any
) -> dict[str, Any]:
    """A Claim Auditor that agrees with the deterministic ceiling."""
    payload: dict[str, Any] = {
        "support": ["E0001", "E0002", "E0003", "E0004"],
        "counter_evidence": [],
        "qualifiers": ["measured on flow-level inputs only"],
        "independence_warnings": ["E0001 and E0002 are two versions of one work"],
        "coverage_state": "8 of 10 relevant works examined, 0 unresolved",
        "recommended_scope": scope.value,
        "maximum_defensible_wording": "Several existing approaches tokenize traffic this way.",
        "rationale": "Three independent works is a corpus pattern, not a field generalization.",
    }
    return {**payload, **overrides}


# ------------------------------------------------------------------------------- workspace


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A workspace with canonical files beside a `.research/` directory.

    The canonical files stand in for accepted state: the audit must leave every byte of
    them untouched (ADR-001).
    """
    root = tmp_path / "project"
    (root / "claims").mkdir(parents=True)
    (root / "corpus").mkdir(parents=True)
    (root / ".research").mkdir(parents=True)
    (root / "claims" / f"{CLAIM_ID}.yaml").write_text(
        "id: C0041\nstatement: accepted state\n", encoding="utf-8"
    )
    (root / "corpus" / "evidence.jsonl").write_text('{"id": "E0001"}\n', encoding="utf-8")
    return root


@pytest.fixture
def research_dir(project: Path) -> Path:
    return project / ".research"


@pytest.fixture
def engine(research_dir: Path) -> WorkflowEngine:
    return WorkflowEngine(RunStore(research_dir))


@pytest.fixture
def audit_input() -> Iterator[ClaimAuditInput]:
    """The deterministic Gate P7 input, with no model configured."""
    yield ClaimAuditInput(
        claim=gate_p7_claim(),
        evidence=gate_p7_evidence(),
        works=gate_p7_works(),
        search_runs=gate_p7_search_runs(),
    )

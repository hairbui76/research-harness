"""VERIFY: one resumable stage per candidate, each an independent check of one assertion.

A stage's fingerprint is the candidate id, a digest of the evidence being checked, the
verifier template version, and the provider/model doing the checking. Re-running the workflow
therefore costs nothing for candidates that have not changed, and a candidate already carrying
a verification result is skipped before a stage is even built — verification is expensive and
buying the same verdict twice buys nothing (Product §20.4).

Selective cross-verification is the exception, and it is opt-in: pass
`cross_verify_providers` and the run asks a second provider the *same* verifier question for
the candidates that sit at a high-value gate — a measured value, or a reading that
contradicts the candidate (Product §20.4). Two rules make that safe.

**The second provider never overwrites the first.** The staged verification record is the
one the first provider produced, and cross-verification writes a `ConflictRecord` beside the
candidate instead of touching it. Provider A versus provider B is a conflict a researcher
resolves, not a merge (ROADMAP Gate P13).

**Agreement changes nothing.** Two providers that agree produce no record, no verdict
change, and no acceptance: a Tier-2 candidate still waits for a person under strict policy
(ADR-005, ADR-007, Task 13.2).

Like extraction, nothing here writes canonical state: verified candidates are written back to
`.research/staging/`, and only a researcher's review turns one into accepted Evidence
(ADR-003, ADR-007).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import VerificationVerdict
from research_harness.domain.ids import ArtifactId, WorkId
from research_harness.evidence.conflicts import (
    ConflictRecord,
    ConflictStore,
    materialize_provider_conflict,
)
from research_harness.evidence.extraction import ModelClient, resolve_backend
from research_harness.evidence.staging import (
    CandidateStatus,
    EvidenceCandidate,
    StagingStore,
)
from research_harness.evidence.verification import (
    DEFAULT_NEIGHBOURS,
    build_source_context,
    verify_candidate,
)
from research_harness.providers.models.base import ModelProvider
from research_harness.providers.models.cross_verify import (
    DEFAULT_POLICY,
    CrossVerification,
    CrossVerificationGate,
    CrossVerifyPolicy,
    Eligibility,
    ProviderCandidate,
    cross_verify,
)
from research_harness.providers.models.router import ProviderEntry
from research_harness.roles.contracts import build_request
from research_harness.roles.verifier import VERIFIER
from research_harness.workflows.engine import (
    StageBase,
    StageContext,
    Workflow,
    WorkflowEngine,
)
from research_harness.workflows.interrogate import DocumentSource, LoadDocument
from research_harness.workflows.models import WorkflowRun
from research_harness.workspace.repository import WorkspaceRepository

logger = logging.getLogger(__name__)

__all__ = [
    "CANDIDATE_GATES",
    "VERIFICATION_DECISION_FIELDS",
    "VERIFY_STAGE_PREFIX",
    "VERIFY_WORKFLOW",
    "CrossVerifyCandidate",
    "VerificationReport",
    "VerifyCandidate",
    "build_verify_workflow",
    "candidate_eligibility",
    "cross_verify_candidate",
    "evidence_digest",
    "run_verification",
    "verify_stage_name",
]

CrossVerifyCandidate = ModelProvider | ProviderCandidate
"""A provider offered for cross-verification: bare, as a `(provider, model)` pair, or routed."""

VERIFICATION_DECISION_FIELDS: tuple[str, ...] = ("verdict",)
"""The verification fields two providers are compared on.

`rationale`, `quoted_support`, and `discrepancies` are prose or evidence *for* a verdict:
two verifiers wording the same reading differently is not a scientific disagreement, and
comparing free text would manufacture conflicts (Product §20.4, §25).
"""

CANDIDATE_GATES: tuple[CrossVerificationGate, ...] = (
    CrossVerificationGate.NUMERIC_HIGH_IMPACT,
    CrossVerificationGate.COUNTER_EVIDENCE_INTERPRETATION,
)
"""Gates a staged candidate can meet on its own, in the order they are tried."""

VERIFY_WORKFLOW = "verify"
WORKFLOW_VERSION = "1.0.0"
VERDICT_FILE_SUFFIX = ".verification.json"


VERIFY_STAGE_PREFIX = "verify."
"""`verify.<candidate_id>`; stage names double as checkpoint filenames, so they stay
path-safe."""


def verify_stage_name(candidate_id: str) -> str:
    """The stage that verifies one candidate."""
    return f"{VERIFY_STAGE_PREFIX}{candidate_id}"


def evidence_digest(candidate: EvidenceCandidate) -> str:
    """A hash of what is being checked: the anchor and the assertion, not who proposed it.

    Re-extracting the same span with another provider must not force re-verification; editing
    the text or moving the anchor must.
    """
    content = candidate.evidence.content
    anchor = candidate.evidence.source
    payload = {
        "anchor": {
            "artifact": str(anchor.artifact),
            "block": str(anchor.block),
            "char_start": anchor.char_start,
            "char_end": anchor.char_end,
            "file_hash": anchor.file_hash,
            "text_hash": anchor.text_hash,
        },
        "content": content.model_dump(mode="json"),
        "field": candidate.field,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


class VerifyCandidate(StageBase):
    """Checks one candidate against its source spans and writes the result back to staging."""

    def __init__(
        self,
        candidate: EvidenceCandidate,
        document: DocumentSource,
        provider: ModelClient,
        staging: StagingStore,
        *,
        neighbors: int = DEFAULT_NEIGHBOURS,
    ) -> None:
        super().__init__(verify_stage_name(candidate.candidate_id), version="1", idempotent=True)
        self.candidate = candidate
        self._document = document
        self._provider = provider
        self._staging = staging
        self._neighbors = neighbors

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        """Candidate identity, what it asserts, the verifier template, and the model used."""
        backend = resolve_backend(self._provider, VERIFIER)
        return {
            "candidate_id": self.candidate.candidate_id,
            "evidence_digest": evidence_digest(self.candidate),
            "template_version": VERIFIER.template_version,
            "provider": backend.provider,
            "model": backend.model,
            "neighbors": self._neighbors,
        }

    def run(self, ctx: StageContext) -> dict[str, Any]:
        verified = verify_candidate(
            self.candidate, self._document.get(), self._provider, neighbors=self._neighbors
        )
        self._staging.put(verified)
        _write_verdict(ctx.staging_dir, verified)
        assert verified.verification is not None
        return {
            "candidate_id": verified.candidate_id,
            "verdict": verified.verification.verdict.value,
            "discrepancies": len(verified.verification.discrepancies),
            "verifier": verified.verifier,
        }


def build_verify_workflow(
    candidates: Sequence[EvidenceCandidate],
    *,
    document: DocumentSource,
    provider: ModelClient,
    staging: StagingStore,
    neighbors: int = DEFAULT_NEIGHBOURS,
) -> Workflow:
    """`load_document` → one `verify:<candidate_id>` stage per candidate."""
    stages: list[Any] = [LoadDocument(document)]
    stages.extend(
        VerifyCandidate(candidate, document, provider, staging, neighbors=neighbors)
        for candidate in candidates
    )
    return Workflow(name=VERIFY_WORKFLOW, version=WORKFLOW_VERSION, stages=stages)


@dataclass(frozen=True)
class VerificationReport:
    """What one verification run decided, and what it did not need to decide again."""

    run: WorkflowRun
    candidates: list[EvidenceCandidate] = field(default_factory=list)
    verdicts: dict[str, VerificationVerdict] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    """Candidates that already carried a verification result and were not re-verified."""

    conflicts: list[ConflictRecord] = field(default_factory=list)
    """Provider disagreements this run materialized; empty when the providers agreed."""

    cross_verifications: dict[str, CrossVerification] = field(default_factory=dict)
    """Candidate id -> what the second opinion found, agreement included, for the run record."""

    def by_verdict(self, verdict: VerificationVerdict) -> list[EvidenceCandidate]:
        """Verified candidates carrying one verdict."""
        return [
            candidate
            for candidate in self.candidates
            if candidate.verification is not None and candidate.verification.verdict is verdict
        ]


def run_verification(
    engine: WorkflowEngine,
    staging: StagingStore,
    repo: WorkspaceRepository,
    work: WorkId,
    provider: ModelClient,
    *,
    candidate_ids: Sequence[str] | None = None,
    run_id: str | None = None,
    artifact: ArtifactId | None = None,
    neighbors: int = DEFAULT_NEIGHBOURS,
    force: bool = False,
    cross_verify_providers: Sequence[CrossVerifyCandidate] | None = None,
    policy: CrossVerifyPolicy | None = None,
) -> VerificationReport:
    """Verify a work's staged candidates (or the named ones) and write the results back.

    Candidates that already carry a verification result are skipped unless `force` is set:
    a second identical verdict is not a second opinion.

    `cross_verify_providers` opts one run into selective cross-verification. It runs after
    the workflow, on the verified candidates that meet a gate in `CANDIDATE_GATES`, and it
    is deliberately outside the stage graph: it must not change any stage fingerprint, and a
    second opinion is a policy decision of the caller rather than part of what verification
    means. The staged verification record is never rewritten — a disagreement becomes a
    `ConflictRecord`, and agreement becomes nothing at all.
    """
    pending: list[EvidenceCandidate] = []
    skipped: list[str] = []
    for candidate in _selected(staging, work, candidate_ids):
        if candidate.verification is not None and not force:
            skipped.append(candidate.candidate_id)
        else:
            pending.append(candidate)

    document = DocumentSource(repo, work, artifact)
    workflow = build_verify_workflow(
        pending, document=document, provider=provider, staging=staging, neighbors=neighbors
    )
    inputs: dict[str, Any] = {
        "work": str(work),
        "artifact": None if artifact is None else str(artifact),
        "candidates": [candidate.candidate_id for candidate in pending],
        "neighbors": neighbors,
    }
    run = engine.start(workflow, inputs) if run_id is None else engine.store.load(run_id)
    run = engine.execute(run.run_id, workflow, inputs, force=force or run_id is not None)

    verified = [staging.get(candidate.candidate_id, work=work) for candidate in pending]
    verifications, conflicts = _cross_verify_all(
        verified,
        document=document,
        providers=cross_verify_providers,
        policy=policy if policy is not None else DEFAULT_POLICY,
        conflicts=ConflictStore(staging.research_dir),
        neighbors=neighbors,
        run_id=run.run_id,
    )
    return VerificationReport(
        run=run,
        candidates=verified,
        verdicts={
            candidate.candidate_id: candidate.verification.verdict
            for candidate in verified
            if candidate.verification is not None
        },
        skipped=skipped,
        conflicts=conflicts,
        cross_verifications=verifications,
    )


# --------------------------------------------------------------- selective cross-checking


def candidate_eligibility(policy: CrossVerifyPolicy, candidate: EvidenceCandidate) -> Eligibility:
    """Whether one staged candidate is worth a second provider, and every reason either way.

    A candidate has no claim and no manuscript sentence behind it yet, so the two gates it
    can meet on its own are the ones Product §20.4 states about the *result*: a measured
    value, and a reading that contradicts what was proposed. Everything else is routine
    extraction and is never doubled.
    """
    reasons: list[str] = []
    for gate in CANDIDATE_GATES:
        if not policy.enables(gate):
            reasons.append(
                f"gate {gate.value!r} is not enabled by this policy; routine work is not "
                "cross-verified (Product 20.4)"
            )
            continue
        matched, reason = _gate_matches(gate, candidate)
        reasons.append(reason)
        if matched:
            return Eligibility(eligible=True, gate=gate, reasons=tuple(reasons))
    return Eligibility(eligible=False, gate=CANDIDATE_GATES[0], reasons=tuple(reasons))


def cross_verify_candidate(
    candidate: EvidenceCandidate,
    doc: ParsedDocument,
    providers: Sequence[CrossVerifyCandidate],
    *,
    policy: CrossVerifyPolicy = DEFAULT_POLICY,
    neighbors: int = DEFAULT_NEIGHBOURS,
) -> CrossVerification | None:
    """Ask several providers the same verifier question about one candidate.

    Returns ``None`` when no gate applies, which is the common case. The request is built the
    way `verify_candidate` builds it — the same source spans, the same candidate assertion,
    and nothing from whoever answered first — so the second opinion is independent rather
    than a review of the first one (ADR-003).
    """
    eligibility = candidate_eligibility(policy, candidate)
    if not eligibility.eligible:
        logger.debug(
            "candidate %s is not cross-verified: %s",
            candidate.candidate_id,
            "; ".join(eligibility.reasons),
        )
        return None
    built = build_request(VERIFIER, build_source_context(doc, candidate, neighbors=neighbors))
    return cross_verify(
        built.request,
        [_as_candidate(item) for item in providers],
        gate=eligibility.gate,
        policy=policy,
        eligibility=eligibility,
        decision_fields=VERIFICATION_DECISION_FIELDS,
        subject=candidate.candidate_id,
    )


# ------------------------------------------------------------------------------ helpers


def _cross_verify_all(
    candidates: Sequence[EvidenceCandidate],
    *,
    document: DocumentSource,
    providers: Sequence[CrossVerifyCandidate] | None,
    policy: CrossVerifyPolicy,
    conflicts: ConflictStore,
    neighbors: int,
    run_id: str,
) -> tuple[dict[str, CrossVerification], list[ConflictRecord]]:
    """Cross-verify the eligible candidates and materialize every disagreement, once each.

    The candidate itself is never written back: keeping the first provider's verdict is what
    makes "one explicit conflict rather than one provider silently overwriting the other"
    true on disk (ROADMAP Gate P13).
    """
    if not providers:
        return ({}, [])
    verifications: dict[str, CrossVerification] = {}
    records: list[ConflictRecord] = []
    doc = document.get()
    for candidate in candidates:
        verification = cross_verify_candidate(
            candidate, doc, providers, policy=policy, neighbors=neighbors
        )
        if verification is None:
            continue
        verifications[candidate.candidate_id] = verification
        record = materialize_provider_conflict(
            verification,
            subject=candidate.candidate_id,
            run_id=run_id,
            current={"verdict": candidate.verdict} if candidate.verdict else None,
        )
        if record is None:
            continue
        records.append(conflicts.open_or_put(record))
        logger.info(
            "candidate %s keeps the verdict of %s; providers disagree in conflict %s",
            candidate.candidate_id,
            candidate.verifier,
            records[-1].conflict_id,
        )
    return (verifications, records)


def _gate_matches(gate: CrossVerificationGate, candidate: EvidenceCandidate) -> tuple[bool, str]:
    """Whether one candidate meets one gate, and the reason it does or does not."""
    if gate is CrossVerificationGate.NUMERIC_HIGH_IMPACT:
        if candidate.evidence.content.numeric is not None:
            return (True, "the candidate carries a measured value (Product 12)")
        return (False, "the candidate carries no measured value")
    if candidate.verdict == VerificationVerdict.CONTRADICTED.value:
        return (True, "the verifier read the source as contradicting the candidate")
    return (False, f"the verifier reported {candidate.verdict or 'nothing yet'}")


def _as_candidate(item: CrossVerifyCandidate) -> ProviderCandidate:
    """Normalize an offered provider into the `(provider, model)` pair `cross_verify` takes."""
    if isinstance(item, ProviderEntry | tuple):
        return item
    return (item, resolve_backend(item, VERIFIER).model)


def _selected(
    staging: StagingStore, work: WorkId, candidate_ids: Sequence[str] | None
) -> list[EvidenceCandidate]:
    """The candidates a run should consider: the named ones, else every proposal for the work."""
    if candidate_ids is None:
        return staging.list(work=work, status=CandidateStatus.PROPOSED)
    return [staging.get(candidate_id, work=work) for candidate_id in candidate_ids]


def _write_verdict(staging_dir: Path, candidate: EvidenceCandidate) -> None:
    """Keep the verdict beside the run for inspection; the store holds the real record."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    path = staging_dir / f"{candidate.candidate_id}{VERDICT_FILE_SUFFIX}"
    payload = (
        None if candidate.verification is None else candidate.verification.model_dump(mode="json")
    )
    path.write_text(
        json.dumps(
            {"candidate_id": candidate.candidate_id, "verification": payload},
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

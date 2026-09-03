"""CLAIM AUDIT: bound one claim, resumably, without touching a single canonical file.

Five stages, each checkpointed: `collect` loads the claim and its accepted evidence through
a caller-supplied loader, `local_audit` computes the deterministic ceiling, `skeptic` runs
the adversarial model pass, `cross_verify` consults a second provider at a high-value gate,
and `report` writes the audit under `.research/staging/claim_audit/<claim>/<run_id>.json`.

The stage split is what makes a re-audit cheap and honest. The deterministic ceiling does
not depend on any provider, so swapping models recomputes the model stages and leaves the
ladder result exactly where it was; and because the model stages' fingerprints name the
provider, the model, and the role template version, changing any of them recomputes that
stage and nothing before it (Product 19.1).

Nothing here writes canonical state. The audit is a proposal: `allowed_strength` on a Claim
changes only when a researcher drives the capability layer with this result, and an override
above the recommendation needs an accepted `epistemic_override` Decision (ADR-001, ADR-003,
ADR-007, Product 38).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from research_harness.claims.audit import (
    ClaimAuditInput,
    ClaimAuditResult,
    apply_auditor,
    apply_cross_verification,
    apply_skeptic,
    audit_claim_locally,
    available_providers,
    backend_label,
    build_auditor_request,
    select_cross_verify_gate,
)
from research_harness.domain.ids import ClaimId
from research_harness.evidence.conflicts import (
    ConflictRecord,
    ConflictStore,
    materialize_provider_conflict,
)
from research_harness.providers.models.cross_verify import (
    DEFAULT_POLICY,
    CrossVerifyPolicy,
    provider_label,
)
from research_harness.roles.auditor import CLAIM_AUDITOR
from research_harness.roles.skeptic import SKEPTIC
from research_harness.workflows.engine import (
    StageBase,
    StageContext,
    Workflow,
    WorkflowEngine,
)
from research_harness.workflows.fingerprints import fingerprint
from research_harness.workflows.models import WorkflowRun
from research_harness.workspace.runs import STAGING_DIRNAME

logger = logging.getLogger(__name__)

__all__ = [
    "CLAIM_AUDIT_WORKFLOW",
    "COLLECT_STAGE",
    "CROSS_VERIFY_STAGE",
    "LOCAL_STAGE",
    "NO_GATE_REASON",
    "NO_MODEL_REASON",
    "REPORT_DIRNAME",
    "REPORT_STAGE",
    "RESULT_FILENAME",
    "SKEPTIC_STAGE",
    "WORKFLOW_VERSION",
    "ClaimAuditSource",
    "CollectClaim",
    "CrossVerifyClaim",
    "LocalAudit",
    "ModelPass",
    "WriteReport",
    "build_claim_audit_workflow",
    "read_result",
    "report_path",
    "run_claim_audit",
]

CLAIM_AUDIT_WORKFLOW = "claim_audit"
WORKFLOW_VERSION = "1.0.0"

COLLECT_STAGE = "collect"
LOCAL_STAGE = "local_audit"
SKEPTIC_STAGE = "skeptic"
CROSS_VERIFY_STAGE = "cross_verify"
REPORT_STAGE = "report"

REPORT_DIRNAME = "claim_audit"
"""Directory under `.research/staging/` the audit reports live in; disposable state."""

RESULT_FILENAME = "audit.json"
"""The working result inside the run's own staging directory, passed between stages."""

NO_MODEL_REASON = "no skeptic or auditor provider is configured"
NO_GATE_REASON = "no enabled cross-verification gate applies to this claim"


# ------------------------------------------------------------------------------- loading


class ClaimAuditSource:
    """Loads the audit input once per process and hands the same objects to every stage.

    Stages need the real objects, but a cached stage never runs, so the load cannot live
    inside `collect.run`. It lives here instead, lazily, and only reads.
    """

    def __init__(self, loader: Callable[[], ClaimAuditInput]) -> None:
        self._loader = loader
        self._input: ClaimAuditInput | None = None
        self._digest: str | None = None

    def get(self) -> ClaimAuditInput:
        """The audit input, loaded on first use."""
        if self._input is None:
            self._input = self._loader()
        return self._input

    def digest(self) -> str:
        """A fingerprint of the audited state: the claim, its evidence, works, and runs.

        The providers are deliberately absent — they belong to the model stages' own
        fingerprints, so configuring a second provider does not invalidate the ladder.
        """
        if self._digest is None:
            data = self.get()
            self._digest = fingerprint(
                {
                    "claim": data.claim,
                    "evidence": dict(data.evidence),
                    "works": dict(data.works),
                    "search_runs": list(data.search_runs),
                    "counter_limit": data.counter_limit,
                    "manuscript_attached": data.manuscript_attached,
                    "submission_ready": data.submission_ready,
                }
            )
        return self._digest


# -------------------------------------------------------------------------------- stages


class CollectClaim(StageBase):
    """Reports what the audit will read, so a run record says what it was about."""

    def __init__(self, source: ClaimAuditSource) -> None:
        super().__init__(COLLECT_STAGE, version="1", idempotent=True)
        self._source = source

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        return {"claim": ctx.inputs.get("claim"), "state": self._source.digest()}

    def run(self, ctx: StageContext) -> dict[str, Any]:
        data = self._source.get()
        return {
            "claim": str(data.claim.id),
            "evidence": sorted(str(key) for key in data.evidence),
            "works": sorted(str(key) for key in data.works),
            "search_runs": [str(run.id) for run in data.search_runs],
            "relations": len(data.claim.relations),
            "counter_finder": data.counter_finder is not None,
            "skeptic": data.skeptic is not None,
            "auditor": data.auditor is not None,
        }


class LocalAudit(StageBase):
    """The deterministic audit: scope ceiling, independence, coverage, and proposals."""

    def __init__(self, source: ClaimAuditSource) -> None:
        super().__init__(LOCAL_STAGE, version="1", idempotent=True)
        self._source = source

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        return {"state": self._source.digest()}

    def run(self, ctx: StageContext) -> dict[str, Any]:
        result = audit_claim_locally(self._source.get())
        _write_result(ctx.staging_dir, result)
        return _summary(result)


class ModelPass(StageBase):
    """The adversarial model pass: the Skeptic looks for what breaks the claim, then the
    Claim Auditor reports the strongest wording it can defend.

    Both are proposals and both may only narrow the deterministic result. The stage is
    skipped when neither provider is configured: a workspace with no model still gets a
    complete audit from the stage before this one.
    """

    def __init__(self, source: ClaimAuditSource) -> None:
        super().__init__(SKEPTIC_STAGE, version="1", idempotent=True)
        self._source = source

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        """The audited state plus which model, under which template, will answer."""
        data = self._source.get()
        return {
            "state": self._source.digest(),
            "skeptic": backend_label(data.skeptic, SKEPTIC),
            "skeptic_template": SKEPTIC.template_version,
            "auditor": backend_label(data.auditor, CLAIM_AUDITOR),
            "auditor_template": CLAIM_AUDITOR.template_version,
        }

    def run(self, ctx: StageContext) -> dict[str, Any]:
        data = self._source.get()
        result = _require_result(ctx.staging_dir)
        if data.skeptic is None and data.auditor is None:
            return {"skipped": NO_MODEL_REASON, **_summary(result)}
        result = apply_skeptic(result, data)
        request = build_auditor_request(data, result).request
        result = apply_auditor(result, data, request=request)
        _write_result(ctx.staging_dir, result)
        return {
            "judgements": [
                {"role": judgement.role, "backend": judgement.label}
                for judgement in result.model_judgements
            ],
            **_summary(result),
        }


class CrossVerifyClaim(StageBase):
    """Runs the auditor request through a second provider at a high-value gate.

    Skipped when no enabled gate applies, which is the normal case: routine audits are not
    doubled (Product 20.4). A disagreement is materialized as one `ConflictRecord` under
    `.research/staging/conflicts/<claim>/` and resolves nothing; agreement writes nothing at
    all, because an agreement record would eventually be read as permission to accept a
    Tier-2 judgement, and two agreeing models are still two models (ADR-007, Task 13.2).

    The stage calls no capability and touches no canonical file either way: the claim's
    `allowed_strength` moves only when a researcher drives the capability layer with this
    result (ADR-001, ADR-004).
    """

    def __init__(
        self, source: ClaimAuditSource, policy: CrossVerifyPolicy, research_dir: Path
    ) -> None:
        super().__init__(CROSS_VERIFY_STAGE, version="1", idempotent=True)
        self._source = source
        self._policy = policy
        self._conflicts = ConflictStore(Path(research_dir))

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        data = self._source.get()
        eligibility = select_cross_verify_gate(data, self._policy)
        return {
            "state": self._source.digest(),
            "gate": None if eligibility is None else eligibility.gate.value,
            "policy": _policy_key(self._policy),
            "providers": [provider_label(item) for item in available_providers(data)],
        }

    def run(self, ctx: StageContext) -> dict[str, Any]:
        data = self._source.get()
        result = _require_result(ctx.staging_dir)
        eligibility = select_cross_verify_gate(data, self._policy)
        if eligibility is None:
            return {"skipped": NO_GATE_REASON, **_summary(result)}
        request = build_auditor_request(data, result).request
        result = apply_cross_verification(result, data, request=request, policy=self._policy)
        _write_result(ctx.staging_dir, result)
        verification = result.cross_verification
        record = self._materialize(result, ctx.run.run_id)
        return {
            "gate": eligibility.gate.value,
            "agreement": verification is not None and verification.agreement,
            "incomplete": verification is not None and verification.incomplete,
            "skipped_reason": None if verification is None else verification.skipped_reason,
            "positions": []
            if verification is None
            else [position.label for position in verification.positions],
            "conflict": result.has_conflict,
            "conflict_id": None if record is None else record.conflict_id,
            **_summary(result),
        }

    def _materialize(self, result: ClaimAuditResult, run_id: str) -> ConflictRecord | None:
        """Persist a provider disagreement as a reviewable object; agreement persists nothing."""
        verification = result.cross_verification
        if verification is None:
            return None
        record = materialize_provider_conflict(
            verification,
            subject=str(result.claim),
            run_id=run_id,
            current={"recommended_scope": result.recommended_scope.value},
        )
        if record is None:
            return None
        stored = self._conflicts.open_or_put(record)
        logger.info(
            "claim %s cross-verification opened conflict %s", result.claim, stored.conflict_id
        )
        return stored


class WriteReport(StageBase):
    """Writes the audit where a reviewer and the CLI can find it; disposable by design."""

    def __init__(self, source: ClaimAuditSource, research_dir: Path, claim: ClaimId) -> None:
        super().__init__(REPORT_STAGE, version="1", idempotent=True)
        self._source = source
        self._research_dir = Path(research_dir)
        self._claim = claim

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        return {"claim": str(self._claim), "state": self._source.digest()}

    def run(self, ctx: StageContext) -> dict[str, Any]:
        result = _require_result(ctx.staging_dir)
        path = report_path(self._research_dir, self._claim, ctx.run.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "workflow": CLAIM_AUDIT_WORKFLOW,
            "workflow_version": WORKFLOW_VERSION,
            "run_id": ctx.run.run_id,
            "claim": str(self._claim),
            "result": result.model_dump(mode="json"),
        }
        path.write_text(_dump(payload), encoding="utf-8")
        return {"report": _relative(path, self._research_dir), **_summary(result)}


# ------------------------------------------------------------------------------ workflow


def build_claim_audit_workflow(
    source: ClaimAuditSource,
    *,
    research_dir: Path,
    claim: ClaimId,
    policy: CrossVerifyPolicy | None = None,
) -> Workflow:
    """`collect` → `local_audit` → `skeptic` → `cross_verify` → `report`."""
    active = policy if policy is not None else DEFAULT_POLICY
    return Workflow(
        name=CLAIM_AUDIT_WORKFLOW,
        version=WORKFLOW_VERSION,
        stages=[
            CollectClaim(source),
            LocalAudit(source),
            ModelPass(source),
            CrossVerifyClaim(source, active, research_dir),
            WriteReport(source, research_dir, claim),
        ],
    )


def run_claim_audit(
    engine: WorkflowEngine,
    research_dir: Path,
    loader: Callable[[], ClaimAuditInput],
    claim_id: ClaimId,
    *,
    policy: CrossVerifyPolicy | None = None,
    run_id: str | None = None,
    force: bool = False,
) -> tuple[WorkflowRun, ClaimAuditResult]:
    """Audit one claim and return the run beside its result; resumes `run_id` when given.

    Passing `run_id` re-executes that run, reusing every stage whose fingerprint still
    matches, so a resume after a provider failure does not pay for the audit twice.
    """
    source = ClaimAuditSource(loader)
    workflow = build_claim_audit_workflow(
        source, research_dir=research_dir, claim=claim_id, policy=policy
    )
    inputs: dict[str, Any] = {
        "claim": str(claim_id),
        "policy": _policy_key(policy if policy is not None else DEFAULT_POLICY),
    }
    run = engine.start(workflow, inputs) if run_id is None else engine.store.load(run_id)
    run = engine.execute(run.run_id, workflow, inputs, force=force or run_id is not None)
    return run, _require_result(engine.store.staging_dir(run.run_id))


def report_path(research_dir: Path, claim: ClaimId, run_id: str) -> Path:
    """`<research_dir>/staging/claim_audit/<claim>/<run_id>.json`."""
    return Path(research_dir) / STAGING_DIRNAME / REPORT_DIRNAME / str(claim) / f"{run_id}.json"


def read_result(path: Path) -> ClaimAuditResult:
    """Read an audit back from a report file written by the `report` stage."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ClaimAuditResult.model_validate(payload["result"])


# ------------------------------------------------------------------------------- helpers


def _result_file(staging_dir: Path) -> Path:
    return staging_dir / RESULT_FILENAME


def _write_result(staging_dir: Path, result: ClaimAuditResult) -> None:
    """Persist the working result so the next stage reads it, cached or not."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    _result_file(staging_dir).write_text(_dump(result.model_dump(mode="json")), encoding="utf-8")


def _require_result(staging_dir: Path) -> ClaimAuditResult:
    """The working result of this run; missing it means the local audit never ran."""
    path = _result_file(staging_dir)
    if not path.is_file():
        raise FileNotFoundError(f"no claim audit result under {staging_dir}; run {LOCAL_STAGE}")
    return ClaimAuditResult.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _summary(result: ClaimAuditResult) -> dict[str, Any]:
    """The part of an audit a checkpoint keeps: ids and decisions, never model prose."""
    return {
        "claim": str(result.claim),
        "requested": result.assessment.requested.value,
        "recommended_scope": result.recommended_scope.value,
        "status": result.status.value,
        "maximum_defensible_wording": result.maximum_defensible_wording,
        "support": [str(item) for item in result.support],
        "counter_evidence": [str(item) for item in result.counter_evidence],
        "qualifiers": [str(item) for item in result.qualifiers],
        "incomparable": [str(item.evidence) for item in result.incomparable],
        "counter_candidates": [item.ref for item in result.counter_candidates],
        "coverage_state": result.coverage_state,
        "escalation_prevented": result.escalation_prevented,
        "warnings": list(result.warnings),
    }


def _policy_key(policy: CrossVerifyPolicy) -> dict[str, Any]:
    """A deterministic rendering of a policy; sets have no order, so the gates are sorted."""
    return {
        "enabled_gates": sorted(gate.value for gate in policy.enabled_gates),
        "min_providers": policy.min_providers,
        "require_distinct_vendors": policy.require_distinct_vendors,
        "max_extra_calls_per_object": policy.max_extra_calls_per_object,
    }


def _relative(path: Path, research_dir: Path) -> str:
    try:
        return path.relative_to(research_dir).as_posix()
    except ValueError:  # pragma: no cover - the report always lands inside the research dir
        return str(path)


def _dump(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

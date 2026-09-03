"""MANUSCRIPT_AUDIT: a resumable audit of a LaTeX project against the research graph.

Four stages, in the order a researcher would do it by hand: `load` reads the manuscript,
the anchors, and the claims; `revalidate_anchors` re-finds every anchored sentence;
`audit` runs :func:`~research_harness.manuscript.audit.audit_manuscript`; `report` writes
the JSON report. The load stage's fingerprint is the manuscript's file hashes plus a digest
of the anchors and of the claims, so re-running after a taxonomy change or a reword
recomputes the audit, and re-running after an unrelated edit does not.

Nothing here writes canonical state. The report lands under
``<research_dir>/staging/manuscript_audit/<run_id>.json``, which is regenerable runtime
state with no scientific authority (ADR-001); acting on a finding is a researcher's job,
through a capability handler, outside this workflow.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from research_harness.domain.claim import Claim
from research_harness.domain.enums import FindingSeverity
from research_harness.domain.ids import ClaimId
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.manuscript.anchors import AnchorRevalidation, anchor_key, revalidate_all
from research_harness.manuscript.audit import AuditContext, ManuscriptAuditReport, audit_manuscript
from research_harness.manuscript.latex import LatexProject
from research_harness.workflows.engine import (
    StageBase,
    StageContext,
    Workflow,
    WorkflowEngine,
)
from research_harness.workflows.fingerprints import fingerprint
from research_harness.workflows.models import WorkflowRun

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_STAGE",
    "LOAD_STAGE",
    "MANUSCRIPT_AUDIT_DIRNAME",
    "MANUSCRIPT_AUDIT_WORKFLOW",
    "REPORT_STAGE",
    "REVALIDATE_STAGE",
    "AuditManuscript",
    "LoadManuscript",
    "ManuscriptSource",
    "RevalidateAnchors",
    "WriteReport",
    "anchors_digest",
    "build_manuscript_audit_workflow",
    "claims_digest",
    "manuscript_digest",
    "report_path",
    "run_manuscript_audit",
]

MANUSCRIPT_AUDIT_WORKFLOW = "manuscript_audit"
WORKFLOW_VERSION = "1.0.0"

LOAD_STAGE = "load"
REVALIDATE_STAGE = "revalidate_anchors"
AUDIT_STAGE = "audit"
REPORT_STAGE = "report"

MANUSCRIPT_AUDIT_DIRNAME = "manuscript_audit"
"""Subdirectory of `<research_dir>/staging` the JSON reports are written to."""


# ------------------------------------------------------------------------------- digests


def manuscript_digest(project: LatexProject) -> str:
    """Hash of every source file of the manuscript, keyed by project-relative path.

    Content, not mtime: reformatting a file changes the audit, touching it does not.
    """
    return fingerprint({item.path: item.text for item in project.files})


def anchors_digest(anchors: Sequence[ManuscriptAnchor]) -> str:
    """Hash of what each anchor points at and what state it is in.

    Timestamps are excluded so that re-saving an unchanged anchor does not invalidate a
    checkpoint; status and staleness are included because they change the verdict. Entries
    are sorted by anchor key, so the digest does not depend on the order they were loaded.
    """
    rows = [
        {
            "key": anchor_key(anchor),
            "claim": str(anchor.claim),
            "citation_keys": list(anchor.citation_keys),
            "status": anchor.status.value,
            "stale": anchor.stale.value,
            "line_start": anchor.line_start,
            "char_start": anchor.char_start,
        }
        for anchor in anchors
    ]
    return fingerprint(sorted(rows, key=lambda row: str(row["key"])))


def claims_digest(claims: Mapping[ClaimId, Claim]) -> str:
    """Hash of everything about a claim that can change an audit finding."""
    rows = [
        {
            "id": str(claim.id),
            "statement": claim.statement,
            "allowed": claim.assessment.allowed_strength.value,
            "status": claim.status.value,
            "stale": claim.stale.value,
            "relations": [
                {"evidence": str(link.evidence), "relation": link.relation.value}
                for link in claim.relations
            ],
        }
        for claim in claims.values()
    ]
    return fingerprint(sorted(rows, key=lambda row: str(row["id"])))


def report_path(research_dir: Path, run_id: str) -> Path:
    """Where a run's JSON report lives: `<research_dir>/staging/manuscript_audit/<run_id>.json`."""
    return Path(research_dir) / "staging" / MANUSCRIPT_AUDIT_DIRNAME / f"{run_id}.json"


# -------------------------------------------------------------------------------- source


class ManuscriptSource:
    """Loads the audit context once per run and caches what each stage derived from it.

    Stages must not each re-parse the manuscript, and the report must be the same object the
    audit stage produced, so the derived values live here rather than in stage state.
    """

    def __init__(self, loader: Callable[[], AuditContext]) -> None:
        self._loader = loader
        self._context: AuditContext | None = None
        self._revalidations: tuple[AnchorRevalidation, ...] | None = None
        self._report: ManuscriptAuditReport | None = None

    def context(self) -> AuditContext:
        """The audit context, loaded on first use."""
        if self._context is None:
            self._context = self._loader()
        return self._context

    def revalidations(self) -> tuple[AnchorRevalidation, ...]:
        """Anchor revalidation verdicts for this run."""
        if self._revalidations is None:
            ctx = self.context()
            self._revalidations = revalidate_all(list(ctx.anchors), ctx.project)
        return self._revalidations

    def report(self) -> ManuscriptAuditReport:
        """The audit report; computed once, and recomputed for nobody."""
        if self._report is None:
            self._report = audit_manuscript(self.context())
        return self._report


# -------------------------------------------------------------------------------- stages


class LoadManuscript(StageBase):
    """Parses the LaTeX project and reports what this run will be auditing."""

    def __init__(self, source: ManuscriptSource) -> None:
        super().__init__(LOAD_STAGE, version="1", idempotent=True)
        self._source = source

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        """The manuscript bytes, the anchors, and the claims: everything the audit reads."""
        del ctx
        context = self._source.context()
        return {
            "manuscript": manuscript_digest(context.project),
            "anchors": anchors_digest(list(context.anchors)),
            "claims": claims_digest(context.claims),
        }

    def run(self, ctx: StageContext) -> dict[str, Any]:
        del ctx
        context = self._source.context()
        return {
            "main": context.project.main,
            "files": [item.path for item in context.project.files],
            "sentences": len(context.project.sentences),
            "anchors": len(context.anchors),
            "claims": len(context.claims),
            "evidence": len(context.evidence),
            "parsed_artifacts": sorted(str(key) for key in context.parsed),
            "warnings": list(context.project.warnings),
        }


class RevalidateAnchors(StageBase):
    """Re-finds every anchored sentence; a reword goes stale rather than moving (ADR-008)."""

    def __init__(self, source: ManuscriptSource) -> None:
        super().__init__(REVALIDATE_STAGE, version="1", idempotent=True)
        self._source = source

    def run(self, ctx: StageContext) -> dict[str, Any]:
        del ctx
        results = self._source.revalidations()
        return {
            "results": [
                {
                    "anchor": anchor_key(result.anchor),
                    "claim": str(result.anchor.claim),
                    "status": result.status.value,
                    "similarity": result.similarity,
                    "reason": result.reason,
                }
                for result in results
            ],
            "valid": sum(1 for result in results if result.status.value == "valid"),
            "stale": sum(1 for result in results if result.status.value == "stale"),
            "missing": sum(1 for result in results if result.status.value == "missing"),
        }


class AuditManuscript(StageBase):
    """Runs the pure auditor and summarizes it; the full report is written by `report`."""

    def __init__(self, source: ManuscriptSource) -> None:
        super().__init__(AUDIT_STAGE, version="1", idempotent=True)
        self._source = source

    def run(self, ctx: StageContext) -> dict[str, Any]:
        del ctx
        report = self._source.report()
        counts: dict[str, int] = {}
        for finding in report.findings:
            counts[finding.kind.value] = counts.get(finding.kind.value, 0) + 1
        return {
            "findings": len(report.findings),
            "errors": len(report.errors),
            "by_kind": counts,
            "sentences_checked": report.sentences_checked,
            "anchored_sentences": report.anchored_sentences,
            "unanchored_substantive": report.unanchored_substantive,
            "trace_links": len(report.trace),
        }


class WriteReport(StageBase):
    """Writes the full JSON report under the run's staging area; no canonical write."""

    def __init__(self, source: ManuscriptSource, research_dir: Path | None = None) -> None:
        super().__init__(REPORT_STAGE, version="1", idempotent=True)
        self._source = source
        self._research_dir = research_dir

    def run(self, ctx: StageContext) -> dict[str, Any]:
        report = self._source.report()
        path = self._path(ctx)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = report.model_dump(mode="json")
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info("wrote manuscript audit report %s", path)
        return {
            "path": path.as_posix(),
            "findings": len(report.findings),
            "errors": sum(
                1 for finding in report.findings if finding.severity is FindingSeverity.ERROR
            ),
        }

    def _path(self, ctx: StageContext) -> Path:
        """`<research_dir>/staging/manuscript_audit/<run_id>.json`.

        When no research directory was supplied the staging root is derived from the run's
        own staging directory, so the report never escapes `.research/staging/`.
        """
        if self._research_dir is not None:
            return report_path(self._research_dir, ctx.run.run_id)
        return ctx.staging_dir.parent / MANUSCRIPT_AUDIT_DIRNAME / f"{ctx.run.run_id}.json"


def build_manuscript_audit_workflow(
    ctx_loader: Callable[[], AuditContext],
    *,
    research_dir: Path | None = None,
    source: ManuscriptSource | None = None,
) -> Workflow:
    """`load` -> `revalidate_anchors` -> `audit` -> `report`, over one manuscript.

    Pass ``source`` to share one :class:`ManuscriptSource` with the caller, which is how
    :func:`run_manuscript_audit` gets back the very report the `audit` stage produced.
    """
    shared = source if source is not None else ManuscriptSource(ctx_loader)
    return Workflow(
        name=MANUSCRIPT_AUDIT_WORKFLOW,
        version=WORKFLOW_VERSION,
        stages=[
            LoadManuscript(shared),
            RevalidateAnchors(shared),
            AuditManuscript(shared),
            WriteReport(shared, research_dir),
        ],
    )


def run_manuscript_audit(
    engine: WorkflowEngine,
    research_dir: Path,
    ctx_loader: Callable[[], AuditContext],
    *,
    run_id: str | None = None,
    force: bool = False,
) -> tuple[WorkflowRun, ManuscriptAuditReport]:
    """Audit a manuscript through a durable run and return the run and its report.

    The report is recomputed in-process when every stage was served from a checkpoint, so
    the returned object is always the audit of the context that was loaded, never a stale
    summary read back from a checkpoint file.
    """
    source = ManuscriptSource(ctx_loader)
    workflow = build_manuscript_audit_workflow(ctx_loader, research_dir=research_dir, source=source)
    inputs: dict[str, Any] = {"workflow": MANUSCRIPT_AUDIT_WORKFLOW}
    run = engine.start(workflow, inputs) if run_id is None else engine.store.load(run_id)
    run = engine.execute(run.run_id, workflow, inputs, force=force or run_id is not None)
    return run, source.report()

"""Binding manuscript prose to the research graph, and keeping the binding honest.

This is the service half of Product 30.1: the pure modules beside it decide *what* a
sentence is (:mod:`~research_harness.manuscript.latex`), *whether* an anchor still
resolves (:mod:`~research_harness.manuscript.anchors`), and *whether* the sentence is
defensible (:mod:`~research_harness.manuscript.audit`); this module opens the workspace,
finds the sentence a researcher pointed at, and writes the anchor through the capability
layer so the canonical file, the semantic event, and the stale set commit together
(ADR-001, ADR-004).

Two rules shape every method here.

*A Claim attaches to substantive prose only.* A heading, a caption, a float, and a
signpost sentence carry no research assertion, so :meth:`ManuscriptService.attach` refuses
them by name rather than recording an anchor nobody can audit.

*Revalidation reports; it never repairs.* A sentence that only moved keeps its anchor and
gains a new line range, because the fingerprint proves it is the same text. A reworded
sentence goes ``stale`` and a vanished one goes ``missing`` - recorded through the same
capability, so the researcher sees the state change instead of the anchor quietly staying
``valid`` over prose that no longer says what the Claim says (ADR-008, Roadmap Task 9.2).
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import (
    AttachManuscriptAnchorRequest,
    MutationResult,
)
from research_harness.capabilities.handlers import attach_manuscript_anchor
from research_harness.domain.claim import Claim
from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import ManuscriptAnchorStatus
from research_harness.domain.errors import AuthorityError, ResearchHarnessError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import ArtifactId, ClaimId, EvidenceId, WorkId
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.domain.work import Artifact, Work
from research_harness.manuscript.anchors import (
    AnchorRevalidation,
    anchor_key,
    apply_revalidation,
    build_anchor,
    revalidate_all,
)
from research_harness.manuscript.audit import (
    AuditContext,
    AuditScope,
    ManuscriptAuditReport,
    TraceLink,
    audit_manuscript,
    is_substantive,
    narrow_report,
)
from research_harness.manuscript.bibtex import BibDatabase, parse_bibtex_file
from research_harness.manuscript.latex import LatexProject, Sentence, normalize_sentence
from research_harness.parsing.base import ParseTarget
from research_harness.parsing.pymupdf_parser import PyMuPdfParser
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workflows.manuscript_audit import run_manuscript_audit
from research_harness.workflows.models import WorkflowRun
from research_harness.workspace.repository import ObjectNotFoundError

__all__ = [
    "BIBLIOGRAPHY_FILENAME",
    "DEFAULT_MAIN_TEX",
    "AuditScope",
    "ManuscriptError",
    "ManuscriptService",
    "RevalidationReport",
    "SentenceRef",
]

logger = logging.getLogger(__name__)

DEFAULT_MAIN_TEX = "main.tex"
"""Entry point of a manuscript project, unless the caller names another one."""

BIBLIOGRAPHY_FILENAME = "references.bib"
"""Bibliography read beside the main file; absent means "no citation closure", not "empty"."""


class ManuscriptError(ResearchHarnessError):
    """A manuscript location does not exist, or does not carry attachable prose."""


SentenceRef = Sentence | tuple[str, int]
"""A sentence itself, or the ``(file, line)`` a researcher pointed at."""


@dataclass(frozen=True, slots=True)
class RevalidationReport:
    """What re-finding every stored anchor produced, and what was recorded because of it.

    ``results`` holds one verdict per stored anchor in workspace order. ``applied`` and
    ``mutations`` are empty for a dry run; otherwise they name the anchors whose recorded
    state changed - a relocation adopting its new lines, or a reword/deletion taking the
    ``stale``/``missing`` status it earned. An anchor whose verdict changes nothing is not
    rewritten, so re-running revalidation is quiet.
    """

    results: tuple[AnchorRevalidation, ...] = ()
    applied: tuple[ManuscriptAnchor, ...] = ()
    mutations: tuple[MutationResult, ...] = ()

    @property
    def valid(self) -> tuple[AnchorRevalidation, ...]:
        """Anchors whose exact sentence is still in the manuscript, moved or not."""
        return self._of(ManuscriptAnchorStatus.VALID)

    @property
    def relocated(self) -> tuple[AnchorRevalidation, ...]:
        """Valid anchors whose sentence is now at a different span."""
        return tuple(result for result in self.valid if result.relocated is not None)

    @property
    def stale(self) -> tuple[AnchorRevalidation, ...]:
        """Anchors whose sentence was reworded: the Claim link needs a human again."""
        return self._of(ManuscriptAnchorStatus.STALE)

    @property
    def missing(self) -> tuple[AnchorRevalidation, ...]:
        """Anchors whose sentence is no longer anywhere in the file."""
        return self._of(ManuscriptAnchorStatus.MISSING)

    @property
    def applied_keys(self) -> tuple[str, ...]:
        """Anchor keys whose recorded state this run changed."""
        return tuple(anchor_key(anchor) for anchor in self.applied)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form for transports and ``--json`` output."""
        return {
            "checked": len(self.results),
            "valid": len(self.valid),
            "relocated": len(self.relocated),
            "stale": len(self.stale),
            "missing": len(self.missing),
            "applied": list(self.applied_keys),
            "results": [
                {
                    "anchor": anchor_key(result.anchor),
                    "claim": str(result.anchor.claim),
                    "file": result.anchor.file,
                    "line_start": result.anchor.line_start,
                    "status": result.status.value,
                    "similarity": result.similarity,
                    "reason": result.reason,
                    "relocated_to": (
                        None
                        if result.relocated is None
                        else [result.relocated.line_start, result.relocated.line_end]
                    ),
                }
                for result in self.results
            ],
            "mutations": [mutation.as_dict() for mutation in self.mutations],
        }

    def _of(self, status: ManuscriptAnchorStatus) -> tuple[AnchorRevalidation, ...]:
        return tuple(result for result in self.results if result.status is status)


@dataclass(frozen=True, slots=True)
class _Graph:
    """The accepted state one audit reads, loaded once from the repository."""

    works: dict[WorkId, Work] = field(default_factory=dict)
    claims: dict[ClaimId, Claim] = field(default_factory=dict)
    evidence: dict[EvidenceId, Evidence] = field(default_factory=dict)
    anchors: tuple[ManuscriptAnchor, ...] = ()


class ManuscriptService:
    """Attach, revalidate, audit, and trace the manuscript of one workspace.

    ``project_root`` defaults to the workspace's canonical ``manuscript/`` directory, so a
    plain ``ManuscriptService(ctx)`` operates on the manuscript the workspace already owns.
    """

    def __init__(
        self,
        ctx: CapabilityContext,
        *,
        project_root: Path | None = None,
        main_tex: str = DEFAULT_MAIN_TEX,
    ) -> None:
        self._ctx = ctx
        self._root = (
            Path(project_root) if project_root is not None else ctx.repo.layout.manuscript_dir
        )
        self._main_tex = main_tex

    # -- locations -------------------------------------------------------------

    @property
    def ctx(self) -> CapabilityContext:
        """The capability context every mutation runs through."""
        return self._ctx

    @property
    def project_root(self) -> Path:
        """Directory holding the manuscript sources; anchors' file paths are relative to it."""
        return self._root

    @property
    def main_path(self) -> Path:
        """The main LaTeX file of the project."""
        return self._root / self._main_tex

    @property
    def bibliography_path(self) -> Path:
        """Where the bibliography is looked for; it does not have to exist."""
        return self._root / BIBLIOGRAPHY_FILENAME

    # -- reading the manuscript ------------------------------------------------

    def load_project(self) -> LatexProject:
        """Parse the manuscript from disk. Never cached: an edit must be visible at once."""
        if not self.main_path.is_file():
            raise ManuscriptError(
                f"no manuscript at {self.main_path}: put a LaTeX project under "
                f"{self._root} or pass project_root"
            )
        return LatexProject.load(self.main_path)

    def bibliography(self) -> BibDatabase | None:
        """The bibliography beside the main file, or ``None`` when there is none."""
        path = self.bibliography_path
        return parse_bibtex_file(path) if path.is_file() else None

    def find_sentence(self, file: str, line: int) -> Sentence:
        """The sentence covering ``file``:``line``; refuses a heading, a float, or a gap."""
        project = self.load_project()
        path = self.relative_path(file)
        if project.file(path) is None:
            known = ", ".join(item.path for item in project.files) or "nothing"
            raise ManuscriptError(f"{path} is not part of this manuscript; it contains: {known}")
        for sentence in project.sentences_for_file(path):
            if sentence.line_start <= line <= sentence.line_end:
                return sentence
        raise ManuscriptError(self._nothing_at(project, path, line))

    def find_sentence_by_text(self, text: str) -> Sentence:
        """The one sentence whose normalized text is ``text``, or contains it.

        Exact matches win over containment, and an ambiguous quotation is refused rather
        than resolved to the first hit: attaching a Claim to the wrong sentence is worse
        than asking the researcher to be specific.
        """
        project = self.load_project()
        needle = normalize_sentence(text)
        if not needle:
            raise ManuscriptError("cannot look up an empty sentence")
        exact = [item for item in project.sentences if item.normalized_text == needle]
        found = exact or [item for item in project.sentences if needle in item.normalized_text]
        if not found:
            raise ManuscriptError(f"no sentence of this manuscript matches {text!r}")
        if len(found) > 1:
            where = ", ".join(f"{item.file}:{item.line_start}" for item in found)
            raise ManuscriptError(
                f"{text!r} matches {len(found)} sentences ({where}); quote more of it, or "
                "use `manuscript attach <file>:<line>`"
            )
        return found[0]

    def resolve(self, sentence: SentenceRef) -> Sentence:
        """A sentence, whether the caller passed the object or a ``(file, line)`` pair."""
        if isinstance(sentence, Sentence):
            return sentence
        return self.find_sentence(*sentence)

    def relative_path(self, file: str | Path) -> str:
        """Normalize a user-supplied path to the project-relative POSIX form anchors use."""
        candidate = Path(file)
        if candidate.is_absolute():
            try:
                return candidate.resolve().relative_to(self._root.resolve()).as_posix()
            except ValueError as error:
                raise ManuscriptError(
                    f"{candidate} is outside the manuscript project at {self._root}"
                ) from error
        return PurePosixPath(candidate.as_posix()).as_posix()

    # -- attaching -------------------------------------------------------------

    def attach(
        self, sentence: SentenceRef, claim: ClaimId
    ) -> tuple[ManuscriptAnchor, MutationResult]:
        """Bind one substantive sentence to an existing Claim (`manuscript.attach_claim`).

        Attaching prose to a Claim is a scientific judgement about what the sentence
        asserts, so it is a researcher action: a model actor is refused (ADR-007). The
        anchor records the sentence's location, its normalized text, its fingerprint, and
        the keys it cites, which is what makes a later reword detectable (ADR-008).
        """
        if not self._ctx.is_human:
            raise AuthorityError(
                "manuscript.attach_claim: only a human actor may attach a Claim to "
                f"manuscript text; {self._ctx.actor!r} is not one"
            )
        target = self.resolve(sentence)
        self._require_substantive(target)
        anchor = build_anchor(target, claim, self._ctx.provenance(workflow="manuscript"))
        mutation = attach_manuscript_anchor(self._ctx, AttachManuscriptAnchorRequest(anchor=anchor))
        logger.info("attached %s to %s:%s", claim, anchor.file, anchor.line_start)
        return anchor, mutation

    def anchors(self) -> tuple[ManuscriptAnchor, ...]:
        """Every stored anchor, newest record per ``<file>#<fingerprint>`` key."""
        return tuple(self._ctx.repo.iter_anchors())

    def anchor_for(self, sentence: Sentence) -> ManuscriptAnchor | None:
        """The stored anchor of ``sentence``, matched on file and fingerprint."""
        return next(
            (
                anchor
                for anchor in self.anchors()
                if anchor.file == sentence.file
                and anchor.sentence_fingerprint == sentence.fingerprint
            ),
            None,
        )

    # -- revalidating ----------------------------------------------------------

    def revalidate(self, *, apply: bool = True) -> RevalidationReport:
        """Re-find every stored anchor in the manuscript as it is now (Roadmap Task 9.2).

        With ``apply`` the verdict is recorded through `manuscript.attach_claim`: a moved
        sentence keeps its key and adopts its new line range, and a reworded or deleted one
        is written back with status ``stale``/``missing`` and marked stale. Nothing is ever
        left recorded as ``valid`` over text that changed, and nothing is reattached to a
        sentence the researcher did not choose (ADR-008).
        """
        project = self.load_project()
        stored = self.anchors()
        results = revalidate_all(list(stored), project)
        if not apply:
            return RevalidationReport(results=results)

        applied: list[ManuscriptAnchor] = []
        mutations: list[MutationResult] = []
        for result in results:
            updated = apply_revalidation(result)
            if _unchanged(result.anchor, updated):
                continue
            mutations.append(
                attach_manuscript_anchor(self._ctx, AttachManuscriptAnchorRequest(anchor=updated))
            )
            applied.append(updated)
            logger.info("revalidated %s: %s", anchor_key(updated), updated.status.value)
        return RevalidationReport(
            results=results, applied=tuple(applied), mutations=tuple(mutations)
        )

    # -- auditing --------------------------------------------------------------

    def audit_context(
        self, *, parsed: bool = True, scope: AuditScope | None = None
    ) -> AuditContext:
        """Assemble everything the auditor reads from this workspace and this manuscript.

        With ``parsed`` the source artifacts behind the evidence are re-parsed from their
        stored bytes, which is what lets the audit resolve a Claim down to a page span and
        notice an anchor that no longer opens (Product 42.D). Without it the audit still
        runs; it simply has no opinion about source spans.

        ``scope`` narrows only the *re-parsing*: an audit of twenty lines re-parses the
        artifacts those lines' claims rest on and nothing else, which is the difference
        between an editor asking on every save and an editor asking once a day. The rules
        the auditor applies are identical either way.
        """
        project = self.load_project()
        graph = self._graph()
        wanted = graph.evidence.values() if scope is None else self._evidence_in_scope(graph, scope)
        return AuditContext(
            project=project,
            bib=self.bibliography(),
            anchors=graph.anchors,
            claims=graph.claims,
            evidence=graph.evidence,
            works=graph.works,
            parsed=self.parsed_documents(wanted) if parsed else {},
        )

    def audit(
        self, *, parsed: bool = True, scope: AuditScope | None = None
    ) -> ManuscriptAuditReport:
        """Audit the manuscript against the accepted graph (Product 30.3). Writes nothing.

        With ``scope`` the report carries only the findings, anchors, and trace links of
        the named file and line range; the counts are recomputed over that range.
        """
        report = audit_manuscript(self.audit_context(parsed=parsed, scope=scope))
        if scope is None:
            return report
        return narrow_report(report, scope, self.load_project())

    def audit_durable(
        self,
        engine: WorkflowEngine,
        research_dir: Path | None = None,
        *,
        parsed: bool = True,
        run_id: str | None = None,
        force: bool = False,
    ) -> tuple[WorkflowRun, ManuscriptAuditReport]:
        """The same audit as a resumable run whose JSON report lands under `.research/`."""
        target = (
            Path(research_dir) if research_dir is not None else self._ctx.repo.layout.research_dir
        )
        return run_manuscript_audit(
            engine,
            target,
            lambda: self.audit_context(parsed=parsed),
            run_id=run_id,
            force=force,
        )

    def trace(self, file: str, line: int) -> TraceLink | None:
        """Product 30.1 end to end: sentence -> Claim -> Evidence -> exact page span.

        ``None`` means the sentence carries no anchor - the chain has no first link yet,
        which is a different answer from "the chain is broken".
        """
        sentence = self.find_sentence(file, line)
        anchor = self.anchor_for(sentence)
        if anchor is None:
            return None
        scope = AuditScope(
            file=sentence.file, line_start=sentence.line_start, line_end=sentence.line_end
        )
        return self.audit(parsed=True, scope=scope).trace_for(anchor_key(anchor))

    # -- source parses ---------------------------------------------------------

    def parsed_documents(
        self, evidence: Iterable[Evidence] | None = None
    ) -> dict[ArtifactId, ParsedDocument]:
        """Re-parse the artifacts the given evidence is anchored in, from stored bytes.

        Parsing is a pure function of the bytes (ADR-002), so replaying the stored original
        reproduces the block ids an anchor was built against. An artifact whose bytes or
        parser are unavailable is skipped with a log line rather than reported as broken
        provenance: "this parse was not loaded" is not "this anchor is invalid".
        """
        items = list(evidence) if evidence is not None else list(self._graph().evidence.values())
        wanted: dict[ArtifactId, WorkId] = {}
        for item in items:
            wanted.setdefault(item.source.artifact, item.source.work)
        parser = PyMuPdfParser()
        documents: dict[ArtifactId, ParsedDocument] = {}
        with tempfile.TemporaryDirectory(prefix="research-manuscript-") as scratch:
            for artifact_id, work_id in wanted.items():
                artifact = self._artifact(artifact_id, work_id)
                if artifact is None or not parser.supports(artifact.mime_type):
                    continue
                document = self._parse(parser, artifact, Path(scratch))
                if document is not None:
                    documents[artifact_id] = document
        return documents

    # -- internals -------------------------------------------------------------

    def _evidence_in_scope(self, graph: _Graph, scope: AuditScope) -> list[Evidence]:
        """Evidence the claims anchored inside ``scope`` rest on, in claim order.

        An anchor outside the range contributes nothing to a narrowed report, so its
        artifacts are never re-parsed; an anchor inside it is audited with exactly the
        source spans a whole-project run would have used.
        """
        claims = {anchor.claim for anchor in graph.anchors if scope.covers_anchor(anchor)}
        wanted: list[Evidence] = []
        for claim_id in claims:
            claim = graph.claims.get(claim_id)
            if claim is None:
                continue
            for link in claim.relations:
                item = graph.evidence.get(link.evidence)
                if item is not None and item not in wanted:
                    wanted.append(item)
        return wanted

    def _graph(self) -> _Graph:
        repo = self._ctx.repo
        works: dict[WorkId, Work] = {}
        evidence: dict[EvidenceId, Evidence] = {}
        for work in repo.list_works():
            works[work.id] = work
            for item in repo.iter_evidence(work.id):
                evidence[item.id] = item
        return _Graph(
            works=works,
            claims={claim.id: claim for claim in repo.list_claims()},
            evidence=evidence,
            anchors=self.anchors(),
        )

    def _artifact(self, artifact: ArtifactId, work: WorkId) -> Artifact | None:
        try:
            return self._ctx.repo.get_artifact(artifact, work=work)
        except ObjectNotFoundError:
            logger.warning("evidence names %s, which is not in this workspace", artifact)
            return None

    def _parse(
        self, parser: PyMuPdfParser, artifact: Artifact, scratch: Path
    ) -> ParsedDocument | None:
        try:
            data = self._ctx.repo.read_artifact_bytes(artifact)
        except ObjectNotFoundError:
            logger.warning("no stored bytes for %s; its spans cannot be resolved", artifact.id)
            return None
        path = scratch / f"{artifact.id}{Path(artifact.original_filename).suffix}"
        path.write_bytes(data)
        try:
            return parser.parse(
                ParseTarget(
                    work=artifact.work,
                    version=artifact.version,
                    artifact=artifact.id,
                    file_hash=artifact.file_hash,
                    path=path,
                    mime_type=artifact.mime_type,
                )
            )
        except ResearchHarnessError as error:
            logger.warning("could not re-parse %s: %s", artifact.id, error)
            return None

    def _require_substantive(self, sentence: Sentence) -> None:
        if is_substantive(sentence):
            return
        raise ManuscriptError(
            f"{sentence.file}:{sentence.line_start} is not a substantive sentence "
            f"({_quote(sentence)}); a Claim attaches to prose that asserts something "
            "about the world (Product 30.1)"
        )

    @staticmethod
    def _nothing_at(project: LatexProject, path: str, line: int) -> str:
        heading = next(
            (item for item in project.headings if item.file == path and item.line == line), None
        )
        if heading is not None:
            return (
                f"{path}:{line} is the heading {heading.title!r}; a Claim attaches to "
                "substantive prose, not to a section title (Product 30.1)"
            )
        block = next(
            (
                item
                for item in project.blocks
                if item.file == path and item.line_start <= line <= item.line_end
            ),
            None,
        )
        if block is not None:
            return (
                f"{path}:{line} is inside the {block.environment!r} environment; a Claim "
                "attaches to substantive prose, not to a caption, float, or display"
            )
        return f"{path}:{line} carries no manuscript sentence"


# ------------------------------------------------------------------------------ helpers


def _unchanged(before: ManuscriptAnchor, after: ManuscriptAnchor) -> bool:
    """True when applying a verdict would rewrite an anchor without changing anything.

    ``updated_at`` is excluded: re-recording an anchor only because a clock moved would
    make every revalidation look like a change.
    """
    skip = {"updated_at"}
    return before.model_dump(exclude=skip) == after.model_dump(exclude=skip)


def _quote(sentence: Sentence, limit: int = 60) -> str:
    text = sentence.normalized_text
    return repr(text if len(text) <= limit else f"{text[: limit - 1]}…")

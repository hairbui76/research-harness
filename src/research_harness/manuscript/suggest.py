"""Model and humanizer edits as staged candidate diffs, never as a source rewrite.

LaTeX spec 4 and Product 30.4 draw the same line twice: model output over manuscript prose
is *always* a candidate, and it replaces accepted manuscript text only after the protected
spans are proved intact, the semantic diff is read, the manuscript audit passes, and a
person says yes. This module is where that line is enforced mechanically.

:func:`suggest_edit` reads one span of one file, asks the writer role to rewrite it, and
writes a :class:`SuggestionCandidate` under `.research/staging/manuscript/`. It never opens
the source file for writing: the hash of the file is taken before and after, and a
difference is a bug loud enough to raise, because a suggestion that edited the manuscript
on the way to proposing an edit would have already lost the property this module exists for.

:func:`apply_suggestion` is the only path from candidate to source, and it is deliberately
narrow. It refuses a candidate whose protected spans moved, whose audit did not pass, and
whose file changed underneath it; when it does write, it writes through
:class:`~research_harness.manuscript.files.ManuscriptFiles` - so the conflict check and the
path confinement are the same ones a researcher's own save goes through - and then records
a ``manuscript.source_written`` event, because "a model's words entered the manuscript" is
exactly the kind of thing the Git-visible log exists to remember (Product 19.3).

What blocks and what only warns is a deliberate split. A changed protected span, a
proposition added, removed, strengthened, or weakened, and a rewritten sentence that now
reads stronger than its anchored Claim allows all block: each of them changes what the
manuscript *says*. An anchor that the rewrite invalidates does not block - every accepted
reword breaks the fingerprint it was anchored by, and the answer to that is
`manuscript.revalidate`, not a refusal to ever edit anchored prose (ADR-008).
"""

from __future__ import annotations

import difflib
import json
import logging
import shutil
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_harness.capabilities.context import CapabilityContext
from research_harness.domain.base import Provenance, Sha256, UtcDatetime, utc_now
from research_harness.domain.claim import Claim
from research_harness.domain.enums import (
    FindingSeverity,
    ManuscriptAnchorStatus,
    ManuscriptFindingKind,
    ResearchEventType,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import ClaimId
from research_harness.domain.manuscript import (
    FindingLocation,
    ManuscriptAnchor,
    ManuscriptAuditFinding,
)
from research_harness.domain.research import ResearchEvent
from research_harness.manuscript.anchors import AnchorRevalidation, anchor_key, revalidate_anchor
from research_harness.manuscript.files import (
    BIB_SUFFIXES,
    TEX_SUFFIXES,
    FileSnapshot,
    ManuscriptFiles,
)
from research_harness.manuscript.latex import LatexProject, Sentence
from research_harness.manuscript.protected import ProtectedSpan, find_protected_spans
from research_harness.manuscript.style import (
    ProtectedViolation,
    SemanticDiff,
    StylePassCandidate,
    StylePolicy,
    StyleReport,
    run_style_pass,
)
from research_harness.manuscript.toolchain import ManuscriptSettings
from research_harness.manuscript.wording import stronger_than, wording_level
from research_harness.providers.models.base import ModelProvider
from research_harness.providers.models.router import ModelRouter
from research_harness.roles import WRITER, InputKind, RoleInput, WriterOutput, build_request
from research_harness.workflows.models import new_run_id
from research_harness.workspace.atomic import atomic_write_text
from research_harness.workspace.journal import Transaction
from research_harness.workspace.repository import ObjectNotFoundError

__all__ = [
    "STAGING_SUGGESTIONS_DIRNAME",
    "SUGGESTION_STYLES",
    "SUGGESTION_SUFFIX",
    "AnchorImpact",
    "AppliedSuggestion",
    "AuditStatus",
    "DiffHunk",
    "DiffLine",
    "DiffLineKind",
    "ModelClient",
    "SuggestionCandidate",
    "SuggestionProvenance",
    "apply_suggestion",
    "list_suggestions",
    "staged_suggestion",
    "suggest_edit",
    "suggestions_dir",
    "unified_hunks",
]

logger = logging.getLogger(__name__)

ModelClient = ModelProvider | ModelRouter
"""What a suggestion may run on: one provider, or the workspace's router (Product 20.2)."""

STAGING_SUGGESTIONS_DIRNAME = "staging/manuscript"
"""Where candidates live: under `.research/`, deletable, and never scientific authority."""

SUGGESTION_SUFFIX = ".json"

DIFF_CONTEXT_LINES = 3
"""Unchanged lines kept either side of a hunk, as in every unified diff a person reads."""

MAX_SPAN_LINES = 400
"""A style pass reads a passage, not a manuscript; a wider selection is refused."""


# --------------------------------------------------------------------------------------
# vocabulary
# --------------------------------------------------------------------------------------


class AuditStatus(StrEnum):
    """Whether a candidate may reach the source, and whether that has been decided yet."""

    PENDING = "pending"
    """The checks could not be completed, so nothing has been decided; a person must look."""

    PASSED = "passed"
    FAILED = "failed"


class DiffLineKind(StrEnum):
    """The three line kinds of a unified diff."""

    CONTEXT = "context"
    ADDED = "added"
    REMOVED = "removed"


# --------------------------------------------------------------------------------------
# the candidate
# --------------------------------------------------------------------------------------


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DiffLine(_Record):
    """One line of one hunk, with the line numbers it holds on either side."""

    kind: DiffLineKind
    text: str
    old_line: int | None = Field(default=None, ge=1)
    new_line: int | None = Field(default=None, ge=1)


class DiffHunk(_Record):
    """One contiguous region of change, in the `@@ -a,b +c,d @@` shape."""

    old_start: int = Field(ge=1)
    old_count: int = Field(ge=0)
    new_start: int = Field(ge=1)
    new_count: int = Field(ge=0)
    lines: tuple[DiffLine, ...] = ()

    @property
    def header(self) -> str:
        return f"@@ -{self.old_start},{self.old_count} +{self.new_start},{self.new_count} @@"


class AnchorImpact(_Record):
    """What the rewrite does to one Claim anchored inside the selected span."""

    anchor_key: str
    claim: ClaimId
    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    status: ManuscriptAnchorStatus
    """``valid`` when the anchored sentence survives byte-identically, else stale/missing."""

    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str


class SuggestionProvenance(_Record):
    """Where a candidate came from: the model, and the conversation that asked for it."""

    provenance: Provenance
    session_id: str | None = None
    message_id: str | None = None
    context_pack_id: str | None = None


class SuggestionCandidate(_Record):
    """A proposed edit to one span, everything that judges it, and nothing that applies it.

    ``source_hash`` is the hash of the whole file at the moment the candidate was built:
    it is what :func:`apply_suggestion` checks against disk, so a candidate that was
    reviewed against text somebody has since changed is refused rather than merged blind.
    """

    candidate_id: str
    created_at: UtcDatetime = Field(default_factory=utc_now)
    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    instruction: str | None = None
    style: str | None = None
    policy: str

    source_hash: Sha256
    """Hash of the file's bytes when the candidate was produced."""

    original_text: str
    proposed_text: str
    proposed_content: str
    """The whole file as it would be after applying; a client never reassembles it itself."""

    hunks: tuple[DiffHunk, ...] = ()
    protected_spans: tuple[ProtectedSpan, ...] = ()
    """Every protected span of the original passage; all of them must survive unchanged."""

    protected_violations: tuple[ProtectedViolation, ...] = ()
    semantic_diff: SemanticDiff
    style_report: StyleReport
    audit_findings: tuple[ManuscriptAuditFinding, ...] = ()
    anchor_impacts: tuple[AnchorImpact, ...] = ()
    audit_status: AuditStatus = AuditStatus.PENDING
    blocked_reason: str | None = None
    provenance: SuggestionProvenance
    applied: bool = False
    applied_at: UtcDatetime | None = None
    path: str | None = None
    """Workspace-relative path of the staged file; set once the candidate is written."""

    @property
    def changed(self) -> bool:
        """True when the rewriter proposed anything at all."""
        return self.original_text != self.proposed_text

    @property
    def protected_preserved(self) -> bool:
        """True when every protected span of the original survived byte-identically."""
        return not self.protected_violations

    @property
    def applicable(self) -> bool:
        """True when nothing stands between this candidate and an explicit application."""
        return (
            self.audit_status is AuditStatus.PASSED
            and self.protected_preserved
            and self.changed
            and not self.applied
        )

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form; the staged file and ``--json`` output share it."""
        payload: dict[str, Any] = self.model_dump(mode="json")
        payload["changed"] = self.changed
        payload["protected_preserved"] = self.protected_preserved
        payload["applicable"] = self.applicable
        return payload


class AppliedSuggestion(_Record):
    """What applying a candidate wrote, and the event that recorded it."""

    candidate: SuggestionCandidate
    snapshot: FileSnapshot
    event: ResearchEvent
    anchors_to_revalidate: tuple[str, ...] = ()
    """Anchor keys the applied rewrite invalidated; `manuscript.revalidate` settles them."""


# --------------------------------------------------------------------------------------
# style policies
# --------------------------------------------------------------------------------------


def _policy(name: str, description: str, *notes: str) -> StylePolicy:
    """A policy that protects everything and prescribes nothing a regex can decide."""
    return StylePolicy(name=name, description=description, notes=notes)


SUGGESTION_STYLES: Mapping[str, StylePolicy] = {
    "humanize": _policy(
        "manuscript.humanize",
        "Plain, human academic prose: no inflated claims, no stock phrasing, no filler.",
        "Say the same thing in fewer words; never say a different thing in better words.",
        "Keep every citation, number, unit, equation, quotation, and identifier verbatim.",
    ),
    "venue": _policy(
        "manuscript.venue",
        "Venue house style: sentence length, voice, and terminology consistency.",
        "Formatting is not meaning: a venue rule never outranks the accepted Claim graph.",
    ),
    "copyedit": _policy(
        "manuscript.copyedit",
        "Grammar, agreement, and punctuation only.",
        "Do not restructure an argument; a copy-edit that changes a proposition is refused.",
    ),
}
"""The style passes `manuscript.suggest` offers. Every one of them keeps every protected
span, because :class:`~research_harness.manuscript.style.StylePolicy` refuses a policy that
drops one (Product 30.4)."""


def policy_for(style: str | None) -> StylePolicy:
    """The policy a named style runs under, or the neutral one for a free instruction."""
    if style is None:
        return _policy("manuscript.instruction", "A researcher's own instruction.")
    policy = SUGGESTION_STYLES.get(style)
    if policy is None:
        known = ", ".join(sorted(SUGGESTION_STYLES))
        raise CapabilityError(f"manuscript.suggest: unknown style {style!r}; known styles: {known}")
    return policy


# --------------------------------------------------------------------------------------
# staging locations
# --------------------------------------------------------------------------------------


def suggestions_dir(ctx: CapabilityContext) -> Path:
    """`.research/staging/manuscript/` of this workspace; created on first write."""
    return ctx.repo.layout.research_dir / STAGING_SUGGESTIONS_DIRNAME


def staged_suggestion(ctx: CapabilityContext, candidate_id: str) -> SuggestionCandidate | None:
    """Read one staged candidate back, or ``None`` when nothing is staged under that id."""
    path = suggestions_dir(ctx) / f"{_checked_id(candidate_id)}{SUGGESTION_SUFFIX}"
    if not path.is_file():
        return None
    return _load(path)


def list_suggestions(ctx: CapabilityContext) -> tuple[SuggestionCandidate, ...]:
    """Every staged candidate, newest first; an unreadable one is skipped, not fatal."""
    directory = suggestions_dir(ctx)
    if not directory.is_dir():
        return ()
    found: list[SuggestionCandidate] = []
    for path in sorted(directory.glob(f"*{SUGGESTION_SUFFIX}")):
        try:
            found.append(_load(path))
        except (OSError, ValueError):  # pragma: no cover - a half-written staging file
            logger.warning("ignoring unreadable suggestion candidate %s", path)
    return tuple(sorted(found, key=lambda item: item.created_at, reverse=True))


def _load(path: Path) -> SuggestionCandidate:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for derived in ("changed", "protected_preserved", "applicable"):
        payload.pop(derived, None)
    return SuggestionCandidate.model_validate(payload)


def _checked_id(candidate_id: str) -> str:
    """Refuse anything that is not a bare staging id; the id becomes a filename."""
    value = candidate_id.strip()
    if not value or not all(char.isalnum() or char in "-_" for char in value):
        raise CapabilityError(
            f"{candidate_id!r} is not a suggestion candidate id; ids are alphanumeric"
        )
    return value


def _stage(ctx: CapabilityContext, candidate: SuggestionCandidate) -> SuggestionCandidate:
    """Write ``candidate`` under `.research/staging/manuscript/`, refusing any other place."""
    directory = suggestions_dir(ctx)
    path = (directory / f"{candidate.candidate_id}{SUGGESTION_SUFFIX}").resolve()
    staging = (ctx.repo.layout.research_dir / "staging").resolve()
    if not path.is_relative_to(staging):  # pragma: no cover - guards a misconfigured layout
        raise CapabilityError(
            f"manuscript.suggest: a candidate belongs under {staging}, never at {path}"
        )
    directory.mkdir(parents=True, exist_ok=True)
    staged = candidate.model_copy(
        update={"path": ctx.repo.layout.relative(path).as_posix()},
    )
    atomic_write_text(
        path, json.dumps(staged.as_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    return staged


# --------------------------------------------------------------------------------------
# producing a candidate
# --------------------------------------------------------------------------------------


def suggest_edit(
    ctx: CapabilityContext,
    *,
    file: str,
    line_start: int,
    line_end: int,
    provider: ModelClient,
    instruction: str | None = None,
    style: str | None = None,
    session_id: str | None = None,
    message_id: str | None = None,
    context_pack_id: str | None = None,
    settings: ManuscriptSettings | None = None,
) -> SuggestionCandidate:
    """Rewrite one span of one manuscript file into a staged candidate diff.

    The source file is read and never written: its hash is taken before the model runs and
    checked again after the candidate is staged, so "a suggestion cannot silently overwrite
    source" is an assertion in the code rather than a claim in a document (LaTeX spec 10.5).
    """
    if instruction is None and style is None:
        raise CapabilityError(
            "manuscript.suggest: name a style (humanize, venue, copyedit) or an instruction"
        )
    files = ManuscriptFiles(ctx.repo.layout)
    snapshot = files.read(file)
    span = _Span.of(snapshot.content, line_start, line_end, snapshot.path)
    resolved = policy_for(style)

    built = build_request(
        WRITER,
        _role_inputs(ctx, snapshot.path, span),
        extra_instructions=_instructions(resolved, instruction, span),
    )
    response = provider.complete(built.request)
    output = response.parsed
    if not isinstance(output, WriterOutput):  # pragma: no cover - schema-enforced
        raise CapabilityError(
            f"manuscript.suggest: the writer returned {type(output).__name__}, not WriterOutput"
        )

    pass_result = run_style_pass(span.text, resolved, rewriter=lambda _: output.draft)
    proposed_content = span.replaced(pass_result.after)
    anchors = _anchors_in(ctx, snapshot.path, line_start, line_end)
    impacts, findings, status_note = _judge_against_claims(
        ctx, snapshot.path, proposed_content, anchors, settings
    )
    audit_status, blocked = _verdict(pass_result, findings, status_note)

    candidate = SuggestionCandidate(
        candidate_id=new_run_id(),
        file=snapshot.path,
        line_start=span.start,
        line_end=span.end,
        instruction=instruction,
        style=style,
        policy=resolved.name,
        source_hash=snapshot.content_hash,
        original_text=span.text,
        proposed_text=pass_result.after,
        proposed_content=proposed_content,
        hunks=unified_hunks(snapshot.content, proposed_content),
        protected_spans=find_protected_spans(span.text),
        protected_violations=pass_result.diff.protected_violations,
        semantic_diff=pass_result.diff,
        style_report=pass_result.report,
        audit_findings=findings,
        anchor_impacts=impacts,
        audit_status=audit_status,
        blocked_reason=blocked,
        provenance=SuggestionProvenance(
            provenance=Provenance.model(
                f"{response.provider}/{response.model}",
                workflow="manuscript.suggest",
                template_version=WRITER.template_version,
            ),
            session_id=session_id,
            message_id=message_id,
            context_pack_id=context_pack_id,
        ),
    )
    staged = _stage(ctx, candidate)
    _assert_source_untouched(files, snapshot)
    logger.info(
        "manuscript suggestion %s for %s:%d-%d is %s",
        staged.candidate_id,
        staged.file,
        staged.line_start,
        staged.line_end,
        staged.audit_status.value,
    )
    return staged


def _assert_source_untouched(files: ManuscriptFiles, snapshot: FileSnapshot) -> None:
    """Producing a candidate reads the manuscript; anything else here is a bug."""
    current = files.hash_of(snapshot.path)
    if current != snapshot.content_hash:
        raise CapabilityError(
            f"manuscript.suggest: {snapshot.path} changed while a candidate was being "
            f"produced ({snapshot.content_hash} -> {current}); a suggestion never writes "
            "manuscript source"
        )


def _instructions(policy: StylePolicy, instruction: str | None, span: _Span) -> str:
    lines = [
        f"Rewrite the passage below, and only that passage. It is lines "
        f"{span.start}-{span.end} of the manuscript file you were given.",
        f"Style policy: {policy.name} - {policy.description}",
        "Return the rewritten passage verbatim in `draft`. Return no commentary, no "
        "surrounding text, and no lines from outside the passage.",
        "Preserve every citation command and key, cross-reference, number, unit, equation, "
        "quotation, identifier, code span, and URL exactly as written.",
        "Preserve epistemic qualifiers, scope, comparison conditions, and negative-evidence "
        "wording; never make a sentence claim more than it claims now.",
    ]
    lines.extend(policy.notes)
    if instruction and instruction.strip():
        lines.append(f"Researcher instruction: {instruction.strip()}")
    lines.append("Passage:")
    lines.append(span.text)
    return "\n".join(lines)


def _role_inputs(ctx: CapabilityContext, file: str, span: _Span) -> list[RoleInput]:
    """The manuscript passage, plus every Claim the span is anchored to.

    Nothing else: the writer is shown the prose it must rewrite and the Claims that bound
    what it may say, and no other accepted state travels with the request (Product 23).
    """
    inputs = [
        RoleInput(
            InputKind.MANUSCRIPT_TEXT,
            f"{file}:{span.start}-{span.end}",
            {"file": file, "line_start": span.start, "line_end": span.end, "text": span.text},
        )
    ]
    for claim in _claims_for(ctx, _anchors_in(ctx, file, span.start, span.end)):
        inputs.append(
            RoleInput(
                InputKind.ACCEPTED_CLAIMS,
                str(claim.id),
                {
                    "id": str(claim.id),
                    "statement": claim.statement,
                    "allowed_strength": claim.assessment.allowed_strength.value,
                    "maximum_defensible_wording": (
                        claim.assessment.maximum_defensible_wording or ""
                    ),
                },
            )
        )
    return inputs


# --------------------------------------------------------------------------------------
# the span
# --------------------------------------------------------------------------------------


class _Span:
    """One inclusive line range of a file, and how to put a replacement back into it."""

    def __init__(self, lines: Sequence[str], start: int, end: int, file: str) -> None:
        self._lines = list(lines)
        self.start = start
        self.end = end
        self.file = file

    @classmethod
    def of(cls, content: str, line_start: int, line_end: int, file: str) -> _Span:
        lines = content.splitlines(keepends=True)
        if line_start < 1:
            raise CapabilityError(
                f"manuscript.suggest: line_start must be 1 or more, not {line_start}"
            )
        if line_end < line_start:
            raise CapabilityError(
                f"manuscript.suggest: {file}:{line_start}-{line_end} ends before it starts"
            )
        if line_end > len(lines):
            raise CapabilityError(
                f"manuscript.suggest: {file} has {len(lines)} lines; "
                f"lines {line_start}-{line_end} are not all in it"
            )
        if line_end - line_start + 1 > MAX_SPAN_LINES:
            raise CapabilityError(
                f"manuscript.suggest: {line_end - line_start + 1} lines is more than the "
                f"{MAX_SPAN_LINES}-line limit for one style pass; select a passage"
            )
        return cls(lines, line_start, line_end, file)

    @property
    def text(self) -> str:
        """The selected lines verbatim, including their line endings."""
        return "".join(self._lines[self.start - 1 : self.end])

    def replaced(self, replacement: str) -> str:
        """The whole file with the selection replaced, keeping the original line ending."""
        body = replacement
        if self.text.endswith("\n") and not body.endswith("\n"):
            body += "\n"
        return "".join([*self._lines[: self.start - 1], body, *self._lines[self.end :]])


# --------------------------------------------------------------------------------------
# the unified diff
# --------------------------------------------------------------------------------------


def unified_hunks(
    before: str, after: str, *, context: int = DIFF_CONTEXT_LINES
) -> tuple[DiffHunk, ...]:
    """The hunks of a unified diff between two texts, as data rather than as text.

    A client renders these; nothing here formats a diff into a string, because a diff a
    reviewer clicks through needs the line numbers, not a rendering of them.
    """
    old = before.splitlines()
    new = after.splitlines()
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    hunks: list[DiffHunk] = []
    for group in matcher.get_grouped_opcodes(context):
        lines: list[DiffLine] = []
        old_start = group[0][1] + 1
        new_start = group[0][3] + 1
        old_count = 0
        new_count = 0
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for offset in range(i2 - i1):
                    lines.append(
                        DiffLine(
                            kind=DiffLineKind.CONTEXT,
                            text=old[i1 + offset],
                            old_line=i1 + offset + 1,
                            new_line=j1 + offset + 1,
                        )
                    )
                old_count += i2 - i1
                new_count += j2 - j1
                continue
            for offset in range(i2 - i1):
                lines.append(
                    DiffLine(
                        kind=DiffLineKind.REMOVED,
                        text=old[i1 + offset],
                        old_line=i1 + offset + 1,
                    )
                )
            old_count += i2 - i1
            for offset in range(j2 - j1):
                lines.append(
                    DiffLine(
                        kind=DiffLineKind.ADDED,
                        text=new[j1 + offset],
                        new_line=j1 + offset + 1,
                    )
                )
            new_count += j2 - j1
        hunks.append(
            DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=tuple(lines),
            )
        )
    return tuple(hunks)


# --------------------------------------------------------------------------------------
# judging the candidate
# --------------------------------------------------------------------------------------


def _anchors_in(
    ctx: CapabilityContext, file: str, line_start: int, line_end: int
) -> tuple[ManuscriptAnchor, ...]:
    """Stored anchors whose recorded span overlaps the selection, in workspace order."""
    return tuple(
        anchor
        for anchor in ctx.repo.iter_anchors()
        if anchor.file == file and anchor.line_start <= line_end and line_start <= anchor.line_end
    )


def _claims_for(ctx: CapabilityContext, anchors: Iterable[ManuscriptAnchor]) -> tuple[Claim, ...]:
    """The Claims those anchors name, skipping any the workspace no longer holds."""
    found: list[Claim] = []
    seen: set[ClaimId] = set()
    for anchor in anchors:
        if anchor.claim in seen:
            continue
        seen.add(anchor.claim)
        try:
            found.append(ctx.repo.get_claim(anchor.claim))
        except ObjectNotFoundError:
            logger.warning(
                "anchor %s names %s, which is not in the graph", anchor.file, anchor.claim
            )
    return tuple(found)


def _judge_against_claims(
    ctx: CapabilityContext,
    file: str,
    proposed_content: str,
    anchors: tuple[ManuscriptAnchor, ...],
    settings: ManuscriptSettings | None,
) -> tuple[tuple[AnchorImpact, ...], tuple[ManuscriptAuditFinding, ...], str | None]:
    """Audit the proposed text against the Claims anchored in it (Product 30.3, 30.4).

    The proposed manuscript is parsed in a throwaway copy of the project, never in place,
    so the audit sees the document the candidate would produce while the real one is
    untouched. Each anchored sentence is re-found there: an unchanged sentence keeps its
    Claim, and a rewritten one is scored against the Claim's allowed strength, which is the
    check that would otherwise disappear the moment the rewrite broke the anchor.
    """
    if not anchors:
        return (), (), None
    claims = {claim.id: claim for claim in _claims_for(ctx, anchors)}
    try:
        project = _proposed_project(ctx, file, proposed_content, settings)
    except (OSError, CapabilityError) as error:
        return (), (), f"the proposed manuscript could not be parsed: {error}"

    impacts: list[AnchorImpact] = []
    findings: list[ManuscriptAuditFinding] = []
    for anchor in anchors:
        verdict = revalidate_anchor(anchor, project)
        impacts.append(_impact(anchor, verdict))
        claim = claims.get(anchor.claim)
        if claim is None:
            findings.append(_orphan_finding(anchor))
            continue
        sentence = _sentence_for(verdict)
        if sentence is not None:
            findings.extend(_wording_findings(anchor, claim, sentence))
        if verdict.status is not ManuscriptAnchorStatus.VALID:
            findings.append(_staleness_finding(anchor, verdict))
    return tuple(impacts), tuple(findings), None


def _proposed_project(
    ctx: CapabilityContext,
    file: str,
    proposed_content: str,
    settings: ManuscriptSettings | None,
) -> LatexProject:
    """Parse the manuscript as it would be, in a throwaway copy of the source tree."""
    root = ctx.repo.layout.manuscript_dir
    entry = (settings or ManuscriptSettings()).entry_file
    with TemporaryDirectory(prefix="rh-suggest-") as directory:
        mirror = Path(directory) / "manuscript"
        _mirror_sources(root, mirror)
        target = mirror / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(proposed_content, encoding="utf-8")
        main = mirror / entry
        if not main.is_file():
            raise CapabilityError(f"no manuscript entry file at {entry}")
        return LatexProject.load(main)


_MIRRORED_SUFFIXES = TEX_SUFFIXES | BIB_SUFFIXES


def _mirror_sources(root: Path, destination: Path) -> None:
    """Copy the readable LaTeX sources of a project; figures and binaries are not parsed."""
    destination.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _MIRRORED_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def _sentence_for(verdict: AnchorRevalidation) -> Sentence | None:
    """The sentence the anchor now points at: the rewrite for a stale verdict, else none."""
    if verdict.status is ManuscriptAnchorStatus.STALE:
        return verdict.relocated
    return None


def _impact(anchor: ManuscriptAnchor, verdict: AnchorRevalidation) -> AnchorImpact:
    return AnchorImpact(
        anchor_key=anchor_key(anchor),
        claim=anchor.claim,
        file=anchor.file,
        line_start=anchor.line_start,
        line_end=anchor.line_end,
        status=verdict.status,
        similarity=verdict.similarity,
        reason=verdict.reason,
    )


def _wording_findings(
    anchor: ManuscriptAnchor, claim: Claim, sentence: Sentence
) -> tuple[ManuscriptAuditFinding, ...]:
    """`wording stronger than the accepted Claim`, checked on the *rewritten* sentence."""
    estimate = wording_level(sentence.normalized_text)
    allowed = claim.assessment.allowed_strength
    if not stronger_than(estimate.level, allowed):
        return ()
    cues = ", ".join(repr(cue) for cue in estimate.cues) or "its phrasing"
    return (
        ManuscriptAuditFinding(
            kind=ManuscriptFindingKind.OVER_STRONG_WORDING,
            severity=FindingSeverity.ERROR,
            message=(
                f"{sentence.file}:{sentence.line_start}: the proposed sentence reads "
                f"{estimate.level.label} via {cues}, but {claim.id} allows only "
                f"{allowed.label}; the defensible wording is "
                f"{claim.assessment.maximum_defensible_wording or allowed.value!r}"
            ),
            anchor=anchor,
            related=(claim.id,),
            location=FindingLocation(
                file=sentence.file,
                line_start=sentence.line_start,
                line_end=sentence.line_end,
                char_start=sentence.char_start,
                char_end=sentence.char_end,
            ),
        ),
    )


def _staleness_finding(
    anchor: ManuscriptAnchor, verdict: AnchorRevalidation
) -> ManuscriptAuditFinding:
    """Reported, never blocking: every accepted reword needs `manuscript.revalidate`."""
    return ManuscriptAuditFinding(
        kind=ManuscriptFindingKind.STALE_CLAIM,
        severity=FindingSeverity.WARNING,
        message=(
            f"{anchor.file}:{anchor.line_start}: applying this candidate leaves the anchor "
            f"to {anchor.claim} {verdict.status.value}: {verdict.reason}"
        ),
        anchor=anchor,
        related=(anchor.claim,),
        location=FindingLocation(
            file=anchor.file, line_start=anchor.line_start, line_end=anchor.line_end
        ),
    )


def _orphan_finding(anchor: ManuscriptAnchor) -> ManuscriptAuditFinding:
    return ManuscriptAuditFinding(
        kind=ManuscriptFindingKind.UNREGISTERED_CLAIM,
        severity=FindingSeverity.ERROR,
        message=f"the anchor in this span names {anchor.claim}, which is not in the graph",
        anchor=anchor,
        related=(anchor.claim,),
        location=FindingLocation(
            file=anchor.file, line_start=anchor.line_start, line_end=anchor.line_end
        ),
    )


def _verdict(
    pass_result: StylePassCandidate,
    findings: tuple[ManuscriptAuditFinding, ...],
    note: str | None,
) -> tuple[AuditStatus, str | None]:
    """Passed, failed, or not decided - and, when it is not passed, exactly why."""
    reasons: list[str] = []
    diff = pass_result.diff
    if diff.protected_violations:
        kinds = ", ".join(sorted({item.kind.value for item in diff.protected_violations}))
        reasons.append(f"{len(diff.protected_violations)} protected span(s) changed ({kinds})")
    moved = len(diff.added) + len(diff.removed) + len(diff.strengthened) + len(diff.weakened)
    if moved:
        reasons.append(f"the semantic diff is not meaning-preserving: {diff.summary()}")
    blocking = [item for item in findings if item.severity is FindingSeverity.ERROR]
    if blocking:
        reasons.append("; ".join(f"{item.kind.value}: {item.message}" for item in blocking[:3]))
    if reasons:
        return AuditStatus.FAILED, "; ".join(reasons)
    if note is not None:
        return AuditStatus.PENDING, note
    return AuditStatus.PASSED, None


# --------------------------------------------------------------------------------------
# applying a candidate
# --------------------------------------------------------------------------------------


def apply_suggestion(
    ctx: CapabilityContext,
    candidate_id: str,
    *,
    expected_hash: str | None = None,
) -> AppliedSuggestion:
    """Write an accepted candidate into the manuscript, as an explicit source mutation.

    Every refusal here is a refusal to change what the manuscript says on somebody's behalf:
    an unaudited candidate, one whose protected spans moved, one already applied, and one
    whose file has changed since it was produced. ``expected_hash`` defaults to the hash the
    candidate was built against, so a reviewer who read the diff and pressed apply is
    checking exactly the text they read (LaTeX spec 4, Product 30.4).
    """
    candidate = staged_suggestion(ctx, candidate_id)
    if candidate is None:
        raise CapabilityError(f"no staged manuscript suggestion {candidate_id!r}")
    _require_applicable(candidate)

    files = ManuscriptFiles(ctx.repo.layout)
    wanted = expected_hash or candidate.source_hash
    with ctx.repo.lock():
        snapshot = files.write(candidate.file, candidate.proposed_content, wanted)
        event = _record_application(ctx, candidate, snapshot)
        applied = _stage(
            ctx, candidate.model_copy(update={"applied": True, "applied_at": ctx.now()})
        )
    stale = tuple(
        impact.anchor_key
        for impact in candidate.anchor_impacts
        if impact.status is not ManuscriptAnchorStatus.VALID
    )
    logger.info("applied manuscript suggestion %s to %s", candidate.candidate_id, snapshot.path)
    return AppliedSuggestion(
        candidate=applied, snapshot=snapshot, event=event, anchors_to_revalidate=stale
    )


def _require_applicable(candidate: SuggestionCandidate) -> None:
    if candidate.applied:
        raise CapabilityError(
            f"suggestion {candidate.candidate_id} was already applied at {candidate.applied_at}"
        )
    if not candidate.changed:
        raise CapabilityError(
            f"suggestion {candidate.candidate_id} proposes no change to {candidate.file}"
        )
    if not candidate.protected_preserved:
        kinds = ", ".join(sorted({item.kind.value for item in candidate.protected_violations}))
        raise CapabilityError(
            f"suggestion {candidate.candidate_id} changes protected span(s) ({kinds}); a "
            "style pass may change wording, never a citation, number, equation, or "
            "identifier (Product 30.4)"
        )
    if candidate.audit_status is not AuditStatus.PASSED:
        raise CapabilityError(
            f"suggestion {candidate.candidate_id} is {candidate.audit_status.value}: "
            f"{candidate.blocked_reason or 'the manuscript audit has not passed'}"
        )


def _record_application(
    ctx: CapabilityContext, candidate: SuggestionCandidate, snapshot: FileSnapshot
) -> ResearchEvent:
    """Append the ``manuscript.source_written`` event for this application.

    The event carries no object digest: manuscript source is the researcher's file, not a
    canonical object the consistency check reconciles, so recording a digest for it would
    make `verify_consistency` report an object it cannot find (Product 19.3).

    The source is written first and the event immediately after, both under the workspace
    lock. A crash between the two under-reports the log; the reverse order would have the
    log claim an edit that never happened, which is the worse of the two.
    """
    event = ResearchEvent(
        event=ResearchEventType.MANUSCRIPT_SOURCE_WRITTEN,
        actor=ctx.actor,
        occurred_at=ctx.now(),
        summary=(
            f"applied manuscript suggestion {candidate.candidate_id} to {candidate.file}:"
            f"{candidate.line_start}-{candidate.line_end}"
        ),
        payload={
            "candidate_id": candidate.candidate_id,
            "file": candidate.file,
            "line_start": candidate.line_start,
            "line_end": candidate.line_end,
            "policy": candidate.policy,
            "style": candidate.style,
            "content_hash": snapshot.content_hash,
            "previous_hash": candidate.source_hash,
            "session_id": candidate.provenance.session_id,
            "message_id": candidate.provenance.message_id,
            "context_pack_id": candidate.provenance.context_pack_id,
        },
    )
    transaction = Transaction(ctx.repo.layout)
    ctx.repo.events.stage(transaction, event)
    transaction.commit()
    return event

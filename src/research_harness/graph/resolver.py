"""Deep-link resolution: the graph proposes, canonical files decide.

`rh://artifact/A0017-3?page=6&block=B0081` is a navigation request, and graph spec §5
requires four answers before anything opens it or puts it in a context pack: does the
object exist *in this project*, what authority does it carry, may it leave the machine, and
does its anchor still hold. Every one of those is read from the canonical object through
`WorkspaceRepository` — never from a projected row, which can be behind — so a stale graph
degrades navigation and can never mislabel authority (ADR-001).

Freshness is the interesting one. An artifact's bytes are immutable, but the *parse* over
them is not: an evidence anchor names both a `file_hash` and a `text_hash`, and a re-parse
that moved the block leaves the anchor pointing at text that is no longer there. The
resolver compares both and says so, rather than opening a page and hoping.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.evidence import Evidence
from research_harness.domain.graph import DeepLink, DeepLinkKind, GraphAuthority, GraphVisibility
from research_harness.domain.ids import (
    ArtifactId,
    ClaimId,
    DecisionId,
    EvidenceId,
    QuestionId,
    VersionId,
    WorkId,
)
from research_harness.graph.projectors import claim_authority, evidence_authority
from research_harness.graph.queries import NodeRecord, node
from research_harness.workspace.repository import WorkspaceRepository

__all__ = ["ResolvedTarget", "resolve_deep_link"]

_UNSUPPORTED = (
    "session and attachment targets resolve through the conversation store, "
    "which this projection does not read"
)


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """What a deep link resolved to, and every reason it may not be followed."""

    link: DeepLink
    project: str
    exists: bool
    authority: GraphAuthority
    visibility: GraphVisibility
    fresh: bool
    node: NodeRecord | None = None
    problems: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """True when the target exists, its anchor still holds, and nothing else objects."""
        return self.exists and self.fresh and not self.problems

    def summary(self) -> str:
        """One line a UI or a log can show."""
        if self.ok:
            return f"{self.link.format()} -> {self.authority.value} in {self.project}"
        return f"{self.link.format()} unavailable: {'; '.join(self.problems) or 'not found'}"


def resolve_deep_link(
    repo: WorkspaceRepository, link: DeepLink | str, *, engine: Engine | None = None
) -> ResolvedTarget:
    """Validate a deep link against canonical state; ``engine`` only speeds the lookup.

    The graph is consulted for the projected node (so a caller can show its label without a
    second read) and, for evidence, for the Work its record lives under. Every decision —
    existence, authority, visibility, freshness — comes from the canonical object.
    """
    parsed = DeepLink.parse(link) if isinstance(link, str) else link
    record = node(engine, _identity_for(parsed)) if engine is not None else None
    problems: list[str] = []
    try:
        authority, fresh, extra = _validate(repo, parsed, record)
    except ResearchHarnessError as error:
        return ResolvedTarget(
            link=parsed,
            project=repo.config.name,
            exists=False,
            authority=GraphAuthority.CANDIDATE,
            visibility=GraphVisibility.PROJECT,
            fresh=False,
            node=record,
            problems=(_reason(error),),
        )
    problems.extend(extra)
    visibility = record.visibility if record is not None else GraphVisibility.PROJECT
    if parsed.kind in {DeepLinkKind.SESSION, DeepLinkKind.ATTACHMENT}:
        return ResolvedTarget(
            link=parsed,
            project=repo.config.name,
            exists=False,
            authority=GraphAuthority.PRIVATE,
            visibility=GraphVisibility.PRIVATE,
            fresh=False,
            node=record,
            problems=(_UNSUPPORTED,),
        )
    return ResolvedTarget(
        link=parsed,
        project=repo.config.name,
        exists=True,
        authority=authority,
        visibility=visibility,
        fresh=fresh,
        node=record,
        problems=tuple(problems),
    )


def _identity_for(link: DeepLink) -> str:
    """The graph identity a link addresses, so the projected node can be shown beside it."""
    if link.kind is DeepLinkKind.MANUSCRIPT:
        from research_harness.graph.projectors import manuscript_file_identity

        return manuscript_file_identity(link.target)
    return link.target


def _validate(
    repo: WorkspaceRepository, link: DeepLink, record: NodeRecord | None
) -> tuple[GraphAuthority, bool, list[str]]:
    match link.kind:
        case DeepLinkKind.WORK:
            repo.get_work(WorkId(link.target))
            return GraphAuthority.ACCEPTED, True, []
        case DeepLinkKind.VERSION:
            repo.get_version(VersionId(link.target))
            return GraphAuthority.ACCEPTED, True, []
        case DeepLinkKind.ARTIFACT:
            return _artifact(repo, link)
        case DeepLinkKind.EVIDENCE:
            return _evidence(repo, link, record)
        case DeepLinkKind.CLAIM:
            claim = repo.get_claim(ClaimId(link.target))
            return claim_authority(claim), claim_authority(claim) is not GraphAuthority.STALE, []
        case DeepLinkKind.QUESTION:
            repo.get_question(QuestionId(link.target))
            return GraphAuthority.ACCEPTED, True, []
        case DeepLinkKind.DECISION:
            repo.get_decision(DecisionId(link.target))
            return GraphAuthority.ACCEPTED, True, []
        case DeepLinkKind.MANUSCRIPT:
            return _manuscript(repo, link)
        case _:
            return GraphAuthority.PRIVATE, False, [_UNSUPPORTED]


def _artifact(repo: WorkspaceRepository, link: DeepLink) -> tuple[GraphAuthority, bool, list[str]]:
    artifact = repo.get_artifact(ArtifactId(link.target))
    problems: list[str] = []
    fresh = True
    if link.block is None and link.page is None:
        return GraphAuthority.ACCEPTED, fresh, problems
    document = repo.get_parsed_document(artifact.id, work=artifact.work)
    if document is None:
        return GraphAuthority.ACCEPTED, False, [f"{artifact.id} has no stored parse to anchor in"]
    if document.file_hash != artifact.file_hash:
        fresh = False
        problems.append("the stored parse was taken from different bytes than the artifact")
    blocks = {str(block.id): block for block in document.blocks}
    if link.block is not None:
        block = blocks.get(link.block)
        if block is None:
            fresh = False
            problems.append(f"block {link.block} is not in the stored parse of {artifact.id}")
        elif link.page is not None and block.page != link.page:
            fresh = False
            problems.append(f"block {link.block} is on page {block.page}, not page {link.page}")
    return GraphAuthority.ACCEPTED, fresh, problems


def _evidence(
    repo: WorkspaceRepository, link: DeepLink, record: NodeRecord | None
) -> tuple[GraphAuthority, bool, list[str]]:
    evidence = _find_evidence(repo, EvidenceId(link.target), record)
    anchor = evidence.source
    authority = evidence_authority(evidence)
    problems: list[str] = []
    fresh = authority is not GraphAuthority.STALE
    if not fresh:
        problems.append(f"{evidence.id} is marked stale")
    artifact = repo.get_artifact(anchor.artifact, work=anchor.work)
    if artifact.file_hash != anchor.file_hash:
        fresh = False
        problems.append("the artifact's bytes are not the ones this anchor was accepted from")
    document = repo.get_parsed_document(anchor.artifact, work=anchor.work)
    blocks = () if document is None else document.blocks
    block = next((item for item in blocks if item.id == anchor.block), None)
    if block is None:
        fresh = False
        problems.append(f"block {anchor.block} is no longer in the stored parse")
    elif block.text_hash != anchor.text_hash:
        fresh = False
        problems.append(f"block {anchor.block} no longer holds the text this anchor recorded")
    return authority, fresh, problems


def _find_evidence(
    repo: WorkspaceRepository, evidence_id: EvidenceId, record: NodeRecord | None
) -> Evidence:
    """The canonical Evidence record, using the projected Work as a hint when there is one."""
    hint = None if record is None else record.metadata.get("work")
    works = [WorkId(str(hint))] if hint else [work.id for work in repo.list_works()]
    for work in works:
        for evidence in repo.iter_evidence(work):
            if evidence.id == evidence_id:
                return evidence
    raise _NotFoundError(f"no evidence {evidence_id} in this project")


def _manuscript(
    repo: WorkspaceRepository, link: DeepLink
) -> tuple[GraphAuthority, bool, list[str]]:
    relative = link.target
    if not relative.startswith(f"{repo.layout.manuscript_dir.name}/"):
        relative = f"{repo.layout.manuscript_dir.name}/{relative}"
    path = repo.layout.resolve(relative)
    if not path.is_file():
        raise _NotFoundError(f"no manuscript file {relative} in this project")
    problems: list[str] = []
    fresh = True
    if link.line is not None:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if link.line > len(lines):
            fresh = False
            problems.append(f"{relative} has {len(lines)} lines; line {link.line} is past the end")
    return GraphAuthority.ACCEPTED, fresh, problems


class _NotFoundError(ResearchHarnessError):
    """Internal: the canonical object a link names does not exist in this project."""


def _reason(error: Exception) -> str:
    collapsed = " ".join(str(error).split())
    return collapsed[:240]

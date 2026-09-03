"""The local research daemon: one FastAPI app in front of the capability registry.

The daemon is a transport and nothing more (ADR-004). It resolves who is calling, hands the
call to :class:`~research_harness.capabilities.registry.CapabilityRegistry`, and renders the
answer. It owns no scientific rule, and there is deliberately no route that runs SQL, writes
a caller-named file, or patches an object field: the whole write surface is the named
capabilities, which is what makes the review gate and the journal impossible to route
around (Product 22, 36).

Three properties are load-bearing:

* **Local only.** `research serve` binds `127.0.0.1`. Authority comes from a token file
  under `.research/`, which only a local process can read; a caller without it is an
  ``agent_host`` principal and may read and stage, never accept (Product 29, 34).
* **Serialized mutation.** Accepted-state calls run under the workspace lock, so a CLI, an
  editor, and this daemon cannot interleave writes (Product 8.2, ADR-001).
* **No held connections.** A long-running capability persists its run first and returns a
  durable run id; the researcher polls `/runs/{id}` (ADR-009).

Four routes exist for the Web cockpit and are reads, every one of them: the immutable
artifact bytes, the stored parse geometry, one composed "what needs attention" answer, and
the built bundle itself. They widen what a client can *see*, never what it can write.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from research_harness import __version__
from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.extra_handlers import ReviewInbox, StaleReport
from research_harness.capabilities.permissions import Permission, Principal
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.claims.service import next_decision_id
from research_harness.domain.claim import Claim
from research_harness.domain.enums import (
    ClaimStatus,
    ManuscriptAnchorStatus,
    QuestionStatus,
    StaleState,
)
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.ids import (
    ArtifactId,
    ClaimId,
    DecisionId,
    EvidenceId,
    QuestionId,
    ResearchId,
    SearchRunId,
    SynthesisId,
    VersionId,
    WorkId,
    parse_id,
)
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.domain.work import Artifact, Work
from research_harness.evidence.conflicts import ConflictRecord, ConflictStore
from research_harness.protocol.dto import (
    ArtifactBlocks,
    AttentionGroup,
    AttentionItem,
    BlockView,
    CandidateView,
    CapabilityCatalog,
    CapabilityResponse,
    ConflictPosition,
    ConflictView,
    CountEntry,
    ErrorBody,
    HealthReport,
    ObjectView,
    OverviewCounts,
    OverviewReport,
    RunStatus,
    WorkspaceIndex,
    WorkSummary,
    error_body,
)
from research_harness.workspace.repository import ObjectNotFoundError, WorkspaceRepository

__all__ = [
    "DAEMON_TOKEN_FILENAME",
    "DEV_ORIGINS",
    "WEB_DIST_ENV",
    "SpaStaticFiles",
    "create_app",
    "dev_mode",
    "ensure_token",
    "token_path",
    "web_dist",
]

logger = logging.getLogger(__name__)

DAEMON_TOKEN_FILENAME = "daemon-token"
"""Where the local authority token lives, under `.research/`. Never a canonical file."""

#: The daemon principal for a caller with no valid local token: an agent host, which may
#: read and stage and must ask a person to accept anything (Product 29).
DEFAULT_HOST = "http"

PrincipalResolver = Callable[[str | None], Principal]


def _caller(request: Request) -> Principal:
    """Who is calling: the local researcher with the token, otherwise an agent host."""
    resolve: PrincipalResolver = request.app.state.principal_resolver
    return resolve(_bearer(request.headers.get("authorization")))


Caller = Annotated[Principal, Depends(_caller)]
"""The principal a route acts for. Resolved from the token, never from the request body."""

RequestBody = Annotated[dict[str, Any] | None, Body()]
"""One capability's request object, validated by the registry rather than by the route."""


def token_path(workspace_root: Path | str) -> Path:
    """The local token file for a workspace."""
    return Path(workspace_root) / ".research" / DAEMON_TOKEN_FILENAME


def ensure_token(workspace_root: Path | str) -> str:
    """Read the workspace's daemon token, creating one on first start.

    The token is regenerable runtime state: deleting it costs nothing but a restart, and it
    carries no scientific authority of its own - it only says "this caller is the local
    researcher" (Product 34: secrets never live in canonical files).
    """
    path = token_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    if existing:
        return existing
    token = secrets.token_urlsafe(32)
    path.write_text(f"{token}\n", encoding="utf-8")
    with_permissions(path)
    return token


def with_permissions(path: Path) -> None:
    """Restrict the token to its owner where the platform supports it."""
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - platforms without POSIX permissions
        logger.debug("could not restrict permissions on %s", path)


def create_app(
    workspace_root: Path | str,
    *,
    registry: CapabilityRegistry | None = None,
    principal_resolver: PrincipalResolver | None = None,
) -> FastAPI:
    """The daemon for one workspace. Nothing here writes canonical state directly."""
    root = Path(workspace_root)
    catalog = registry if registry is not None else build_default_registry()
    token = ensure_token(root)
    resolve = principal_resolver or _default_resolver(token)
    mutation_gate = threading.Lock()

    app = FastAPI(
        title="Research Harness daemon",
        version=__version__,
        summary="Named capabilities over one local research workspace (Product 22).",
    )
    app.state.workspace_root = root
    app.state.registry = catalog
    app.state.token_path = token_path(root)
    app.state.principal_resolver = resolve

    @app.get("/health", response_model=HealthReport)
    def health() -> HealthReport:
        """Whether this daemon can serve its workspace, and what it is serving."""
        repo = _open_repo(root)
        return HealthReport(
            ok=True,
            workspace=str(repo.root),
            project=repo.config.name,
            review_policy=repo.review_policy.value,
            capabilities=len(catalog),
            version=__version__,
        )

    @app.get("/capabilities", response_model=CapabilityCatalog)
    def capabilities() -> CapabilityCatalog:
        """Every named capability with its permission and both JSON schemas."""
        return CapabilityCatalog.of(catalog)

    @app.post("/capabilities/{name}", response_model=CapabilityResponse)
    def invoke(
        name: str,
        response: Response,
        caller: Caller,
        request: RequestBody = None,
    ) -> CapabilityResponse:
        """Invoke one capability. The body is that capability's request object."""
        return _invoke(
            catalog,
            name,
            request or {},
            root=root,
            caller=caller,
            gate=mutation_gate,
            response=response,
        )

    @app.get("/runs/{run_id}", response_model=RunStatus)
    def run(run_id: str, caller: Caller) -> RunStatus:
        """The durable record of one long-running workflow."""
        return _run_capability(catalog, "run.status", {"run_id": run_id}, root, caller)

    @app.post("/runs/{run_id}/cancel", response_model=RunStatus)
    def cancel(run_id: str, caller: Caller) -> RunStatus:
        """Ask a run to stop before its next stage; the flag is durable."""
        return _run_capability(catalog, "run.cancel", {"run_id": run_id}, root, caller)

    @app.get("/objects/{object_id}", response_model=ObjectView)
    def obj(object_id: str, caller: Caller) -> ObjectView:
        """One canonical object, read through the repository's typed accessors."""
        caller.authorize(f"objects.get:{object_id}", Permission.READ, human_only=False)
        return _read_object(_open_repo(root), object_id)

    @app.get("/artifacts/{artifact_id}/bytes")
    def artifact_bytes(artifact_id: str, caller: Caller) -> FileResponse:
        """The immutable bytes an evidence anchor was accepted against (Product 42 D).

        Read-only and byte-identical: there is no counterpart that writes an artifact,
        because an artifact is registered once and never edited (ADR-002).
        """
        caller.authorize(f"artifacts.bytes:{artifact_id}", Permission.READ, human_only=False)
        return _artifact_bytes(_open_repo(root), artifact_id)

    @app.get("/blocks/{artifact_id}", response_model=ArtifactBlocks)
    def blocks(artifact_id: str, caller: Caller) -> ArtifactBlocks:
        """The stored parse of one artifact: page, order, and geometry for each block.

        This is what lets a source pane draw the evidence span on the page without
        re-parsing the PDF, which is why the blocks are canonical (Product 8.1).
        """
        caller.authorize(f"blocks.get:{artifact_id}", Permission.READ, human_only=False)
        return _read_blocks(_open_repo(root), artifact_id)

    @app.get("/candidates/{candidate_id}", response_model=CandidateView)
    def candidate(candidate_id: str, caller: Caller) -> CandidateView:
        """One staged candidate, verbatim, so a review action can post the object back.

        Staging is a proposal store with no authority (ADR-003): reading it changes nothing,
        and accepting what it holds still goes through `evidence.accept`.
        """
        caller.authorize(f"candidates.get:{candidate_id}", Permission.READ, human_only=False)
        return _read_candidate(_open_repo(root), candidate_id)

    @app.get("/index", response_model=WorkspaceIndex)
    def index(caller: Caller) -> WorkspaceIndex:
        """Everything the cockpit's navigation lists, summarised, in one read."""
        caller.authorize("index", Permission.READ, human_only=False)
        return _workspace_index(_open_repo(root))

    @app.get("/overview", response_model=OverviewReport)
    def overview(caller: Caller) -> OverviewReport:
        """What needs attention now, composed server-side (Product 26, principle P10)."""
        caller.authorize("overview", Permission.READ, human_only=False)
        return _overview(catalog, root, caller)

    _serve_bundle(app)
    _allow_dev_origins(app)
    return app


# -- invocation --------------------------------------------------------------


def _invoke(
    registry: CapabilityRegistry,
    name: str,
    request: Mapping[str, Any],
    *,
    root: Path,
    caller: Principal,
    gate: threading.Lock,
    response: Response,
) -> CapabilityResponse:
    """Run one capability under the right lock, and render success or failure the same way."""
    try:
        spec = registry.get(name)
    except ResearchHarnessError as exc:
        return _failure(name, exc, response)

    ctx = open_context(root, caller.actor)
    try:
        if spec.permission in {Permission.MUTATE, Permission.ADMIN}:
            with gate, ctx.repo.lock():
                result = registry.invoke(name, ctx, request, principal=caller)
        else:
            result = registry.invoke(name, ctx, request, principal=caller)
    except ResearchHarnessError as exc:
        return _failure(name, exc, response)
    except ValueError as exc:  # a domain validator refusing the payload
        return _failure(name, exc, response)
    return CapabilityResponse.succeeded(name, result)


def _run_capability(
    registry: CapabilityRegistry,
    name: str,
    request: Mapping[str, Any],
    root: Path,
    caller: Principal,
) -> RunStatus:
    """`/runs/...` is `run.status` / `run.cancel` under a friendlier URL, not a second path."""
    ctx = open_context(root, caller.actor)
    try:
        result = registry.invoke(name, ctx, request, principal=caller)
    except ResearchHarnessError as exc:
        body = error_body(exc, capability=name)
        raise HTTPException(status_code=body.status, detail=body.model_dump(mode="json")) from exc
    if not isinstance(result, RunStatus):  # pragma: no cover - the registry guarantees the model
        raise TypeError(f"{name} returned {type(result).__name__}, not a run record")
    return result


def _failure(name: str, exc: Exception, response: Response) -> CapabilityResponse:
    """Render a refusal: the same body on every transport, with the mapped HTTP status."""
    failed = CapabilityResponse.failed(name, exc)
    body: ErrorBody | None = failed.error
    response.status_code = body.status if body is not None else 400
    return failed


def _default_resolver(token: str) -> PrincipalResolver:
    """Bearer token means the local researcher; anything else is an agent host."""

    def resolve(presented: str | None) -> Principal:
        if presented is not None and secrets.compare_digest(presented, token):
            return Principal.human()
        return Principal.agent_host(DEFAULT_HOST)

    return resolve


def _bearer(authorization: str | None) -> str | None:
    """The token out of an ``Authorization: Bearer <token>`` header."""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


# -- typed object reads ------------------------------------------------------


_READERS: tuple[tuple[type[ResearchId], str, Callable[[WorkspaceRepository, Any], BaseModel]], ...]
_READERS = (
    (WorkId, "work", lambda repo, key: repo.get_work(key)),
    (VersionId, "version", lambda repo, key: repo.get_version(key)),
    (ArtifactId, "artifact", lambda repo, key: repo.get_artifact(key)),
    (ClaimId, "claim", lambda repo, key: repo.get_claim(key)),
    (QuestionId, "question", lambda repo, key: repo.get_question(key)),
    (DecisionId, "decision", lambda repo, key: repo.get_decision(key)),
    (SynthesisId, "matrix", lambda repo, key: repo.get_matrix(key)),
    (SearchRunId, "search_run", lambda repo, key: repo.get_search_run(key)),
)


def _read_object(repo: WorkspaceRepository, object_id: str) -> ObjectView:
    """One canonical object by id. Reads only; there is no write counterpart by design."""
    try:
        identifier = parse_id(object_id)
    except ResearchHarnessError as exc:
        raise HTTPException(status_code=404, detail=f"{object_id} is not a research id") from exc
    if isinstance(identifier, EvidenceId):
        return _read_evidence(repo, identifier)
    for id_type, kind, read in _READERS:
        if type(identifier) is id_type:
            try:
                found = read(repo, identifier)
            except ObjectNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return ObjectView(id=str(identifier), kind=kind, object=found.model_dump(mode="json"))
    raise HTTPException(status_code=404, detail=f"no readable object for {object_id}")


def _read_evidence(repo: WorkspaceRepository, evidence: EvidenceId) -> ObjectView:
    """Evidence lives in its Work's append-only file, so it is found by scan, not by path."""
    for work in repo.list_works():
        for item in repo.iter_evidence(work.id):
            if item.id == evidence:
                return ObjectView(
                    id=str(evidence), kind="evidence", object=item.model_dump(mode="json")
                )
    raise HTTPException(status_code=404, detail=f"no accepted evidence {evidence}")


def _open_repo(root: Path) -> WorkspaceRepository:
    """Open the workspace for a read, refusing clearly when there is not one."""
    try:
        return WorkspaceRepository.open(root)
    except ResearchHarnessError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# -- web cockpit reads -------------------------------------------------------


def _artifact(repo: WorkspaceRepository, artifact_id: str) -> Artifact:
    """One Artifact by id, refusing anything that is not an artifact id."""
    try:
        identifier = parse_id(artifact_id)
    except ResearchHarnessError as exc:
        raise HTTPException(status_code=404, detail=f"{artifact_id} is not a research id") from exc
    if not isinstance(identifier, ArtifactId):
        raise HTTPException(status_code=404, detail=f"{artifact_id} is not an artifact id")
    try:
        return repo.get_artifact(identifier)
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _artifact_bytes(repo: WorkspaceRepository, artifact_id: str) -> FileResponse:
    """Stream the stored file for one Artifact, inline, with its recorded media type."""
    artifact = _artifact(repo, artifact_id)
    path = repo.layout.artifact_bytes_file(artifact)
    if not path.is_file():
        raise HTTPException(
            status_code=404, detail=f"no stored bytes for artifact {artifact.id} at {path}"
        )
    return FileResponse(
        path,
        media_type=artifact.mime_type or DEFAULT_ARTIFACT_MEDIA_TYPE,
        filename=artifact.original_filename,
        content_disposition_type="inline",
    )


def _read_blocks(repo: WorkspaceRepository, artifact_id: str) -> ArtifactBlocks:
    """The stored parse of one Artifact; an unparsed artifact answers with no blocks."""
    artifact = _artifact(repo, artifact_id)
    blocks = list(repo.iter_blocks(artifact.id, work=artifact.work))
    return ArtifactBlocks(
        artifact=str(artifact.id),
        work=str(artifact.work),
        version=str(artifact.version),
        mime_type=artifact.mime_type,
        file_hash=artifact.file_hash,
        page_count=max((block.page for block in blocks), default=0),
        blocks=tuple(
            BlockView(
                id=str(block.id),
                kind=block.kind.value,
                page=block.page,
                order=block.order,
                text=block.text,
                section_path=block.section_path,
                bbox=None if block.bbox is None else block.bbox.as_tuple(),
            )
            for block in blocks
        ),
    )


def _read_candidate(repo: WorkspaceRepository, candidate_id: str) -> CandidateView:
    """One staged candidate by id, through the same function `review.candidate` calls.

    A candidate that is not there is a 404, not an empty one: the route and the capability
    give the same answer because they are the same code (ADR-009).
    """
    from research_harness.capabilities.reads import candidate_view

    try:
        return candidate_view(repo, candidate_id)
    except ResearchHarnessError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# -- the navigation index ----------------------------------------------------


def _workspace_index(repo: WorkspaceRepository) -> WorkspaceIndex:
    """Every navigation list, through the same function the `*.list` capabilities call.

    `GET /index` predates the list capabilities and is kept because the cockpit reads the
    whole navigation in one round trip; it composes the *same* summaries, so a client that
    switches to `claim.list` sees byte-identical objects (ADR-009).
    """
    from research_harness.capabilities.reads import workspace_index

    return workspace_index(repo)


def _work_summary(repo: WorkspaceRepository, work: Work) -> WorkSummary:
    """One Work with its files, and whether each of them has a stored parse."""
    from research_harness.capabilities.reads import work_summary

    return work_summary(repo, work)


# -- the overview ------------------------------------------------------------

#: How many stale marks the overview reads before it stops counting.
STALE_LIMIT = 500

#: How many items of each attention group the overview carries; the rest live in its view.
ATTENTION_ITEMS = 5

#: Claim statuses that can carry a manuscript sentence. Anything else is a sentence the
#: accepted state does not support yet, which is what Product 26 counts on the Overview.
SUPPORTING_CLAIM_STATUSES: frozenset[ClaimStatus] = frozenset(
    {ClaimStatus.SUPPORTED, ClaimStatus.QUALIFIED}
)

#: Question states that are still work (Product 31).
OPEN_QUESTION_STATUSES: frozenset[QuestionStatus] = frozenset(
    {QuestionStatus.OPEN, QuestionStatus.PARTIALLY_ANSWERED, QuestionStatus.BLOCKED}
)


def _overview(registry: CapabilityRegistry, root: Path, caller: Principal) -> OverviewReport:
    """Compose the attention surfaces of Product 26 from reads that already exist.

    Every judgement the Overview renders is made here: which review items are waiting,
    which conflicts are open, what is stale, and which manuscript sentences rest on a Claim
    that cannot carry them. A client displays this; it never recomputes it (principle P10).
    """
    repo = _open_repo(root)
    ctx = open_context(root, caller.actor)
    inbox = _read_result(registry, "review.inbox", {}, ctx, caller, ReviewInbox)
    stale = _read_result(registry, "state.stale", {"limit": STALE_LIMIT}, ctx, caller, StaleReport)
    conflicts = _conflict_views(ConflictStore(repo.layout.research_dir).list(status="open"))
    works = repo.list_works()
    claims = {claim.id: claim for claim in repo.list_claims()}
    questions = repo.list_questions()
    anchors = tuple(repo.iter_anchors())
    unsupported = _unsupported_anchors(anchors, claims)

    return OverviewReport(
        project=repo.config.name,
        workspace=str(repo.root),
        review_policy=repo.review_policy.value,
        principal=caller.kind.value,
        actor=caller.actor,
        next_decision_id=str(next_decision_id(ctx)),
        counts=OverviewCounts(
            works=len(works),
            accepted_evidence=sum(1 for work in works for _ in repo.iter_evidence(work.id)),
            claims=len(claims),
            questions=len(questions),
            artifacts=sum(len(repo.list_artifacts(work.id)) for work in works),
            decisions=len(repo.list_decisions()),
            matrices=len(repo.list_matrices()),
            manuscript_anchors=len(anchors),
        ),
        attention=(
            _group("review_items", "review item", "/review", inbox.count, _review_items(inbox)),
            _group(
                "conflicts", "conflict", "/conflicts", len(conflicts), _conflict_items(conflicts)
            ),
            _group("stale", "stale object", "/stale", stale.count, _stale_items(stale)),
            _group(
                "unsupported_manuscript_claims",
                "unsupported manuscript claim",
                "/manuscript",
                len(unsupported),
                unsupported,
            ),
        ),
        claim_health=tuple(
            CountEntry(key=status.value, count=count)
            for status, count in (
                (status, sum(1 for claim in claims.values() if claim.status is status))
                for status in ClaimStatus
            )
            if count
        ),
        open_questions=tuple(
            AttentionItem(
                id=str(question.id), label=question.question, detail=question.status.value
            )
            for question in questions
            if question.status in OPEN_QUESTION_STATUSES
        ),
        conflicts=conflicts,
    )


def _group(
    kind: str, noun: str, route: str, count: int, items: tuple[AttentionItem, ...]
) -> AttentionGroup:
    """One attention surface: its size in words, where it lives, and its first few items."""
    plural = noun if count == 1 else f"{noun}s"
    return AttentionGroup(
        kind=kind,
        label=f"{count} {plural}",
        count=count,
        route=route,
        items=items[:ATTENTION_ITEMS],
    )


def _review_items(inbox: ReviewInbox) -> tuple[AttentionItem, ...]:
    """The queue's own order, already Product 24.2: conflict, high-risk, stale, ..."""
    return tuple(
        AttentionItem(
            id=str(item.get("candidate_id", "")),
            label=f"{item.get('field', '?')} · {item.get('work', '?')}",
            detail="; ".join(str(reason) for reason in item.get("reasons", ())),
            priority=int(item.get("priority", 0)),
        )
        for item in inbox.items
    )


def _conflict_items(conflicts: tuple[ConflictView, ...]) -> tuple[AttentionItem, ...]:
    return tuple(
        AttentionItem(
            id=conflict.conflict_id,
            label=f"{conflict.kind} · {conflict.subject}",
            detail=conflict.summary,
        )
        for conflict in conflicts
    )


def _stale_items(stale: StaleReport) -> tuple[AttentionItem, ...]:
    """Stale marks in the order `state.stale` reports them: highest impact first."""
    return tuple(
        AttentionItem(
            id=mark.object_id,
            label=mark.object_id,
            detail=mark.reason,
            priority=mark.priority,
        )
        for mark in stale.marks
    )


def _unsupported_anchors(
    anchors: tuple[ManuscriptAnchor, ...], claims: Mapping[ClaimId, Claim]
) -> tuple[AttentionItem, ...]:
    """Manuscript sentences whose Claim cannot carry them, worst reason first.

    A sentence is flagged when its Claim is missing, is not `supported`/`qualified`, or
    when the Claim or the anchor has gone stale. Nothing is repaired and nothing is
    hidden: an anchor with a broken foundation is a finding, not a silent rewrite (ADR-008).
    """
    found: list[AttentionItem] = []
    for anchor in anchors:
        claim = claims.get(anchor.claim)
        if claim is None:
            reason = f"{anchor.claim} is not a registered Claim"
        elif claim.status not in SUPPORTING_CLAIM_STATUSES:
            reason = f"claim {claim.id} is {claim.status.value}"
        elif claim.stale is StaleState.STALE:
            reason = f"claim {claim.id} is stale"
        elif anchor.status is not ManuscriptAnchorStatus.VALID:
            reason = f"anchor is {anchor.status.value}"
        elif anchor.stale is StaleState.STALE:
            reason = "anchor is stale"
        else:
            continue
        found.append(
            AttentionItem(
                id=f"{anchor.file}:{anchor.line_start}",
                label=anchor.sentence,
                detail=reason,
            )
        )
    return tuple(found)


def _conflict_views(records: Sequence[ConflictRecord]) -> tuple[ConflictView, ...]:
    """Open conflicts as the cockpit shows them: every side kept, no winner picked."""
    return tuple(
        ConflictView(
            conflict_id=record.conflict_id,
            kind=record.kind.value,
            subject=record.subject,
            summary=record.summary,
            tier=int(record.tier),
            status=record.status,
            created_at=record.created_at.isoformat(),
            differing_fields=record.differing_fields,
            positions=tuple(
                ConflictPosition(
                    label=position.label,
                    provider=position.provider,
                    model=position.model,
                    decision=dict(position.decision),
                    rationale=position.rationale,
                )
                for position in record.positions
            ),
            proposed_changes=tuple(dict(change) for change in record.proposed_changes),
        )
        for record in records
    )


def _read_result[T: BaseModel](
    registry: CapabilityRegistry,
    name: str,
    request: Mapping[str, Any],
    ctx: CapabilityContext,
    caller: Principal,
    model_type: type[T],
) -> T:
    """Invoke one read capability and insist on its declared response model."""
    result = registry.invoke(name, ctx, request, principal=caller)
    if not isinstance(result, model_type):  # pragma: no cover - the registry guarantees it
        raise TypeError(f"{name} returned {type(result).__name__}, not {model_type.__name__}")
    return result


# -- the built bundle --------------------------------------------------------

WEB_DIST_ENV = "RESEARCH_HARNESS_WEB_DIST"
"""Overrides where the built Web bundle is looked for; a path to a directory of files."""

DEV_ENV = "RESEARCH_HARNESS_DEV"
"""Set to ``1`` to allow the Vite dev server's origin. Off in every other case."""

DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
"""The Vite dev server, on loopback. Never a remote origin: the daemon is local-first."""

DEFAULT_ARTIFACT_MEDIA_TYPE = "application/pdf"


def web_dist() -> Path | None:
    """Where the built cockpit lives, or None when it has not been built.

    The override wins outright when it is set, so a daemon told where the bundle is never
    quietly serves a different one. Otherwise it is looked for beside the package (a wheel
    that ships the bundle), then in the source checkout's `web/dist`. Serving it is optional
    by design: the daemon is complete without a UI, and `pnpm dev` runs against it.
    """
    override = os.environ.get(WEB_DIST_ENV, "").strip()
    here = Path(__file__).resolve()
    candidates = (
        [Path(override)] if override else [here.parent / "static", here.parents[3] / "web" / "dist"]
    )
    return next((path for path in candidates if (path / "index.html").is_file()), None)


def dev_mode() -> bool:
    """True when the daemon is running beside a dev server and may widen its origins."""
    return os.environ.get(DEV_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


class SpaStaticFiles(StaticFiles):
    """Static files with a single-page fallback: an unknown path renders the app shell."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def _serve_bundle(app: FastAPI) -> None:
    """Mount the built cockpit at `/`, after every API route so none of them is shadowed."""
    directory = web_dist()
    if directory is None:
        logger.debug("no built web bundle found; serving the API only")
        return
    app.mount("/", SpaStaticFiles(directory=directory, html=True), name="web")


def _allow_dev_origins(app: FastAPI) -> None:
    """Let the Vite dev server call the daemon, and only in development."""
    if not dev_mode():
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEV_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

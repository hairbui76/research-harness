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
from collections import Counter
from collections.abc import Callable, Container, Iterable, Mapping, Sequence
from datetime import datetime, timedelta
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
from research_harness.capabilities.registry import CapabilityRegistry
from research_harness.claims.service import next_decision_id
from research_harness.domain.base import utc_now
from research_harness.domain.claim import Claim
from research_harness.domain.enums import (
    ClaimStatus,
    DecisionStatus,
    ManuscriptAnchorStatus,
    QuestionStatus,
    ResearchEventType,
    StaleState,
)
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.evidence import Evidence, NumericValue
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
from research_harness.domain.research import (
    Decision,
    SynthesisMatrix,
    Taxonomy,
    TaxonomyTerm,
)
from research_harness.domain.work import Artifact, Work
from research_harness.evidence.conflicts import ConflictRecord, ConflictStore
from research_harness.local_app.runtime import LEGACY_PROJECT_ID, WorkspaceRuntime
from research_harness.projection.rows import (
    MANUSCRIPT_ANCHOR_PREFIX,
    NODE_SEPARATOR,
    TAXONOMY_PREFIX,
    manuscript_anchor_key,
)
from research_harness.protocol.dto import (
    ArtifactBlocks,
    AttentionGroup,
    AttentionItem,
    BlockView,
    CandidateView,
    CapabilityCatalog,
    CapabilityResponse,
    ChangeEntry,
    ConflictPosition,
    ConflictView,
    CountEntry,
    ErrorBody,
    HealthReport,
    MatrixCellView,
    MatrixColumnView,
    MatrixEvidenceView,
    MatrixRowView,
    MatrixView,
    ObjectView,
    OverviewCounts,
    OverviewReport,
    RecentChanges,
    ResearchGroup,
    RunStatus,
    StaleOverview,
    SynthesisReport,
    TaxonomyReport,
    TaxonomyTermView,
    TaxonomyView,
    WorkspaceIndex,
    WorkSummary,
    error_body,
)
from research_harness.server.routes_attachments import register_attachment_routes
from research_harness.server.routes_manuscript import register_manuscript_routes
from research_harness.server.routes_sessions import register_session_routes
from research_harness.workspace.conversations import ConversationStore
from research_harness.workspace.repository import ObjectNotFoundError, WorkspaceRepository

__all__ = [
    "DAEMON_TOKEN_FILENAME",
    "DEV_ORIGINS",
    "WEB_DIST_ENV",
    "SpaStaticFiles",
    "bearer_token",
    "create_app",
    "create_workspace_app",
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
    """The daemon for one workspace. Nothing here writes canonical state directly.

    `research serve` runs one workspace, so it owns the token file and serves the built
    bundle; the routes themselves come from :func:`create_workspace_app`, which the
    multi-project host mounts once per opened project.
    """
    root = Path(workspace_root)
    token = ensure_token(root)
    runtime = WorkspaceRuntime.create(LEGACY_PROJECT_ID, root, catalog=registry)
    resolve = principal_resolver or _default_resolver(token)
    app = create_workspace_app(runtime, principal_resolver=resolve, serve_bundle=True)
    app.state.token_path = token_path(root)
    return app


def create_workspace_app(
    runtime: WorkspaceRuntime,
    *,
    principal_resolver: PrincipalResolver,
    serve_bundle: bool,
) -> FastAPI:
    """Every workspace route over one runtime, as a plain ASGI app.

    The one-workspace daemon and each project of the multi-project host publish exactly
    these routes: there is one implementation, so the two modes cannot drift. Nothing is
    read from a module-level global, so several of these can serve different workspaces in
    one process; `serve_bundle` is False for a mounted project app, whose SPA is served by
    the host that mounted it.
    """
    root = runtime.root
    catalog = runtime.catalog
    mutation_gate = runtime.mutation_gate

    app = FastAPI(
        title="Research Harness daemon",
        version=__version__,
        summary="Named capabilities over one local research workspace (Product 22).",
    )
    app.state.workspace_root = root
    app.state.registry = catalog
    app.state.principal_resolver = principal_resolver
    app.state.runtime = runtime

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

    @app.get("/stale", response_model=StaleOverview)
    def stale(caller: Caller) -> StaleOverview:
        """What went out of date and why, grouped by scientific impact (Product 37).

        Staleness is decay this daemon declares. A client never computes one, and the
        reasons here are the same ones the Overview's own stale group carries.
        """
        caller.authorize("stale", Permission.READ, human_only=False)
        return _stale_overview(catalog, root, caller)

    @app.get("/taxonomy", response_model=TaxonomyReport)
    def taxonomy(caller: Caller) -> TaxonomyReport:
        """The classification, and the terms no accepted Decision stands behind (Product 32)."""
        caller.authorize("taxonomy", Permission.READ, human_only=False)
        return _taxonomy_report(root)

    @app.get("/synthesis", response_model=SynthesisReport)
    def synthesis(caller: Caller) -> SynthesisReport:
        """The matrices, and the readings nobody has recorded for them (Product 7.1)."""
        caller.authorize("synthesis", Permission.READ, human_only=False)
        return _synthesis_report(root)

    register_manuscript_routes(app, root)
    register_attachment_routes(app, root)
    register_session_routes(app, root)
    if serve_bundle:
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


def bearer_token(authorization: str | None) -> str | None:
    """The token out of an ``Authorization: Bearer <token>`` header.

    Public because every host that resolves a principal - this daemon and the
    multi-project app - must read the header the same way.
    """
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


_bearer = bearer_token
"""The name `server/app.py` used before the multi-project host needed the same reader."""


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

#: How many changes the Overview carries. It is a first screen, not a log viewer: the rest
#: stay where they were written, in `events/research.jsonl`.
CHANGE_ITEMS = 8

#: The window "what changed" falls back to when the project has fewer than two conversation
#: sessions to bound one with. Stated in `RecentChanges` and said in words on the page.
RECENT_WINDOW = timedelta(days=7)

#: Which research surface each reportable event moved. Everything else in the log — a parse,
#: a search run, a revalidation — is machinery rather than a change of scientific state, and
#: a returning researcher is not asked to read it.
CHANGE_KINDS: Mapping[ResearchEventType, str] = {
    ResearchEventType.WORK_INGESTED: "work",
    ResearchEventType.EVIDENCE_ACCEPTED: "evidence",
    ResearchEventType.CLAIM_CREATED: "claim",
    ResearchEventType.CLAIM_AUDITED: "claim",
    ResearchEventType.CLAIM_QUALIFIED: "claim",
    ResearchEventType.CLAIM_OVERRIDDEN: "claim",
    ResearchEventType.CLAIM_SUPERSEDED: "claim",
    ResearchEventType.DECISION_ACCEPTED: "decision",
    ResearchEventType.DECISION_SUPERSEDED: "decision",
}

#: Which id prefix has a screen of its own in the cockpit, and where. An id whose type is
#: not here is shown inside its list rather than linked to a page that cannot hold it.
OBJECT_ROUTES: Mapping[type[ResearchId], str] = {
    WorkId: "/corpus",
    EvidenceId: "/evidence",
    ClaimId: "/claims",
    ArtifactId: "/source",
}

#: What each kind of object is called in a sentence, capitalised the way the product
#: capitalises its terms: a Claim and a Decision are named things a researcher recorded,
#: while a work's evidence is the reading it holds.
OBJECT_KINDS: Mapping[type[ResearchId], str] = {
    WorkId: "work",
    EvidenceId: "evidence",
    ClaimId: "Claim",
    QuestionId: "question",
    DecisionId: "Decision",
    SynthesisId: "matrix",
    ArtifactId: "file",
}

#: Month names, so a change reads identically on every machine. `strftime('%B')` follows the
#: process locale, and a research log whose wording depends on `LC_TIME` is one two
#: researchers cannot compare.
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

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
    store = ConflictStore(repo.layout.research_dir)
    conflicts = _conflict_views(store.list(status="open"))
    works = repo.list_works()
    claims = {claim.id: claim for claim in repo.list_claims()}
    questions = repo.list_questions()
    anchors = tuple(repo.iter_anchors())
    unsupported = _unsupported_anchors(anchors, claims)
    names = _ObjectNames(repo)
    staged = _staged_candidates(inbox)
    attention = (
        _group("review_items", "review item", "/review", inbox.count, _review_items(inbox)),
        _group(
            "conflicts",
            "conflict",
            "/conflicts",
            len(conflicts),
            _conflict_items(conflicts, names, staged),
        ),
        _group("stale", "stale object", "/stale", stale.count, _stale_items(stale, names), "stale"),
        _group(
            "unsupported_manuscript_claims",
            "unsupported manuscript claim",
            "/manuscript",
            len(unsupported),
            unsupported,
        ),
    )

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
        attention_summary=_attention_summary(attention),
        attention=attention,
        since_last_session=_since_last_session(repo, store.list()),
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
        conflict_summary=_conflict_summary(conflicts),
        conflict_groups=_conflict_groups(conflicts, names, staged),
    )


def _conflict_groups(
    conflicts: tuple[ConflictView, ...],
    names: _ObjectNames,
    staged: Mapping[str, tuple[str, str]],
) -> tuple[AttentionGroup, ...]:
    """The open disagreements, grouped by what kind of disagreement each one is.

    Product 25 lists six kinds and treats them as different questions: an extractor against
    its verifier is not a taxonomy revision against the classifications that depend on it.
    Which group a record belongs in is therefore drawn here, beside the store that recorded
    the kind, and the Conflicts page reads the grouping rather than rebuilding it.

    The store's own order is kept inside every group: it is the order the disagreements were
    opened in, and nothing on the page re-ranks it.
    """
    grouped: dict[str, list[ConflictView]] = {}
    for conflict in conflicts:
        grouped.setdefault(conflict.kind, []).append(conflict)
    return tuple(
        AttentionGroup(
            kind=kind,
            label=f"{len(members)} conflict" if len(members) == 1 else f"{len(members)} conflicts",
            count=len(members),
            route="/conflicts",
            surface="conflict",
            items=tuple(
                AttentionItem(
                    id=conflict.conflict_id,
                    label=_conflict_subject(conflict, names, staged),
                    detail=conflict.summary,
                    priority=conflict.tier,
                    route=_conflict_route(conflict.subject),
                )
                for conflict in members
            ),
        )
        for kind, members in grouped.items()
    )


def _conflict_subject(
    conflict: ConflictView, names: _ObjectNames, staged: Mapping[str, tuple[str, str]]
) -> str:
    """What one disagreement is about, in the words the rest of the cockpit uses for it.

    A conflict is recorded against an id, and an id is not a name. An object that already
    exists carries its own title, so both the Conflicts page and the Overview call the
    disputed Claim what the Claims page calls it. A staged candidate is named the way the
    review queue names it — the field it answers, and the work the span was read from —
    because that is where the disagreement is decided and what it is called there.

    A subject that is neither, and a candidate the queue no longer holds, keep the text the
    record holds: inventing a name for a subject nothing in the workspace answers to would
    be worse than showing what was written down.
    """
    named = names.title(conflict.subject)
    if named:
        return named
    candidate = staged.get(conflict.subject)
    if candidate is not None:
        return _candidate_name(*candidate)
    if conflict.differing_fields:
        return conflict.differing_fields[0]
    return conflict.subject


def _staged_candidates(inbox: ReviewInbox) -> Mapping[str, tuple[str, str]]:
    """The field and work of every candidate still in the queue, by candidate id."""
    return {
        str(item.get("candidate_id", "")): (str(item.get("field", "")), str(item.get("work", "")))
        for item in inbox.items
    }


def _candidate_name(field: str, work: str) -> str:
    """What one staged candidate is called wherever it is named: `<field> · <work>`.

    The review queue, the review screen, the command palette and now a conflict over that
    candidate all say the same thing, so one candidate never has two names.
    """
    return f"{field or '?'} · {work or '?'}"


def _conflict_route(subject: str) -> str:
    """Where one disagreement is decided, or "" when the cockpit has no screen for it.

    A conflict over a staged candidate is resolved on that candidate's review screen, beside
    the source it was read from (Product 25); a conflict over an object that already exists
    is read on that object's own page. A subject that is neither — a table, a section — has
    nowhere of its own, and the item is text rather than a link that goes nowhere useful.
    """
    if subject.startswith("cand_"):
        return f"/review/{subject}"
    return _object_route(subject)


def _conflict_summary(conflicts: tuple[ConflictView, ...]) -> str:
    """The Conflicts page's own first line: how much is in dispute, and what that means."""
    if not conflicts:
        return "Nothing in this project is in dispute."
    counted = "1 conflict is" if len(conflicts) == 1 else f"{len(conflicts)} conflicts are"
    return f"{counted} open. Every side is kept, and none of them is preferred until you decide."


def _group(
    kind: str,
    noun: str,
    route: str,
    count: int,
    items: tuple[AttentionItem, ...],
    surface: str = "decide",
) -> AttentionGroup:
    """One attention surface: its size in words, where it lives, and its first few items."""
    plural = noun if count == 1 else f"{noun}s"
    return AttentionGroup(
        kind=kind,
        label=f"{count} {plural}",
        count=count,
        route=route,
        items=items[:ATTENTION_ITEMS],
        surface=surface,
    )


def _attention_summary(groups: Sequence[AttentionGroup]) -> str:
    """The one line the Overview leads with: what needs a researcher, in the daemon's words.

    It is written here rather than assembled in a client because deciding what counts as
    waiting is the same judgement that built the groups (Product 5 P10). Each group already
    states its own size in words, so the sentence only has to join them.
    """
    waiting = [group for group in groups if group.count]
    if not waiting:
        return "Nothing needs a researcher right now."
    verb = "needs" if len(waiting) == 1 and waiting[0].count == 1 else "need"
    return f"{_join_phrases([group.label for group in waiting])} {verb} a researcher."


def _join_phrases(phrases: Sequence[str]) -> str:
    """`a`, `a and b`, `a, b and c` — one list read as one sentence."""
    if len(phrases) <= 1:
        return "".join(phrases)
    return f"{', '.join(phrases[:-1])} and {phrases[-1]}"


def _object_route(object_id: str) -> str:
    """Where the cockpit shows one object, or "" when it has no screen of its own."""
    try:
        parsed = parse_id(object_id)
    except ResearchHarnessError:
        return ""
    base = OBJECT_ROUTES.get(type(parsed))
    return f"{base}/{parsed}" if base else ""


class _ObjectNames:
    """What one research object is called, in the words a person reads.

    An id is how the daemon holds an object, not what it is. Naming one is a judgement
    about the workspace — which field of the record is its name, and what a composite node
    like a matrix cell is called at all — so it is made here, once, and every surface that
    shows the object reads the same title (Product 5 P10). Two pages humanising the same
    id in two different ways would be two names for one thing.

    Every index is read on first use and kept for the life of one request. A project with
    nothing stale and nothing in dispute never opens its evidence files at all, and one
    that does reads each list once however many marks point into it.
    """

    __slots__ = ("_evidence", "_named", "_repo", "_works")

    def __init__(self, repo: WorkspaceRepository) -> None:
        self._repo = repo
        self._named: dict[str, str] | None = None
        self._works: dict[str, str] | None = None
        self._evidence: dict[str, str] | None = None

    def title(self, object_id: str) -> str:
        """The object's own name, or "" when this workspace cannot name it.

        An id nothing in the workspace answers to — a node left behind by an object that
        has since been deleted — names nothing, and the surface falls back to the id.
        """
        text = str(object_id)
        if text.startswith(TAXONOMY_PREFIX):
            return text[len(TAXONOMY_PREFIX) :]
        if text.startswith(MANUSCRIPT_ANCHOR_PREFIX):
            return self._anchor(text)
        if NODE_SEPARATOR in text:
            _, _, rest = text.partition(NODE_SEPARATOR)
            work, _, field = rest.partition(NODE_SEPARATOR)
            return f"{field} · {self._work(work)}" if field else ""
        try:
            parsed = parse_id(text)
        except ResearchHarnessError:
            return ""
        if isinstance(parsed, EvidenceId):
            return self._evidence_titles().get(text, "")
        return self._names().get(text, "")

    def kind(self, object_id: str) -> str:
        """The word for what kind of object this is, as the product capitalises it."""
        text = str(object_id)
        if text.startswith(TAXONOMY_PREFIX):
            return "taxonomy"
        if text.startswith(MANUSCRIPT_ANCHOR_PREFIX):
            return "manuscript sentence"
        if NODE_SEPARATOR in text:
            return "classification"
        try:
            parsed = parse_id(text)
        except ResearchHarnessError:
            return ""
        return OBJECT_KINDS.get(type(parsed), "")

    def reason(self, reason: str, source_change: str) -> str:
        """One stale reason with the object that moved named rather than coded.

        `state.stale` records the change as the id it happened to — "upstream D0001
        changed" — because the projection has nothing but ids. Here the workspace is open,
        so the id becomes the object's own name and the sentence stops asking a researcher
        to remember which Decision D0001 was. A reason that names nothing resolvable is
        left exactly as the daemon recorded it.
        """
        named = self.title(source_change)
        kind = self.kind(source_change)
        if not named or not source_change or source_change not in reason:
            return reason
        return reason.replace(source_change, f"{kind} “{named}”" if kind else f"“{named}”")

    def _work(self, work: str) -> str:
        """One Work's title, falling back to its id when the corpus has no such Work."""
        return self._work_titles().get(work, work)

    def _anchor(self, node: str) -> str:
        """The manuscript sentence one anchor holds, found by the node id it is keyed by."""
        for anchor in self._repo.iter_anchors():
            if manuscript_anchor_key(anchor.file, anchor.sentence_fingerprint) == node:
                return anchor.sentence
        return ""

    def _work_titles(self) -> dict[str, str]:
        if self._works is None:
            self._works = {str(work.id): work.title for work in self._repo.list_works()}
        return self._works

    def _names(self) -> dict[str, str]:
        """Every object whose name is a field of its own file, by id."""
        if self._named is None:
            named = dict(self._work_titles())
            named.update({str(claim.id): claim.statement for claim in self._repo.list_claims()})
            named.update(
                {str(question.id): question.question for question in self._repo.list_questions()}
            )
            named.update(
                # A Decision may carry no title, and then its rationale is what a researcher
                # recorded it as: it is the sentence the decision was taken for.
                {
                    str(decision.id): decision.title or decision.rationale
                    for decision in self._repo.list_decisions()
                }
            )
            named.update({str(matrix.id): matrix.name for matrix in self._repo.list_matrices()})
            self._named = named
        return self._named

    def _evidence_titles(self) -> dict[str, str]:
        """Accepted evidence, named the way the review queue names the candidate it came from.

        `field · work` is what a researcher decided this evidence under (`candidateName` in
        the cockpit), so the accepted object keeps the name the candidate had.
        """
        if self._evidence is None:
            found: dict[str, str] = {}
            for work in self._repo.list_works():
                for evidence in self._repo.iter_evidence(work.id):
                    field = evidence.content.field or "evidence"
                    found[str(evidence.id)] = f"{field} · {work.title}"
            self._evidence = found
        return self._evidence


def _review_items(inbox: ReviewInbox) -> tuple[AttentionItem, ...]:
    """The queue's own order, already Product 24.2: conflict, high-risk, stale, ..."""
    return tuple(
        AttentionItem(
            id=str(item.get("candidate_id", "")),
            label=_candidate_name(str(item.get("field", "")), str(item.get("work", ""))),
            detail="; ".join(str(reason) for reason in item.get("reasons", ())),
            priority=int(item.get("priority", 0)),
            route=f"/review/{item.get('candidate_id', '')}",
        )
        for item in inbox.items
    )


def _conflict_items(
    conflicts: tuple[ConflictView, ...],
    names: _ObjectNames,
    staged: Mapping[str, tuple[str, str]],
) -> tuple[AttentionItem, ...]:
    """The open disagreements as the Overview lists them: the kind, then what it is about.

    The subject is composed by the same function the Conflicts page's own groups use, so
    one disagreement carries one name on both pages. The kind stays in front of it here
    because this list is not grouped by kind and the Conflicts page's is.
    """
    return tuple(
        AttentionItem(
            id=conflict.conflict_id,
            label=f"{conflict.kind} · {_conflict_subject(conflict, names, staged)}",
            detail=conflict.summary,
        )
        for conflict in conflicts
    )


def _stale_items(stale: StaleReport, names: _ObjectNames) -> tuple[AttentionItem, ...]:
    """Stale marks in the order `state.stale` reports them: highest impact first.

    The projection knows each object by its node id and nothing else, so the name and the
    reason are composed here against the open workspace: the object's own title, and the
    upstream object that moved named rather than coded. The id stays in `label`, because a
    researcher repairing a stale object works with it.
    """
    return tuple(
        AttentionItem(
            id=mark.object_id,
            label=mark.object_id,
            title=names.title(mark.object_id),
            detail=names.reason(mark.reason, mark.source_change),
            priority=mark.priority,
            route=_object_route(mark.object_id),
        )
        for mark in stale.marks
    )


# -- what changed since the researcher last worked ---------------------------


def _since_last_session(
    repo: WorkspaceRepository, conflicts: Sequence[ConflictRecord]
) -> RecentChanges:
    """What moved while the researcher was away, newest first (the DTO states the rule).

    Two sources, because scientific state and disagreements are recorded in two places: the
    Git-visible semantic event log (Product 19.3) says what was ingested, accepted, promoted
    and decided, and the conflict store says which disagreements opened and which the
    researcher answered. Both already carry their own sentence and their own instant, so
    nothing here interprets anything — it selects a window, merges, orders and caps.
    """
    since, basis = _change_window(repo)
    dated = [*_event_changes(repo, since), *_conflict_changes(conflicts, since)]
    dated.sort(key=lambda pair: pair[0], reverse=True)
    entries = tuple(entry for _, entry in dated[:CHANGE_ITEMS])
    left_out = len(dated) - len(entries)
    if not dated and not _has_history(repo):
        basis = "no_history"
    return RecentChanges(
        basis=basis,
        since=since.isoformat(),
        summary=_change_summary(basis, since, len(dated)),
        more=(
            ""
            if left_out <= 0
            else f"{left_out} more {'change is' if left_out == 1 else 'changes are'} "
            "recorded in this project's event log."
        ),
        entries=entries,
        total=len(dated),
    )


def _change_window(repo: WorkspaceRepository) -> tuple[datetime, str]:
    """When the researcher last stopped working, and which rule said so.

    The session before the most recent one is the boundary, so a researcher who comes back
    sees the work of their own last sitting as well as anything that happened after it. One
    session cannot bound a window and neither can none, so the fallback is `RECENT_WINDOW`.
    """
    ends = sorted(
        (
            session.last_message_at
            for session in ConversationStore.for_repository(repo).list_sessions()
            if session.last_message_at is not None
        ),
        reverse=True,
    )
    if len(ends) >= 2:
        return ends[1], "previous_session"
    return utc_now() - RECENT_WINDOW, "recent_window"


def _has_history(repo: WorkspaceRepository) -> bool:
    """True once this project has ever recorded a change worth reporting."""
    return any(event.event in CHANGE_KINDS for event in repo.iter_events())


def _change_summary(basis: str, since: datetime, count: int) -> str:
    """The window and its size in one sentence, so no client has to infer either."""
    if basis == "no_history":
        return "No research activity has been recorded in this project yet."
    window = (
        f"since your previous session ended on {_human_moment(since)}"
        if basis == "previous_session"
        else "in the last seven days"
    )
    if count == 0:
        return f"Nothing has changed {window}."
    return f"{count} {'change' if count == 1 else 'changes'} {window}."


def _human_moment(moment: datetime) -> str:
    """One instant in the words a person reads, in the time zone the daemon runs in."""
    local = moment.astimezone()
    return f"{local.day} {MONTHS[local.month - 1]}, {local:%H:%M}"


def _event_changes(
    repo: WorkspaceRepository, since: datetime
) -> list[tuple[datetime, ChangeEntry]]:
    """Works added, evidence accepted, claims moved and decisions taken, from the log."""
    found: list[tuple[datetime, ChangeEntry]] = []
    for event in repo.iter_events():
        kind = CHANGE_KINDS.get(event.event)
        if kind is None or event.occurred_at < since:
            continue
        subject = str(event.subjects[0]) if event.subjects else ""
        found.append(
            (
                event.occurred_at,
                ChangeEntry(
                    id=f"{event.event.value}:{event.occurred_at.isoformat()}:{subject}",
                    kind=kind,
                    label=event.summary,
                    detail=subject,
                    at=event.occurred_at.isoformat(),
                    when=_human_moment(event.occurred_at),
                    route=_object_route(subject),
                ),
            )
        )
    return found


def _conflict_changes(
    conflicts: Sequence[ConflictRecord], since: datetime
) -> list[tuple[datetime, ChangeEntry]]:
    """Disagreements opened, and disagreements a researcher answered, in the same window.

    A conflict that opened and was answered inside one window is two changes, because it is
    two things a returning researcher would want to know happened.
    """
    found: list[tuple[datetime, ChangeEntry]] = []
    for record in conflicts:
        if record.created_at >= since:
            found.append(
                (
                    record.created_at,
                    _conflict_change(record, record.created_at, "opened", record.summary),
                )
            )
        resolution = record.resolution
        if resolution is not None and resolution.resolved_at >= since:
            found.append(
                (
                    resolution.resolved_at,
                    _conflict_change(
                        record,
                        resolution.resolved_at,
                        "resolved",
                        f"{record.summary} — resolved as {resolution.choice}: {resolution.reason}",
                    ),
                )
            )
    return found


def _conflict_change(
    record: ConflictRecord, moment: datetime, verb: str, summary: str
) -> ChangeEntry:
    return ChangeEntry(
        id=f"{record.conflict_id}:{verb}",
        kind="conflict",
        label=f"Conflict {verb}: {summary}",
        detail=record.subject,
        at=moment.isoformat(),
        when=_human_moment(moment),
        route="/conflicts",
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


# -- the research pages the Overview's pattern reaches ------------------------
#
# Three pages that used to be a table in a card now read the way the Overview reads: what
# needs a researcher first, stated in sentences, then the instrument the page exists for.
# Every line those pages group by is drawn here, because deciding which group an object
# belongs in is the same scientific judgement that decides whether it needs attention at
# all (Product 5 P10). A client renders these answers and composes none of them.

#: Product 37's tiers of scientific impact, highest first: the priority `state.stale`
#: records, a stable key, what the tier is called on screen, the noun one of its objects is,
#: where the cockpit shows those objects, and what going stale in that tier costs.
STALE_TIERS: tuple[tuple[int, str, str, str, str, str], ...] = (
    (
        5,
        "manuscript",
        "Manuscript sentences",
        "manuscript sentence",
        "/manuscript",
        "A sentence in the manuscript is attached to a Claim whose support has moved, so "
        "what is written no longer rests on what the accepted state says. Nothing is "
        "rewritten for you; this is the tier to repair first.",
    ),
    (
        4,
        "claims",
        "Accepted claims",
        "claim",
        "/claims",
        "A Claim was audited against evidence that has since changed, so the strength it is "
        "allowed to state was settled on a reading that no longer stands.",
    ),
    (
        3,
        "synthesis",
        "Synthesis matrices",
        "matrix",
        "/synthesis",
        "A matrix cell was read from evidence that has since changed, so the row it sits in "
        "no longer reads the corpus as the corpus now stands.",
    ),
    (
        2,
        "taxonomy",
        "Classifications",
        "classification",
        "/taxonomy",
        "A work was classified under a term whose Decision has since been revised. The "
        "classification is never rewritten silently; a researcher decides what it becomes.",
    ),
    (
        1,
        "index",
        "Index entries",
        "index entry",
        "",
        "A projection entry is behind the canonical files it is derived from. Rebuilding "
        "the projection settles it, and no canonical object is affected.",
    ),
)

#: How many works with no row of their own one synthesis gap group names before it stops
#: listing them. The group's own sentence still states the whole number.
UNCOVERED_ITEMS = 5


def _counted(count: int, noun: str, plural: str | None = None) -> str:
    """`1 claim` / `4 claims` — a count only ever read inside the thing it counts."""
    return f"{count} {noun if count == 1 else (plural or f'{noun}s')}"


def _has(count: int) -> str:
    """`has` or `have`, so a sentence built around a count still parses."""
    return "has" if count == 1 else "have"


# -- what went stale, and why ------------------------------------------------


def _stale_overview(registry: CapabilityRegistry, root: Path, caller: Principal) -> StaleOverview:
    """`state.stale`, grouped into the scientific-impact tiers of Product 37.

    The items are built by :func:`_stale_items`, which is the Overview's own "Gone stale"
    group. That is deliberate: two surfaces reporting the same decay in two different sets
    of words would be two accounts of one fact, and a researcher would have to decide which
    to believe. There is one account, and both pages read it.
    """
    ctx = open_context(root, caller.actor)
    report = _read_result(registry, "state.stale", {"limit": STALE_LIMIT}, ctx, caller, StaleReport)
    items = _stale_items(report, _ObjectNames(_open_repo(root)))
    groups: list[ResearchGroup] = []
    for priority, key, title, noun, route, detail in STALE_TIERS:
        tier = tuple(item for item in items if item.priority == priority)
        if not tier:
            continue
        groups.append(
            ResearchGroup(
                key=key,
                title=title,
                summary=f"{_counted(len(tier), noun)} {_has(len(tier))} gone stale",
                detail=detail,
                count=len(tier),
                route=route,
                items=tier,
            )
        )
    left_out = report.count - len(items)
    return StaleOverview(
        summary=_stale_summary(report.count),
        count=report.count,
        reported=len(items),
        more=(
            ""
            if left_out <= 0
            else f"{_counted(left_out, 'further stale mark')} {_has(left_out)} been recorded "
            "beyond the ones listed here."
        ),
        groups=tuple(groups),
    )


def _stale_summary(count: int) -> str:
    """The Stale page's own line: decay the daemon declared, never a client's guess."""
    if not count:
        return "Nothing in this project has gone out of date."
    subject = "it rests" if count == 1 else "they rest"
    return f"{_counted(count, 'object')} went stale because something {subject} on changed."


# -- the classification, and the terms nothing stands behind -----------------


def _taxonomy_report(root: Path) -> TaxonomyReport:
    """Every taxonomy of this project, and which of its terms need a researcher.

    A taxonomy is a researcher-approved project decision rather than a universal domain
    fact (Product 32). A term with no Decision, or one whose Decision has been superseded,
    is therefore classifying works on an authority the project has not granted — which is
    the work this page opens with, before the classification itself.
    """
    repo = _open_repo(root)
    decisions = {str(decision.id): decision for decision in repo.list_decisions()}
    views: list[TaxonomyView] = []
    waiting: list[AttentionItem] = []
    total = 0
    for taxonomy in repo.list_taxonomies():
        terms: list[TaxonomyTermView] = []
        approved = 0
        for term, depth in _ordered_terms(taxonomy):
            standing, status, reason = _term_standing(term, decisions)
            approved += 1 if standing else 0
            terms.append(
                TaxonomyTermView(
                    term=str(term.term),
                    parent=str(term.parent or ""),
                    definition=term.definition or "",
                    decision=str(term.decision or ""),
                    decision_status=status,
                    approved=standing,
                    depth=depth,
                )
            )
            if not standing:
                waiting.append(
                    AttentionItem(
                        id=f"{taxonomy.name}:{term.term}",
                        label=f"{term.term} · {taxonomy.name}",
                        detail=reason,
                    )
                )
        total += len(terms)
        views.append(
            TaxonomyView(
                name=taxonomy.name,
                summary=_taxonomy_summary(len(terms), approved),
                count=len(terms),
                approved=approved,
                terms=tuple(terms),
            )
        )
    group = ResearchGroup(
        key="needs_decision",
        # Named for what the group is, not for what it is doing. "Waiting for a Decision"
        # is the Overview's heading for the review queue in a second capitalisation, and
        # this group is not a queue: it is the terms this project classifies by that no
        # accepted Decision stands behind.
        title="Terms without a Decision",
        summary=f"{_counted(len(waiting), 'term')} {_has(len(waiting))} no accepted Decision "
        f"behind {'it' if len(waiting) == 1 else 'them'}",
        detail=(
            "A term becomes this project's classification when a Decision approves it, and a "
            "Decision that has been superseded no longer carries the term it approved. Until "
            "a researcher records one, anything classified by the term rests on nothing the "
            "project has agreed."
        ),
        count=len(waiting),
        items=tuple(waiting),
    )
    return TaxonomyReport(
        summary=_taxonomy_page_summary(total, len(waiting)),
        count=total,
        needs_decision=group,
        taxonomies=tuple(views),
    )


def _taxonomy_summary(count: int, approved: int) -> str:
    """One taxonomy's own line: how much it classifies, and how much of it is agreed."""
    if not count:
        return "No term has been recorded in this taxonomy yet"
    if approved == count:
        return f"{_counted(count, 'term')}, every one approved by an accepted Decision"
    return f"{_counted(count, 'term')}, {count - approved} of them without an accepted Decision"


def _taxonomy_page_summary(total: int, waiting: int) -> str:
    """The Taxonomy page's own line: the work first, the size of the classification after."""
    if not total:
        return "This project has agreed no classification yet."
    if not waiting:
        return (
            f"Every one of this project's {_counted(total, 'term')} is approved by an "
            "accepted Decision."
        )
    subject = "it" if waiting == 1 else "them"
    return (
        f"{_counted(waiting, 'term')} {_has(waiting)} no accepted Decision behind {subject}, "
        f"out of {_counted(total, 'term')} in this project."
    )


def _ordered_terms(taxonomy: Taxonomy) -> tuple[tuple[TaxonomyTerm, int], ...]:
    """The terms in the order the classification reads: each root, then what hangs under it.

    A taxonomy is a tree, and walking it is the daemon's job so that no client has to
    reconstruct the shape from a `parent` column. A term the walk cannot reach — which the
    model's own validator makes impossible for a missing parent, and leaves possible only
    for a cycle — is still reported, at the root, rather than dropped off the page.
    """
    children: dict[str, list[TaxonomyTerm]] = {}
    for term in taxonomy.terms:
        children.setdefault(str(term.parent or ""), []).append(term)
    ordered: list[tuple[TaxonomyTerm, int]] = []
    seen: set[str] = set()

    def walk(parent: str, depth: int) -> None:
        for term in sorted(children.get(parent, ()), key=lambda item: str(item.term)):
            if str(term.term) in seen:
                continue
            seen.add(str(term.term))
            ordered.append((term, depth))
            walk(str(term.term), depth + 1)

    walk("", 0)
    ordered.extend((term, 0) for term in taxonomy.terms if str(term.term) not in seen)
    return tuple(ordered)


def _term_standing(term: TaxonomyTerm, decisions: Mapping[str, Decision]) -> tuple[bool, str, str]:
    """Whether an accepted Decision stands behind ``term``, its status, and why not."""
    if term.decision is None:
        return False, "", "no Decision approves it yet"
    named = str(term.decision)
    decision = decisions.get(named)
    if decision is None:
        return False, "", f"{named} is named as its approval but is not recorded here"
    status = decision.status.value
    if status == DecisionStatus.ACCEPTED.value:
        return True, status, ""
    if status == DecisionStatus.SUPERSEDED.value:
        return False, status, f"{named} approved it and has since been superseded"
    return False, status, f"{named} proposes it and has not been accepted"


# -- the matrices, and what they cannot say yet ------------------------------


def _synthesis_report(root: Path) -> SynthesisReport:
    """Every matrix of this project, and the readings nobody has recorded for it.

    A matrix reads one property across works and proposes nothing. A cell with no labels
    means "not recorded", never "the work lacks the property", and novelty is never
    inferred from a gap (Product 7.1, 33) — so every sentence composed here is about the
    record, and none of them is about a work.
    """
    repo = _open_repo(root)
    names = _ObjectNames(repo)
    corpus = tuple(str(work.id) for work in repo.list_works())
    matrices = repo.list_matrices()
    spans = _cited_evidence(repo, matrices)
    views: list[MatrixView] = []
    groups: list[ResearchGroup] = []
    missing_total = 0
    uncovered_total = 0
    for matrix in matrices:
        rows = tuple(str(work) for work in matrix.works)
        read = {(str(cell.work), cell.field) for cell in matrix.cells if cell.labels}
        declared = len(rows) * len(matrix.fields)
        recorded = sum(1 for row in rows for field in matrix.fields if (row, field) in read)
        missing = declared - recorded
        missing_total += missing
        uncovered = tuple(work for work in corpus if work not in rows)
        uncovered_total += len(uncovered)
        views.append(
            MatrixView(
                id=str(matrix.id),
                name=matrix.name,
                taxonomy=matrix.taxonomy or "",
                stale=matrix.stale.value,
                works=len(rows),
                fields=matrix.fields,
                cells=len(matrix.cells),
                recorded=recorded,
                shape=_matrix_shape(len(rows), len(matrix.fields)),
                coverage=_matrix_coverage(recorded, declared),
                labels_from=_matrix_vocabulary(matrix.taxonomy),
                columns=_matrix_columns(matrix),
                rows=_matrix_rows(matrix, spans, names.title),
            )
        )
        items = _matrix_gaps(str(matrix.id), rows, matrix.fields, read, uncovered)
        if items:
            groups.append(
                ResearchGroup(
                    key=str(matrix.id),
                    title=matrix.name,
                    summary=_matrix_gap_summary(missing, len(uncovered)),
                    detail=(
                        "A matrix reads one property across works, from accepted evidence. A "
                        "reading nobody has recorded is a gap in the record: it never means "
                        "the work lacks the property, and nothing is proposed for it here."
                    ),
                    count=missing + len(uncovered),
                    items=items,
                )
            )
    return SynthesisReport(
        summary=_synthesis_summary(len(views), missing_total, uncovered_total),
        count=len(views),
        missing=missing_total,
        gaps=tuple(groups),
        matrices=tuple(views),
    )


def _matrix_gaps(
    matrix_id: str,
    rows: Sequence[str],
    fields: Sequence[str],
    read: Container[tuple[str, str]],
    uncovered: Sequence[str],
) -> tuple[AttentionItem, ...]:
    """One item per column that is missing a reading, then the works with no row at all.

    A field is named once, with how much of the column is unread, rather than once per
    empty cell: a column nobody has read is one gap in the record, not five.
    """
    items: list[AttentionItem] = []
    for field in fields:
        unread = [row for row in rows if (row, field) not in read]
        if not unread:
            continue
        items.append(
            AttentionItem(
                id=f"{matrix_id}:{field}",
                label=field,
                detail=(
                    "no work in this matrix has been read for it yet"
                    if len(unread) == len(rows)
                    else f"{len(unread)} of its {_counted(len(rows), 'work')} "
                    f"{_has(len(unread))} not been read for it"
                ),
                priority=len(unread),
            )
        )
    for work in uncovered[:UNCOVERED_ITEMS]:
        items.append(
            AttentionItem(
                id=f"{matrix_id}:{work}",
                label=work,
                detail="this matrix has no row for it",
                route=_object_route(work),
            )
        )
    return tuple(items)


def _cited_evidence(
    repo: WorkspaceRepository, matrices: Sequence[SynthesisMatrix]
) -> Mapping[str, Evidence]:
    """Every accepted Evidence object some matrix cell cites, by id.

    A grid that opens a cell has to quote the span the reading was taken from, and the
    span lives in the evidence file rather than in the matrix. The index is read once for
    the whole page, and a project whose cells cite nothing never opens an evidence file at
    all — the same rule `_ObjectNames` follows for the marks it names.
    """
    cited = {
        str(evidence) for matrix in matrices for cell in matrix.cells for evidence in cell.evidence
    }
    if not cited:
        return {}
    found: dict[str, Evidence] = {}
    for work in repo.list_works():
        for evidence in repo.iter_evidence(work.id):
            key = str(evidence.id)
            if key in cited:
                found[key] = evidence
    return found


def _matrix_vocabulary(taxonomy: str | None) -> str:
    """Which vocabulary a matrix's labels come from: an approved one, or the matrix's own.

    A taxonomy is a project decision rather than a universal fact (Product 32), so a grid
    whose labels rest on one names it, and a grid whose labels rest on none says that too
    instead of leaving a reader to assume there is an approved vocabulary behind them.
    """
    if not taxonomy:
        return "Its labels are this matrix's own; no taxonomy stands behind them."
    return f"Its labels come from the {taxonomy} taxonomy."


def _matrix_columns(matrix: SynthesisMatrix) -> tuple[MatrixColumnView, ...]:
    """One column per declared field, in the matrix's own order, read down its works.

    Reading one property across every work is the question a matrix exists to answer, so
    how a column reads is composed here: which labels were recorded under it, for how many
    works, and whether the works read for it recorded the same label. All of that is a
    count of the record. None of it prefers a reading, resolves a disagreement, or says
    anything about a work nobody has read.
    """
    works = tuple(str(work) for work in matrix.works)
    recorded = {(str(cell.work), cell.field): cell.labels for cell in matrix.cells if cell.labels}
    columns: list[MatrixColumnView] = []
    for field in matrix.fields:
        counts: Counter[str] = Counter()
        read = 0
        for work in works:
            labels = recorded.get((work, field))
            if not labels:
                continue
            read += 1
            counts.update(labels)
        columns.append(
            MatrixColumnView(
                field=field,
                recorded=read,
                coverage=_column_coverage(read, len(works)),
                reading=_column_reading(read, len(works), counts),
            )
        )
    return tuple(columns)


def _column_coverage(recorded: int, works: int) -> str:
    """How much of one column is recorded, said about the record and not about the works."""
    if not works:
        return "This matrix declares no works to read for it"
    if not recorded:
        return "No work in this matrix has been read for it yet"
    if recorded == works:
        return f"All {_counted(works, 'work')} read for it"
    return f"{recorded} of {_counted(works, 'work')} read for it"


def _column_reading(recorded: int, works: int, counts: Counter[str]) -> str:
    """How one column reads across the works: the labels on record, and how many carry each.

    The order is the frequent label first and then alphabetical, which is the order
    `ComparisonTable.label_counts` already puts them in: one ordering of one fact, decided
    once. A column whose works do not all record the same label says so, because two
    different readings on record is the thing a researcher opened the matrix to find — and
    it is stated as a difference in the record, never as a disagreement resolved here.
    """
    coverage = _column_coverage(recorded, works)
    if not recorded:
        return f"{coverage}, so there is nothing to read across it."
    listed = ", ".join(
        f"{label} ({_counted(count, 'work')})"
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )
    sentence = f"{coverage}. Recorded: {listed}."
    if len(counts) > 1:
        sentence += " The works read for it do not all record the same label."
    return sentence


def _matrix_rows(
    matrix: SynthesisMatrix,
    spans: Mapping[str, Evidence],
    title: Callable[[str], str],
) -> tuple[MatrixRowView, ...]:
    """One row per declared work, in the matrix's own order, with a cell per declared field.

    Every declared field gets a cell, including the ones nobody has read: the grid's shape
    is what the matrix declares, and a row that quietly dropped its unread columns would
    show a reader a smaller matrix than the project actually built.
    """
    cells = {(str(cell.work), cell.field): cell for cell in matrix.cells}
    rows: list[MatrixRowView] = []
    for work in (str(work) for work in matrix.works):
        drawn: list[MatrixCellView] = []
        recorded = 0
        for field in matrix.fields:
            cell = cells.get((work, field))
            labels = cell.labels if cell else ()
            evidence = _cell_evidence(cell.evidence if cell else (), spans, title)
            if labels:
                recorded += 1
            drawn.append(
                MatrixCellView(
                    work=work,
                    field=field,
                    recorded=bool(labels),
                    reading=", ".join(labels),
                    measurement=next(
                        (span.measurement for span in evidence if span.measurement), ""
                    ),
                    detail=_cell_detail(bool(labels), evidence),
                    evidence=evidence,
                )
            )
        rows.append(
            MatrixRowView(
                work=work,
                title=title(work),
                route=_object_route(work),
                summary=_row_summary(recorded, len(matrix.fields)),
                cells=tuple(drawn),
            )
        )
    return tuple(rows)


def _row_summary(recorded: int, fields: int) -> str:
    """How much of one work's row is recorded, in the same words the matrix's own uses."""
    if not fields:
        return "This matrix declares no fields to read it for"
    if not recorded:
        return f"None of its {_counted(fields, 'reading')} recorded yet"
    if recorded == fields:
        return f"All {_counted(fields, 'reading')} recorded"
    return f"{recorded} of {_counted(fields, 'reading')} recorded"


def _cell_evidence(
    cited: Iterable[EvidenceId],
    spans: Mapping[str, Evidence],
    title: Callable[[str], str],
) -> tuple[MatrixEvidenceView, ...]:
    """The accepted spans one cell rests on, quoted exactly as they were recorded.

    A span is never shortened here. A trimmed quotation is a different quotation, and a
    matrix cell whose evidence a reader cannot check word for word is a reading on trust.
    """
    found: list[MatrixEvidenceView] = []
    for evidence in cited:
        key = str(evidence)
        held = spans.get(key)
        found.append(
            MatrixEvidenceView(
                id=key,
                title=title(key) if held is not None else "",
                route=_object_route(key),
                quote=held.content.exact_text if held is not None else "",
                measurement=(
                    _measured(held.content.numeric)
                    if held is not None and held.content.numeric is not None
                    else ""
                ),
                found=held is not None,
            )
        )
    return tuple(found)


def _cell_detail(recorded: bool, evidence: Sequence[MatrixEvidenceView]) -> str:
    """What one cell is, in words: what its reading rests on, or what a blank one means.

    The blank is the sentence this whole page exists to keep honest. An empty cell means
    the reading has not been taken; it is never the work read as lacking the property, and
    nothing anywhere infers novelty or absence from one (Product 7.1, 11, 33).
    """
    if not recorded:
        return (
            "No reading has been recorded here yet. A blank cell is a gap in the record, "
            "never a reading of the work."
        )
    missing = [span for span in evidence if not span.found]
    if not evidence:
        return "No accepted evidence is recorded behind this reading."
    stated = f"Read from {_counted(len(evidence), 'accepted evidence span')}."
    if missing:
        stated += (
            " One of them is no longer in this workspace."
            if len(missing) == 1
            else f" {len(missing)} of them are no longer in this workspace."
        )
    return stated


def _measured(numeric: NumericValue) -> str:
    """A measured reading with the metric and the unit it was recorded under (Product 12).

    A number without them is not the number that was read: the writer must never silently
    change metric, unit, dataset or condition, and a grid that printed `94.32` alone would
    be the first surface to do it.
    """
    parts = [numeric.metric, numeric.raw]
    if numeric.unit:
        parts.append(numeric.unit)
    return " ".join(parts)


def _matrix_shape(works: int, fields: int) -> str:
    """What one matrix lines up, in words: never two numbers with a cross between them."""
    if not works or not fields:
        return "This matrix declares no works or no fields to read them for"
    return f"{_counted(works, 'work')} read for {_counted(fields, 'field')}"


def _matrix_coverage(recorded: int, declared: int) -> str:
    """How much of a matrix has been recorded, said about the record and not the works."""
    if not declared:
        return "Nothing to read yet"
    if recorded == declared:
        return f"All {_counted(declared, 'reading')} recorded"
    return f"{recorded} of {_counted(declared, 'reading')} recorded"


def _matrix_gap_summary(missing: int, uncovered: int) -> str:
    """One matrix's own gap line: what is unrecorded, and what has no row at all."""
    phrases = []
    if missing:
        phrases.append(
            f"{_counted(missing, 'reading')} this matrix declares {_has(missing)} not been recorded"
        )
    if uncovered:
        phrases.append(
            f"{_counted(uncovered, 'work')} in the corpus {_has(uncovered)} no row in it"
        )
    return _join_phrases(phrases)


def _synthesis_summary(matrices: int, missing: int, uncovered: int) -> str:
    """The Synthesis page's own line: what the matrices cannot say yet, before their size."""
    if not matrices:
        return "No matrix has been built yet, so nothing reads a property across this corpus."
    recorded = "Every reading these matrices declare has been recorded"
    if not missing and not uncovered:
        return f"{recorded}."
    if not missing:
        return (
            f"{recorded}, and {_counted(uncovered, 'work')} in the corpus "
            f"{_has(uncovered)} no row in any of them."
        )
    return (
        f"{_counted(missing, 'reading')} these matrices declare {_has(missing)} not been "
        "recorded yet."
    )


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

"""The session namespace: Session, Message, and Attachment nodes from `conversations/`.

This is the projector graph spec §2 leaves to the conversation subsystem, and it is the
one namespace whose nodes are *private working context* rather than canonical scientific
state. Two rules follow from that and are enforced here rather than by the caller:

* **Authority.** Every node and edge this projector writes is
  :attr:`~research_harness.domain.graph.GraphAuthority.PRIVATE`. A transcript is never
  accepted state (`domain.conversation.Message` refuses the label outright), so the
  projection must not hand it one either — a `contains` edge is "accepted" for corpus
  structure because the corpus tree is reviewed state, and a session tree is not.
* **Visibility.** A message and an attachment inherit their session's egress class, and
  the stricter of the two wins: a `project`-visible message inside a `private` session
  projects as `private`. Nothing downstream has to remember to join the session record
  back on, which is what makes the privacy-filtered traversal of graph spec §8 a property
  of the data instead of a rule every query has to re-apply.

The unit of projection is one durable file, exactly as everywhere else in `graph/`:
`session.yaml`, `messages.jsonl`, and each `attachments/SA####.yaml` carry their own
fingerprint, so appending one message re-projects one session's transcript and nothing
else (graph spec §4, §11.6).

Identities are the plain ids — `CS0001`, `M0042`, `SA0003` — so `@CS0001` resolves through
canonical identity after `.research/` is deleted and rebuilt, like every other reference
(graph spec §5, §11.1 extended to sessions).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator

from research_harness.domain.conversation import (
    AttachmentBlock,
    AttachmentState,
    ConversationSession,
    Message,
    ReferenceBlock,
    SessionAttachment,
    Visibility,
)
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.graph import (
    DeepLink,
    DeepLinkKind,
    EdgeKind,
    EdgeOrigin,
    GraphAuthority,
    GraphEdge,
    GraphNode,
    GraphVisibility,
    NodeKind,
)
from research_harness.domain.ids import ConversationSessionId, SessionAttachmentId
from research_harness.graph.projectors import (
    ProjectionContext,
    ProjectionUnit,
    _clip,
    _meta,
    project_identity,
)
from research_harness.graph.resolver import ResolvedTarget
from research_harness.workspace.conversations import ConversationStore
from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "SessionProjector",
    "message_visibility",
    "resolve_session_link",
    "session_visibility",
]

logger = logging.getLogger(__name__)

_SESSION_AUTHORITY = GraphAuthority.PRIVATE
"""Working context is never accepted state; the label says so on every row (Product 8.2)."""


def session_visibility(session: ConversationSession) -> GraphVisibility:
    """Egress class of a session node, read off its durable record."""
    return GraphVisibility(session.visibility.value)


def message_visibility(session: ConversationSession, member: Visibility | None) -> GraphVisibility:
    """The stricter of a session's class and a member's own; private always wins.

    A message or attachment cannot be more visible than the session holding it: raising a
    member's class above its session would be exactly the "route around the restriction"
    graph spec §8 forbids, one field wide.
    """
    if session.visibility is Visibility.PRIVATE or member is Visibility.PRIVATE:
        return GraphVisibility.PRIVATE
    return GraphVisibility.PROJECT


class SessionProjector:
    """Sessions, transcripts, and attachments from `conversations/` (plan §0.2).

    A session directory that cannot be read is skipped with a warning rather than failing
    the build: the graph is disposable and a workspace must stay indexable even when one
    durable record is being written, half-written, or was hand-edited into invalidity. The
    transcript itself is never touched — `conversations/` is durable state this only reads.
    """

    name = "session"

    def project(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        store = ConversationStore.for_repository(ctx.repo)
        root = project_identity(ctx.project)
        for session_id in _session_ids(ctx):
            try:
                session = store.get_session(session_id)
                yield self._session(ctx, session, root)
                yield from self._transcript(ctx, store, session)
                yield from self._attachments(ctx, store, session)
            except ResearchHarnessError as error:
                logger.warning("session %s is not projectable: %s", session_id, error)

    # -- session -------------------------------------------------------------

    def _session(
        self, ctx: ProjectionContext, session: ConversationSession, root: str
    ) -> ProjectionUnit:
        path = ctx.layout.session_file(session.id)
        source = ctx.relative(path)
        identity = str(session.id)
        node = GraphNode(
            identity=identity,
            kind=NodeKind.SESSION,
            authority=_SESSION_AUTHORITY,
            visibility=session_visibility(session),
            label=session.title,
            text=_clip(session.title),
            source=source,
            fingerprint=ctx.digest(path),
            metadata=_meta(
                messages=session.message_count,
                opened_at=session.created_at.isoformat(),
                updated_at=session.updated_at.isoformat(),
                last_message=None if session.last_message is None else str(session.last_message),
                mode=session.defaults.mode,
            ),
        )
        edge = GraphEdge(
            from_id=root,
            to_id=identity,
            kind=EdgeKind.CONTAINS,
            origin=EdgeOrigin.STRUCTURAL,
            authority=_SESSION_AUTHORITY,
            source=source,
        )
        return ProjectionUnit(
            source_key=source, fingerprint=ctx.digest(path), nodes=(node,), edges=(edge,)
        )

    # -- transcript ----------------------------------------------------------

    def _transcript(
        self, ctx: ProjectionContext, store: ConversationStore, session: ConversationSession
    ) -> Iterator[ProjectionUnit]:
        path = ctx.layout.messages_file(session.id)
        if not path.is_file():
            return
        source = ctx.relative(path)
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        for message in store.iter_messages(session.id):
            nodes.append(self._message_node(message, session, source, ctx.digest(path)))
            edges.extend(self._message_edges(message, session, source))
        yield ProjectionUnit(
            source_key=source,
            fingerprint=ctx.digest(path),
            nodes=tuple(nodes),
            edges=tuple(edges),
        )

    def _message_node(
        self, message: Message, session: ConversationSession, source: str, fingerprint: str
    ) -> GraphNode:
        text = message.text()
        return GraphNode(
            identity=str(message.id),
            kind=NodeKind.MESSAGE,
            authority=_SESSION_AUTHORITY,
            visibility=message_visibility(session, message.visibility),
            label=_clip(text) or f"{message.role.value} message {message.id}",
            text=_clip(text, _MESSAGE_TEXT_CHARS),
            source=source,
            fingerprint=fingerprint,
            metadata=_meta(
                session=str(message.session),
                role=message.role.value,
                written_at=message.created_at.isoformat(),
                incomplete=message.incomplete or None,
                attempt=message.attempt.status.value,
                context_pack=None if message.context_pack is None else str(message.context_pack),
                provider=None if message.model is None else message.model.provider,
                model=None if message.model is None else message.model.model,
            ),
        )

    def _message_edges(
        self, message: Message, session: ConversationSession, source: str
    ) -> Iterator[GraphEdge]:
        identity = str(message.id)
        yield GraphEdge(
            from_id=str(message.session),
            to_id=identity,
            kind=EdgeKind.CONTAINS,
            origin=EdgeOrigin.STRUCTURAL,
            authority=_SESSION_AUTHORITY,
            source=source,
            metadata=_meta(role=message.role.value),
        )
        placed = {
            block.attachment: block.caption
            for block in message.blocks
            if isinstance(block, AttachmentBlock)
        }
        for attachment in message.attachments:
            yield GraphEdge(
                from_id=str(attachment),
                to_id=identity,
                kind=EdgeKind.ATTACHED_TO,
                origin=EdgeOrigin.STRUCTURAL,
                authority=_SESSION_AUTHORITY,
                source=source,
                metadata=_meta(session=str(session.id), caption=placed.get(attachment)),
            )
        for target, block in _references(message):
            yield GraphEdge(
                from_id=identity,
                to_id=target,
                kind=EdgeKind.MENTIONED_IN,
                origin=EdgeOrigin.STRUCTURAL,
                authority=_SESSION_AUTHORITY,
                source=source,
                metadata=_meta(
                    session=str(session.id),
                    role=message.role.value,
                    locator=block.locator,
                    recorded_authority=None if block.authority is None else block.authority.value,
                ),
            )

    # -- attachments ---------------------------------------------------------

    def _attachments(
        self, ctx: ProjectionContext, store: ConversationStore, session: ConversationSession
    ) -> Iterator[ProjectionUnit]:
        for attachment in store.list_attachments(session.id):
            path = ctx.layout.session_attachment_file(session.id, attachment.id)
            source = ctx.relative(path)
            identity = str(attachment.id)
            node = GraphNode(
                identity=identity,
                kind=NodeKind.ATTACHMENT,
                authority=_SESSION_AUTHORITY,
                visibility=message_visibility(session, attachment.visibility),
                label=attachment.filename,
                text=_clip(f"{attachment.filename} {attachment.description or ''}"),
                source=source,
                fingerprint=ctx.digest(path),
                metadata=_meta(
                    session=str(attachment.session),
                    state=attachment.state.value,
                    media_type=attachment.media_type,
                    size_bytes=attachment.size_bytes or None,
                    pages=attachment.page_count,
                    content_hash=attachment.content_hash,
                    work=None if attachment.work is None else str(attachment.work),
                    version=None if attachment.version is None else str(attachment.version),
                    artifact=None if attachment.artifact is None else str(attachment.artifact),
                ),
            )
            yield ProjectionUnit(
                source_key=source,
                fingerprint=ctx.digest(path),
                nodes=(node,),
                edges=tuple(self._attachment_edges(attachment, source)),
            )

    def _attachment_edges(self, attachment: SessionAttachment, source: str) -> Iterator[GraphEdge]:
        identity = str(attachment.id)
        yield GraphEdge(
            from_id=identity,
            to_id=str(attachment.session),
            kind=EdgeKind.ATTACHED_TO,
            origin=EdgeOrigin.STRUCTURAL,
            authority=_SESSION_AUTHORITY,
            source=source,
            metadata=_meta(state=attachment.state.value),
        )
        if attachment.version is None:
            return
        # `Save to corpus` finished: the session copy joins the corpus spine exactly where
        # the Artifact it became sits, so a traversal from the Version reaches both. The
        # node stays private — promotion copies bytes, it does not publish the session.
        yield GraphEdge(
            from_id=identity,
            to_id=str(attachment.version),
            kind=EdgeKind.ARTIFACT_OF,
            origin=EdgeOrigin.STRUCTURAL,
            authority=_SESSION_AUTHORITY,
            source=source,
            status=attachment.state.value,
            metadata=_meta(
                work=None if attachment.work is None else str(attachment.work),
                artifact=None if attachment.artifact is None else str(attachment.artifact),
            ),
        )


def _session_ids(ctx: ProjectionContext) -> list[ConversationSessionId]:
    """Session directories under `conversations/`, in id order.

    Read from the directory names rather than from `ConversationStore.list_sessions`, so
    one unreadable `session.yaml` costs that session's rows and not the whole namespace.
    """
    root = ctx.layout.conversations_dir
    if not root.is_dir():
        return []
    found: list[ConversationSessionId] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not _SESSION_DIRECTORY.fullmatch(path.name):
            continue
        found.append(ConversationSessionId(path.name))
    return found


_SESSION_DIRECTORY = re.compile(ConversationSessionId.pattern())

_MESSAGE_TEXT_CHARS = 4_000
"""How much of a message the FTS projection carries; the transcript keeps the whole of it."""


def _references(message: Message) -> Iterator[tuple[str, ReferenceBlock]]:
    """Each distinct `@`-reference in a message, with the block that recorded it."""
    seen: set[str] = set()
    for block in message.blocks:
        if not isinstance(block, ReferenceBlock):
            continue
        target = str(block.target)
        if target in seen:
            continue
        seen.add(target)
        yield target, block


# --- deep links into the session namespace ----------------------------------


def resolve_session_link(repo: WorkspaceRepository, link: DeepLink) -> ResolvedTarget:
    """Validate `rh://session/CS0001?message=M0042` or `rh://attachment/SA0003`.

    `graph.resolver` answers for canonical scientific state; a session lives in
    `conversations/`, so this reads the durable record through `ConversationStore` and
    answers in the same shape. Existence, privacy, and freshness come from the durable
    file, never from a projected row (graph spec §5).
    """
    store = ConversationStore.for_repository(repo)
    project = repo.config.name
    try:
        if link.kind is DeepLinkKind.SESSION:
            return _resolved_session(store, link, project)
        return _resolved_attachment(store, link, project)
    except ResearchHarnessError as error:
        return _unresolved(link, project, " ".join(str(error).split())[:240])


def _resolved_session(store: ConversationStore, link: DeepLink, project: str) -> ResolvedTarget:
    session = store.get_session(ConversationSessionId(link.target))
    problems: list[str] = []
    if link.message is not None:
        found = any(str(message.id) == link.message for message in store.iter_messages(session.id))
        if not found:
            problems.append(f"no message {link.message} in session {session.id}")
    return ResolvedTarget(
        link=link,
        project=project,
        exists=True,
        authority=_SESSION_AUTHORITY,
        visibility=session_visibility(session),
        fresh=not problems,
        problems=tuple(problems),
    )


def _resolved_attachment(store: ConversationStore, link: DeepLink, project: str) -> ResolvedTarget:
    attachment_id = SessionAttachmentId(link.target)
    for session in store.list_sessions():
        for attachment in store.list_attachments(session.id):
            if attachment.id != attachment_id:
                continue
            problems = _attachment_problems(store, attachment)
            return ResolvedTarget(
                link=link,
                project=project,
                exists=True,
                authority=_SESSION_AUTHORITY,
                visibility=message_visibility(session, attachment.visibility),
                fresh=not problems,
                problems=tuple(problems),
            )
    return _unresolved(link, project, f"no attachment {attachment_id} in this project")


def _attachment_problems(store: ConversationStore, attachment: SessionAttachment) -> list[str]:
    if attachment.state is AttachmentState.FAILED:
        return [f"{attachment.id} failed: {attachment.failure_reason or 'no reason recorded'}"]
    if not store.attachment_bytes_path(attachment).is_file():
        return [f"{attachment.id} has no stored bytes yet"]
    return []


def _unresolved(link: DeepLink, project: str, problem: str) -> ResolvedTarget:
    return ResolvedTarget(
        link=link,
        project=project,
        exists=False,
        authority=_SESSION_AUTHORITY,
        visibility=GraphVisibility.PRIVATE,
        fresh=False,
        problems=(problem,),
    )

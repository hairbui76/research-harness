"""One object the capabilities, the CLI, and the daemon hold: the conversation service.

It composes the four pieces of this package — the store, the assembler, the send loop, and
promotion — and owns exactly one decision of its own: which retrieval source to prefer.
The ResearchGraph ranks across sessions when the projection is there; a direct transcript
scan answers when it is not, which is why deleting `.research/` costs ranking quality and
nothing else (conversation design SS8).

Everything else here is a thin pass-through, on purpose. A second business-logic layer
would be a second place for the rules to disagree (ADR-004).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from research_harness.capabilities.context import CapabilityContext
from research_harness.conversation.context import (
    AssembledContext,
    AttachmentPlan,
    ContextAssembler,
    ContextBudget,
    ProviderProfile,
)
from research_harness.conversation.promote import ClaimProposal, Promotion, PromotionService
from research_harness.conversation.retrieval import (
    ContextSource,
    GraphExcerpts,
    TranscriptScan,
    graph_is_available,
)
from research_harness.conversation.send import (
    ProviderSelector,
    Selection,
    SendOutcome,
    SendService,
    SendStarted,
    join_send,
    stream_events,
)
from research_harness.domain.conversation import (
    ContextPack,
    ConversationSession,
    EgressClass,
    Message,
    PromotionRequest,
    SessionAttachment,
    SessionDefaults,
    Visibility,
)
from research_harness.domain.enums import DecisionType
from research_harness.domain.ids import (
    ContextPackId,
    ConversationSessionId,
    MessageId,
    SessionAttachmentId,
)
from research_harness.privacy.policy import EgressPolicy, load_policy
from research_harness.workspace.conversations import (
    DEFAULT_SEARCH_LIMIT,
    ConversationStore,
    SessionMatch,
    derive_summary,
)
from research_harness.workspace.runs import RunStore

__all__ = ["ConversationService", "SessionPage"]

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
"""Messages one `session.get` returns when the caller names no limit."""


@dataclass(frozen=True, slots=True)
class SessionPage:
    """One page of a transcript, plus everything needed to resume the session."""

    session: ConversationSession
    messages: tuple[Message, ...]
    total: int
    offset: int
    attachments: tuple[SessionAttachment, ...] = ()
    summary: str | None = None

    @property
    def next_offset(self) -> int | None:
        """Where the next page starts, or `None` at the end of the transcript."""
        end = self.offset + len(self.messages)
        return end if end < self.total else None


class ConversationService:
    """Sessions, transcripts, context packs, sending, and promotion, for one workspace."""

    def __init__(
        self,
        ctx: CapabilityContext,
        *,
        store: ConversationStore | None = None,
        sources: Sequence[ContextSource] | None = None,
        providers: ProviderSelector | None = None,
        graph: Any | None = None,
        policy: EgressPolicy | None = None,
    ) -> None:
        self._ctx = ctx
        self._store = store or ConversationStore.for_repository(ctx.repo)
        self._graph = graph
        self._sources = sources
        self._providers = providers
        self._policy = policy

    @property
    def store(self) -> ConversationStore:
        """The durable conversation store this service reads and writes."""
        return self._store

    # -- sessions ------------------------------------------------------------

    def create(
        self,
        title: str,
        *,
        visibility: Visibility = Visibility.PRIVATE,
        model: str | None = None,
        mode: str | None = None,
        token_budget: int | None = None,
    ) -> ConversationSession:
        """Open a session. Private by default: conversation is local working context."""
        from research_harness.domain.conversation import ModelIdentity

        identity = None
        if model is not None:
            provider, _, name = model.partition("/")
            identity = ModelIdentity(provider=provider, model=name or provider)
        defaults = SessionDefaults(model=identity, mode=mode, token_budget=token_budget)
        return self._store.create_session(
            title=title,
            provenance=self._ctx.provenance(workflow="session"),
            visibility=visibility,
            defaults=defaults,
        )

    def rename(self, session: ConversationSessionId, title: str) -> ConversationSession:
        """Give a session a new title; ids, transcript, and attachments are untouched."""
        return self._store.rename_session(session, title)

    def sessions(self) -> list[ConversationSession]:
        """Every session in the project, ordered by id."""
        return self._store.list_sessions()

    def transcript(
        self,
        session: ConversationSessionId,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> SessionPage:
        """One page of a session, oldest first: what `session.get` answers with."""
        resumed = self._store.resume(session)
        start = max(offset, 0)
        window = resumed.messages[start : start + max(limit, 0)]
        return SessionPage(
            session=resumed.session,
            messages=window,
            total=len(resumed.messages),
            offset=start,
            attachments=resumed.attachments,
            summary=self._store.read_summary(session),
        )

    def search(self, query: str, *, limit: int = DEFAULT_SEARCH_LIMIT) -> list[SessionMatch]:
        """Sessions whose title or messages contain ``query``; a direct transcript read."""
        return self._store.search(query, limit=limit)

    def summarize(self, session: ConversationSessionId) -> str:
        """Regenerate the derived summary. Deterministic, and never an authority.

        There is no model call: the summary is derived from the transcript, so it says the
        same thing on a workstation with no provider configured as on one with several.
        """
        return self._store.regenerate_summary(session)

    def summary_preview(self, session: ConversationSessionId) -> str:
        """What `summarize` would write, without writing it."""
        resumed = self._store.resume(session)
        return derive_summary(resumed.session, resumed.messages, resumed.attachments)

    # -- context -------------------------------------------------------------

    def preview(
        self,
        session: ConversationSessionId,
        draft: str = "",
        references: Sequence[str] = (),
        *,
        model: str | None = None,
        budget: ContextBudget | None = None,
        persist: bool = True,
    ) -> tuple[ContextPack, AssembledContext]:
        """Assemble a pack without sending it (`context.preview`).

        The pack is assembled against the provider that *would* answer, so the receipt
        shows exactly what that provider would have been refused, and then records
        `egress = none`, because nothing was sent.
        """
        selection = self._preview_selection(model, budget)
        profile = ProviderProfile() if selection is None else selection.profile
        assembled = self.assembler().assemble(
            session,
            draft,
            references,
            model=profile,
            policy=self._egress_policy(),
            budget=budget,
            attachments=self._preview_attachments(session, selection),
        )
        if not persist:
            return (
                assembled.pack(
                    ContextPackId.make(0),
                    session,
                    self._ctx.provenance(workflow="context.preview"),
                    egress=EgressClass.NONE,
                ),
                assembled,
            )
        pack = self._store.write_context_pack(
            session,
            lambda pack_id: assembled.pack(
                pack_id,
                session,
                self._ctx.provenance(workflow="context.preview"),
                egress=EgressClass.NONE,
            ),
        )
        return pack, assembled

    def read_pack(self, session: ConversationSessionId, pack: ContextPackId) -> ContextPack:
        """One recorded receipt, so a researcher can explain what the model saw."""
        return self._store.read_context_pack(session, pack)

    def packs(self, session: ConversationSessionId) -> list[ContextPackId]:
        """Every pack recorded for a session, in order."""
        return self._store.list_context_packs(session)

    # -- sending -------------------------------------------------------------

    def send(
        self,
        session: ConversationSessionId,
        text: str,
        *,
        references: Sequence[str] = (),
        attachments: Sequence[SessionAttachmentId] = (),
        model: str | None = None,
        budget: ContextBudget | None = None,
        background: bool = True,
    ) -> SendStarted:
        """Append the message, write its pack, and stream the answer into a durable run."""
        return self.sender().start(
            session,
            text,
            references=references,
            attachments=attachments,
            model=model,
            budget=budget,
            background=background,
        )

    def stop(self, run_id: str) -> str:
        """Cancel a stream; whatever arrived is kept and the message is marked incomplete."""
        return self.sender().stop(run_id)

    def retry(
        self,
        message: MessageId,
        *,
        session: ConversationSessionId | None = None,
        model: str | None = None,
        background: bool = True,
    ) -> SendStarted:
        """Answer again as a new attempt; the failed one is kept exactly as it is."""
        return self.sender().retry(message, session=session, model=model, background=background)

    def outcome(self, run_id: str) -> SendOutcome:
        """How a send ended, from its durable run record."""
        return self.sender().outcome(run_id)

    def events(self, run_id: str, *, after: int = 0) -> list[tuple[str, dict[str, Any]]]:
        """The events a run has produced so far, in the order of plan SS0.4."""
        runs = RunStore(self._ctx.repo.layout.research_dir)
        return list(stream_events(runs, run_id, after=after))

    def wait(self, run_id: str, timeout: float = 30.0) -> bool:
        """Wait for a stream this process started; `True` when it finished."""
        return join_send(run_id, timeout)

    # -- promotion -----------------------------------------------------------

    def promote(
        self,
        request: PromotionRequest,
        *,
        claim: ClaimProposal | None = None,
        decision_type: DecisionType = DecisionType.OTHER,
        title: str | None = None,
    ) -> Promotion:
        """Copy an excerpt into reviewable research state; the message is untouched."""
        return PromotionService(self._ctx, store=self._store).promote(
            request, claim=claim, decision_type=decision_type, title=title
        )

    # -- composition ---------------------------------------------------------

    def assembler(self) -> ContextAssembler:
        """The context assembler, wired to the best retrieval source available."""
        return ContextAssembler(
            self._ctx.repo, self._store, sources=self.sources(), graph=self.graph()
        )

    def sender(self) -> SendService:
        """The send loop, sharing this service's store, assembler, and provider selector."""
        return SendService(
            self._ctx,
            store=self._store,
            assembler=self.assembler(),
            providers=self._providers,
            policy=self._egress_policy(),
        )

    def sources(self) -> tuple[ContextSource, ...]:
        """Retrieval sources in preference order: the graph, then the direct scan."""
        if self._sources is not None:
            return tuple(self._sources)
        graph = self.graph()
        scan = TranscriptScan(self._store)
        if graph is not None and graph_is_available(graph):
            return (GraphExcerpts(graph), scan)
        return (scan,)

    def graph(self) -> Any | None:
        """The ResearchGraph, when this build has one. A missing graph is not an error."""
        if self._graph is not None:
            return self._graph
        try:
            from research_harness.graph.service import ResearchGraph
        except ImportError:  # pragma: no cover - only without the projection extras
            return None
        self._graph = ResearchGraph(self._ctx.repo)
        return self._graph

    # -- internals -----------------------------------------------------------

    def _egress_policy(self) -> EgressPolicy:
        return self._policy if self._policy is not None else load_policy(self._ctx.repo)

    def _preview_selection(
        self, model: str | None, budget: ContextBudget | None
    ) -> Selection | None:
        """The provider a preview assembles against, or `None` when there is none.

        A workspace with no provider configured still previews: the pack then describes a
        call to nobody, which is the honest answer to "what would you send?".
        """
        if self._providers is None and not self._ctx.repo.config.providers:
            return None
        try:
            selector = self._providers or _default_selector()
            return selector.select(self._ctx, model=model, budget=budget or ContextBudget())
        except Exception as exc:  # a preview must work when sending would not
            logger.info("context.preview has no usable provider: %s", exc)
            return None

    def _preview_attachments(
        self, session: ConversationSessionId, selection: Selection | None
    ) -> AttachmentPlan | None:
        """What the attachment check would say, for a preview that sends nothing.

        A preview *reports* a blocked attachment rather than refusing it: seeing what would
        happen before it happens is the whole point (attachments design SS5).
        """
        if selection is None or selection.capabilities is None:
            return None
        from research_harness.conversation.attachments import (
            AttachmentService,
            receipt_items,
            sendability,
        )

        service = AttachmentService(self._store)
        tray = self._store.list_attachments(session)
        if not tray:
            return None
        check = sendability(
            tray,
            provider=selection.profile.provider,
            model=selection.profile.model,
            capabilities=selection.capabilities,
            policy=self._egress_policy(),
            alternatives=selection.alternatives,
            limits=service.limits,
        )
        included, omitted = receipt_items(check)
        return AttachmentPlan(included=included, omitted=omitted)


def _default_selector() -> ProviderSelector:
    from research_harness.conversation.send import WorkspaceProviders

    return WorkspaceProviders()

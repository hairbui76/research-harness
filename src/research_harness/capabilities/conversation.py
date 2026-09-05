"""The `session.*` and `context.*` capabilities (implementation plan SS0.4, Phase 18).

One rule shapes this module: conversation is *private working context*, so a host may not
write it. Reads are host-readable like every other read; every mutation is `MUTATE` and
therefore researcher-only, exactly like `note.add` — an agent host can be shown a
transcript, and cannot append to one, stop one, or promote out of one on the researcher's
behalf (Product 24, 29; ADR-007).

`session.send` is `long_running`: it persists the user's message, the `ContextPack`, and a
durable run *before* it answers, then streams on a worker thread. The caller gets ids it
can already read, and follows the answer on `GET /runs/{id}/events` rather than holding a
connection open (ADR-009).

Every service import is deferred into its handler, so importing the capability layer still
pulls in no provider and no projection engine (Gate P1), and the response models embed the
domain objects rather than restating them, so the wire cannot drift from the transcript.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import CapabilityRequest
from research_harness.capabilities.permissions import Permission
from research_harness.domain.conversation import (
    ContextPack,
    ConversationSession,
    Message,
    PromotionRequest,
    PromotionTarget,
    SessionAttachment,
    Visibility,
)
from research_harness.domain.enums import ClaimScope, ClaimType, DecisionType
from research_harness.domain.ids import (
    ClaimId,
    ContextPackId,
    ConversationSessionId,
    EvidenceId,
    MessageId,
    QuestionId,
    SessionAttachmentId,
)

if TYPE_CHECKING:  # imported lazily at runtime so this layer stays provider-free
    from research_harness.capabilities.registry import CapabilitySpec

__all__ = [
    "CONVERSATION_CAPABILITIES",
    "CONVERSATION_CAPABILITY_HANDLERS",
    "ConfigureSessionRequest",
    "ContextGetRequest",
    "ContextPackView",
    "ContextPreviewRequest",
    "CreateSessionRequest",
    "GetSessionRequest",
    "ListSessionsRequest",
    "PromoteMessageRequest",
    "PromotionView",
    "RenameSessionRequest",
    "RetryMessageRequest",
    "SearchSessionsRequest",
    "SendMessageRequest",
    "SendStarted",
    "SessionList",
    "SessionStopped",
    "SessionSummaryView",
    "SessionTranscript",
    "SessionView",
    "StopSendRequest",
    "SummarizeSessionRequest",
    "conversation_specs",
]

DEFAULT_PAGE_SIZE = 50


# -- requests ----------------------------------------------------------------


class CreateSessionRequest(CapabilityRequest):
    """`session.create`: open a durable conversation bound to this project.

    `visibility` defaults to `project`, the class that may reach the selected provider;
    `private` keeps the transcript on this machine and is asked for by name.
    """

    title: str
    visibility: Visibility = Visibility.PROJECT
    model: str | None = None
    """Default provider entry for this session, as `research.yaml` names it."""

    mode: str | None = None
    token_budget: int | None = Field(default=None, ge=0)


class RenameSessionRequest(CapabilityRequest):
    """`session.rename`: retitle a session. Ids and transcript are untouched."""

    session: ConversationSessionId
    title: str


class ConfigureSessionRequest(CapabilityRequest):
    """`session.configure`: bind a session to a runtime and model, or to an entry, or clear.

    Exactly one of `runtime`, `entry`, `clear`; `model` is required with `runtime`;
    `reasoning` is allowed only with `runtime`. Nothing is written to `research.yaml`.
    """

    session: ConversationSessionId
    runtime: str | None = None
    model: str | None = None
    reasoning: str | None = None
    entry: str | None = None
    clear: bool = False

    @model_validator(mode="after")
    def _exactly_one_target(self) -> ConfigureSessionRequest:
        if sum((self.runtime is not None, self.entry is not None, self.clear)) != 1:
            raise ValueError("give exactly one of runtime, entry, or clear")
        if self.runtime is not None and self.model is None:
            raise ValueError("model is required with runtime")
        if self.runtime is None and (self.model is not None or self.reasoning is not None):
            raise ValueError("model and reasoning are only for a runtime binding")
        return self


class ListSessionsRequest(CapabilityRequest):
    """`session.list`: every session in the project."""


class GetSessionRequest(CapabilityRequest):
    """`session.get`: one session's transcript, paginated oldest first."""

    session: ConversationSessionId
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=500)


class SearchSessionsRequest(CapabilityRequest):
    """`session.search`: sessions whose title or messages contain the query."""

    query: str
    limit: int = Field(default=20, ge=1, le=200)


class SummarizeSessionRequest(CapabilityRequest):
    """`session.summarize`: regenerate the derived `summary.md` from the transcript."""

    session: ConversationSessionId


class ContextPreviewRequest(CapabilityRequest):
    """`context.preview`: assemble a `ContextPack` without sending it."""

    session: ConversationSessionId
    text: str = ""
    references: tuple[str, ...] = ()
    model: str | None = None
    token_budget: int | None = Field(default=None, ge=1)
    persist: bool = True
    """Write the pack under `conversations/<id>/context/`; a dry run may say no."""


class ContextGetRequest(CapabilityRequest):
    """`context.get`: read a `Context used` receipt that was already recorded."""

    session: ConversationSessionId
    pack: ContextPackId


class SendMessageRequest(CapabilityRequest):
    """`session.send`: append a message and stream an answer into a durable run."""

    session: ConversationSessionId
    text: str
    references: tuple[str, ...] = ()
    attachments: tuple[SessionAttachmentId, ...] = ()
    model: str | None = None
    token_budget: int | None = Field(default=None, ge=1)


class StopSendRequest(CapabilityRequest):
    """`session.stop`: cancel a stream; the partial answer is kept and marked incomplete."""

    run_id: str


class RetryMessageRequest(CapabilityRequest):
    """`session.retry`: answer again as a new attempt, keeping the failed one."""

    message: MessageId
    session: ConversationSessionId | None = None
    model: str | None = None


class PromoteMessageRequest(CapabilityRequest):
    """`session.promote`: copy an excerpt into reviewable research state.

    ``target`` accepts the string ``"evidence"`` on purpose: the schema takes it so the
    refusal can explain itself, naming the anchor requirement instead of answering "not a
    valid enum value" (Product 42 M).
    """

    session: ConversationSessionId
    message: MessageId
    target: PromotionTarget | Literal["evidence", "evidence_candidate"]
    excerpt: str = ""
    """Defaults to the whole message text."""

    rationale: str | None = None
    question: QuestionId | None = None
    claim: ClaimId | None = None
    supporting_evidence: tuple[EvidenceId, ...] = ()
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    claim_type: ClaimType = ClaimType.DESCRIPTIVE
    scope: ClaimScope = ClaimScope.INDIVIDUAL
    corpus: str | None = None
    decision_type: DecisionType = DecisionType.OTHER
    title: str | None = None


# -- responses ---------------------------------------------------------------


class _View(BaseModel):
    """Frozen, closed read model; every transport sees the same JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SessionView(_View):
    """One session record, verbatim."""

    session: ConversationSession


class SessionList(_View):
    """Every session in the project, ordered by id."""

    count: int
    sessions: tuple[ConversationSession, ...] = ()


class SessionTranscript(_View):
    """One page of a transcript, with what is needed to resume the session."""

    session: ConversationSession
    messages: tuple[Message, ...] = ()
    attachments: tuple[SessionAttachment, ...] = ()
    context_packs: tuple[ContextPackId, ...] = ()
    total: int = 0
    offset: int = 0
    next_offset: int | None = None
    summary: str | None = None


class SessionMatchView(_View):
    """One session that matched a search, and the messages that matched inside it."""

    session: ConversationSessionId
    title: str
    title_matched: bool
    messages: tuple[MessageId, ...] = ()
    snippet: str | None = None
    updated_at: str


class SessionSearchResults(_View):
    """Search hits, most recently updated first."""

    count: int
    matches: tuple[SessionMatchView, ...] = ()


class SessionSummaryView(_View):
    """The derived summary, and how far it covers the transcript."""

    session: ConversationSessionId
    summary: str
    summarized_through: MessageId | None = None


class OmissionView(_View):
    """One thing the model did not see, and why. The receipt's "why not" line."""

    source: str
    context_class: str
    reason: str
    tokens: int = 0
    label: str | None = None
    detail: str | None = None


class DiscrepancyView(_View):
    """Where remembered conversation disagreed with accepted state, and what won."""

    accepted: str
    message: str
    detail: str


class ContextPackView(_View):
    """One `Context used` receipt: what was sent, what was not, and what it cost."""

    pack: ContextPack
    tokens: int = 0
    tokens_by_class: dict[str, int] = Field(default_factory=dict)
    omissions: tuple[OmissionView, ...] = ()
    discrepancies: tuple[DiscrepancyView, ...] = ()
    unresolved: tuple[str, ...] = ()


class SendStarted(_View):
    """What `session.send` answers with: durable ids, before a byte is streamed."""

    run_id: str
    session: ConversationSessionId
    assistant_message: MessageId
    context_pack: ContextPackId
    attempt: int
    user_message: MessageId | None = None
    unresolved: tuple[str, ...] = ()
    events: str = ""
    """Where the deltas are read: `GET /runs/{run_id}/events`."""


class SessionStopped(_View):
    """The state a cancelled run reached; the partial answer is already on disk."""

    run_id: str
    state: str


class PromotionView(_View):
    """What a promotion produced, and what still has to review it."""

    target: PromotionTarget
    session: ConversationSessionId
    message: MessageId
    object_id: str | None = None
    note_key: str | None = None
    accepted: bool = False
    review: str = ""
    decision: dict[str, Any] | None = None
    """The drafted, unaccepted Decision, for a decision candidate."""


# -- handlers ----------------------------------------------------------------


def create_session(ctx: CapabilityContext, request: CreateSessionRequest) -> SessionView:
    """`session.create`: open a session. `project` by default; `private` is asked for."""
    return SessionView(
        session=_service(ctx).create(
            request.title,
            visibility=request.visibility,
            model=request.model,
            mode=request.mode,
            token_budget=request.token_budget,
        )
    )


def rename_session(ctx: CapabilityContext, request: RenameSessionRequest) -> SessionView:
    """`session.rename`: a new title, and nothing else changes."""
    return SessionView(session=_service(ctx).rename(request.session, request.title))


def configure_session(ctx: CapabilityContext, request: ConfigureSessionRequest) -> SessionView:
    """`session.configure`: the binding changes, and nothing else does (binding spec §8)."""
    return SessionView(
        session=_service(ctx).configure(
            request.session,
            runtime=request.runtime,
            model=request.model,
            reasoning=request.reasoning,
            entry=request.entry,
            clear=request.clear,
        )
    )


def list_sessions(ctx: CapabilityContext, request: ListSessionsRequest) -> SessionList:
    """`session.list`: every session in this project."""
    del request
    sessions = _service(ctx).sessions()
    return SessionList(count=len(sessions), sessions=tuple(sessions))


def get_session(ctx: CapabilityContext, request: GetSessionRequest) -> SessionTranscript:
    """`session.get`: reopen a session with its transcript intact (Gate P18)."""
    service = _service(ctx)
    page = service.transcript(request.session, offset=request.offset, limit=request.limit)
    return SessionTranscript(
        session=page.session,
        messages=page.messages,
        attachments=page.attachments,
        context_packs=tuple(service.packs(request.session)),
        total=page.total,
        offset=page.offset,
        next_offset=page.next_offset,
        summary=page.summary,
    )


def search_sessions(ctx: CapabilityContext, request: SearchSessionsRequest) -> SessionSearchResults:
    """`session.search`: a direct transcript read, so it works without the projection."""
    matches = _service(ctx).search(request.query, limit=request.limit)
    return SessionSearchResults(
        count=len(matches),
        matches=tuple(
            SessionMatchView(
                session=match.session,
                title=match.title,
                title_matched=match.title_matched,
                messages=match.messages,
                snippet=match.snippet,
                updated_at=match.updated_at.isoformat(),
            )
            for match in matches
        ),
    )


def summarize_session(
    ctx: CapabilityContext, request: SummarizeSessionRequest
) -> SessionSummaryView:
    """`session.summarize`: regenerate the derived summary. No model call, ever."""
    service = _service(ctx)
    summary = service.summarize(request.session)
    record = service.store.get_session(request.session)
    return SessionSummaryView(
        session=record.id, summary=summary, summarized_through=record.summarized_through
    )


def preview_context(ctx: CapabilityContext, request: ContextPreviewRequest) -> ContextPackView:
    """`context.preview`: what would be sent, and what would be refused, without sending."""
    from research_harness.conversation.context import ContextBudget

    budget = None if request.token_budget is None else ContextBudget(total=request.token_budget)
    pack, _ = _service(ctx).preview(
        request.session,
        request.text,
        request.references,
        model=request.model,
        budget=budget,
        persist=request.persist,
    )
    return _pack_view(pack)


def get_context(ctx: CapabilityContext, request: ContextGetRequest) -> ContextPackView:
    """`context.get`: the receipt a past message names, in the shape `context.preview` returns.

    The pack is read from `conversations/<session>/context/`, which is durable: the answer
    survives deleting `.research/` and is the same one the researcher saw when the message
    was sent (Product 42 M).
    """
    return _pack_view(_service(ctx).read_pack(request.session, request.pack))


def send_message(ctx: CapabilityContext, request: SendMessageRequest) -> SendStarted:
    """`session.send`: append, assemble, and stream. Durable before it returns."""
    from research_harness.conversation.context import ContextBudget

    budget = None if request.token_budget is None else ContextBudget(total=request.token_budget)
    started = _service(ctx).send(
        request.session,
        request.text,
        references=request.references,
        attachments=request.attachments,
        model=request.model,
        budget=budget,
    )
    return SendStarted(
        run_id=started.run_id,
        session=started.session,
        assistant_message=started.assistant_message,
        context_pack=started.context_pack,
        attempt=started.attempt,
        user_message=started.user_message,
        unresolved=started.unresolved,
        events=f"/runs/{started.run_id}/events",
    )


def stop_send(ctx: CapabilityContext, request: StopSendRequest) -> SessionStopped:
    """`session.stop`: cancel the run; the partial answer is kept as incomplete."""
    return SessionStopped(run_id=request.run_id, state=_service(ctx).stop(request.run_id))


def retry_message(ctx: CapabilityContext, request: RetryMessageRequest) -> SendStarted:
    """`session.retry`: a new attempt naming the one it retries; nothing is deleted."""
    started = _service(ctx).retry(request.message, session=request.session, model=request.model)
    return SendStarted(
        run_id=started.run_id,
        session=started.session,
        assistant_message=started.assistant_message,
        context_pack=started.context_pack,
        attempt=started.attempt,
        user_message=started.user_message,
        unresolved=started.unresolved,
        events=f"/runs/{started.run_id}/events",
    )


def promote_message(ctx: CapabilityContext, request: PromoteMessageRequest) -> PromotionView:
    """`session.promote`: copy an excerpt into reviewable state; evidence is refused."""
    from research_harness.conversation.promote import ClaimProposal, PromotionService

    PromotionService.refuse_evidence(str(request.target))
    target = PromotionTarget(str(request.target))
    proposal = (
        ClaimProposal(
            subject=request.subject or "",
            predicate=request.predicate or "",
            object=request.object or "",
            claim_type=request.claim_type,
            scope=request.scope,
            corpus=request.corpus,
        )
        if target is PromotionTarget.CLAIM_CANDIDATE
        and request.subject
        and request.predicate
        and request.object
        else None
    )
    promotion = _service(ctx).promote(
        PromotionRequest(
            session=request.session,
            message=request.message,
            target=target,
            excerpt=request.excerpt or _message_text(ctx, request),
            rationale=request.rationale,
            question=request.question,
            claim=request.claim,
            supporting_evidence=request.supporting_evidence,
            provenance=ctx.provenance(workflow="session.promote"),
        ),
        claim=proposal,
        decision_type=request.decision_type,
        title=request.title,
    )
    return PromotionView(
        target=promotion.target,
        session=request.session,
        message=request.message,
        object_id=promotion.object_id,
        note_key=promotion.note_key,
        accepted=promotion.accepted,
        review=promotion.review,
        decision=(
            None if promotion.decision is None else promotion.decision.model_dump(mode="json")
        ),
    )


# -- registration ------------------------------------------------------------


CONVERSATION_CAPABILITY_HANDLERS: Mapping[str, Callable[[CapabilityContext, Any], Any]] = (
    MappingProxyType(
        {
            "session.create": create_session,
            "session.rename": rename_session,
            "session.configure": configure_session,
            "session.list": list_sessions,
            "session.get": get_session,
            "session.search": search_sessions,
            "session.summarize": summarize_session,
            "session.send": send_message,
            "session.stop": stop_send,
            "session.retry": retry_message,
            "session.promote": promote_message,
            "context.preview": preview_context,
            "context.get": get_context,
        }
    )
)

CONVERSATION_CAPABILITIES: tuple[str, ...] = tuple(CONVERSATION_CAPABILITY_HANDLERS)
"""The names this module contributes, for the registry's section table."""


def conversation_specs() -> list[CapabilitySpec]:
    """Every `session.*` and `context.*` capability, with its permission and schemas."""
    from research_harness.capabilities.registry import CapabilitySpec

    def spec(
        name: str,
        *,
        summary: str,
        semantics: str,
        permission: Permission,
        request_model: type[BaseModel],
        response_model: type[BaseModel],
        long_running: bool = False,
    ) -> CapabilitySpec:
        return CapabilitySpec(
            name=name,
            summary=summary,
            permission=permission,
            scientific_semantics=semantics,
            request_model=request_model,
            response_model=response_model,
            handler=CONVERSATION_CAPABILITY_HANDLERS[name],
            long_running=long_running,
        )

    private = "reads durable private working context; changes nothing"
    working = "writes private working context; creates no accepted scientific state"
    return [
        spec(
            "session.create",
            summary="Open a durable conversation session bound to this project.",
            semantics=working,
            permission=Permission.MUTATE,
            request_model=CreateSessionRequest,
            response_model=SessionView,
        ),
        spec(
            "session.rename",
            summary="Retitle a session; its ids and transcript are untouched.",
            semantics=working,
            permission=Permission.MUTATE,
            request_model=RenameSessionRequest,
            response_model=SessionView,
        ),
        spec(
            "session.configure",
            summary=(
                "Bind a session to a runtime and model, or to a research.yaml entry, or clear "
                "it; research.yaml is untouched."
            ),
            semantics=working,
            permission=Permission.MUTATE,
            request_model=ConfigureSessionRequest,
            response_model=SessionView,
        ),
        spec(
            "session.list",
            summary="Every conversation session in this project.",
            semantics=private,
            permission=Permission.READ,
            request_model=ListSessionsRequest,
            response_model=SessionList,
        ),
        spec(
            "session.get",
            summary="One session's transcript, attachments, and recorded receipts.",
            semantics=private,
            permission=Permission.READ,
            request_model=GetSessionRequest,
            response_model=SessionTranscript,
        ),
        spec(
            "session.search",
            summary="Sessions whose title or messages contain a query.",
            semantics=private,
            permission=Permission.READ,
            request_model=SearchSessionsRequest,
            response_model=SessionSearchResults,
        ),
        spec(
            "session.summarize",
            summary="Regenerate a session's derived summary from its transcript.",
            semantics=(
                "rewrites a derived summary of private working context; a summary never "
                "outranks the transcript, and neither outranks accepted state"
            ),
            permission=Permission.MUTATE,
            request_model=SummarizeSessionRequest,
            response_model=SessionSummaryView,
        ),
        spec(
            "session.send",
            summary="Send a message and stream the answer into a durable run.",
            semantics=(
                "appends to a private transcript and records what the model was shown; "
                "creates no accepted scientific state"
            ),
            permission=Permission.MUTATE,
            request_model=SendMessageRequest,
            response_model=SendStarted,
            long_running=True,
        ),
        spec(
            "session.stop",
            summary="Stop a streaming answer, keeping what already arrived.",
            semantics="cancels a run and marks the partial answer incomplete",
            permission=Permission.MUTATE,
            request_model=StopSendRequest,
            response_model=SessionStopped,
        ),
        spec(
            "session.retry",
            summary="Answer again as a new attempt, keeping the failed one.",
            semantics="adds a new model attempt; the failed attempt's record is kept",
            permission=Permission.MUTATE,
            request_model=RetryMessageRequest,
            response_model=SendStarted,
            long_running=True,
        ),
        spec(
            "session.promote",
            summary="Promote an excerpt to a note, question, claim, or decision candidate.",
            semantics=(
                "copies an excerpt into reviewable state with provenance to the session and "
                "message; the message is untouched, review is not bypassed, and evidence "
                "from prose is refused"
            ),
            permission=Permission.MUTATE,
            request_model=PromoteMessageRequest,
            response_model=PromotionView,
        ),
        spec(
            "context.preview",
            summary="Assemble the context a message would send, without sending it.",
            semantics="reads what would be packed and what would be refused; sends nothing",
            permission=Permission.READ,
            request_model=ContextPreviewRequest,
            response_model=ContextPackView,
        ),
        spec(
            "context.get",
            summary="Read the `Context used` receipt recorded for one past model call.",
            semantics=(
                "reads a stored receipt of private working context; the receipt is a record "
                "of what a model was shown and carries no scientific authority"
            ),
            permission=Permission.READ,
            request_model=ContextGetRequest,
            response_model=ContextPackView,
        ),
    ]


# -- helpers -----------------------------------------------------------------


def _service(ctx: CapabilityContext) -> Any:
    from research_harness.conversation.service import ConversationService

    return ConversationService(ctx)


def _message_text(ctx: CapabilityContext, request: PromoteMessageRequest) -> str:
    """The whole message, when the caller promoted without naming an excerpt."""
    from research_harness.workspace.conversations import ConversationStore

    store = ConversationStore.for_repository(ctx.repo)
    return store.get_message(request.session, request.message).text()


def _pack_view(pack: ContextPack) -> ContextPackView:
    """The receipt as a host reads it: the pack, plus the parts a UI groups by.

    Everything comes off the stored pack, so `context.preview` and `context.get` answer
    with the same object for the same receipt -- one assembled just now, one read back off
    disk.
    """
    return ContextPackView(
        pack=pack,
        tokens=pack.receipt.total_tokens(),
        tokens_by_class={
            context_class.value: tokens
            for context_class, tokens in pack.receipt.tokens_by_class().items()
        },
        omissions=tuple(
            OmissionView(
                source=item.source,
                context_class=item.context_class.value,
                reason=item.reason.value,
                tokens=item.tokens,
                label=item.label,
                detail=item.detail,
            )
            for item in pack.receipt.omitted
        ),
        discrepancies=tuple(
            DiscrepancyView(accepted=item.accepted, message=item.message, detail=item.detail)
            for item in pack.receipt.discrepancies
        ),
        unresolved=tuple(pack.receipt.unresolved),
    )

"""Sending one message: the durable run, the stream, and what survives an interruption.

`session.send` is a capability like any other, and the streaming is a *read* of the run it
starts (implementation plan SS3). The order below is the whole design, and every step is
durable before the next one begins:

1. the user's message is appended to the transcript, with a `ReferenceBlock` for every
   `@` token that resolved and the raw text kept for every one that did not;
2. the assistant's `M####` is *reserved*, so the events a client reads can name the
   message from the first delta;
3. the `ContextPack` is assembled and written, so `Context used` is readable before the
   answer exists, let alone after it;
4. a durable run is created, and only then does anything reach a provider;
5. every delta is persisted into the run before it is emitted, so a client that
   reconnects reads the same content it already saw;
6. the assistant message is appended exactly once -- complete, interrupted, or failed.

Step 6 is what "provider unavailability does not corrupt the session" means concretely: a
provider that never answers leaves a transcript that gained one user message and one
failed attempt record, and nothing else. A retry is a *new* message carrying a new attempt
that points back at the one it retries; the failed attempt is never rewritten or removed
(conversation design SS8).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from research_harness.capabilities.context import CapabilityContext
from research_harness.conversation.context import (
    AssembledContext,
    AttachmentPlan,
    ContextAssembler,
    ContextBudget,
    ProviderProfile,
    ResolvedReference,
)
from research_harness.domain.base import utc_now
from research_harness.domain.conversation import (
    AttemptStatus,
    AuthorityLabel,
    ConversationSession,
    EgressClass,
    Message,
    MessageAttempt,
    MessageRole,
    ModelIdentity,
    SessionDefaults,
    TextBlock,
    Visibility,
)
from research_harness.domain.errors import CapabilityError, ResearchHarnessError
from research_harness.domain.ids import (
    ContextPackId,
    ConversationSessionId,
    MessageId,
    SessionAttachmentId,
)
from research_harness.privacy.policy import EgressDeniedError, EgressPolicy, is_local_endpoint
from research_harness.providers.models.base import (
    ModelProvider,
    ModelRequirements,
    ProviderCapabilities,
    ProviderError,
)
from research_harness.providers.models.streaming import (
    DEFAULT_CHUNK_WORDS,
    StreamingModelProvider,
    chat_request,
    streaming_provider,
)
from research_harness.workflows.models import (
    Attempt,
    RunStatus,
    StageRecord,
    StageStatus,
    WorkflowRun,
    new_run_id,
)
from research_harness.workspace.conversations import ConversationStore
from research_harness.workspace.runs import RunNotFoundError, RunStore

__all__ = [
    "SEND_ROLE",
    "SEND_WORKFLOW",
    "STREAM_STAGE",
    "ProviderSelector",
    "ScriptedProviders",
    "Selection",
    "SendOutcome",
    "SendService",
    "SendStarted",
    "StreamState",
    "WorkspaceProviders",
    "join_send",
    "run_state",
    "stream_events",
]

logger = logging.getLogger(__name__)

SEND_WORKFLOW = "session.send"
SEND_WORKFLOW_VERSION = "1"
STREAM_STAGE = "stream"
INPUTS_STAGE = "inputs"
"""Checkpoint holding what the run is about, so a reader needs no other source."""
SEND_ROLE = "conversation"
"""The routing role a conversation turn asks for; entries may restrict themselves to it."""

DEFAULT_JOIN_TIMEOUT = 30.0
"""Seconds `join_send` waits for a stream started in this process."""

_THREADS: dict[str, threading.Thread] = {}
_THREADS_LOCK = threading.Lock()

#: Run status -> the `state` of the SSE contract (implementation plan SS0.4).
_SSE_STATE: Mapping[RunStatus, str] = {
    RunStatus.pending: "queued",
    RunStatus.running: "running",
    RunStatus.succeeded: "succeeded",
    RunStatus.failed: "failed",
    RunStatus.cancelled: "cancelled",
    RunStatus.interrupted: "incomplete",
}

TERMINAL_STATES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled", "incomplete"})
"""States that end an event stream. The four the Web client treats as final."""


def run_state(status: RunStatus | str) -> str:
    """The wire `state` for a durable run status."""
    if isinstance(status, str):
        status = RunStatus(status)
    return _SSE_STATE[status]


# -- what the run persists ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class StreamState:
    """The run checkpoint a streaming answer writes, and the event stream reads.

    Everything a reconnecting client needs is here: which message the deltas belong to,
    which attempt, which pack explains the call, every delta in order, and the terminal
    state with its error. It is written before each delta is emitted, so the stream can
    never be ahead of what is on disk.
    """

    message: str
    attempt: int
    context_pack: str | None = None
    state: str = "running"
    deltas: tuple[str, ...] = ()
    error: Mapping[str, Any] | None = None
    detail: str | None = None

    @property
    def text(self) -> str:
        """The answer so far."""
        return "".join(self.deltas)

    def with_delta(self, text: str) -> StreamState:
        return StreamState(
            message=self.message,
            attempt=self.attempt,
            context_pack=self.context_pack,
            state=self.state,
            deltas=(*self.deltas, text),
            error=self.error,
            detail=self.detail,
        )

    def finished(
        self, state: str, *, error: Mapping[str, Any] | None = None, detail: str | None = None
    ) -> StreamState:
        return StreamState(
            message=self.message,
            attempt=self.attempt,
            context_pack=self.context_pack,
            state=state,
            deltas=self.deltas,
            error=error,
            detail=detail,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "attempt": self.attempt,
            "context_pack": self.context_pack,
            "state": self.state,
            "deltas": list(self.deltas),
            "error": dict(self.error) if self.error else None,
            "detail": self.detail,
        }

    @classmethod
    def of(cls, payload: Mapping[str, Any] | None) -> StreamState | None:
        """Read a checkpoint back, or `None` when the run has not written one."""
        if not payload or not isinstance(payload.get("message"), str):
            return None
        deltas = payload.get("deltas")
        error = payload.get("error")
        return cls(
            message=str(payload["message"]),
            attempt=int(payload.get("attempt", 1)),
            context_pack=_optional(payload.get("context_pack")),
            state=str(payload.get("state", "running")),
            deltas=tuple(str(item) for item in deltas) if isinstance(deltas, list) else (),
            error=dict(error) if isinstance(error, dict) else None,
            detail=_optional(payload.get("detail")),
        )


@dataclass(frozen=True, slots=True)
class SendStarted:
    """What `session.send` answers with: durable ids, before a byte is streamed."""

    run_id: str
    session: ConversationSessionId
    assistant_message: MessageId
    context_pack: ContextPackId
    attempt: int
    user_message: MessageId | None = None
    unresolved: tuple[str, ...] = ()
    """Composer tokens that named nothing; kept as text in the message, and reported."""


@dataclass(frozen=True, slots=True)
class SendOutcome:
    """How a stream ended, once it has."""

    run_id: str
    session: ConversationSessionId
    assistant_message: MessageId
    context_pack: ContextPackId
    attempt: int
    state: str
    text: str = ""
    error: str | None = None
    user_message: MessageId | None = None


# -- provider selection ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Selection:
    """The backend one send will use, and how the pack must describe it.

    `capabilities` and `alternatives` are what the attachment pre-send check needs: what
    this model accepts, and which other configured model could take what it cannot, so a
    refusal can name a way forward instead of only a problem (attachments design SS5).
    """

    provider: StreamingModelProvider
    profile: ProviderProfile
    capabilities: ProviderCapabilities | None = None
    alternatives: tuple[tuple[str, ProviderCapabilities], ...] = ()


class ProviderSelector(Protocol):
    """How a send finds its backend. Configuration, never a branch in domain code."""

    def select(
        self,
        ctx: CapabilityContext,
        *,
        model: str | None,
        budget: ContextBudget,
        defaults: SessionDefaults | None = None,
    ) -> Selection:
        """The provider for this call, refusing before a request exists (Product 34)."""


class WorkspaceProviders:
    """The `providers:` table of `research.yaml`, under the project's egress policy.

    Selection happens *before* assembly, because the provider's egress class is what
    decides whether private material may be packed at all. A provider the policy refuses
    is never called and never selected: the refusal is raised here, where the researcher
    who asked can see it.
    """

    def select(
        self,
        ctx: CapabilityContext,
        *,
        model: str | None,
        budget: ContextBudget,
        defaults: SessionDefaults | None = None,
    ) -> Selection:
        from research_harness.conversation.binding import (
            EntryBinding,
            RuntimeBinding,
            binding_of,
            validation_sentence,
        )
        from research_harness.privacy.policy import load_policy
        from research_harness.privacy.traces import trace_writer_for
        from research_harness.providers.models.router import (
            ModelRouter,
            RouterConfig,
            RouterProviderConfig,
            build_router,
        )

        config = RouterConfig.model_validate({"providers": list(ctx.repo.config.providers)})
        # A per-message `model` wins; otherwise the session's binding; otherwise the
        # project default in priority order (binding spec §9).
        binding = None if model is not None or defaults is None else binding_of(defaults)
        wanted = model
        label: str | None = None
        if isinstance(binding, RuntimeBinding):
            # Validated exactly as the `research.yaml` entry it stands in for, so a record
            # whose runtime lost its bounded posture in a newer registry refuses with the
            # entry's own sentence rather than spawning.
            try:
                session_entry = RouterProviderConfig(
                    name=binding.label,
                    kind="local_cli",
                    runtime=binding.runtime,
                    model=binding.model,
                    reasoning=binding.reasoning,
                    priority=0,
                )
            except ValidationError as exc:
                raise CapabilityError(validation_sentence(exc)) from exc
            config = RouterConfig(providers=[*config.providers, session_entry])
            wanted = label = binding.label
        elif isinstance(binding, EntryBinding):
            wanted = binding.name
        if not config.providers and not isinstance(binding, EntryBinding):
            # An entry binding names something; "no provider named ..." below says which,
            # and an empty table is one way for that name to be gone (binding spec §9).
            raise CapabilityError(
                "no model providers configured: add a `providers:` list to research.yaml, "
                "or preview the context with `context.preview`"
            )
        policy = load_policy(ctx.repo)
        router = build_router(config, policy=policy)
        entries = [
            entry
            for entry in router.entries
            if wanted is None or wanted in entry.tags or entry.provider.name == wanted
        ]
        if not entries:
            known = ", ".join(sorted(item.name for item in config.providers if item.enabled))
            raise CapabilityError(
                f"no provider named {wanted!r} in research.yaml (have: {known or 'none'})"
            )
        narrowed = ModelRouter(entries, policy=policy)
        refusal = narrowed.egress_refusal()
        if refusal is not None:
            raise refusal
        entry = narrowed.select(_requirements(budget.total), SEND_ROLE)
        capabilities = entry.provider.capabilities()
        alternatives = tuple(
            (other.label, other.provider.capabilities())
            for other in router.entries
            if other is not entry
        )
        return Selection(
            capabilities=capabilities,
            alternatives=alternatives,
            provider=streaming_provider(
                entry.provider, model=entry.model, trace=trace_writer_for(ctx.repo)
            ),
            profile=ProviderProfile(
                # A session-bound answer is labelled `session:<runtime>` in the transcript,
                # the receipt and the run record; the trace keeps the adapter's own name,
                # because the trace writer records the adapter (plan ruling 2).
                provider=label or entry.provider.name,
                model=entry.model,
                egress=(
                    EgressClass.LOCAL
                    if is_local_endpoint(capabilities.egress.endpoint_host)
                    else EgressClass.EXTERNAL
                ),
                vision=capabilities.vision,
                max_context_tokens=capabilities.max_context_tokens,
            ),
        )


class ScriptedProviders:
    """One in-process provider, delivered in chunks: the offline and demo selector.

    The provider is a real adapter running the real contract, so a scripted send exercises
    exactly the loop a hosted one does -- including a multi-delta stream and an
    interruption part way through it.
    """

    def __init__(
        self,
        provider: ModelProvider,
        *,
        chunk_words: int = DEFAULT_CHUNK_WORDS,
        egress: EgressClass = EgressClass.LOCAL,
        vision: bool = False,
        model: str | None = None,
    ) -> None:
        self._provider = provider
        self._chunk_words = chunk_words
        self._egress = egress
        self._vision = vision
        self._model = model or str(getattr(provider, "model", "scripted-1"))

    def select(
        self,
        ctx: CapabilityContext,
        *,
        model: str | None,
        budget: ContextBudget,
        defaults: SessionDefaults | None = None,
    ) -> Selection:
        del ctx, model, budget, defaults
        return Selection(
            capabilities=self._provider.capabilities(),
            provider=streaming_provider(
                self._provider, chunk_words=self._chunk_words, model=self._model
            ),
            profile=ProviderProfile(
                provider=self._provider.name,
                model=self._model,
                egress=self._egress,
                vision=self._vision,
            ),
        )


# -- the service -------------------------------------------------------------


class SendService:
    """Appends a message, assembles its context, and streams the answer into a run."""

    def __init__(
        self,
        ctx: CapabilityContext,
        *,
        store: ConversationStore | None = None,
        assembler: ContextAssembler | None = None,
        providers: ProviderSelector | None = None,
        runs: RunStore | None = None,
        policy: EgressPolicy | None = None,
    ) -> None:
        self._ctx = ctx
        self._store = store or ConversationStore.for_repository(ctx.repo)
        self._assembler = assembler or ContextAssembler(ctx.repo, self._store)
        self._providers: ProviderSelector = providers or WorkspaceProviders()
        self._runs = runs or RunStore(ctx.repo.layout.research_dir)
        self._policy = policy

    # -- public API ----------------------------------------------------------

    def start(
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
        """Append the message, write its pack, and start the stream.

        Everything durable happens before this returns: a caller that gets a run id can
        already read the user's message and the `Context used` receipt, whatever the
        provider does next.
        """
        prepared = self._prepare(
            session,
            text,
            references=references,
            attachments=attachments,
            model=model,
            budget=budget,
        )
        self._launch(prepared, background=background)
        return prepared.started

    def retry(
        self,
        message: MessageId,
        *,
        session: ConversationSessionId | None = None,
        model: str | None = None,
        budget: ContextBudget | None = None,
        background: bool = True,
    ) -> SendStarted:
        """Answer again, as a new attempt that names the one it retries.

        The failed message stays exactly as it is. Its context is re-assembled rather than
        replayed, because the workspace may have moved on since it failed and a receipt
        must describe the call that was actually made.
        """
        failed, record = self._failed_message(message, session)
        prompt = self._prompt_for(failed, record)
        prepared = self._prepare(
            record,
            prompt.text,
            references=prompt.references,
            attachments=(),
            model=model,
            budget=budget,
            retry_of=failed,
            append_user_message=False,
        )
        self._launch(prepared, background=background)
        return prepared.started

    def stop(self, run_id: str) -> str:
        """Ask a stream to stop; the flag is durable and the partial answer is kept."""
        try:
            run = self._runs.request_cancel(run_id)
        except RunNotFoundError as exc:
            raise CapabilityError(f"session.stop: {exc}") from exc
        return run_state(run.status)

    def outcome(self, run_id: str) -> SendOutcome:
        """How a run ended (or where it is), read from its durable record."""
        run = self._runs.load(run_id)
        state = StreamState.of(self._runs.load_checkpoint(run_id, STREAM_STAGE))
        inputs = self._runs.load_checkpoint(run_id, INPUTS_STAGE) or {}
        if state is None or run.workflow != SEND_WORKFLOW:
            raise CapabilityError(f"run {run_id} is not a conversation send")
        return SendOutcome(
            run_id=run_id,
            session=ConversationSessionId(str(inputs.get("session"))),
            assistant_message=MessageId(state.message),
            context_pack=ContextPackId(str(state.context_pack or inputs.get("context_pack"))),
            attempt=state.attempt,
            state=state.state if state.state in TERMINAL_STATES else run_state(run.status),
            text=state.text,
            error=None if state.error is None else str(state.error.get("message")),
        )

    # -- preparation ---------------------------------------------------------

    def _prepare(
        self,
        session: ConversationSessionId,
        text: str,
        *,
        references: Sequence[str],
        attachments: Sequence[SessionAttachmentId],
        model: str | None,
        budget: ContextBudget | None,
        retry_of: Message | None = None,
        append_user_message: bool = True,
    ) -> _Prepared:
        record = self._store.get_session(session)
        allowance = budget or ContextBudget(
            total=record.defaults.token_budget or ContextBudget().total
        )
        selection = self._providers.select(
            self._ctx, model=model, budget=allowance, defaults=record.defaults
        )
        _refuse_private_egress(record, selection.profile)
        plan = self._attachment_plan(record.id, selection, attachments)
        resolved = self._assembler.resolve_references(references, text)

        user_message: Message | None = None
        if append_user_message:
            user_message = self._append_user_message(record.id, text, resolved, attachments)

        assistant_id = self._store.reserve_message_id(record.id)
        assembled = self._assembler.assemble(
            record.id,
            text,
            model=selection.profile,
            policy=self._policy,
            budget=allowance,
            resolved=resolved,
            attachments=plan,
        )
        pack = self._store.write_context_pack(
            record.id,
            lambda pack_id: assembled.pack(
                pack_id,
                record.id,
                self._ctx.provenance(workflow="session.send"),
                message=assistant_id,
            ),
        )
        attempt = 1 if retry_of is None else retry_of.attempt.number + 1
        run = self._create_run(
            record.id, assistant_id, pack.id, attempt, provider=selection.profile
        )
        state = StreamState(message=str(assistant_id), attempt=attempt, context_pack=str(pack.id))
        self._runs.save_checkpoint(run.run_id, STREAM_STAGE, state.as_dict())
        return _Prepared(
            started=SendStarted(
                run_id=run.run_id,
                session=record.id,
                assistant_message=assistant_id,
                context_pack=pack.id,
                attempt=attempt,
                user_message=None if user_message is None else user_message.id,
                unresolved=assembled.unresolved,
            ),
            assembled=assembled,
            selection=selection,
            state=state,
            visibility=record.visibility,
            retry_of=None if retry_of is None else retry_of.id,
        )

    def _attachment_plan(
        self,
        session: ConversationSessionId,
        selection: Selection,
        named: Sequence[SessionAttachmentId],
    ) -> AttachmentPlan | None:
        """Decide what the session's attachments may do on this call, before writing.

        A *ready* attachment the selected model cannot take refuses the whole send, with a
        reason per item and a compatible model named where there is one: an item that
        silently disappeared from a request is the failure the attachments design forbids
        (SS5, SS7). Items that were never ready are omitted and reported, and do not block.
        """
        from research_harness.conversation.attachments import (
            AttachmentService,
            receipt_items,
            sendability,
        )

        if selection.capabilities is None:
            return None
        service = AttachmentService(self._store)
        wanted = set(named)
        tray = [
            attachment
            for attachment in self._store.list_attachments(session)
            if not wanted or attachment.id in wanted
        ]
        if not tray:
            return None
        check = sendability(
            tray,
            provider=selection.profile.provider,
            model=selection.profile.model,
            capabilities=selection.capabilities,
            policy=self._policy,
            alternatives=selection.alternatives,
            limits=service.limits,
        )
        refusal = check.refusal()
        if refusal is not None:
            raise CapabilityError(f"session.send: {refusal}")
        included, omitted = receipt_items(check)
        return AttachmentPlan(
            included=included, omitted=omitted, inputs=tuple(service.inputs(session, check))
        )

    def _append_user_message(
        self,
        session: ConversationSessionId,
        text: str,
        resolved: Sequence[ResolvedReference],
        attachments: Sequence[SessionAttachmentId],
    ) -> Message:
        """The researcher's message: prose, plus one block per reference that resolved."""
        record = self._store.get_session(session)
        blocks: list[Any] = [TextBlock(text=text)]
        blocks.extend(block for block in (item.block() for item in resolved) if block is not None)
        return self._store.append_message(
            session,
            lambda message_id: Message(
                id=message_id,
                session=session,
                role=MessageRole.USER,
                blocks=tuple(blocks),
                authority=AuthorityLabel.PRIVATE,
                visibility=record.visibility,
                attachments=tuple(dict.fromkeys(attachments)),
                provenance=self._ctx.provenance(workflow="session.send"),
            ),
        )

    def _create_run(
        self,
        session: ConversationSessionId,
        message: MessageId,
        pack: ContextPackId,
        attempt: int,
        *,
        provider: ProviderProfile,
    ) -> WorkflowRun:
        """One durable run for one streamed answer, reusing the workflow run substrate."""
        now = utc_now()
        inputs = {
            "session": str(session),
            "message": str(message),
            "context_pack": str(pack),
            "attempt": attempt,
            "provider": provider.provider,
            "model": provider.model,
            "egress": provider.egress.value,
        }
        run = WorkflowRun(
            run_id=new_run_id(),
            workflow=SEND_WORKFLOW,
            workflow_version=SEND_WORKFLOW_VERSION,
            status=RunStatus.running,
            created_at=now,
            updated_at=now,
            inputs_fingerprint=_fingerprint(inputs),
            stages=[
                StageRecord(
                    name=STREAM_STAGE,
                    version=SEND_WORKFLOW_VERSION,
                    status=StageStatus.running,
                    attempts=[Attempt(number=attempt, started_at=now)],
                )
            ],
        )
        self._runs.create(run)
        self._runs.save_checkpoint(run.run_id, INPUTS_STAGE, inputs)
        return run

    # -- streaming -----------------------------------------------------------

    def _launch(self, prepared: _Prepared, *, background: bool) -> None:
        if not background:
            self._stream(prepared, self._store)
            return
        # The streaming thread outlives the call that started it, so it may not share the
        # caller's repository lock: `WorkspaceRepository.lock` is reentrant within one
        # repository object, and a thread that inherited it would write beside the request
        # instead of behind it. Its own store takes the workspace lock in its own right.
        thread = threading.Thread(
            target=self._stream,
            args=(prepared, ConversationStore(self._store.layout)),
            name=f"{SEND_WORKFLOW}:{prepared.started.run_id}",
            daemon=True,
        )
        with _THREADS_LOCK:
            _THREADS[prepared.started.run_id] = thread
        thread.start()

    def _stream(self, prepared: _Prepared, store: ConversationStore) -> SendOutcome:
        """Run the call, persisting every delta before it is emitted."""
        run_id = prepared.started.run_id
        state = prepared.state
        request = chat_request(
            instructions=_instructions(prepared.assembled),
            inputs=prepared.assembled.inputs,
            context_tokens=prepared.assembled.token_budget,
            role=SEND_ROLE,
            vision=prepared.selection.profile.vision,
            metadata={
                "session": str(prepared.started.session),
                "message": str(prepared.started.assistant_message),
                "context_pack": str(prepared.started.context_pack),
            },
        )
        error: Mapping[str, Any] | None = None
        final = "succeeded"
        try:
            for delta in prepared.selection.provider.stream(request):
                # Persist first, then look at the cancel flag: a delta the provider
                # already handed over was *received*, and an interruption preserves
                # received content (conversation design SS8). Stopping is prompt either
                # way -- the check happens before the next one is asked for.
                # A native stream ends with a terminal delta carrying only the model,
                # stop reason and usage; it adds no text, so it emits no `delta` event.
                if delta.text:
                    state = state.with_delta(delta.text)
                    self._runs.save_checkpoint(run_id, STREAM_STAGE, state.as_dict())
                if self._cancelled(run_id):
                    final = "cancelled"
                    break
        except (ProviderError, ResearchHarnessError) as exc:
            error = _error_body(exc)
            final = "incomplete" if state.text else "failed"
        except Exception as exc:
            # Whatever went wrong, the message is appended and the run reaches a terminal
            # state: a stream that vanished would leave a reserved id, a `running` run, and
            # a client waiting for a status that never comes.
            logger.exception("the %s stream for run %s failed unexpectedly", SEND_WORKFLOW, run_id)
            error = _error_body(exc)
            final = "incomplete" if state.text else "failed"
        state = state.finished(final, error=error)
        self._runs.save_checkpoint(run_id, STREAM_STAGE, state.as_dict())
        message = self._append_answer(prepared, state, store)
        self._close_run(run_id, final, error)
        return SendOutcome(
            run_id=run_id,
            session=prepared.started.session,
            assistant_message=message.id,
            context_pack=prepared.started.context_pack,
            attempt=prepared.started.attempt,
            state=final,
            text=state.text,
            error=None if error is None else str(error.get("message")),
            user_message=prepared.started.user_message,
        )

    def _append_answer(
        self, prepared: _Prepared, state: StreamState, store: ConversationStore
    ) -> Message:
        """Append the assistant message exactly once, however the stream ended."""
        status = {
            "succeeded": AttemptStatus.COMPLETE,
            "cancelled": AttemptStatus.INTERRUPTED,
            "incomplete": AttemptStatus.INTERRUPTED,
            "failed": AttemptStatus.FAILED,
        }[state.state]
        detail = None if state.error is None else str(state.error.get("message"))
        if status is AttemptStatus.INTERRUPTED and detail is None:
            detail = "the stream was stopped; the answer received so far was kept"
        blocks = (
            (TextBlock(text=state.text),) if state.text or status is AttemptStatus.COMPLETE else ()
        )
        message = Message(
            id=prepared.started.assistant_message,
            session=prepared.started.session,
            role=MessageRole.ASSISTANT,
            blocks=blocks,
            authority=AuthorityLabel.PRIVATE,
            visibility=prepared.visibility,
            context_pack=prepared.started.context_pack,
            model=ModelIdentity(
                provider=prepared.selection.profile.provider,
                model=prepared.selection.profile.model,
            ),
            attempt=MessageAttempt(
                number=prepared.started.attempt,
                status=status,
                retry_of=prepared.retry_of,
                error=detail if status is not AttemptStatus.COMPLETE else None,
                started_at=None,
                finished_at=utc_now(),
            ),
            provenance=self._ctx.provenance(workflow="session.send"),
        )
        return store.append_reserved_message(prepared.started.session, message)

    def _close_run(self, run_id: str, final: str, error: Mapping[str, Any] | None) -> None:
        """Write the terminal run record; the checkpoint already holds the content."""
        run = self._runs.load(run_id)
        run.status = {
            "succeeded": RunStatus.succeeded,
            "failed": RunStatus.failed,
            "cancelled": RunStatus.cancelled,
            "incomplete": RunStatus.interrupted,
        }[final]
        run.error = None if error is None else str(error.get("message"))
        run.updated_at = utc_now()
        stage = run.stages[0]
        stage.status = StageStatus.succeeded if final == "succeeded" else StageStatus.failed
        if stage.attempts:
            stage.attempts[-1] = stage.attempts[-1].finished(
                status=stage.status, at=run.updated_at, error=run.error
            )
        run.stages = [stage]
        self._runs.save(run)

    def _cancelled(self, run_id: str) -> bool:
        try:
            return self._runs.load(run_id).cancel_requested
        except RunNotFoundError:  # pragma: no cover - the run was created moments ago
            return False

    # -- retry helpers -------------------------------------------------------

    def _failed_message(
        self, message: MessageId, session: ConversationSessionId | None
    ) -> tuple[Message, ConversationSessionId]:
        found = (
            self._store.get_message(session, message)
            if session is not None
            else self._store.find_message(message)
        )
        if found is None:
            raise CapabilityError(f"session.retry: no message {message} in this workspace")
        if found.role is not MessageRole.ASSISTANT:
            raise CapabilityError(
                f"session.retry: {message} is a {found.role.value} message; a retry answers "
                "again, so it names the model message that failed"
            )
        if not found.incomplete:
            raise CapabilityError(f"session.retry: {message} completed; there is nothing to retry")
        return found, found.session

    def _prompt_for(self, failed: Message, session: ConversationSessionId) -> _Prompt:
        """The researcher's question behind a failed answer: the message before it."""
        previous: Message | None = None
        for message in self._store.iter_messages(session):
            if message.id == failed.id:
                break
            if message.role is MessageRole.USER:
                previous = message
        if previous is None:
            raise CapabilityError(
                f"session.retry: {failed.id} has no question before it to answer again"
            )
        from research_harness.domain.conversation import ReferenceBlock

        return _Prompt(
            text=previous.text(),
            references=tuple(
                str(block.target) for block in previous.blocks if isinstance(block, ReferenceBlock)
            ),
        )


@dataclass(frozen=True, slots=True)
class _Prompt:
    text: str
    references: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Prepared:
    """Everything the streaming step needs, all of it already durable."""

    started: SendStarted
    assembled: AssembledContext
    selection: Selection
    state: StreamState
    visibility: Visibility
    retry_of: MessageId | None = None


def join_send(run_id: str, timeout: float = DEFAULT_JOIN_TIMEOUT) -> bool:
    """Wait for a stream this process started; `True` when it finished.

    Only useful in the process that started the run -- the CLI, a test, an embedded
    daemon. A remote client waits by reading `GET /runs/{id}/events` instead, which is the
    point of persisting every delta.
    """
    with _THREADS_LOCK:
        thread = _THREADS.get(run_id)
    if thread is None:
        return False
    thread.join(timeout)
    finished = not thread.is_alive()
    if finished:
        with _THREADS_LOCK:
            _THREADS.pop(run_id, None)
    return finished


def stream_events(
    runs: RunStore, run_id: str, *, after: int = 0
) -> Iterator[tuple[str, dict[str, Any]]]:
    """The events a run has produced so far, in contract order (plan SS0.4).

    Pure: it reads the durable record and yields `(event, payload)` pairs. The transport
    decides how long to keep asking; this function never blocks and never sleeps.
    """
    run = runs.load(run_id)
    state = StreamState.of(runs.load_checkpoint(run_id, STREAM_STAGE))
    if state is None:
        return
    for index, text in enumerate(state.deltas):
        if index < after:
            continue
        yield (
            "delta",
            {"message_id": state.message, "attempt": state.attempt, "text": text},
        )
    if state.state in TERMINAL_STATES:
        if state.error is not None:
            yield ("error", dict(state.error))
        yield (
            "status",
            {
                "run_id": run_id,
                "state": state.state,
                "message_id": state.message,
                "attempt": state.attempt,
                "context_pack_id": state.context_pack,
                "detail": state.detail,
            },
        )
        return
    yield (
        "status",
        {
            "run_id": run_id,
            "state": run_state(run.status),
            "message_id": state.message,
            "attempt": state.attempt,
            "context_pack_id": state.context_pack,
            "detail": state.detail,
        },
    )


def _instructions(assembled: AssembledContext) -> str:
    """Policy plus the one sentence that says what to do with the pack."""
    return (
        f"{assembled.instructions}\n\n"
        "Answer the researcher's latest message. Use the context below; when it is not "
        "enough, say what is missing rather than inventing it."
    )


def _error_body(exc: Exception) -> dict[str, Any]:
    """The `error` event for a failure: a stable code, the message, and retryability."""
    from research_harness.providers.models.base import (
        ProviderAuthError,
        ProviderRateLimitError,
        ProviderTransportError,
    )

    if isinstance(exc, ProviderRateLimitError):
        code, retryable = "provider_rate_limited", True
    elif isinstance(exc, ProviderTransportError):
        code, retryable = "provider_unavailable", True
    elif isinstance(exc, ProviderAuthError):
        code, retryable = "provider_auth_failed", False
    elif isinstance(exc, ProviderError):
        code, retryable = "provider_error", True
    elif isinstance(exc, ResearchHarnessError):
        code, retryable = "capability_error", False
    else:
        code, retryable = "internal_error", False
    return {"code": code, "message": str(exc), "retryable": retryable}


def _fingerprint(inputs: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(inputs), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _refuse_private_egress(record: ConversationSession, profile: ProviderProfile) -> None:
    """Refuse an external send from a private session, before anything is written.

    A private session may not leave the workstation, so packing one for an external
    provider would send the policy text and nothing else -- a call that costs money, looks
    like an answer, and saw none of the question. Refusing says what to do instead, and
    `context.preview` still shows exactly what would and would not be sent.
    """
    if not profile.leaves_the_machine or record.visibility is not Visibility.PRIVATE:
        return
    raise EgressDeniedError(
        f"session {record.id} is private and {profile.provider}/{profile.model} is an "
        f"external provider, so nothing in this conversation may be sent to it "
        "(Product 34; workspace design SS7). Send it to a local provider, or make the "
        "session shareable with `research chat new --visibility project` on a new "
        "conversation.",
        provider=profile.provider,
        endpoint_host=profile.model,
        policy_fields=("visibility",),
    )


def _requirements(context_tokens: int) -> ModelRequirements:
    """What a conversation turn asks of a model: prose, and a window big enough to hold
    the pack that was budgeted."""
    return ModelRequirements(
        structured_output=True,
        context_tokens=max(context_tokens, 1),
        reasoning="medium",
    )


def _optional(value: Any) -> str | None:
    return None if value is None else str(value)

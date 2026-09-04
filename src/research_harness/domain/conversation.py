"""Conversation sessions, messages, attachments, and context packs (Product 39, 42 M-N).

A session is durable *working context*, not accepted scientific state. Everything in this
module is therefore built to be inspectable and promotable, never authoritative: a message
may not label its own content `accepted`, an attachment is session-only until an explicit
`Save to corpus`, and a `ContextPack` records exactly what a model was shown -- including
what it was *not* shown, and why.

The vocabularies live here rather than in `domain/enums.py` because they belong to the
conversation subsystem (implementation plan v1.1 SS0.3); `domain/graph.py` reuses
`AuthorityLabel` and `Visibility` from this module so the two layers cannot drift apart.

No provider, host, or vendor concept appears here (Product P9). `ModelIdentity.provider`
is an opaque adapter label, and `EgressClass` says how far content travelled without
naming who received it.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from research_harness.domain.base import (
    CanonicalObject,
    DomainModel,
    NonEmptyStr,
    Sha256,
    TrackedObject,
    UtcDatetime,
)
from research_harness.domain.errors import TransitionError
from research_harness.domain.ids import (
    ArtifactId,
    ClaimId,
    ContextPackId,
    ConversationSessionId,
    EvidenceId,
    MessageId,
    QuestionId,
    ResearchId,
    SessionAttachmentId,
    VersionId,
    WorkId,
)

__all__ = [
    "ATTACHMENT_TRANSITIONS",
    "CONTEXT_ORDER",
    "STORED_ATTACHMENT_STATES",
    "AttachmentBlock",
    "AttachmentState",
    "AttemptStatus",
    "AuthorityLabel",
    "ClassBudget",
    "ContentBlock",
    "ContentBlockKind",
    "ContextClass",
    "ContextDiscrepancy",
    "ContextItem",
    "ContextPack",
    "ContextReceipt",
    "ConversationSession",
    "EgressClass",
    "Message",
    "MessageAttempt",
    "MessageRole",
    "ModelIdentity",
    "OmissionReason",
    "OmittedContextItem",
    "PromotionRequest",
    "PromotionTarget",
    "ReferenceBlock",
    "SessionAttachment",
    "SessionDefaults",
    "TextBlock",
    "Visibility",
    "allowed_attachment_transitions",
    "transition_attachment",
]


# ---------------------------------------------------------------------------
# vocabularies
# ---------------------------------------------------------------------------


class AuthorityLabel(StrEnum):
    """How much authority a referenced object carries (workspace design SS3).

    `accepted` is reserved for reviewed scientific state. Conversation content is
    `private` working context; a promotion produces a `candidate`.
    """

    ACCEPTED = "accepted"
    CANDIDATE = "candidate"
    QUALIFIED = "qualified"
    CONTESTED = "contested"
    STALE = "stale"
    PRIVATE = "private"


class Visibility(StrEnum):
    """Whether an object may leave the machine at all under the egress policy."""

    PRIVATE = "private"
    """Never leaves this workstation unless the policy explicitly allows it."""
    PROJECT = "project"
    """May reach the selected provider when the project's egress policy permits it."""


class MessageRole(StrEnum):
    """Who authored a transcript entry."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class AttachmentState(StrEnum):
    """Lifecycle of a session attachment (attachments design SS2)."""

    SELECTED = "selected"
    VALIDATING = "validating"
    READY = "ready"
    SENDING = "sending"
    SESSION_ONLY = "session_only"
    PROMOTING = "promoting"
    IN_CORPUS = "in_corpus"
    FAILED = "failed"


class ContextClass(StrEnum):
    """The kind of material an item in a `ContextPack` came from."""

    POLICY = "policy"
    ACCEPTED_STATE = "accepted_state"
    CURRENT_SESSION = "current_session"
    PRIOR_SESSIONS = "prior_sessions"
    ATTACHMENTS = "attachments"
    CORPUS_BLOCKS = "corpus_blocks"
    DISCOVERY = "discovery"


#: Assembly order of workspace design SS6: policy first, accepted scientific state before
#: any conversational memory, and discovery last. The assembler fills the budget in this
#: order, which is what makes "accepted state outranks chat" a mechanical property.
CONTEXT_ORDER: tuple[ContextClass, ...] = (
    ContextClass.POLICY,
    ContextClass.ACCEPTED_STATE,
    ContextClass.CURRENT_SESSION,
    ContextClass.PRIOR_SESSIONS,
    ContextClass.ATTACHMENTS,
    ContextClass.CORPUS_BLOCKS,
    ContextClass.DISCOVERY,
)


class OmissionReason(StrEnum):
    """Why an item the researcher might expect did not reach the model."""

    TOKEN_BUDGET = "token_budget"
    PRIVACY_POLICY = "privacy_policy"
    EGRESS_BLOCKED = "egress_blocked"
    UNSUPPORTED_MEDIA = "unsupported_media"
    STALE = "stale"
    LOW_RELEVANCE = "low_relevance"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    CONFLICTS_WITH_ACCEPTED = "conflicts_with_accepted"


class PromotionTarget(StrEnum):
    """What a promoted message or selection becomes (conversation design SS6).

    There is deliberately no Evidence member: evidence needs an artifact and an exact
    resolvable anchor, so it is created through the evidence capabilities and never from
    prose alone.
    """

    NOTE = "note"
    QUESTION = "question"
    CLAIM_CANDIDATE = "claim_candidate"
    DECISION_CANDIDATE = "decision_candidate"


class EgressClass(StrEnum):
    """How far the assembled context actually travelled (Product 34).

    The domain never names a provider; the class says only whether content left this
    workstation.
    """

    NONE = "none"
    """Assembled but not sent -- a `context.preview`."""
    LOCAL = "local"
    """Sent to an endpoint on this workstation; nothing left the machine."""
    EXTERNAL = "external"
    """Sent to a provider off this workstation under the project's egress policy."""


class AttemptStatus(StrEnum):
    """How one model attempt ended (conversation design SS8)."""

    COMPLETE = "complete"
    INTERRUPTED = "interrupted"
    """The stream was stopped; whatever arrived is kept and flagged incomplete."""
    FAILED = "failed"


class ContentBlockKind(StrEnum):
    """Discriminator of the message content union."""

    TEXT = "text"
    REFERENCE = "reference"
    ATTACHMENT = "attachment"


# ---------------------------------------------------------------------------
# content blocks
# ---------------------------------------------------------------------------


class TextBlock(DomainModel):
    """Prose exactly as written or received.

    Mathematics stays inside the text: TeX (`$x^2$`, `\\[ ... \\]`) is never split into a
    separate block and never normalized, so what the renderer receives is byte-for-byte
    what the transcript holds.
    """

    kind: Literal[ContentBlockKind.TEXT] = ContentBlockKind.TEXT
    text: str


class ReferenceBlock(DomainModel):
    """A structured reference to a stable id, as produced by an `@` composer token.

    The reference stores the *resolved* target rather than the text the researcher typed,
    so a transcript never depends on re-parsing prose to know what was meant.
    """

    kind: Literal[ContentBlockKind.REFERENCE] = ContentBlockKind.REFERENCE
    target: ResearchId
    label: str | None = None
    """Display text at the time of writing; never authoritative for the target's name."""
    locator: str | None = None
    """Sub-object locator of the deep link (`page=6&block=B0081`, `line=120`)."""
    authority: AuthorityLabel | None = None
    """Authority of the target when the reference was written, for later comparison."""


class AttachmentBlock(DomainModel):
    """An attachment placed in the flow of a message."""

    kind: Literal[ContentBlockKind.ATTACHMENT] = ContentBlockKind.ATTACHMENT
    attachment: SessionAttachmentId
    caption: str | None = None


ContentBlock = Annotated[TextBlock | ReferenceBlock | AttachmentBlock, Field(discriminator="kind")]
"""One piece of message content. Hidden model reasoning is never a block: the harness
neither asks for it nor stores it (Product 20.5)."""


# ---------------------------------------------------------------------------
# model metadata
# ---------------------------------------------------------------------------


class ModelIdentity(DomainModel):
    """Which model answered, in provider-neutral terms (Product 20.5).

    `provider` is the adapter's own name and `model` the model it served; the domain
    treats both as opaque labels and never branches on their values.
    """

    provider: NonEmptyStr
    model: NonEmptyStr
    request_fingerprint: str | None = None


# ---------------------------------------------------------------------------
# sessions and messages
# ---------------------------------------------------------------------------


RUNTIME_PROVIDER_PREFIX = "local_cli:"
"""A `defaults.model` whose provider starts with this names a runtime binding (spec §7)."""


class SessionDefaults(DomainModel):
    """What a new message in this session uses unless the composer overrides it."""

    model: ModelIdentity | None = None
    mode: str | None = None
    """Opaque composer mode label (a role or task preset), never interpreted here."""
    token_budget: int | None = Field(default=None, ge=0)
    reasoning: str | None = None
    """The runtime's own effort name for a runtime binding; `None` otherwise."""

    @model_validator(mode="after")
    def _reasoning_needs_a_runtime_binding(self) -> SessionDefaults:
        # The one shape rule the domain enforces (binding spec §7): what runtimes, models
        # and effort names exist is decided by the capability and routing layers.
        if self.reasoning is not None and not (
            self.model is not None and self.model.provider.startswith(RUNTIME_PROVIDER_PREFIX)
        ):
            raise ValueError("reasoning is only for a runtime binding (provider local_cli:<id>)")
        return self


class ConversationSession(CanonicalObject):
    """A durable, private conversation bound to one project (Product 39).

    Deriving from `CanonicalObject` fixes the record *shape* -- schema version, stable id,
    timestamps, provenance -- and says nothing about scientific authority: a session is
    working context, is excluded from Git publication by default, and never outranks
    accepted Evidence, Claims, or Decisions (Product 8.2).

    The counters (`message_count`, `last_message`) are part of the durable record so the
    next `M####` can be allocated without reading every transcript, and so a workspace
    whose `.research/` was deleted still knows where it was.
    """

    id: ConversationSessionId
    title: NonEmptyStr
    visibility: Visibility = Visibility.PRIVATE
    defaults: SessionDefaults = SessionDefaults()
    message_count: int = Field(default=0, ge=0)
    last_message: MessageId | None = None
    last_message_at: UtcDatetime | None = None
    summarized_through: MessageId | None = None
    """Last message the derived `summary.md` covers; a summary never covers more."""
    summary_updated_at: UtcDatetime | None = None
    reserved_messages: tuple[MessageId, ...] = ()
    """`M####` handed out for a streaming answer that has not been appended yet.

    A streamed message must have its id *before* its content exists: the events a client
    reads name the message every delta belongs to, so a reservation is written here, is
    durable, and is excluded from the next allocation. It is released when the message is
    appended -- complete, interrupted, or failed. A process that dies mid-stream leaves an
    unused id, which costs a gap in the numbering and nothing else; ids must be unique,
    not consecutive.
    """

    @model_validator(mode="after")
    def _counters_agree(self) -> ConversationSession:
        if (self.message_count == 0) != (self.last_message is None):
            raise ValueError("message_count and last_message must both be set or both be empty")
        if (self.last_message is None) != (self.last_message_at is None):
            raise ValueError("last_message and last_message_at must be recorded together")
        if self.summarized_through is not None and self.summary_updated_at is None:
            raise ValueError("a summary that covers a message must record when it was written")
        if len(set(self.reserved_messages)) != len(self.reserved_messages):
            raise ValueError("a message id is reserved at most once")
        return self


class MessageAttempt(DomainModel):
    """One model attempt behind a message (conversation design SS8).

    A retry is a *new* message carrying a new attempt that points back at the failed one,
    so the failed attempt's metadata survives instead of being overwritten.
    """

    number: int = Field(default=1, ge=1)
    status: AttemptStatus = AttemptStatus.COMPLETE
    retry_of: MessageId | None = None
    error: str | None = None
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None

    @property
    def incomplete(self) -> bool:
        """True when the content is partial: the attempt was interrupted or failed."""
        return self.status is not AttemptStatus.COMPLETE

    @model_validator(mode="after")
    def _attempt_is_self_consistent(self) -> MessageAttempt:
        if self.status is AttemptStatus.FAILED and not self.error:
            raise ValueError("a failed attempt must record why it failed")
        if (self.number > 1) != (self.retry_of is not None):
            raise ValueError("a retry must name the attempt it retries, and only a retry may")
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("an attempt cannot finish before it started")
        return self


class Message(CanonicalObject):
    """One transcript entry: role, content blocks, and what produced them.

    Chat is working context, never accepted state, so `authority` may not be `accepted`
    (workspace design SS3). Promotion is the only path from a message to research state,
    and it copies rather than moves: the message is never rewritten or deleted.
    """

    id: MessageId
    session: ConversationSessionId
    role: MessageRole
    blocks: tuple[ContentBlock, ...] = ()
    authority: AuthorityLabel = AuthorityLabel.PRIVATE
    visibility: Visibility = Visibility.PRIVATE
    attachments: tuple[SessionAttachmentId, ...] = ()
    """Every attachment this message carries, whether or not a block places it inline."""
    context_pack: ContextPackId | None = None
    """The `Context used` receipt for the call that produced this message."""
    model: ModelIdentity | None = None
    attempt: MessageAttempt = MessageAttempt()

    @property
    def incomplete(self) -> bool:
        """True when the content is partial (an interrupted or failed attempt)."""
        return self.attempt.incomplete

    def text(self) -> str:
        """The message's prose, blocks joined by a blank line. Math is left untouched."""
        return "\n\n".join(block.text for block in self.blocks if isinstance(block, TextBlock))

    @model_validator(mode="after")
    def _chat_is_never_accepted_state(self) -> Message:
        if self.authority is AuthorityLabel.ACCEPTED:
            raise ValueError(
                "a message is working context and cannot be labelled accepted; promote it "
                "to a Note, Question, Claim candidate, or Decision candidate instead"
            )
        return self

    @model_validator(mode="after")
    def _content_matches_the_attempt(self) -> Message:
        if not self.blocks and not self.attempt.incomplete:
            raise ValueError("a completed message must carry at least one content block")
        return self

    @model_validator(mode="after")
    def _attachments_are_indexed(self) -> Message:
        if len(set(self.attachments)) != len(self.attachments):
            raise ValueError("a message must not list the same attachment twice")
        placed = {block.attachment for block in self.blocks if isinstance(block, AttachmentBlock)}
        missing = sorted(placed - set(self.attachments))
        if missing:
            raise ValueError(f"attachment blocks reference unlisted attachments: {missing}")
        return self

    @model_validator(mode="after")
    def _only_a_model_answer_has_a_non_trivial_attempt(self) -> Message:
        if self.role is MessageRole.USER and (
            self.attempt.incomplete or self.attempt.retry_of is not None
        ):
            raise ValueError("a user message is not a model attempt and cannot fail or retry")
        return self


# ---------------------------------------------------------------------------
# attachments
# ---------------------------------------------------------------------------

#: States that imply the bytes are durably stored in the session and hashed.
STORED_ATTACHMENT_STATES: frozenset[AttachmentState] = frozenset(
    {
        AttachmentState.READY,
        AttachmentState.SENDING,
        AttachmentState.SESSION_ONLY,
        AttachmentState.PROMOTING,
        AttachmentState.IN_CORPUS,
    }
)

ATTACHMENT_TRANSITIONS: Mapping[AttachmentState, frozenset[AttachmentState]] = MappingProxyType(
    {
        AttachmentState.SELECTED: frozenset({AttachmentState.VALIDATING, AttachmentState.FAILED}),
        AttachmentState.VALIDATING: frozenset({AttachmentState.READY, AttachmentState.FAILED}),
        # `Save to corpus` is offered from the composer, transcript, viewer, and inspector
        # (attachments design SS6), so a ready attachment promotes without being sent first.
        AttachmentState.READY: frozenset(
            {
                AttachmentState.SENDING,
                AttachmentState.SESSION_ONLY,
                AttachmentState.PROMOTING,
                AttachmentState.FAILED,
            }
        ),
        AttachmentState.SENDING: frozenset({AttachmentState.SESSION_ONLY, AttachmentState.FAILED}),
        AttachmentState.SESSION_ONLY: frozenset(
            {AttachmentState.SENDING, AttachmentState.PROMOTING, AttachmentState.FAILED}
        ),
        AttachmentState.PROMOTING: frozenset({AttachmentState.IN_CORPUS, AttachmentState.FAILED}),
        # The corpus copy is immutable and identity-resolved; there is no way back.
        AttachmentState.IN_CORPUS: frozenset(),
        # A failure keeps the session copy, so the operation that failed is retryable.
        AttachmentState.FAILED: frozenset(
            {AttachmentState.VALIDATING, AttachmentState.SENDING, AttachmentState.PROMOTING}
        ),
    }
)


class SessionAttachment(CanonicalObject):
    """A file attached to a session: working material, never corpus state.

    An attachment gets its `SA####` identity as soon as it is durably copied into the
    session directory. Being sent to a model, previewed, or read does not give it
    Work/Version/Artifact identity: only an explicit `Save to corpus` does, and the
    resulting ids are recorded here so the session copy and the corpus copy stay linked.
    """

    id: SessionAttachmentId
    session: ConversationSessionId
    state: AttachmentState = AttachmentState.SELECTED
    filename: NonEmptyStr
    """Display metadata from the intake, never a trusted path (attachments design SS8)."""
    media_type: NonEmptyStr
    size_bytes: int = Field(default=0, ge=0)
    content_hash: Sha256 | None = None
    page_count: int | None = Field(default=None, ge=1)
    description: str | None = None
    """Researcher-supplied alt text or description, kept apart from scientific reading."""
    visibility: Visibility = Visibility.PRIVATE
    failure_reason: str | None = None
    """Why the last operation failed; kept after a retry so the history stays readable."""
    work: WorkId | None = None
    version: VersionId | None = None
    artifact: ArtifactId | None = None

    @model_validator(mode="after")
    def _state_matches_the_record(self) -> SessionAttachment:
        if self.state in STORED_ATTACHMENT_STATES and self.content_hash is None:
            raise ValueError(f"an attachment in {self.state.value!r} must record its content hash")
        if self.state is AttachmentState.FAILED and not self.failure_reason:
            raise ValueError("a failed attachment must record why it failed")
        corpus = (self.work, self.version, self.artifact)
        if self.state is AttachmentState.IN_CORPUS:
            if any(value is None for value in corpus):
                raise ValueError(
                    "an attachment in the corpus must link its Work, Version, and Artifact"
                )
        elif any(value is not None for value in corpus):
            raise ValueError(
                "corpus links belong to an attachment that reached in_corpus; "
                "a promotion that has not finished links nothing"
            )
        return self


def allowed_attachment_transitions() -> Mapping[str, frozenset[str]]:
    """The attachment transition table as plain strings, for UIs and capability discovery."""
    return MappingProxyType(
        {
            str(source): frozenset(str(target) for target in targets)
            for source, targets in ATTACHMENT_TRANSITIONS.items()
        }
    )


def transition_attachment(
    attachment: SessionAttachment, to_state: AttachmentState, **updates: Any
) -> SessionAttachment:
    """Move an attachment to ``to_state``, applying ``updates`` in the same step.

    Raises `TransitionError` for any move outside `ATTACHMENT_TRANSITIONS`; the fields a
    state requires (a content hash, a failure reason, the corpus links) are then enforced
    by the schema, so an illegal state and an incomplete one both fail loudly.
    """
    allowed = ATTACHMENT_TRANSITIONS.get(attachment.state, frozenset())
    if to_state not in allowed:
        options = ", ".join(sorted(str(state) for state in allowed)) or "none"
        raise TransitionError(
            f"attachment: {attachment.state} -> {to_state} is not allowed (allowed: {options})"
        )
    return attachment.touch(state=to_state, **updates)


# ---------------------------------------------------------------------------
# context packs
# ---------------------------------------------------------------------------


class ContextItem(DomainModel):
    """One piece of material that reached the model, with where it came from."""

    context_class: ContextClass
    source: NonEmptyStr
    """Pointer to the material: a deep link (`rh://claim/C0041`) or a workspace path."""
    id: ResearchId | None = None
    """Stable id when the material has one; policy text and derived summaries have none."""
    authority: AuthorityLabel = AuthorityLabel.PRIVATE
    label: str | None = None
    tokens: int = Field(default=0, ge=0)


class OmittedContextItem(ContextItem):
    """One piece of material that did *not* reach the model, and why.

    `tokens` is what including it would have cost, so a receipt can explain a budget
    decision rather than merely assert it.
    """

    reason: OmissionReason
    detail: str | None = None


class ClassBudget(DomainModel):
    """Tokens allocated to one context class before assembly started."""

    context_class: ContextClass
    tokens: int = Field(ge=0)


class ContextDiscrepancy(DomainModel):
    """One place where remembered conversation disagreed with accepted state.

    Recorded on the receipt rather than only returned to the caller that assembled the
    pack, because the disagreement is the *reason* a passage is missing: a receipt read
    back a week later has to answer "what did the model see, and what did it not" without
    reassembling anything (Product 42 M).
    """

    accepted: NonEmptyStr
    """Stable id of the accepted object that won."""

    message: NonEmptyStr
    """Source pointer of the passage that was left out."""

    detail: NonEmptyStr


class ContextReceipt(DomainModel):
    """What a model was shown and what it was not (conversation design SS5).

    A source pointer appears at most once, and never in both lists: a receipt that both
    included and omitted the same material would not be an explanation.

    `discrepancies` and `unresolved` are the two facts a bare included/omitted pair cannot
    carry: which accepted object outranked a remembered passage, and which `@` token named
    nothing this workspace holds. Both default to empty, so a pack written before they
    existed still validates.
    """

    included: tuple[ContextItem, ...] = ()
    omitted: tuple[OmittedContextItem, ...] = ()
    discrepancies: tuple[ContextDiscrepancy, ...] = ()
    unresolved: tuple[str, ...] = ()
    """Composer tokens that resolved to nothing, in the order they were written."""

    def total_tokens(self) -> int:
        """Tokens spent on included material."""
        return sum(item.tokens for item in self.included)

    def tokens_by_class(self) -> Mapping[ContextClass, int]:
        """Tokens spent per context class, in the order the classes were assembled."""
        spent = dict.fromkeys(CONTEXT_ORDER, 0)
        for item in self.included:
            spent[item.context_class] = spent.get(item.context_class, 0) + item.tokens
        return MappingProxyType({name: value for name, value in spent.items() if value})

    def omissions_by_reason(self) -> Mapping[OmissionReason, tuple[OmittedContextItem, ...]]:
        """Omitted material grouped by reason, for the receipt's "why not" section."""
        grouped: dict[OmissionReason, list[OmittedContextItem]] = {}
        for item in self.omitted:
            grouped.setdefault(item.reason, []).append(item)
        return MappingProxyType({key: tuple(value) for key, value in grouped.items()})

    @model_validator(mode="after")
    def _every_source_appears_once(self) -> ContextReceipt:
        included = [item.source for item in self.included]
        omitted = [item.source for item in self.omitted]
        for name, sources in (("included", included), ("omitted", omitted)):
            duplicates = sorted({value for value in sources if sources.count(value) > 1})
            if duplicates:
                raise ValueError(f"{name} context repeats a source pointer: {duplicates}")
        both = sorted(set(included) & set(omitted))
        if both:
            raise ValueError(f"context is both included and omitted: {both}")
        repeated = sorted({token for token in self.unresolved if self.unresolved.count(token) > 1})
        if repeated:
            raise ValueError(f"unresolved repeats a reference token: {repeated}")
        return self


class ContextPack(CanonicalObject):
    """The context assembled for one model call, plus its `Context used` receipt.

    The pack is written whether or not the call was made: `context.preview` assembles one
    with `egress = none`, which is how a researcher inspects what *would* be sent.
    """

    id: ContextPackId
    session: ConversationSessionId
    receipt: ContextReceipt
    message: MessageId | None = None
    """The message this pack produced, once there is one."""
    model: ModelIdentity | None = None
    egress: EgressClass = EgressClass.NONE
    token_budget: int | None = Field(default=None, ge=0)
    budgets: tuple[ClassBudget, ...] = ()

    def budget_for(self, context_class: ContextClass) -> int | None:
        """Tokens allocated to ``context_class``, or ``None`` when it was not budgeted."""
        for budget in self.budgets:
            if budget.context_class is context_class:
                return budget.tokens
        return None

    @model_validator(mode="after")
    def _spending_stays_inside_the_budget(self) -> ContextPack:
        classes = [budget.context_class for budget in self.budgets]
        if len(set(classes)) != len(classes):
            raise ValueError("a context class is budgeted at most once")
        spent = self.receipt.tokens_by_class()
        for budget in self.budgets:
            used = spent.get(budget.context_class, 0)
            if used > budget.tokens:
                raise ValueError(
                    f"context class {budget.context_class.value!r} used {used} tokens of the "
                    f"{budget.tokens} it was allocated"
                )
        total = self.receipt.total_tokens()
        if self.token_budget is not None and total > self.token_budget:
            raise ValueError(
                f"the pack used {total} tokens of the {self.token_budget} it was allocated"
            )
        return self


# ---------------------------------------------------------------------------
# promotion
# ---------------------------------------------------------------------------


class PromotionRequest(TrackedObject):
    """A request to turn part of a message into reviewable research state (design SS6).

    Promotion copies: the original message is neither deleted nor rewritten, and the
    result is a Note, a Question, or a *candidate* Claim or Decision that still follows
    the existing review workflow. Evidence has no target here because evidence needs an
    artifact and an exact anchor, which prose does not have.
    """

    session: ConversationSessionId
    message: MessageId
    target: PromotionTarget
    excerpt: NonEmptyStr
    """The promoted text, copied from the message exactly as it was written."""
    rationale: str | None = None
    question: QuestionId | None = None
    """The research question this promotion answers or extends, when there is one."""
    claim: ClaimId | None = None
    """The claim a decision candidate is about (an epistemic override, for example)."""
    supporting_evidence: tuple[EvidenceId, ...] = ()

    @model_validator(mode="after")
    def _links_match_the_target(self) -> PromotionRequest:
        if self.claim is not None and self.target is not PromotionTarget.DECISION_CANDIDATE:
            raise ValueError("only a decision candidate is promoted about a claim")
        if self.supporting_evidence and self.target not in {
            PromotionTarget.CLAIM_CANDIDATE,
            PromotionTarget.DECISION_CANDIDATE,
        }:
            raise ValueError(
                "supporting evidence belongs to a claim or decision candidate; a note or "
                "question carries none"
            )
        if len(set(self.supporting_evidence)) != len(self.supporting_evidence):
            raise ValueError("a promotion must not cite the same evidence twice")
        return self

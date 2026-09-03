"""Assembling one model call's context, and the receipt that explains it.

The order is fixed by the workspace design (SS6) and by :data:`CONTEXT_ORDER`: policy,
accepted scientific state, the current session, relevant prior sessions, attachments,
corpus blocks, discovery. Filling the budget in that order is what makes "accepted state
outranks chat" a *mechanical* property rather than a promise -- the accepted objects are
already packed by the time conversational memory is considered.

Three rules decide what does not go:

* **Privacy first.** Private sessions and messages are removed before anything is scored
  or packed whenever the selected provider's egress class is external. A local provider
  may receive them: privacy is about what leaves the workstation, not about what the
  researcher may read (Product 34).
* **Accepted state wins a conflict.** When a remembered message contradicts an accepted
  Decision or Claim it references, the accepted object is included and the message is
  omitted as `conflicts_with_accepted`. The disagreement is not silently dropped: it is
  reported as a :class:`Discrepancy` for the inspector.
* **Budget by class.** Every class gets an allocation up front; an item that does not fit
  is omitted as `token_budget` with the tokens it would have cost, so the receipt can
  explain the decision rather than assert it.

Token counting is one deterministic function, :func:`estimate_tokens`. It is an estimate
and says so; the point is that the same pack always reports the same numbers, so two
receipts can be compared.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from research_harness.conversation.retrieval import (
    DEFAULT_EXCERPT_LIMIT,
    MIN_RELEVANCE,
    ContextSource,
    Excerpt,
    relevance,
    terms,
)
from research_harness.domain.base import Provenance
from research_harness.domain.conversation import (
    CONTEXT_ORDER,
    AttachmentState,
    AuthorityLabel,
    ClassBudget,
    ContextClass,
    ContextDiscrepancy,
    ContextItem,
    ContextPack,
    ContextReceipt,
    ConversationSession,
    EgressClass,
    Message,
    MessageRole,
    ModelIdentity,
    OmissionReason,
    OmittedContextItem,
    ReferenceBlock,
    SessionAttachment,
    Visibility,
)
from research_harness.domain.enums import ClaimStatus, DecisionStatus, EvidenceStatus, StaleState
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.ids import (
    ArtifactId,
    ClaimId,
    ContextPackId,
    ConversationSessionId,
    DecisionId,
    EvidenceId,
    MessageId,
    QuestionId,
    ResearchId,
    WorkId,
    parse_id,
)
from research_harness.privacy.policy import EgressPolicy
from research_harness.providers.models.base import InputEnvelope
from research_harness.workspace.conversations import ConversationNotFoundError, ConversationStore
from research_harness.workspace.repository import ObjectNotFoundError, WorkspaceRepository

__all__ = [
    "CHARS_PER_TOKEN",
    "CONTRADICTION_CUES",
    "DEFAULT_SHARES",
    "DEFAULT_TOKEN_BUDGET",
    "POLICY_TEXT",
    "AssembledContext",
    "AttachmentPlan",
    "ContextAssembler",
    "ContextBudget",
    "Discrepancy",
    "ProviderProfile",
    "ResolvedReference",
    "estimate_tokens",
    "reference_tokens",
]

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4
"""The estimator's divisor. An estimate, and named as one; determinism is the property."""

CLASS_TOKEN_FLOOR: Mapping[ContextClass, int] = MappingProxyType(
    {
        ContextClass.POLICY: 8,
        ContextClass.ACCEPTED_STATE: 16,
        ContextClass.CURRENT_SESSION: 8,
        ContextClass.PRIOR_SESSIONS: 8,
        ContextClass.ATTACHMENTS: 16,
        ContextClass.CORPUS_BLOCKS: 16,
        ContextClass.DISCOVERY: 8,
    }
)
"""Per-class floor: an item never costs nothing, because sending it never costs nothing."""

DEFAULT_TOKEN_BUDGET = 8000
"""Tokens a call packs when neither the session nor the caller names a budget."""

DEFAULT_SHARES: Mapping[ContextClass, float] = MappingProxyType(
    {
        ContextClass.POLICY: 0.05,
        ContextClass.ACCEPTED_STATE: 0.35,
        ContextClass.CURRENT_SESSION: 0.30,
        ContextClass.PRIOR_SESSIONS: 0.15,
        ContextClass.ATTACHMENTS: 0.05,
        ContextClass.CORPUS_BLOCKS: 0.05,
        ContextClass.DISCOVERY: 0.05,
    }
)
"""Where the budget goes. Accepted state is the largest share on purpose (design SS4)."""

POLICY_TEXT = (
    "You are answering inside a research workspace. Accepted Evidence, Claims, Decisions, "
    "and source anchors outrank anything remembered from conversation: when they disagree, "
    "follow the accepted object and say that it does. Conversation is working context, not "
    "accepted scientific state. Do not present a conclusion as evidence: evidence needs an "
    "artifact and an exact anchor, and a claim, question, or decision becomes research "
    "state only through an explicit, reviewed promotion. Cite the stable ids you were "
    "given (W####, E####, C####, D####, RQ####) when you rely on them."
)
"""The task policy, packed first. It is instruction, not scientific state (Product 39)."""

CONTRADICTION_CUES: tuple[str, ...] = (
    "actually",
    "disagree",
    "ignore",
    "incorrect",
    "instead",
    "is wrong",
    "no longer",
    "not true",
    "override",
    "overrule",
    "supersede",
    "that's wrong",
    "was wrong",
)
"""Phrases that mark a message as arguing *against* something it references.

Deliberately a small, explicit list. A conflict detector that guessed would either hide
chat the researcher wanted or quietly promote a heuristic into an authority rule; this one
can be read, argued with, and extended in one place.
"""

MAX_LOW_RELEVANCE_REPORTED = 5
"""How many near-miss objects a receipt names. Enough to explain, not a second corpus."""

_ID_TOKEN = re.compile(r"@?\b((?:CS|SA|CP|RQ|SR|A|B|C|D|E|M|S|V|W)\d{4,}(?:-\d+)?)\b")


def estimate_tokens(text: str, context_class: ContextClass) -> int:
    """Estimated tokens for ``text`` in ``context_class``: characters / 4, never below the
    class floor.

    One function, used by every class and by the receipt, so a pack's numbers are
    reproducible and two receipts are comparable. It is not a tokenizer and does not
    pretend to be one.
    """
    length = len(text)
    estimate = -(-length // CHARS_PER_TOKEN)
    if length == 0:
        return 0
    return max(CLASS_TOKEN_FLOOR.get(context_class, 8), estimate)


def reference_tokens(text: str) -> tuple[str, ...]:
    """Every stable id mentioned in ``text``, with or without a leading `@`, in order."""
    seen: dict[str, None] = {}
    for match in _ID_TOKEN.finditer(text):
        seen.setdefault(match.group(1), None)
    return tuple(seen)


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """The selected provider, in the terms a `ContextPack` records.

    `egress` is the fact that decides privacy: `external` means content leaves this
    workstation, `local` means it does not, and `none` is a preview that sends nothing.
    """

    provider: str = "(none)"
    model: str = "(none)"
    egress: EgressClass = EgressClass.NONE
    vision: bool = False
    max_context_tokens: int | None = None

    @property
    def leaves_the_machine(self) -> bool:
        """True when packing for this provider is an act of disclosure."""
        return self.egress is EgressClass.EXTERNAL

    def identity(self) -> ModelIdentity | None:
        """The provider/model pair as the transcript records it, or `None` for a preview."""
        if self.egress is EgressClass.NONE and self.provider == "(none)":
            return None
        return ModelIdentity(provider=self.provider, model=self.model)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """The token budget and how it is divided between context classes."""

    total: int = DEFAULT_TOKEN_BUDGET
    shares: Mapping[ContextClass, float] = DEFAULT_SHARES

    def allocations(self) -> tuple[ClassBudget, ...]:
        """Tokens per class, in `CONTEXT_ORDER`; the remainder goes to accepted state."""
        allocated = {
            context_class: int(self.total * self.shares.get(context_class, 0.0))
            for context_class in CONTEXT_ORDER
        }
        spare = self.total - sum(allocated.values())
        allocated[ContextClass.ACCEPTED_STATE] += max(spare, 0)
        return tuple(
            ClassBudget(context_class=context_class, tokens=allocated[context_class])
            for context_class in CONTEXT_ORDER
        )


@dataclass(frozen=True, slots=True)
class AttachmentPlan:
    """What the attachment pre-send check decided, ready to be packed and sent.

    Built by `session.send` (and by a preview that knows its provider) from
    `conversation.attachments.sendability`, so the receipt's attachment lines and the
    request's media parts are two views of one decision rather than two rules that could
    disagree. An assembly given no plan falls back to describing the tray, which is what a
    preview on a workspace with no provider can honestly say.
    """

    included: tuple[ContextItem, ...] = ()
    omitted: tuple[OmittedContextItem, ...] = ()
    inputs: tuple[InputEnvelope, ...] = ()


Discrepancy = ContextDiscrepancy
"""One place where remembered conversation disagrees with accepted state.

The name assembly has always used, kept as an alias now that the record is a domain
object written into the receipt: a `Context used` read back later carries the
disagreement, not merely the gap it left (Product 42 M).
"""


@dataclass(frozen=True, slots=True)
class ResolvedReference:
    """One `@` composer token, resolved (or not) at send time."""

    token: str
    target: ResearchId | None = None
    label: str | None = None
    authority: AuthorityLabel = AuthorityLabel.PRIVATE
    source: str | None = None
    text: str = ""
    kind: str = "unknown"
    detail: str | None = None

    @property
    def resolved(self) -> bool:
        return self.target is not None

    def block(self) -> ReferenceBlock | None:
        """The structured composer block for this token, or `None` when it did not resolve."""
        if self.target is None:
            return None
        return ReferenceBlock(target=self.target, label=self.label, authority=self.authority)


@dataclass(frozen=True, slots=True)
class AssembledContext:
    """One assembled pack, before it has an id.

    A `ContextPack` is a stored object whose `CP####` is allocated inside the workspace
    lock, so assembly cannot mint one; :meth:`pack` builds the stored object once the store
    hands over an id.
    """

    receipt: ContextReceipt
    budgets: tuple[ClassBudget, ...]
    token_budget: int
    profile: ProviderProfile
    instructions: str
    inputs: tuple[InputEnvelope, ...] = ()
    references: tuple[ResolvedReference, ...] = ()
    discrepancies: tuple[Discrepancy, ...] = ()

    @property
    def unresolved(self) -> tuple[str, ...]:
        """Composer tokens that named nothing this workspace holds."""
        return tuple(item.token for item in self.references if not item.resolved)

    def pack(
        self,
        pack_id: ContextPackId,
        session: ConversationSessionId,
        provenance: Provenance,
        *,
        message: MessageId | None = None,
        egress: EgressClass | None = None,
    ) -> ContextPack:
        """The stored `ContextPack` for this assembly.

        ``egress`` overrides what the pack records travelled. A preview passes
        `EgressClass.NONE` -- it assembles against the provider it *would* use, so the
        receipt shows what that provider would have been refused, and then records that
        nothing was actually sent (see `ContextPack`).
        """
        return ContextPack(
            id=pack_id,
            session=session,
            receipt=self.receipt,
            message=message,
            model=self.profile.identity(),
            egress=self.profile.egress if egress is None else egress,
            token_budget=self.token_budget,
            budgets=self.budgets,
            provenance=provenance,
        )


class _Packer:
    """Fills one class's allocation, recording what fitted and what did not."""

    def __init__(self, budgets: Sequence[ClassBudget]) -> None:
        self._remaining = {budget.context_class: budget.tokens for budget in budgets}
        self.included: list[tuple[int, ContextItem]] = []
        self.omitted: list[OmittedContextItem] = []
        self.texts: dict[str, str] = {}
        self._sources: set[str] = set()

    def adopt(self, item: ContextItem) -> ContextItem | None:
        """Pack an item another subsystem already decided on, if its class has room.

        The attachment check owns what may be sent and what it costs, so its verdict is
        packed verbatim; the budget still applies, because the budget is the pack's.
        """
        if item.source in self._sources:
            return None
        if item.tokens > self._remaining.get(item.context_class, 0):
            self.drop(
                item.context_class,
                source=item.source,
                reason=OmissionReason.TOKEN_BUDGET,
                tokens=item.tokens,
                identity=item.id,
                authority=item.authority,
                label=item.label,
                detail=f"{item.tokens} tokens did not fit the {item.context_class.value} budget",
            )
            return None
        self._remaining[item.context_class] -= item.tokens
        self._sources.add(item.source)
        self.included.append((0, item))
        return item

    def adopt_omission(self, item: OmittedContextItem) -> None:
        """Record an omission another subsystem decided, with its own reason."""
        if item.source in self._sources:
            return
        self._sources.add(item.source)
        self.omitted.append(item)

    def offer(
        self,
        context_class: ContextClass,
        *,
        source: str,
        text: str,
        identity: ResearchId | None = None,
        authority: AuthorityLabel = AuthorityLabel.PRIVATE,
        label: str | None = None,
        rank: int = 0,
    ) -> ContextItem | None:
        """Include one item when its class still has room; else omit it as `token_budget`.

        ``rank`` orders the item *inside* its class for reading. It is separate from the
        order items are offered in, because the two differ where it matters: the current
        session is offered newest first, so the budget drops the oldest turn, and then read
        oldest first, because that is how a conversation reads.
        """
        if source in self._sources:
            return None
        cost = estimate_tokens(text, context_class)
        if cost > self._remaining.get(context_class, 0):
            self.drop(
                context_class,
                source=source,
                reason=OmissionReason.TOKEN_BUDGET,
                tokens=cost,
                identity=identity,
                authority=authority,
                label=label,
                detail=(
                    f"{cost} tokens did not fit the {self._remaining.get(context_class, 0)} "
                    f"left in the {context_class.value} budget"
                ),
            )
            return None
        self._remaining[context_class] -= cost
        item = ContextItem(
            context_class=context_class,
            source=source,
            id=identity,
            authority=authority,
            label=label,
            tokens=cost,
        )
        self._sources.add(source)
        self.texts[source] = text
        self.included.append((rank, item))
        return item

    def drop(
        self,
        context_class: ContextClass,
        *,
        source: str,
        reason: OmissionReason,
        tokens: int = 0,
        identity: ResearchId | None = None,
        authority: AuthorityLabel = AuthorityLabel.PRIVATE,
        label: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Record one omission. A source already spoken for is never recorded twice."""
        if source in self._sources:
            return
        self._sources.add(source)
        self.omitted.append(
            OmittedContextItem(
                context_class=context_class,
                source=source,
                id=identity,
                authority=authority,
                label=label,
                tokens=tokens,
                reason=reason,
                detail=detail,
            )
        )

    def receipt(
        self,
        *,
        discrepancies: Sequence[ContextDiscrepancy] = (),
        unresolved: Sequence[str] = (),
    ) -> ContextReceipt:
        """The receipt for what was packed: `CONTEXT_ORDER`, then each class's own order.

        ``discrepancies`` and ``unresolved`` are recorded on the receipt itself so a stored
        pack explains itself without being reassembled (`context.get`).
        """
        order = {context_class: index for index, context_class in enumerate(CONTEXT_ORDER)}
        included = sorted(
            enumerate(self.included),
            key=lambda entry: (order.get(entry[1][1].context_class, 99), entry[1][0], entry[0]),
        )
        return ContextReceipt(
            included=tuple(item for _, (_, item) in included),
            omitted=tuple(self.omitted),
            discrepancies=tuple(discrepancies),
            unresolved=tuple(unresolved),
        )


class ContextAssembler:
    """Builds one `ContextPack` for one draft, under a token and privacy budget."""

    def __init__(
        self,
        repo: WorkspaceRepository,
        store: ConversationStore,
        *,
        sources: Sequence[ContextSource] = (),
        graph: Any | None = None,
    ) -> None:
        self._repo = repo
        self._store = store
        self._sources = tuple(sources)
        self._graph = graph

    # -- entry point ---------------------------------------------------------

    def assemble(
        self,
        session: ConversationSessionId,
        draft: str,
        references: Sequence[str] = (),
        *,
        model: ProviderProfile | None = None,
        policy: EgressPolicy | None = None,
        budget: ContextBudget | None = None,
        resolved: Sequence[ResolvedReference] | None = None,
        attachments: AttachmentPlan | None = None,
    ) -> AssembledContext:
        """Assemble the context for ``draft`` in ``session``, in `CONTEXT_ORDER`.

        ``resolved`` is the already-resolved composer tokens, so a caller that had to
        resolve them earlier -- `session.send` writes them into the user message before it
        assembles anything -- resolves each reference exactly once.
        """
        profile = model or ProviderProfile()
        rules = policy or EgressPolicy()
        record = self._store.get_session(session)
        allowance = budget or ContextBudget(
            total=record.defaults.token_budget or DEFAULT_TOKEN_BUDGET
        )
        budgets = allowance.allocations()
        packer = _Packer(budgets)

        resolved = (
            tuple(resolved) if resolved is not None else self.resolve_references(references, draft)
        )
        query = terms(draft)
        query.extend(term for item in resolved for term in terms(item.token))

        packer.offer(
            ContextClass.POLICY,
            source="policy://conversation/task",
            text=self.instructions(),
            label="task policy",
        )
        accepted = self._pack_accepted_state(packer, resolved, query, profile, rules)
        discrepancies = self._pack_current_session(packer, record, profile, accepted)
        discrepancies += self._pack_prior_sessions(packer, record, draft, query, profile, accepted)
        self._pack_attachments(packer, record, profile, attachments)
        self._pack_corpus_blocks(packer, resolved, profile, rules)
        self._pack_discovery(packer, query, profile)

        receipt = packer.receipt(
            discrepancies=discrepancies,
            unresolved=[item.token for item in resolved if not item.resolved],
        )
        return AssembledContext(
            receipt=receipt,
            budgets=budgets,
            token_budget=allowance.total,
            profile=profile,
            instructions=self.instructions(),
            inputs=(
                *self._inputs(receipt, packer),
                *(() if attachments is None else attachments.inputs),
            ),
            references=resolved,
            discrepancies=discrepancies,
        )

    def instructions(self) -> str:
        """The policy text this assembler packs. One place, so a receipt can quote it."""
        return POLICY_TEXT

    # -- classes -------------------------------------------------------------

    def _pack_accepted_state(
        self,
        packer: _Packer,
        references: Sequence[ResolvedReference],
        query: Sequence[str],
        profile: ProviderProfile,
        rules: EgressPolicy,
    ) -> dict[str, ContextItem]:
        """Referenced objects first, then whatever the draft is lexically about.

        Returns the accepted objects that made it in, keyed by id, because the conflict
        rule below needs to know which accepted object won.
        """
        packed: dict[str, ContextItem] = {}
        for reference in references:
            if reference.target is None:
                packer.drop(
                    ContextClass.ACCEPTED_STATE,
                    source=f"reference://{reference.token}",
                    reason=OmissionReason.UNRESOLVED_REFERENCE,
                    label=reference.token,
                    detail=reference.detail or f"{reference.token} names nothing in this workspace",
                )
                continue
            if reference.source is None or not reference.text:
                continue
            item = packer.offer(
                ContextClass.ACCEPTED_STATE,
                source=reference.source,
                text=reference.text,
                identity=reference.target,
                authority=reference.authority,
                label=reference.label,
            )
            if item is not None:
                packed[str(reference.target)] = item

        near_misses: list[tuple[float, str, str, ResearchId, AuthorityLabel]] = []
        for identity, label, text, authority, stale, source in self._accepted_objects():
            if source in packed:
                continue
            score = relevance(query, f"{label}\n{text}")
            if score < MIN_RELEVANCE:
                if score > 0:
                    near_misses.append((score, source, label, identity, authority))
                continue
            if stale:
                packer.drop(
                    ContextClass.ACCEPTED_STATE,
                    source=source,
                    reason=OmissionReason.STALE,
                    identity=identity,
                    authority=AuthorityLabel.STALE,
                    label=label,
                    detail=(
                        "marked stale by a dependency change; reference it explicitly to "
                        "send it anyway"
                    ),
                )
                continue
            if profile.leaves_the_machine and not rules.allow_source_text:
                packer.drop(
                    ContextClass.ACCEPTED_STATE,
                    source=source,
                    reason=OmissionReason.PRIVACY_POLICY,
                    identity=identity,
                    authority=authority,
                    label=label,
                    detail="privacy.allow_source_text is false for this project",
                )
                continue
            item = packer.offer(
                ContextClass.ACCEPTED_STATE,
                source=source,
                text=f"{label}\n{text}",
                identity=identity,
                authority=authority,
                label=label,
            )
            if item is not None:
                packed[str(identity)] = item

        for score, source, label, identity, authority in sorted(near_misses, reverse=True)[
            :MAX_LOW_RELEVANCE_REPORTED
        ]:
            packer.drop(
                ContextClass.ACCEPTED_STATE,
                source=source,
                reason=OmissionReason.LOW_RELEVANCE,
                identity=identity,
                authority=authority,
                label=label,
                detail=f"relevance {score:.2f} is below the {MIN_RELEVANCE} threshold",
            )
        return packed

    def _pack_current_session(
        self,
        packer: _Packer,
        record: ConversationSession,
        profile: ProviderProfile,
        accepted: Mapping[str, ContextItem],
    ) -> tuple[Discrepancy, ...]:
        """The active transcript, newest first until the class budget is spent.

        Recency, not relevance: the thread the researcher is in the middle of is the
        context, and a message the budget cannot hold is the *oldest* one.
        """
        messages = [
            message
            for message in self._store.iter_messages(record.id)
            if message.text().strip() and message.role is not MessageRole.SYSTEM
        ]
        discrepancies: list[Discrepancy] = []
        selected: list[Message] = []
        for message in reversed(messages):
            source = f"rh://session/{record.id}?message={message.id}"
            blocked = self._privacy_refusal(record, message, profile)
            if blocked is not None:
                packer.drop(
                    ContextClass.CURRENT_SESSION,
                    source=source,
                    reason=blocked[0],
                    identity=message.id,
                    label=message.role.value,
                    detail=blocked[1],
                )
                continue
            conflict = self._conflict(message.text(), _message_references(message), accepted)
            if conflict is not None:
                winner, detail = conflict
                packer.drop(
                    ContextClass.CURRENT_SESSION,
                    source=source,
                    reason=OmissionReason.CONFLICTS_WITH_ACCEPTED,
                    identity=message.id,
                    label=message.role.value,
                    detail=detail,
                )
                discrepancies.append(Discrepancy(accepted=winner, message=source, detail=detail))
                continue
            selected.append(message)
        ranks = {message.id: rank for rank, message in enumerate(reversed(selected))}
        for message in selected:
            packer.offer(
                ContextClass.CURRENT_SESSION,
                source=f"rh://session/{record.id}?message={message.id}",
                text=f"{message.role.value}: {message.text()}",
                identity=message.id,
                authority=message.authority,
                label=f"{record.title} · {message.role.value}",
                rank=ranks[message.id],
            )
        return tuple(discrepancies)

    def _pack_prior_sessions(
        self,
        packer: _Packer,
        record: ConversationSession,
        draft: str,
        query: Sequence[str],
        profile: ProviderProfile,
        accepted: Mapping[str, ContextItem],
    ) -> tuple[Discrepancy, ...]:
        """Relevance-selected excerpts from other sessions, never a blind concatenation."""
        discrepancies: list[Discrepancy] = []
        for excerpt in self._prior_excerpts(record, draft, query):
            if excerpt.visibility is Visibility.PRIVATE and profile.leaves_the_machine:
                packer.drop(
                    ContextClass.PRIOR_SESSIONS,
                    source=excerpt.source,
                    reason=OmissionReason.EGRESS_BLOCKED,
                    identity=excerpt.identity,
                    label=excerpt.label,
                    detail=(
                        "a private session excerpt may not reach an external provider "
                        "(Product 34; workspace design SS7)"
                    ),
                )
                continue
            conflict = self._conflict(excerpt.text, excerpt.references, accepted)
            if conflict is not None:
                winner, detail = conflict
                packer.drop(
                    ContextClass.PRIOR_SESSIONS,
                    source=excerpt.source,
                    reason=OmissionReason.CONFLICTS_WITH_ACCEPTED,
                    identity=excerpt.identity,
                    label=excerpt.label,
                    detail=detail,
                )
                discrepancies.append(
                    Discrepancy(accepted=winner, message=excerpt.source, detail=detail)
                )
                continue
            packer.offer(
                ContextClass.PRIOR_SESSIONS,
                source=excerpt.source,
                text=excerpt.text,
                identity=excerpt.identity,
                authority=excerpt.authority,
                label=excerpt.label,
            )
        return tuple(discrepancies)

    def _pack_attachments(
        self,
        packer: _Packer,
        record: ConversationSession,
        profile: ProviderProfile,
        plan: AttachmentPlan | None,
    ) -> None:
        """Session attachments: what the model can be given, and what it cannot.

        With a plan, the pre-send check has already decided per item — including the media
        the model cannot take and the privacy refusals — and its verdict is packed as it
        stands. Without one, the tray is described from the records, which is all an
        assembly with no selected provider can honestly say.
        """
        if plan is not None:
            for item in plan.included:
                packer.adopt(item)
            for omission in plan.omitted:
                packer.adopt_omission(omission)
            return
        for attachment in self._attachments(record.id):
            source = f"rh://attachment/{attachment.id}"
            label = f"{attachment.filename} ({attachment.media_type})"
            if attachment.state not in {
                AttachmentState.READY,
                AttachmentState.SESSION_ONLY,
                AttachmentState.IN_CORPUS,
            }:
                continue
            if attachment.visibility is Visibility.PRIVATE and profile.leaves_the_machine:
                packer.drop(
                    ContextClass.ATTACHMENTS,
                    source=source,
                    reason=OmissionReason.EGRESS_BLOCKED,
                    identity=attachment.id,
                    label=label,
                    detail="a private attachment may not reach an external provider",
                )
                continue
            if attachment.media_type.startswith("image/") and not profile.vision:
                packer.drop(
                    ContextClass.ATTACHMENTS,
                    source=source,
                    reason=OmissionReason.UNSUPPORTED_MEDIA,
                    identity=attachment.id,
                    label=label,
                    detail=f"{profile.model} does not accept image input",
                )
                continue
            described = attachment.description or "no description"
            packer.offer(
                ContextClass.ATTACHMENTS,
                source=source,
                text=f"attachment {attachment.id}: {label} — {described}",
                identity=attachment.id,
                label=label,
            )

    def _pack_corpus_blocks(
        self,
        packer: _Packer,
        references: Sequence[ResolvedReference],
        profile: ProviderProfile,
        rules: EgressPolicy,
    ) -> None:
        """Parsed blocks of an artifact the composer referenced explicitly."""
        for reference in references:
            if not isinstance(reference.target, ArtifactId):
                continue
            source = f"rh://artifact/{reference.target}?blocks=1"
            if profile.leaves_the_machine and not rules.allow_source_text:
                packer.drop(
                    ContextClass.CORPUS_BLOCKS,
                    source=source,
                    reason=OmissionReason.PRIVACY_POLICY,
                    identity=reference.target,
                    label=reference.label,
                    detail="privacy.allow_source_text is false for this project",
                )
                continue
            text = self._artifact_text(reference.target)
            if not text:
                continue
            packer.offer(
                ContextClass.CORPUS_BLOCKS,
                source=source,
                text=text,
                identity=reference.target,
                authority=AuthorityLabel.ACCEPTED,
                label=reference.label,
            )

    def _pack_discovery(
        self, packer: _Packer, query: Sequence[str], profile: ProviderProfile
    ) -> None:
        """Recorded discovery runs the draft is about; last, because they are the weakest."""
        del profile
        for run in self._repo.list_search_runs():
            text = f"search {run.id}: {run.question} [{'; '.join(run.queries)}]"
            if relevance(query, text) < MIN_RELEVANCE:
                continue
            packer.offer(
                ContextClass.DISCOVERY,
                source=f"rh://search_run/{run.id}",
                text=text,
                identity=run.id,
                authority=AuthorityLabel.ACCEPTED,
                label=f"search run {run.id}",
            )

    # -- inputs --------------------------------------------------------------

    def _inputs(self, receipt: ContextReceipt, packer: _Packer) -> tuple[InputEnvelope, ...]:
        """The included material as provider-neutral input envelopes, in pack order."""
        envelopes: list[InputEnvelope] = []
        for item in receipt.included:
            if item.context_class is ContextClass.POLICY:
                continue
            text = packer.texts.get(item.source, "")
            if not text:
                continue
            envelopes.append(
                InputEnvelope(
                    object_id=None if item.id is None else str(item.id),
                    kind=item.context_class.value,
                    content=text,
                )
            )
        return tuple(envelopes)

    # -- resolution ----------------------------------------------------------

    def resolve_references(
        self, references: Sequence[str], draft: str = ""
    ) -> tuple[ResolvedReference, ...]:
        """Every `@` token, resolved through the graph when it is there, else canonically.

        Tokens named by the caller come first, then any stable id typed into the draft, so
        `@E0482` and a bare `E0482` reach the model as the same structured reference.
        """
        tokens: list[str] = []
        for token in (*references, *reference_tokens(draft)):
            cleaned = token.strip().lstrip("@")
            if cleaned and cleaned not in tokens:
                tokens.append(cleaned)
        return tuple(self._resolve_one(token) for token in tokens)

    def _resolve_one(self, token: str) -> ResolvedReference:
        """One token: graph first (it knows labels and authority), canonical read second."""
        node = self._graph_node(token)
        if node is not None:
            identity = _parsed(token)
            source = f"rh://node/{token}"
            text = f"{getattr(node, 'label', token)}\n{getattr(node, 'text', '')}".strip()
            resolved = ResolvedReference(
                token=token,
                target=identity,
                label=str(getattr(node, "label", token)),
                authority=_authority_of(getattr(node, "authority", None)),
                source=source,
                text=text,
                kind=str(getattr(getattr(node, "kind", ""), "value", "node")),
            )
            if identity is not None:
                return resolved
        return self._resolve_canonically(token)

    def _resolve_canonically(self, token: str) -> ResolvedReference:
        """Read the object itself. This is the answer that survives a deleted projection."""
        identity = _parsed(token)
        if identity is None:
            return ResolvedReference(token=token, detail=f"{token} is not a stable research id")
        try:
            rendered = self._render_object(identity)
        except (ObjectNotFoundError, ConversationNotFoundError, ResearchHarnessError) as exc:
            return ResolvedReference(token=token, detail=str(exc))
        if rendered is None:
            return ResolvedReference(
                token=token, detail=f"{token} is not a reference this workspace can resolve"
            )
        label, text, authority, source, kind = rendered
        return ResolvedReference(
            token=token,
            target=identity,
            label=label,
            authority=authority,
            source=source,
            text=text,
            kind=kind,
        )

    def _render_object(
        self, identity: ResearchId
    ) -> tuple[str, str, AuthorityLabel, str, str] | None:
        """Label, text, authority, deep link, and kind for one canonical object."""
        repo = self._repo
        if isinstance(identity, ClaimId):
            claim = repo.get_claim(identity)
            return (
                f"Claim {claim.id}",
                f"{claim.statement}\nstatus: {claim.assessment.status.value}; "
                f"allowed strength: {claim.assessment.allowed_strength.value}",
                _claim_authority(claim.assessment.status, claim.stale),
                f"rh://claim/{claim.id}",
                "claim",
            )
        if isinstance(identity, EvidenceId):
            return self._render_evidence(identity)
        if isinstance(identity, DecisionId):
            decision = repo.get_decision(identity)
            return (
                f"Decision {decision.id}",
                f"{decision.title or decision.type.value}: {decision.rationale}",
                (
                    AuthorityLabel.ACCEPTED
                    if decision.status is DecisionStatus.ACCEPTED
                    else AuthorityLabel.CANDIDATE
                ),
                f"rh://decision/{decision.id}",
                "decision",
            )
        if isinstance(identity, QuestionId):
            question = repo.get_question(identity)
            return (
                f"Question {question.id}",
                f"{question.question} (status: {question.status.value})",
                AuthorityLabel.ACCEPTED,
                f"rh://question/{question.id}",
                "question",
            )
        if isinstance(identity, WorkId):
            work = repo.get_work(identity)
            authors = ", ".join(work.authors)
            return (
                f"Work {work.id}",
                f"{work.title}\n{authors}" + (f" ({work.year})" if work.year else ""),
                AuthorityLabel.ACCEPTED,
                f"rh://work/{work.id}",
                "work",
            )
        if isinstance(identity, ArtifactId):
            artifact = repo.get_artifact(identity)
            return (
                f"Artifact {artifact.id}",
                f"{artifact.original_filename} ({artifact.mime_type})",
                AuthorityLabel.ACCEPTED,
                f"rh://artifact/{artifact.id}",
                "artifact",
            )
        if isinstance(identity, MessageId):
            message = self._store.find_message(identity)
            if message is None:
                return None
            return (
                f"Message {message.id}",
                message.text(),
                AuthorityLabel.PRIVATE,
                f"rh://session/{message.session}?message={message.id}",
                "message",
            )
        if isinstance(identity, ConversationSessionId):
            session = self._store.get_session(identity)
            summary = self._store.read_summary(identity) or session.title
            return (
                f"Session {session.id}",
                summary,
                AuthorityLabel.PRIVATE,
                f"rh://session/{session.id}",
                "session",
            )
        return None

    def _render_evidence(
        self, identity: EvidenceId
    ) -> tuple[str, str, AuthorityLabel, str, str] | None:
        """Evidence is stored per Work, so it is found by scanning the works that have any."""
        for work in self._repo.list_works():
            for evidence in self._repo.iter_evidence(work.id):
                if evidence.id != identity:
                    continue
                anchor = evidence.source
                return (
                    f"Evidence {evidence.id}",
                    f"{evidence.content.exact_text}\n"
                    f"source: {anchor.artifact} block {anchor.block}"
                    + (f", page {anchor.page}" if anchor.page else ""),
                    _evidence_authority(evidence.verification.status, evidence.stale),
                    f"rh://evidence/{evidence.id}",
                    "evidence",
                )
        return None

    # -- helpers -------------------------------------------------------------

    def _graph_node(self, token: str) -> Any | None:
        """Ask the graph to resolve a token, tolerating a missing or broken projection."""
        resolve = getattr(self._graph, "resolve", None)
        if resolve is None:
            return None
        try:
            return resolve(token)
        except Exception:  # pragma: no cover - the projection is disposable
            logger.warning("the research graph could not resolve %s", token, exc_info=True)
            return None

    def _prior_excerpts(
        self, record: ConversationSession, draft: str, query: Sequence[str]
    ) -> tuple[Excerpt, ...]:
        """Candidates for the prior-sessions class, from the first source that has any.

        The sources are *preferences*, not a union: the graph ranks better when it is
        built, and a direct transcript scan answers when it is not. Merging them would
        risk the same passage entering one pack twice under two different pointers, and
        would make the receipt harder to read than the thing it explains.
        """
        for source in self._sources:
            try:
                offered = source.excerpts(
                    # The draft's content words, not its prose: a source backed by a
                    # full-text index matches terms, and punctuation and stopwords only
                    # narrow what it can find. The scan re-tokenizes either way.
                    query=" ".join(query) or draft,
                    session=str(record.id),
                    limit=DEFAULT_EXCERPT_LIMIT,
                )
            except Exception:  # pragma: no cover - one bad source never fails a send
                logger.warning("context source %s failed", source.name, exc_info=True)
                continue
            if offered:
                return tuple(sorted(offered, key=lambda item: (-item.score, item.source)))
        return ()

    def _attachments(self, session: ConversationSessionId) -> Sequence[SessionAttachment]:
        try:
            return self._store.list_attachments(session)
        except ConversationNotFoundError:  # pragma: no cover - the session was just read
            return ()

    def _artifact_text(self, artifact: ArtifactId) -> str:
        """The stored parse of one artifact, joined; empty when it has never been parsed."""
        try:
            blocks = list(self._repo.iter_blocks(artifact))
        except (ObjectNotFoundError, ResearchHarnessError):
            return ""
        return "\n".join(block.text for block in blocks if getattr(block, "text", ""))

    def _accepted_objects(
        self,
    ) -> Iterable[tuple[ResearchId, str, str, AuthorityLabel, bool, str]]:
        """Every accepted object worth offering, as (id, label, text, authority, stale, link)."""
        for claim in self._repo.list_claims():
            yield (
                claim.id,
                f"Claim {claim.id}",
                f"{claim.statement} (status: {claim.assessment.status.value})",
                _claim_authority(claim.assessment.status, claim.stale),
                claim.stale is StaleState.STALE,
                f"rh://claim/{claim.id}",
            )
        for decision in self._repo.list_decisions():
            if decision.status is not DecisionStatus.ACCEPTED:
                continue
            yield (
                decision.id,
                f"Decision {decision.id}",
                f"{decision.title or decision.type.value}: {decision.rationale}",
                AuthorityLabel.ACCEPTED,
                False,
                f"rh://decision/{decision.id}",
            )
        for work in self._repo.list_works():
            for evidence in self._repo.iter_evidence(work.id):
                if evidence.verification.status is not EvidenceStatus.ACCEPTED:
                    continue
                yield (
                    evidence.id,
                    f"Evidence {evidence.id}",
                    evidence.content.exact_text,
                    _evidence_authority(evidence.verification.status, evidence.stale),
                    evidence.stale is StaleState.STALE,
                    f"rh://evidence/{evidence.id}",
                )
        for question in self._repo.list_questions():
            yield (
                question.id,
                f"Question {question.id}",
                question.question,
                AuthorityLabel.ACCEPTED,
                question.stale is StaleState.STALE,
                f"rh://question/{question.id}",
            )

    def _privacy_refusal(
        self, record: ConversationSession, message: Message, profile: ProviderProfile
    ) -> tuple[OmissionReason, str] | None:
        """Why this message may not be packed for this provider, or `None`."""
        if not profile.leaves_the_machine:
            return None
        if record.visibility is Visibility.PRIVATE or message.visibility is Visibility.PRIVATE:
            return (
                OmissionReason.EGRESS_BLOCKED,
                "private conversation content may not reach an external provider "
                "(Product 34; workspace design SS7)",
            )
        return None

    def _conflict(
        self,
        text: str,
        referenced: Sequence[str],
        accepted: Mapping[str, ContextItem],
    ) -> tuple[str, str] | None:
        """Whether this passage argues against an accepted object that is already packed.

        Returns the winning object's id and the sentence a receipt shows, or `None`. The
        two rules are the whole detector: an explicit contradiction cue about an object
        that is accepted state, or an accepted Decision that governs the object the
        passage relies on and postdates the passage.
        """
        mentioned = [
            identity for identity in {*referenced, *reference_tokens(text)} if identity in accepted
        ]
        if not mentioned:
            return None
        lowered = text.casefold()
        cue = next((phrase for phrase in CONTRADICTION_CUES if phrase in lowered), None)
        if cue is not None:
            winner = sorted(mentioned)[0]
            return (
                winner,
                f"the passage says {cue!r} about {winner}, which is accepted state; the "
                "accepted object was sent instead (workspace design SS3)",
            )
        superseding = self._superseding_decision(mentioned)
        if superseding is not None:
            target, decision = superseding
            return (
                str(decision),
                f"accepted Decision {decision} governs {target}; the remembered passage "
                "relies on it without recording it, so the Decision was sent instead",
            )
        return None

    def _superseding_decision(self, mentioned: Sequence[str]) -> tuple[str, DecisionId] | None:
        """An accepted Decision about one of these objects, when there is one."""
        for decision in self._repo.list_decisions():
            if decision.status is not DecisionStatus.ACCEPTED:
                continue
            for identity in mentioned:
                if decision.claim is not None and str(decision.claim) == identity:
                    return (identity, decision.id)
                if decision.supersedes is not None and str(decision.supersedes) == identity:
                    return (identity, decision.id)
        return None


def _message_references(message: Message) -> tuple[str, ...]:
    """Stable ids a message points at through its structured reference blocks."""
    return tuple(str(block.target) for block in message.blocks if isinstance(block, ReferenceBlock))


def _parsed(token: str) -> ResearchId | None:
    """``token`` as a typed id, or `None` when it is not one."""
    try:
        return parse_id(token)
    except ResearchHarnessError:
        return None


def _authority_of(value: Any) -> AuthorityLabel:
    try:
        return AuthorityLabel(str(getattr(value, "value", value)))
    except ValueError:
        return AuthorityLabel.PRIVATE


def _claim_authority(status: ClaimStatus, stale: StaleState) -> AuthorityLabel:
    """A claim's authority label: what it is allowed to be relied on for."""
    if stale is StaleState.STALE:
        return AuthorityLabel.STALE
    if status is ClaimStatus.CONTESTED:
        return AuthorityLabel.CONTESTED
    if status is ClaimStatus.QUALIFIED:
        return AuthorityLabel.QUALIFIED
    if status in {ClaimStatus.SUPPORTED}:
        return AuthorityLabel.ACCEPTED
    return AuthorityLabel.CANDIDATE


def _evidence_authority(status: EvidenceStatus, stale: StaleState) -> AuthorityLabel:
    """Evidence authority: accepted only when the review said so."""
    if stale is StaleState.STALE or status is EvidenceStatus.STALE:
        return AuthorityLabel.STALE
    if status is EvidenceStatus.ACCEPTED:
        return AuthorityLabel.ACCEPTED
    return AuthorityLabel.CANDIDATE

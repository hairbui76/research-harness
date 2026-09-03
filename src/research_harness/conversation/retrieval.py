"""Cross-session retrieval: what an earlier conversation said that bears on this draft.

Two sources sit behind one :class:`ContextSource` protocol, and the difference between
them is availability, not authority:

* :class:`TranscriptScan` reads `conversations/` directly. It is slow in the way a linear
  scan is slow and it is *always right*, because the transcripts are the durable record.
  Deleting `.research/` therefore reduces nothing here (conversation design SS8).
* :class:`GraphExcerpts` adapts the ResearchGraph's session-aware context query. It is the
  preferred source when the projection exists, because it ranks across sessions with the
  graph's own privacy filtering rather than re-deriving it.

Relevance is deliberately small and explainable: which of the draft's terms a passage
contains, with a light frequency tie-break. There is no learned model and no hidden state,
so the same draft ranks the same passages on every machine and a receipt that says
"included because it is relevant" can be checked by reading it.

Nothing here decides what reaches a provider. Selection, budgeting, and the privacy
decision belong to :mod:`research_harness.conversation.context`; this module only offers
candidates with their visibility attached.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from research_harness.domain.conversation import (
    AuthorityLabel,
    ConversationSession,
    Message,
    MessageRole,
    ReferenceBlock,
    Visibility,
)
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.ids import MessageId, ResearchId, parse_id
from research_harness.workspace.conversations import ConversationStore

__all__ = [
    "DEFAULT_EXCERPT_LIMIT",
    "STOPWORDS",
    "ContextSource",
    "Excerpt",
    "GraphContext",
    "GraphExcerpts",
    "TranscriptScan",
    "graph_is_available",
    "relevance",
    "terms",
]

logger = logging.getLogger(__name__)

DEFAULT_EXCERPT_LIMIT = 12
"""Candidates a source offers before budgeting; the assembler takes what fits."""

MIN_RELEVANCE = 0.15
"""Below this a passage is `low_relevance`, not context. One threshold, stated once."""

_WORD = re.compile(r"[A-Za-z0-9_]+")

_STOPWORDS: tuple[str, ...] = (
    "a",
    "about",
    "after",
    "all",
    "also",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "might",
    "more",
    "most",
    "no",
    "not",
    "of",
    "on",
    "or",
    "our",
    "out",
    "over",
    "should",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "to",
    "under",
    "up",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
)

STOPWORDS: frozenset[str] = frozenset(_STOPWORDS)
"""Words that carry no retrieval signal. Small and fixed, so ranking is reproducible."""


def terms(text: str) -> list[str]:
    """Lowercased content words of ``text``, in order, stopwords removed."""
    return [
        word
        for word in (match.group(0).lower() for match in _WORD.finditer(text))
        if word not in STOPWORDS and len(word) > 1
    ]


def relevance(query: Sequence[str], text: str) -> float:
    """How much of the query ``text`` covers, in [0, 1]; deterministic and explainable.

    Coverage (the share of distinct query terms present) dominates, and a logarithmic
    frequency term breaks ties towards a passage that discusses the terms rather than
    mentioning them once. A passage that shares nothing scores exactly zero.
    """
    wanted = set(query)
    if not wanted:
        return 0.0
    found = terms(text)
    if not found:
        return 0.0
    counts = {term: found.count(term) for term in wanted if term in found}
    if not counts:
        return 0.0
    coverage = len(counts) / len(wanted)
    density = sum(math.log1p(count) for count in counts.values()) / (len(wanted) * math.log1p(8))
    return round(min(1.0, 0.8 * coverage + 0.2 * min(1.0, density)), 6)


@dataclass(frozen=True, slots=True)
class Excerpt:
    """One passage a source offers, with everything the receipt will need about it."""

    text: str
    source: str
    """Deep link or workspace pointer, e.g. `rh://session/CS0001?message=M0042`."""

    score: float
    visibility: Visibility = Visibility.PRIVATE
    authority: AuthorityLabel = AuthorityLabel.PRIVATE
    label: str | None = None
    identity: ResearchId | None = None
    """Stable id of the passage when it has one; a derived summary has none."""

    session: str | None = None
    kind: str = "message"
    """`message`, `summary`, or whatever the graph called the fragment."""

    references: tuple[str, ...] = field(default_factory=tuple)
    """Stable ids the passage mentions, used to detect a conflict with accepted state."""


@runtime_checkable
class ContextSource(Protocol):
    """Anything that can offer prior-session passages relevant to a draft."""

    name: str

    def excerpts(
        self,
        *,
        query: str,
        session: str | None = None,
        limit: int = DEFAULT_EXCERPT_LIMIT,
        references: Sequence[str] = (),
    ) -> Sequence[Excerpt]:
        """Candidate passages, best first. Private material is returned and *labelled*.

        ``session`` is the conversation being assembled *for*, not a filter: the caller
        packs that session's own transcript itself, in order, from the durable record, so
        a source offers what the *other* sessions know.
        """


class TranscriptScan:
    """Direct, index-free retrieval over `conversations/`.

    It reads the durable transcripts, so it answers with the projection deleted, mid-build,
    or on a machine that has never run a rebuild. That is the whole point: a missing index
    may cost ranking quality, never access to a researcher's own conversations.
    """

    name = "transcript-scan"

    def __init__(self, store: ConversationStore, *, min_relevance: float = MIN_RELEVANCE) -> None:
        self._store = store
        self._min_relevance = min_relevance

    def excerpts(
        self,
        *,
        query: str,
        session: str | None = None,
        limit: int = DEFAULT_EXCERPT_LIMIT,
        references: Sequence[str] = (),
    ) -> Sequence[Excerpt]:
        """Messages and summaries from other sessions that share terms with the draft."""
        wanted = terms(query)
        wanted.extend(term for reference in references for term in terms(reference))
        if not wanted:
            return ()
        found: list[Excerpt] = []
        for record in self._store.list_sessions():
            if session is not None and str(record.id) == str(session):
                continue
            found.extend(self._session_excerpts(record, wanted))
        found.sort(key=lambda item: (-item.score, item.source))
        return tuple(found[:limit])

    def _session_excerpts(
        self, session: ConversationSession, wanted: Sequence[str]
    ) -> Iterable[Excerpt]:
        """The relevant passages of one session: its messages, then its derived summary."""
        for message in self._store.iter_messages(session.id):
            text = message.text().strip()
            if not text or message.role is MessageRole.SYSTEM:
                continue
            score = relevance(wanted, text)
            if score < self._min_relevance:
                continue
            yield Excerpt(
                text=text,
                source=f"rh://session/{session.id}?message={message.id}",
                score=score,
                visibility=_effective_visibility(session, message),
                authority=message.authority,
                label=f"{session.title} · {message.role.value}",
                identity=message.id,
                session=str(session.id),
                kind="message",
                references=_referenced_ids(message),
            )
        summary = self._store.read_summary(session.id)
        if summary is None:
            return
        score = relevance(wanted, summary)
        if score >= self._min_relevance:
            yield Excerpt(
                text=summary.strip(),
                source=f"rh://session/{session.id}?summary=1",
                score=score,
                visibility=session.visibility,
                authority=AuthorityLabel.PRIVATE,
                label=f"{session.title} · summary",
                session=str(session.id),
                kind="summary",
            )


@runtime_checkable
class GraphContext(Protocol):
    """The graph's session-aware context query (implemented by `ResearchGraph`).

    Declared structurally so `conversation/` never imports `graph/`: the assembler prefers
    this source when the projection is available and falls back to a transcript scan when
    it is not, and a fake satisfying this protocol is all a unit test needs.
    """

    def context_fragments(
        self,
        *,
        session: str | None = None,
        query: str = "",
        references: Sequence[str] = (),
        visibility: Sequence[Any] | None = None,
        limit: int = DEFAULT_EXCERPT_LIMIT,
    ) -> Sequence[Any]:
        """Provenance-bearing fragments for a draft, ranked and privacy-labelled."""


class GraphExcerpts:
    """A :class:`GraphContext` seen as a :class:`ContextSource`.

    The fragments come from another subsystem, so they are read defensively: whatever the
    graph calls its fields, an excerpt needs text, a source pointer, a score, and a
    visibility, and anything missing is filled with the conservative value (private,
    unranked). A fragment with no text is dropped rather than guessed at.

    ``classes`` keeps this source to the context classes it is being asked about — prior
    sessions by default. Accepted state, attachments, corpus blocks, and discovery are
    assembled from canonical reads, and taking them from the graph as well would put the
    same material in a pack twice under two different pointers.

    The graph is asked for everything this *machine* holds, private material included, and
    the egress decision is made once, by the assembler, which records each refusal in the
    receipt. A source that filtered silently could not produce the receipt line the
    acceptance scenario requires ("display the omission reason").
    """

    name = "research-graph"

    def __init__(
        self, graph: GraphContext, *, classes: Sequence[str] = ("prior_sessions",)
    ) -> None:
        self._graph = graph
        self._classes = frozenset(classes)

    def excerpts(
        self,
        *,
        query: str,
        session: str | None = None,
        limit: int = DEFAULT_EXCERPT_LIMIT,
        references: Sequence[str] = (),
    ) -> Sequence[Excerpt]:
        """Ask the graph, and translate what it says into excerpts.

        ``session`` is passed through as the graph's own `session=`: it is the request's
        focus, which is how the graph decides that a node belongs to the *current* session
        rather than a prior one. Its current-session fragments are then dropped by the
        class filter, because the caller packs that transcript from the durable record.
        """
        try:
            fragments = self._graph.context_fragments(
                session=session, query=query, references=tuple(references), limit=limit
            )
        except Exception:  # pragma: no cover - a disposable projection never breaks a send
            logger.warning("the research graph could not answer a context query", exc_info=True)
            return ()
        return tuple(
            excerpt
            for excerpt in (_as_excerpt(fragment) for fragment in fragments)
            if excerpt is not None and (not self._classes or excerpt.kind in self._classes)
        )


def graph_is_available(graph: object) -> bool:
    """True when a graph object reports a usable projection.

    `status()` is asked for `available` first and `current` second, so this keeps working
    whichever name the graph settles on; anything that raises is treated as unavailable,
    because a missing index degrades retrieval and must never fail a send.
    """
    status = getattr(graph, "status", None)
    if status is None:
        return False
    try:
        report = status()
    except Exception:  # pragma: no cover - defensive: the projection is disposable
        logger.warning("the research graph could not report its status", exc_info=True)
        return False
    for attribute in ("available", "current", "exists"):
        value = getattr(report, attribute, None)
        if value is not None:
            return bool(value)
    return False  # pragma: no cover - a status object with none of the three


def _as_excerpt(fragment: Any) -> Excerpt | None:
    """One graph fragment as an excerpt, or `None` when it carries no text."""
    if isinstance(fragment, Excerpt):
        return fragment
    text = _first(fragment, ("text", "content", "excerpt"))
    if not isinstance(text, str) or not text.strip():
        return None
    identity = _first(fragment, ("identity", "id", "node"))
    source = _first(fragment, ("source_pointer", "source", "link", "pointer")) or (
        f"rh://graph/{identity}" if identity else "rh://graph/fragment"
    )
    score = _first(fragment, ("score", "rank", "relevance"))
    visibility = _first(fragment, ("visibility",))
    authority = _first(fragment, ("authority",))
    identity_text = "" if identity is None else str(identity)
    pointer = str(source)
    if identity_text and identity_text not in pointer:
        # The graph points at the durable file a fragment came from, and one file holds a
        # whole transcript. A receipt names one passage, so the identity is appended:
        # without it two messages of one session would collide on a single pointer and the
        # second would be dropped as a duplicate.
        pointer = f"{pointer}#{identity_text}"
    return Excerpt(
        text=text.strip(),
        source=pointer,
        score=float(score) if isinstance(score, int | float) else 0.0,
        visibility=_visibility(visibility),
        authority=_authority(authority),
        label=_optional_str(_first(fragment, ("label", "title"))),
        identity=_as_id(identity),
        session=_optional_str(_first(fragment, ("session",))),
        kind=str(_first(fragment, ("context_class", "kind")) or "fragment"),
        references=tuple(str(item) for item in _first(fragment, ("references",)) or ()),
    )


def _first(fragment: Any, names: Sequence[str]) -> Any:
    """The first attribute (or mapping key) of ``fragment`` that is present and set."""
    for name in names:
        value = fragment.get(name) if isinstance(fragment, dict) else getattr(fragment, name, None)
        if value is not None:
            return value
    return None


def _as_id(value: Any) -> ResearchId | None:
    """A fragment's identity as a typed id when it is one; graph identities are strings."""
    if isinstance(value, ResearchId):
        return value
    if not isinstance(value, str):
        return None
    try:
        return parse_id(value)
    except ResearchHarnessError:
        return None


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _visibility(value: Any) -> Visibility:
    """A visibility label, defaulting to `private`: the conservative reading."""
    try:
        return Visibility(str(value))
    except ValueError:
        return Visibility.PRIVATE


def _authority(value: Any) -> AuthorityLabel:
    """An authority label, defaulting to `private`: chat is never accepted state."""
    try:
        return AuthorityLabel(str(value))
    except ValueError:
        return AuthorityLabel.PRIVATE


def _effective_visibility(session: ConversationSession, message: Message) -> Visibility:
    """A message is only as shareable as its session: private wins."""
    if session.visibility is Visibility.PRIVATE or message.visibility is Visibility.PRIVATE:
        return Visibility.PRIVATE
    return Visibility.PROJECT


def _referenced_ids(message: Message) -> tuple[str, ...]:
    """The stable ids a message points at, from its structured reference blocks."""
    return tuple(str(block.target) for block in message.blocks if isinstance(block, ReferenceBlock))


def message_pointer(session: str, message: MessageId) -> str:
    """The deep link naming one message of one session."""
    return f"rh://session/{session}?message={message}"

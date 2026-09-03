"""Graph-aware context assembly: a provenance-bearing subgraph under a privacy budget.

Graph spec §7 fixes the order a context assembler must select in, and this module is that
order made mechanical:

1. exact referenced accepted objects;
2. the accepted relations that directly support, contradict, or qualify them;
3. the current session's own messages and attachments;
4. relevant cross-session and corpus nodes, found lexically over the query;
5. broader one- and two-hop neighbours of everything already selected.

Three properties are enforced here rather than left to the caller:

* **Privacy is a filter on the walk, not on the result.** An excluded node is never
  expanded, so a fragment cannot be reached by hopping through a node the request was not
  allowed to see (graph spec §8, §11.5). The whole assembly runs inside one
  `GraphVisibility` allow-list which `graph.queries` applies at every hop.
* **Candidate and stale material is labelled, never substituted.** A node whose authority
  is `candidate` or `stale` is demoted to the lowest tier and classed `discovery`, whatever
  reached it — so a model's proposal cannot occupy the slot an accepted object would have
  had, and a researcher reading the receipt sees which is which (ADR-003).
* **Every fragment says how it was reached.** `relation_path` is the identities walked
  from the seed, ending at the fragment itself, so a response can be traced back through
  the same graph that produced it.

Nothing here scores relevance scientifically. `score` is an assembly rank derived from the
selection tier and position, and vector similarity or lexical rank never grants authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy.engine import Engine

from research_harness.domain.graph import (
    ContextFragment,
    EdgeKind,
    EdgeOrigin,
    GraphAuthority,
    GraphVisibility,
    NodeKind,
)
from research_harness.graph.queries import (
    Direction,
    GraphFilter,
    NodeRecord,
    neighbors,
    node,
    resolve,
    search,
)

__all__ = [
    "ACCEPTED_STATE",
    "ATTACHMENTS",
    "CORPUS_BLOCKS",
    "CURRENT_SESSION",
    "DEFAULT_LIMIT",
    "DISCOVERY",
    "PRIOR_SESSIONS",
    "ContextAssembly",
    "OmittedFragment",
    "assemble",
    "context_class_for",
    "estimate_tokens",
]

# The `domain.conversation.ContextClass` names, as plain strings: `domain/graph.py` and
# `domain/conversation.py` are independent modules, and the graph must not import the
# conversation vocabulary to describe what it found (plan §0.3).
ACCEPTED_STATE: Final = "accepted_state"
CURRENT_SESSION: Final = "current_session"
PRIOR_SESSIONS: Final = "prior_sessions"
ATTACHMENTS: Final = "attachments"
CORPUS_BLOCKS: Final = "corpus_blocks"
DISCOVERY: Final = "discovery"

DEFAULT_LIMIT = 40
"""Fragments a request asks for when it does not say; the caller owns the token budget."""

_CHARS_PER_TOKEN = 4
"""Deterministic estimate. A real tokenizer is provider-specific and this layer has none."""

_TIER_BASE: Final[tuple[float, ...]] = (1.0, 0.8, 0.6, 0.4, 0.2)
_TIER_DECAY = 0.002
_TIER_FLOOR = 0.19
"""Position decay never crosses a tier boundary, so the spec's order survives ranking."""

_SEED_EXPANSION = 12
"""Seeds whose broader neighbourhood is walked; a bound on the two-hop fan-out."""

_SCIENTIFIC_RELATIONS: Final = (EdgeKind.SUPPORTS, EdgeKind.CONTRADICTS, EdgeKind.QUALIFIES)

_SESSION_KINDS: Final = frozenset({NodeKind.SESSION, NodeKind.MESSAGE, NodeKind.ATTACHMENT})

_ACCEPTED_KINDS: Final = frozenset(
    {
        NodeKind.EVIDENCE,
        NodeKind.CLAIM,
        NodeKind.QUESTION,
        NodeKind.DECISION,
        NodeKind.SYNTHESIS,
    }
)

_LABELLED_AUTHORITIES: Final = frozenset({GraphAuthority.CANDIDATE, GraphAuthority.STALE})
"""Authorities that cannot outrank accepted material, however they were reached."""

_LOWEST_TIER = len(_TIER_BASE)


@dataclass(frozen=True, slots=True)
class OmittedFragment:
    """One thing the caller might have expected, and why it is not in the assembly.

    Only material the caller *named* — a reference, or the session it asked about — and
    material that lost the ranking is reported. A private node the request was never
    allowed to see is not described here: saying "there is something you may not have"
    about content the walk excluded would be the leak the exclusion exists to prevent.
    """

    id: str
    reason: str
    """One of the `domain.conversation.OmissionReason` names."""

    detail: str = ""


@dataclass(frozen=True, slots=True)
class ContextAssembly:
    """What the graph offers one context request: the fragments, and the omissions."""

    fragments: tuple[ContextFragment, ...] = ()
    omitted: tuple[OmittedFragment, ...] = ()

    def total_tokens(self) -> int:
        """Estimated cost of every fragment, for a caller filling a token budget."""
        return sum(fragment.tokens for fragment in self.fragments)


def estimate_tokens(text: str) -> int:
    """Deterministic token estimate: characters divided by four, rounded up."""
    return -(-len(text) // _CHARS_PER_TOKEN)


def context_class_for(record: NodeRecord, *, session: str | None) -> str:
    """Which `ContextClass` a projected node belongs to in an assembled pack.

    Authority decides first: a candidate or stale node is `discovery` whatever its kind,
    so no receipt can file an unreviewed proposal under accepted state.
    """
    if record.authority in _LABELLED_AUTHORITIES:
        return DISCOVERY
    if record.kind is NodeKind.ATTACHMENT:
        return ATTACHMENTS
    if record.kind in _SESSION_KINDS:
        return CURRENT_SESSION if _belongs_to(record, session) else PRIOR_SESSIONS
    if record.kind in _ACCEPTED_KINDS:
        return ACCEPTED_STATE
    return CORPUS_BLOCKS


def _belongs_to(record: NodeRecord, session: str | None) -> bool:
    if session is None:
        return False
    return record.identity == session or str(record.metadata.get("session", "")) == session


# --- assembly ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Candidate:
    """One node the assembler is considering, with the tier and path that found it."""

    tier: int
    order: int
    record: NodeRecord
    path: tuple[str, ...]

    @property
    def identity(self) -> str:
        return self.record.identity


def assemble(
    engine: Engine | None,
    *,
    session: str | None = None,
    query: str = "",
    references: Sequence[str] = (),
    visibility: GraphVisibility = GraphVisibility.PRIVATE,
    limit: int = DEFAULT_LIMIT,
) -> ContextAssembly:
    """Select a provenance-bearing subgraph in the order of graph spec §7.

    ``visibility`` is the egress class of the *request*: ``project`` assembles only what
    may reach the selected provider, ``private`` assembles everything this machine holds.
    A missing graph returns an empty assembly rather than raising — direct canonical reads
    stay possible while the projection is absent or rebuilding (graph spec §8).
    """
    if engine is None or limit <= 0:
        return ContextAssembly()
    allowed = _allowed(visibility)
    omitted: list[OmittedFragment] = []
    candidates: list[_Candidate] = []
    seen: set[str] = set()

    seeds = _referenced(engine, references, allowed, omitted, seen, candidates)
    _relations(engine, seeds, allowed, seen, candidates)
    _current_session(engine, session, allowed, omitted, seen, candidates)
    _relevant(engine, query, allowed, limit, seen, candidates)
    _broader(engine, allowed, limit, seen, candidates)

    return _rank(candidates, session=session, limit=limit, omitted=omitted)


def _allowed(visibility: GraphVisibility) -> tuple[GraphVisibility, ...]:
    """The egress classes a request of this class may see; `private` sees everything."""
    if visibility is GraphVisibility.PRIVATE:
        return (GraphVisibility.PRIVATE, GraphVisibility.PROJECT)
    return (GraphVisibility.PROJECT,)


def _tier_for(record: NodeRecord, tier: int) -> int:
    """A candidate or stale node never ranks above the accepted material it might replace."""
    return _LOWEST_TIER if record.authority in _LABELLED_AUTHORITIES else tier


def _take(
    record: NodeRecord,
    *,
    tier: int,
    path: tuple[str, ...],
    seen: set[str],
    into: list[_Candidate],
) -> bool:
    """Record one candidate the first time its identity is reached."""
    if record.identity in seen:
        return False
    seen.add(record.identity)
    into.append(_Candidate(tier=_tier_for(record, tier), order=len(into), record=record, path=path))
    return True


# 1. exact referenced objects -------------------------------------------------


def _referenced(
    engine: Engine,
    references: Sequence[str],
    allowed: tuple[GraphVisibility, ...],
    omitted: list[OmittedFragment],
    seen: set[str],
    into: list[_Candidate],
) -> list[NodeRecord]:
    """Resolve every `@`-reference the caller named, in the order they were given."""
    resolved: list[NodeRecord] = []
    for reference in references:
        text = str(reference).strip()
        if not text:
            continue
        record = resolve(engine, text)
        if record is None:
            omitted.append(
                OmittedFragment(
                    id=text,
                    reason="unresolved_reference",
                    detail="no object with this identity is projected in this workspace",
                )
            )
            continue
        if record.visibility not in allowed:
            omitted.append(
                OmittedFragment(
                    id=record.identity,
                    reason="privacy_policy",
                    detail=f"{record.identity} is {record.visibility.value}; this request "
                    f"assembles {'/'.join(value.value for value in allowed)} material only",
                )
            )
            continue
        resolved.append(record)
        _take(record, tier=1, path=(record.identity,), seen=seen, into=into)
    return resolved


# 2. the accepted relations of what was referenced -----------------------------


def _relations(
    engine: Engine,
    seeds: Iterable[NodeRecord],
    allowed: tuple[GraphVisibility, ...],
    seen: set[str],
    into: list[_Candidate],
) -> None:
    """Directly supporting, contradicting, and qualifying *accepted* relations only.

    ``origins=(ACCEPTED,)`` is what keeps a model-proposed `supports` edge out of this
    tier: it stays visible, one tier lower, still labelled candidate (graph spec §11.3).
    """
    for record in seeds:
        for neighbour in neighbors(
            engine,
            record.identity,
            hops=1,
            direction=Direction.BOTH,
            edge_kinds=_SCIENTIFIC_RELATIONS,
            origins=(EdgeOrigin.ACCEPTED,),
            visibility=allowed,
            limit=0,
        ):
            _take(
                neighbour.node,
                tier=2,
                path=(record.identity, neighbour.node.identity),
                seen=seen,
                into=into,
            )


# 3. the current session -------------------------------------------------------


def _current_session(
    engine: Engine,
    session: str | None,
    allowed: tuple[GraphVisibility, ...],
    omitted: list[OmittedFragment],
    seen: set[str],
    into: list[_Candidate],
) -> None:
    """The session's own record, its transcript, and its attachments, newest message first."""
    if session is None:
        return
    record = node(engine, session)
    if record is None:
        omitted.append(
            OmittedFragment(
                id=session,
                reason="unresolved_reference",
                detail="the session is not projected; read its transcript directly",
            )
        )
        return
    if record.visibility not in allowed:
        omitted.append(
            OmittedFragment(
                id=session,
                reason="privacy_policy",
                detail=f"session {session} is private and this request may not carry "
                "private material off this machine",
            )
        )
        return
    _take(record, tier=3, path=(record.identity,), seen=seen, into=into)
    members = [
        neighbour.node
        for neighbour in neighbors(
            engine,
            record.identity,
            hops=1,
            direction=Direction.BOTH,
            edge_kinds=(EdgeKind.CONTAINS, EdgeKind.ATTACHED_TO),
            visibility=allowed,
            kinds=(NodeKind.MESSAGE, NodeKind.ATTACHMENT),
            limit=0,
        )
    ]
    for member in sorted(members, key=lambda item: item.identity, reverse=True):
        _take(
            member,
            tier=3,
            path=(record.identity, member.identity),
            seen=seen,
            into=into,
        )


# 4. relevant cross-session and corpus material --------------------------------


def _relevant(
    engine: Engine,
    query: str,
    allowed: tuple[GraphVisibility, ...],
    limit: int,
    seen: set[str],
    into: list[_Candidate],
) -> None:
    """Lexical retrieval over the projected text, constrained by the same allow-list."""
    terms = str(query).strip()
    if not terms:
        return
    filters = GraphFilter(visibility=allowed, limit=limit * 2)
    for hit in search(engine, terms, limit=limit * 2, filters=filters):
        _take(hit.node, tier=4, path=(hit.node.identity,), seen=seen, into=into)


# 5. broader neighbours --------------------------------------------------------


def _broader(
    engine: Engine,
    allowed: tuple[GraphVisibility, ...],
    limit: int,
    seen: set[str],
    into: list[_Candidate],
) -> None:
    """One hop, then a second, from what is already selected — the widest tier.

    The walk is done a hop at a time rather than with ``hops=2`` so every fragment can
    record the identities it was actually reached through; the privacy filter is passed to
    both hops, so neither can route around it.
    """
    seeds = list(into)[:_SEED_EXPANSION]
    first: list[_Candidate] = []
    for candidate in seeds:
        for neighbour in neighbors(
            engine,
            candidate.identity,
            hops=1,
            direction=Direction.BOTH,
            visibility=allowed,
            limit=limit,
        ):
            path = (*candidate.path, neighbour.node.identity)
            if _take(neighbour.node, tier=5, path=path, seen=seen, into=into):
                first.append(into[-1])
    for candidate in first[:_SEED_EXPANSION]:
        for neighbour in neighbors(
            engine,
            candidate.identity,
            hops=1,
            direction=Direction.BOTH,
            visibility=allowed,
            limit=limit,
        ):
            path = (*candidate.path, neighbour.node.identity)
            _take(neighbour.node, tier=5, path=path, seen=seen, into=into)


# --- ranking ------------------------------------------------------------------


def _rank(
    candidates: Sequence[_Candidate],
    *,
    session: str | None,
    limit: int,
    omitted: list[OmittedFragment],
) -> ContextAssembly:
    """Order by tier, then by the order each tier found them, and cut at ``limit``."""
    ordered = sorted(candidates, key=lambda item: (item.tier, item.order, item.identity))
    positions: dict[int, int] = {}
    fragments: list[ContextFragment] = []
    for candidate in ordered:
        position = positions.get(candidate.tier, 0)
        positions[candidate.tier] = position + 1
        fragments.append(_fragment(candidate, position=position, session=session))
    for rank, fragment in enumerate(fragments[limit:], start=limit + 1):
        omitted.append(
            OmittedFragment(
                id=fragment.id,
                reason="low_relevance",
                detail=f"ranked {rank} of {len(fragments)} for a request that asked for {limit}",
            )
        )
    return ContextAssembly(fragments=tuple(fragments[:limit]), omitted=tuple(omitted))


def _fragment(candidate: _Candidate, *, position: int, session: str | None) -> ContextFragment:
    record = candidate.record
    text = record.text or record.label
    return ContextFragment(
        id=record.identity,
        kind=record.kind,
        authority=record.authority,
        visibility=record.visibility,
        source_pointer=record.source or record.identity,
        relation_path=candidate.path,
        text=text,
        tokens=estimate_tokens(text),
        score=_score(candidate.tier, position),
        context_class=context_class_for(record, session=session),
    )


def _score(tier: int, position: int) -> float:
    """Deterministic assembly rank: the tier's base, decayed by position inside it."""
    base = _TIER_BASE[min(tier, _LOWEST_TIER) - 1]
    return round(base - min(_TIER_FLOOR, position * _TIER_DECAY), 6)

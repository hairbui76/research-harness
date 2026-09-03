"""ResearchGraph vocabularies, node/edge values, stable references, and deep links.

The graph is a *projection* (PRODUCT 15.1, ADR-006): it makes references resolvable and
neighbourhoods traversable, and it has no scientific authority of its own. This module is
the pure half of it — vocabularies, two frozen value objects, and the two reference
grammars a human or a composer types — so `graph/` can build a SQLite index out of values
that already carry their own invariants.

The invariant that matters most lives on :class:`GraphEdge`: an edge a model proposed can
never be labelled ``accepted``. Acceptance is a review decision recorded in canonical
state; a projection that could relabel a proposal would be the "index becomes the
knowledge model" failure PRODUCT §43 names, one field wide.

Two grammars:

* stable references — ``@W0017``, ``@E0482``, ``@C0041``, ``@RQ0002``, ``@CS0001`` — which
  address a canonical object by its own identity, never by a database row;
* deep links — ``rh://artifact/A0017-3?page=6&block=B0081`` — which address an exact local
  target inside one. Parsing a link says only what it *means*; whether it may be opened is
  decided against the canonical object by `graph.resolver`.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Self
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

from pydantic import Field, model_validator

from research_harness.domain.base import DomainModel, NonEmptyStr
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.ids import ID_TYPES, ResearchId

__all__ = [
    "DEEP_LINK_QUERY_KEYS",
    "DEEP_LINK_SCHEME",
    "DETERMINISTIC_EDGE_KINDS",
    "ID_GRAMMAR",
    "NEW_REFERENCE_PREFIXES",
    "REFERENCE_SIGIL",
    "SCIENTIFIC_EDGE_KINDS",
    "DeepLink",
    "DeepLinkKind",
    "EdgeKind",
    "EdgeOrigin",
    "GraphAuthority",
    "GraphEdge",
    "GraphMetadata",
    "GraphNode",
    "GraphVisibility",
    "MetadataValue",
    "NodeKind",
    "StableReference",
    "known_reference_prefixes",
]


class NodeKind(StrEnum):
    """Every namespace the graph projects (graph spec §2, plan §0.3).

    `session`, `message`, and `attachment` are declared here and projected by the
    conversation projector; the vocabulary is fixed so a later projector adds rows, never
    a new enum member.
    """

    PROJECT = "project"
    SESSION = "session"
    MESSAGE = "message"
    ATTACHMENT = "attachment"
    WORK = "work"
    VERSION = "version"
    ARTIFACT = "artifact"
    SECTION = "section"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    FIGURE = "figure"
    EQUATION = "equation"
    REFERENCE = "reference"
    EVIDENCE = "evidence"
    CLAIM = "claim"
    QUESTION = "question"
    DECISION = "decision"
    SYNTHESIS = "synthesis"
    MANUSCRIPT_FILE = "manuscript_file"
    MANUSCRIPT_ANCHOR = "manuscript_anchor"
    CITATION = "citation"


class EdgeKind(StrEnum):
    """Deterministic and scientific relations (graph spec §3)."""

    CONTAINS = "contains"
    VERSION_OF = "version_of"
    ARTIFACT_OF = "artifact_of"
    CITES = "cites"
    ATTACHED_TO = "attached_to"
    ANCHORED_AT = "anchored_at"
    MENTIONED_IN = "mentioned_in"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"
    DERIVED_FROM = "derived_from"
    DEPENDS_ON = "depends_on"


DETERMINISTIC_EDGE_KINDS: frozenset[EdgeKind] = frozenset(
    {
        EdgeKind.CONTAINS,
        EdgeKind.VERSION_OF,
        EdgeKind.ARTIFACT_OF,
        EdgeKind.CITES,
        EdgeKind.ATTACHED_TO,
        EdgeKind.ANCHORED_AT,
        EdgeKind.MENTIONED_IN,
    }
)
"""Edges derived from explicit structure or identity; regenerable without judgement."""

SCIENTIFIC_EDGE_KINDS: frozenset[EdgeKind] = frozenset(
    {
        EdgeKind.SUPPORTS,
        EdgeKind.CONTRADICTS,
        EdgeKind.QUALIFIES,
        EdgeKind.DERIVED_FROM,
        EdgeKind.DEPENDS_ON,
    }
)
"""Edges that assert something about the science; they carry origin and authority."""


class EdgeOrigin(StrEnum):
    """Where an edge came from (graph spec §3)."""

    STRUCTURAL = "structural"
    """Derived from canonical structure or identity, with no judgement involved."""

    ACCEPTED = "accepted"
    """Read off an accepted canonical relation a researcher reviewed."""

    MODEL_PROPOSED = "model_proposed"
    """A model's proposal, staged and unreviewed; can never be `accepted` authority."""

    RESEARCHER = "researcher"
    """Asserted directly by the researcher outside a reviewed canonical relation."""


class GraphAuthority(StrEnum):
    """Authority label carried by every node and edge.

    Mirrors `domain.conversation.AuthorityLabel` value for value; the graph declares its
    own so `domain/graph.py` and `domain/conversation.py` stay independent modules.
    """

    ACCEPTED = "accepted"
    CANDIDATE = "candidate"
    QUALIFIED = "qualified"
    CONTESTED = "contested"
    STALE = "stale"
    PRIVATE = "private"


class GraphVisibility(StrEnum):
    """Egress class of a projected node (graph spec §8).

    Mirrors `domain.conversation.Visibility`: `private` never leaves the machine unless
    policy explicitly allows it; `project` may reach the selected provider.
    """

    PRIVATE = "private"
    PROJECT = "project"


MetadataValue = str | int | float | bool | None
"""Projection metadata is scalar only, so a row is a faithful, diff-free echo."""

GraphMetadata = dict[str, MetadataValue]

_UNSAFE_IDENTITY = re.compile(r"[\n\r\t]")


def _checked_identity(value: str, field: str) -> str:
    if _UNSAFE_IDENTITY.search(value):
        raise ValueError(f"{field} must not contain a newline or tab: {value!r}")
    return value


class GraphNode(DomainModel):
    """One projected node: stable identity, kind, authority, and where it came from.

    ``identity`` is the external identity a human or a composer types or a link addresses
    (``W0017``, ``E0482``, ``file:main.tex``, ``anchor:<file>#<fingerprint>``), never a
    database row id: rebuilding the projection must not change it (graph spec §5).
    """

    identity: NonEmptyStr
    kind: NodeKind
    authority: GraphAuthority = GraphAuthority.ACCEPTED
    visibility: GraphVisibility = GraphVisibility.PROJECT
    label: str = ""
    """Short human-readable name; indexed for autocomplete and search."""

    text: str = ""
    """Searchable body text; indexed alongside ``label``."""

    source: str | None = None
    """Workspace-relative pointer to the durable file this node was projected from."""

    fingerprint: str | None = None
    """Digest of that source, so a changed source can be re-projected on its own."""

    metadata: GraphMetadata = Field(default_factory=dict)
    """Scalar projection metadata: page, block, order, status details."""

    @model_validator(mode="after")
    def _identity_stays_one_line(self) -> GraphNode:
        _checked_identity(self.identity, "node identity")
        return self


class GraphEdge(DomainModel):
    """One projected edge, carrying origin, authority, status, and a source pointer.

    A model-proposed edge may never claim accepted authority, and an edge read off an
    accepted canonical relation may never be labelled a candidate. Both directions are
    enforced here rather than in the writer, so no projector, capability, or test helper
    can construct the forbidden value in the first place (graph spec §3, ADR-003).
    """

    from_id: NonEmptyStr
    to_id: NonEmptyStr
    kind: EdgeKind
    origin: EdgeOrigin
    authority: GraphAuthority
    status: str = ""
    source: str | None = None
    metadata: GraphMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def _authority_matches_origin(self) -> GraphEdge:
        _checked_identity(self.from_id, "edge from_id")
        _checked_identity(self.to_id, "edge to_id")
        if self.origin is EdgeOrigin.MODEL_PROPOSED and self.authority is GraphAuthority.ACCEPTED:
            raise ValueError(
                "a model-proposed edge cannot be accepted; acceptance is a reviewed "
                "canonical relation, never a projection label"
            )
        if self.origin is EdgeOrigin.ACCEPTED and self.authority is GraphAuthority.CANDIDATE:
            raise ValueError("an edge read off an accepted relation is not a candidate")
        return self

    @property
    def is_scientific(self) -> bool:
        """True when this edge asserts a scientific relation rather than structure."""
        return self.kind in SCIENTIFIC_EDGE_KINDS

    @property
    def key(self) -> tuple[str, str, str, str]:
        """Primary key of the edge row: ``(from, to, kind, origin)``."""
        return (self.from_id, self.to_id, self.kind.value, self.origin.value)


# --- stable references ------------------------------------------------------

REFERENCE_SIGIL = "@"
"""What a composer reference starts with: ``@W0017``."""

ID_GRAMMAR = re.compile(r"^(?P<prefix>[A-Z]+)(?P<number>\d{4,})(?:-(?P<suffix>\d+))?$")
"""``^[A-Z]+\\d{4,}(-\\d+)?$`` — the shape every stable research id has."""

NEW_REFERENCE_PREFIXES: tuple[str, ...] = ("CP", "CS", "M", "SA")
"""Conversation-era prefixes accepted as opaque ids even before their types land."""


def known_reference_prefixes() -> frozenset[str]:
    """Every prefix a stable reference may carry, typed or still opaque."""
    return frozenset(id_type.prefix for id_type in ID_TYPES) | frozenset(NEW_REFERENCE_PREFIXES)


class StableReference(DomainModel):
    """A parsed ``@``-reference: the prefix, and the id text it addresses.

    The prefix is the maximal leading run of capitals, so ``CS0001`` is a session and
    ``C0041`` a claim with no ambiguity to resolve. A reference resolves through canonical
    identity; this type only says the text is a well-formed id of a prefix the project
    knows (graph spec §5).
    """

    prefix: NonEmptyStr
    identifier: NonEmptyStr

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse ``@W0017`` or ``W0017``; raises for anything else."""
        reference = cls.try_parse(text)
        if reference is None:
            known = ", ".join(sorted(known_reference_prefixes()))
            raise DomainValidationError(
                f"{text!r} is not a stable reference; expected {REFERENCE_SIGIL}<PREFIX><digits> "
                f"with a known prefix ({known})"
            )
        return reference

    @classmethod
    def try_parse(cls, text: str) -> Self | None:
        """Parse, or return ``None`` — the form autocomplete and link scanners want."""
        candidate = str(text).strip()
        if candidate.startswith(REFERENCE_SIGIL):
            candidate = candidate[len(REFERENCE_SIGIL) :]
        match = ID_GRAMMAR.match(candidate)
        if match is None or match.group("prefix") not in known_reference_prefixes():
            return None
        return cls(prefix=match.group("prefix"), identifier=candidate)

    def format(self) -> str:
        """The reference as a human types it: ``@W0017``."""
        return f"{REFERENCE_SIGIL}{self.identifier}"

    @property
    def is_typed(self) -> bool:
        """True when a concrete `ResearchId` subclass owns this prefix."""
        return any(id_type.prefix == self.prefix for id_type in ID_TYPES)

    def as_research_id(self) -> ResearchId | None:
        """The typed id, or ``None`` while the prefix is still an opaque string."""
        for id_type in ID_TYPES:
            if id_type.prefix == self.prefix:
                return id_type(self.identifier)
        return None


# --- deep links -------------------------------------------------------------

DEEP_LINK_SCHEME = "rh"
"""``rh://<kind>/<id>[?query]``."""

DEEP_LINK_QUERY_KEYS: tuple[str, ...] = ("page", "block", "line", "message")
"""Query keys a deep link may carry, in the order :meth:`DeepLink.format` writes them."""


class DeepLinkKind(StrEnum):
    """What a deep link addresses (plan §0.1)."""

    ARTIFACT = "artifact"
    EVIDENCE = "evidence"
    CLAIM = "claim"
    WORK = "work"
    VERSION = "version"
    QUESTION = "question"
    DECISION = "decision"
    SESSION = "session"
    ATTACHMENT = "attachment"
    MANUSCRIPT = "manuscript"


class DeepLink(DomainModel):
    """``rh://artifact/A0017-3?page=6&block=B0081`` parsed into its parts.

    ``target`` is an id for every kind but ``manuscript``, whose target is the
    workspace-relative path of a user-owned source file.
    """

    kind: DeepLinkKind
    target: NonEmptyStr
    page: int | None = Field(default=None, ge=1)
    block: str | None = None
    line: int | None = Field(default=None, ge=1)
    message: str | None = None

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse a ``rh://`` link; raises :class:`DomainValidationError` if malformed."""
        parts = urlsplit(str(text).strip())
        if parts.scheme != DEEP_LINK_SCHEME:
            raise DomainValidationError(
                f"a deep link starts with {DEEP_LINK_SCHEME}://, got {text!r}"
            )
        try:
            kind = DeepLinkKind(parts.netloc)
        except ValueError:
            known = ", ".join(member.value for member in DeepLinkKind)
            raise DomainValidationError(
                f"unknown deep-link kind {parts.netloc!r}; known kinds: {known}"
            ) from None
        target = unquote(parts.path).lstrip("/")
        if not target:
            raise DomainValidationError(f"deep link {text!r} names no target")
        query = dict(parse_qsl(parts.query, keep_blank_values=False))
        unknown = sorted(set(query) - set(DEEP_LINK_QUERY_KEYS))
        if unknown:
            raise DomainValidationError(
                f"deep link {text!r} carries unsupported query key(s): {', '.join(unknown)}"
            )
        try:
            return cls(
                kind=kind,
                target=target,
                page=_as_int(query.get("page"), "page"),
                block=query.get("block"),
                line=_as_int(query.get("line"), "line"),
                message=query.get("message"),
            )
        except ValueError as error:
            raise DomainValidationError(f"deep link {text!r} is invalid: {error}") from error

    @classmethod
    def try_parse(cls, text: str) -> Self | None:
        """Parse, or return ``None`` for anything that is not a valid link."""
        try:
            return cls.parse(text)
        except DomainValidationError:
            return None

    def format(self) -> str:
        """The canonical text of this link; parsing it again yields an equal object."""
        query = [
            (key, str(value))
            for key, value in (
                ("page", self.page),
                ("block", self.block),
                ("line", self.line),
                ("message", self.message),
            )
            if value is not None
        ]
        path = quote(self.target, safe="/")
        suffix = f"?{urlencode(query)}" if query else ""
        return f"{DEEP_LINK_SCHEME}://{self.kind.value}/{path}{suffix}"

    def __str__(self) -> str:
        return self.format()

    @property
    def reference(self) -> StableReference | None:
        """The ``@`` reference this link addresses, when its target is a stable id."""
        return StableReference.try_parse(self.target)


def _as_int(value: str | None, key: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{key} must be an integer, got {value!r}") from None

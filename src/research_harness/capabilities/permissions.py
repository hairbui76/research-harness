"""Who may call which capability, decided server-side (Product 22, 29; ADR-004, ADR-009).

Permissions are a property of the capability layer, not of a transport: HTTP, MCP, the Web
cockpit, and the CLI all reach the same handlers, so the only place a check cannot be
skipped is here. Four permissions describe what a call is allowed to touch:

``read``
    Reads accepted state or a regenerable projection; writes nothing.
``stage``
    Writes only under ``.research/staging`` - proposals a person still has to review.
``mutate``
    Changes accepted scientific state.
``admin``
    Rebuilds or initializes regenerable infrastructure.

The one rule that carries scientific weight: accepted-state mutation requires a human
principal. An agent host (Claude, ChatGPT, or any other) may read and stage, and asks for
approval by leaving something in the review queue - it never accepts on the researcher's
behalf (Product 24, 29; ADR-003, ADR-007). Model providers are workers, not principals
(Product 21), so their principal kind is narrower still.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from research_harness.domain.errors import AuthorityError, CapabilityError
from research_harness.domain.transitions import HUMAN_ACTOR

__all__ = [
    "AGENT_HOST_PERMISSIONS",
    "HUMAN_AUTHORITY",
    "HUMAN_PERMISSIONS",
    "MODEL_PERMISSIONS",
    "CapabilityNotFound",
    "InvalidRequest",
    "Permission",
    "PermissionDenied",
    "Principal",
    "PrincipalKind",
]


class Permission(StrEnum):
    """What a capability is allowed to touch."""

    READ = "read"
    STAGE = "stage"
    MUTATE = "mutate"
    ADMIN = "admin"


class PrincipalKind(StrEnum):
    """Who is calling. A host is where a researcher sits; a model is a worker (Product 21)."""

    HUMAN = "human"
    AGENT_HOST = "agent_host"
    MODEL = "model"


#: Permissions that require a human principal, whatever else was granted. Accepting
#: evidence, auditing a claim, and rebuilding state are researcher acts (ADR-007).
HUMAN_AUTHORITY: frozenset[Permission] = frozenset({Permission.MUTATE, Permission.ADMIN})

HUMAN_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

#: Claude, ChatGPT, and every other host get the same set: read the project, propose into
#: staging, and ask for approval. Identical for every host (Product 29, ADR-009).
AGENT_HOST_PERMISSIONS: frozenset[Permission] = frozenset({Permission.READ, Permission.STAGE})

MODEL_PERMISSIONS: frozenset[Permission] = frozenset({Permission.READ, Permission.STAGE})


class CapabilityNotFound(CapabilityError):  # noqa: N818 - the ROADMAP Task 10.1 contract name
    """No capability with that name is registered."""


class InvalidRequest(CapabilityError):  # noqa: N818 - the ROADMAP Task 10.1 contract name
    """The request payload does not validate against the capability's request model."""


class PermissionDenied(AuthorityError):  # noqa: N818 - the ROADMAP Task 10.1 contract name
    """The principal may not invoke this capability.

    An :class:`~research_harness.domain.errors.AuthorityError`, because refusing a host
    that tries to accept evidence is the same refusal as a model trying to: the actor lacks
    the authority, not the syntax.
    """


class Principal(BaseModel):
    """Who a call is on behalf of, and what that identity is allowed to do.

    ``actor`` is the string the capability layer records as provenance, so it follows the
    Product 7.3 vocabulary (``human``/``human:<name>`` for the researcher). ``host`` names
    the agent host for auditing only; no capability behaves differently because of it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = HUMAN_ACTOR
    kind: PrincipalKind = PrincipalKind.HUMAN
    host: str | None = None
    granted: frozenset[Permission] = Field(default_factory=lambda: HUMAN_PERMISSIONS)

    @classmethod
    def human(cls, actor: str = HUMAN_ACTOR) -> Principal:
        """The researcher at this workstation: every permission."""
        return cls(actor=actor, kind=PrincipalKind.HUMAN, granted=HUMAN_PERMISSIONS)

    @classmethod
    def agent_host(cls, host: str, *, actor: str | None = None) -> Principal:
        """An agent host (Claude, ChatGPT, ...): read and stage, never accept."""
        return cls(
            actor=actor or host,
            kind=PrincipalKind.AGENT_HOST,
            host=host,
            granted=AGENT_HOST_PERMISSIONS,
        )

    @classmethod
    def model(cls, actor: str) -> Principal:
        """An internal model worker proposing into staging (Product 21)."""
        return cls(actor=actor, kind=PrincipalKind.MODEL, granted=MODEL_PERMISSIONS)

    @property
    def is_human(self) -> bool:
        """True when this principal may exercise researcher authority."""
        return self.kind is PrincipalKind.HUMAN

    def allows(self, permission: Permission) -> bool:
        """True when the principal holds ``permission`` and its kind may exercise it."""
        if permission not in self.granted:
            return False
        return self.is_human or permission not in HUMAN_AUTHORITY

    def authorize(self, capability: str, permission: Permission, *, human_only: bool) -> None:
        """Refuse the call unless this principal may make it. Raises `PermissionDenied`."""
        if permission not in self.granted:
            held = ", ".join(sorted(item.value for item in self.granted)) or "none"
            raise PermissionDenied(
                f"{capability}: a {self.kind.value} principal does not hold the "
                f"{permission.value!r} permission (holds: {held})"
            )
        if (permission in HUMAN_AUTHORITY or human_only) and not self.is_human:
            raise PermissionDenied(
                f"{capability}: a {self.kind.value} principal may not change accepted state; "
                "an agent host reads and proposes, and the researcher accepts (Product 24, 29)"
            )

    @property
    def label(self) -> str:
        """How this principal is named in a log line.

        Refusals name the *kind*, never the identity: which host asked is an audit fact,
        and putting it in the error body would make the same refusal read differently on
        two transports that must answer identically (ADR-009).
        """
        if self.host:
            return f"{self.kind.value} {self.host!r}"
        return f"{self.kind.value} {self.actor!r}"

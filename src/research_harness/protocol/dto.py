"""Transport-neutral envelopes shared by HTTP and MCP (ADR-009).

A capability call has the same shape whichever transport carries it: a name, a request
body, and who is asking. A capability result has the same shape too: it worked and here is
the typed payload, or it did not and here is why. Both transports build these envelopes
from the *same* registry descriptors, so "the HTTP surface and the MCP surface agree" is a
property of the code rather than a promise in a document.

Nothing here holds business logic, and nothing here decides permissions - the registry
does both (ADR-004).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_harness.capabilities.extra_handlers import RunStatus
from research_harness.capabilities.permissions import (
    CapabilityNotFound,
    InvalidRequest,
    PermissionDenied,
    PrincipalKind,
)
from research_harness.capabilities.reads import (
    AnchorSummary,
    ArtifactSummary,
    CandidateView,
    ClaimSummary,
    DecisionSummary,
    MatrixSummary,
    QuestionSummary,
    TaxonomySummary,
    WorkspaceIndex,
    WorkSummary,
)
from research_harness.capabilities.registry import (
    CapabilityDescriptor,
    CapabilityRegistry,
    PlannedCapability,
)
from research_harness.domain.errors import (
    AuthorityError,
    ProjectionError,
    ResearchHarnessError,
    TransitionError,
    WorkspaceError,
)
from research_harness.workspace.repository import ObjectNotFoundError

__all__ = [
    "AnchorSummary",
    "ArtifactBlocks",
    "ArtifactSummary",
    "AttentionGroup",
    "AttentionItem",
    "BlockView",
    "CandidateView",
    "CapabilityCatalog",
    "CapabilityDescriptor",
    "CapabilityRequest",
    "CapabilityResponse",
    "ChangeEntry",
    "ClaimSummary",
    "ConflictPosition",
    "ConflictView",
    "CountEntry",
    "DecisionSummary",
    "ErrorBody",
    "HealthReport",
    "MatrixSummary",
    "ObjectView",
    "OverviewCounts",
    "OverviewReport",
    "PlannedCapability",
    "QuestionSummary",
    "RecentChanges",
    "RunStatus",
    "TaxonomySummary",
    "WorkSummary",
    "WorkspaceIndex",
    "error_body",
]


#: Harness errors, mapped to the stable ``code`` a client branches on and the HTTP status
#: the daemon answers with. The code is part of the contract; the message is not.
_ERROR_CODES: tuple[tuple[type[Exception], str, int], ...] = (
    (CapabilityNotFound, "capability_not_found", 404),
    (PermissionDenied, "permission_denied", 403),
    (InvalidRequest, "invalid_request", 422),
    (AuthorityError, "authority_error", 403),
    (TransitionError, "transition_error", 409),
    (ObjectNotFoundError, "object_not_found", 404),
    (WorkspaceError, "workspace_error", 409),
    (ProjectionError, "projection_error", 409),
    (ResearchHarnessError, "capability_error", 400),
)


class ErrorBody(BaseModel):
    """Why a call failed, identically on every transport."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    capability: str | None = None

    @property
    def status(self) -> int:
        """The HTTP status this error answers with."""
        for _, code, status in _ERROR_CODES:
            if code == self.code:
                return status
        return 400


def error_body(exc: Exception, *, capability: str | None = None) -> ErrorBody:
    """The wire error for ``exc``; an unrecognised exception is never leaked verbatim."""
    for kind, code, _ in _ERROR_CODES:
        if isinstance(exc, kind):
            return ErrorBody(code=code, message=str(exc), capability=capability)
    return ErrorBody(code="internal_error", message=str(exc), capability=capability)


class CapabilityRequest(BaseModel):
    """One capability call: what to do, with what, on whose authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: str
    request: dict[str, Any] = Field(default_factory=dict)
    actor: str | None = None
    """Overrides the actor the transport resolved; refused when it claims more authority."""

    principal_kind: PrincipalKind | None = None
    """Declared for auditing. A transport never widens a principal on a caller's say-so."""


class CapabilityResponse(BaseModel):
    """One capability result: the typed payload, or the error that replaced it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: str
    ok: bool
    result: dict[str, Any] | None = None
    error: ErrorBody | None = None
    run_id: str | None = None
    """Set when the capability is long-running: poll `run.status` rather than waiting."""

    @classmethod
    def succeeded(cls, capability: str, result: BaseModel) -> CapabilityResponse:
        """Wrap a handler's typed response for the wire."""
        payload = result.model_dump(mode="json")
        run_id = payload.get("run_id") if isinstance(payload, dict) else None
        return cls(
            capability=capability,
            ok=True,
            result=payload,
            run_id=run_id if isinstance(run_id, str) else None,
        )

    @classmethod
    def failed(cls, capability: str, exc: Exception) -> CapabilityResponse:
        """Wrap a failure; every transport reports the same code and message."""
        return cls(capability=capability, ok=False, error=error_body(exc, capability=capability))


class CapabilityCatalog(BaseModel):
    """What a host can call, and what it cannot call yet."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capabilities: tuple[CapabilityDescriptor, ...] = ()
    planned: tuple[PlannedCapability, ...] = ()

    @classmethod
    def of(cls, registry: CapabilityRegistry) -> CapabilityCatalog:
        """The catalog for ``registry``, in name order."""
        return cls(capabilities=tuple(registry.describe()), planned=registry.planned())


class ObjectView(BaseModel):
    """One canonical object, read through the repository's typed accessors."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: str
    object: dict[str, Any]


class HealthReport(BaseModel):
    """Whether the daemon can serve this workspace at all."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    workspace: str
    project: str
    review_policy: str
    capabilities: int
    version: str


# -- web cockpit reads -------------------------------------------------------
#
# The Web cockpit needs three things the capability registry does not carry, all of them
# reads: the immutable artifact bytes to render beside a decision, the parsed geometry to
# draw the highlight on, and one composed "what needs attention" answer. They are DTOs here
# rather than rules in React, because Product 5 P10 says a frontend owns no research logic.
#
# The summaries a navigation lists (`WorkSummary`, `ClaimSummary`, `CandidateView`,
# `WorkspaceIndex`, ...) are *not* defined here any more: `GET /index` and
# `GET /candidates/{id}` answer with the same models the `claim.list`, `work.list`, and
# `review.candidate` capabilities return, so the route and the capability cannot drift into
# two shapes for one answer (ADR-009). They are imported above and re-exported unchanged.


class BlockView(BaseModel):
    """One parsed block with the page geometry a source pane draws a highlight on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: str
    page: int
    order: int
    text: str
    section_path: tuple[str, ...] = ()
    bbox: tuple[float, float, float, float] | None = None


class ArtifactBlocks(BaseModel):
    """Every stored block of one artifact, in reading order, with its file identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    work: str
    version: str
    mime_type: str
    file_hash: str
    page_count: int
    blocks: tuple[BlockView, ...] = ()


class ConflictPosition(BaseModel):
    """One side of a disagreement: who said it, and what they decided."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    provider: str
    model: str
    decision: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = None


class ConflictView(BaseModel):
    """One open disagreement as the cockpit shows it (Product 25): every side, no winner."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conflict_id: str
    kind: str
    subject: str
    summary: str
    tier: int
    status: str
    created_at: str
    differing_fields: tuple[str, ...] = ()
    positions: tuple[ConflictPosition, ...] = ()
    proposed_changes: tuple[dict[str, Any], ...] = ()


class AttentionItem(BaseModel):
    """One thing waiting for the researcher, already ordered by the server."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    detail: str = ""
    priority: int = 0
    route: str = ""
    """Where this one item lives, when the cockpit has a screen for it.

    A waiting review item is reachable on its own (`/review/<candidate>`); a stale Work,
    Claim, or Evidence object has a page of its own. Anything the cockpit can only show
    inside its list leaves this empty, and the group's own `route` carries the reader
    there instead. The path is the daemon's, exactly as `AttentionGroup.route` is.
    """


class AttentionGroup(BaseModel):
    """One attention surface of Product 26: its size, where it lives, and its top items."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    label: str
    count: int
    route: str
    items: tuple[AttentionItem, ...] = ()
    surface: str = "decide"
    """Which kind of attention this group asks for: `decide` or `stale`.

    A candidate in the queue, an open conflict, and a manuscript sentence with no support
    are all waiting for a researcher to decide something. A stale object is not: it is
    accepted state that has gone out of date and has to be repaired, and nothing is
    silently re-anchored (ADR-008). The distinction is scientific, so the daemon draws it
    and the Overview reads it rather than deciding from `kind` which is which.
    """


class CountEntry(BaseModel):
    """One labelled tally. Never a model-confidence number (Product 26, 43)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    count: int


class OverviewCounts(BaseModel):
    """The size of the project, as the Overview header states it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    works: int = 0
    accepted_evidence: int = 0
    claims: int = 0
    questions: int = 0
    artifacts: int = 0
    decisions: int = 0
    matrices: int = 0
    manuscript_anchors: int = 0


class ChangeEntry(BaseModel):
    """One thing that changed while the researcher was away, as the daemon recorded it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: str
    """Which research surface moved: `work`, `evidence`, `claim`, `decision`, `conflict`."""

    label: str
    """The sentence the daemon wrote when it happened. A client renders it; it never
    composes one of its own out of ids and enum values."""

    detail: str = ""
    at: str
    """When it happened, ISO-8601 in UTC — the machine-readable half of `when`."""

    when: str
    """The same instant in the words a person reads, in the machine's own time zone."""

    route: str = ""
    """Where the changed object lives, when the cockpit has a screen for it."""


class RecentChanges(BaseModel):
    """`OverviewReport.since_last_session`: what changed while the researcher was away.

    **Where the window opens.** The daemon reads this project's conversation sessions,
    keeps the ones that recorded a message, and orders them by that message, newest first.
    With two or more, the window opens at the end of the session *before* the most recent
    one, so what a researcher sees on returning is the work of their last sitting and
    everything after it — which is the question "what changed since I last worked" actually
    asks. With fewer than two sessions there is nothing to bound a window with, so the
    window is the last seven days. `basis` names which rule applied (`previous_session`,
    `recent_window`, or `no_history` for a project that has recorded no research yet) and
    `summary` says it in words, so nothing on screen has to guess.

    **What counts as a change.** Works added, evidence accepted, claims promoted or
    reclassified, and decisions taken, read from the Git-visible semantic event log
    (Product 19.3); conflicts opened or resolved, read from the conflict store. Newest
    first, capped, with `more` saying in words what the cap left out. Every judgement here
    is the daemon's: a client displays this list and never rebuilds it (Product 5 P10).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    basis: str = "no_history"
    since: str = ""
    """Start of the window, ISO-8601 in UTC. Empty only when nothing bounds one."""

    summary: str = ""
    """One line: which window this is, and how much happened inside it."""

    more: str = ""
    """What the cap left out, in words. Empty when nothing was left out."""

    entries: tuple[ChangeEntry, ...] = ()
    total: int = 0
    """Everything in the window, including what the cap left out of `entries`."""


class OverviewReport(BaseModel):
    """`GET /overview`: next actions first, then claim health and open questions.

    The ordering, the grouping, and every rule that decides whether something needs
    attention are settled here so no client re-derives them (Product 5 P10, 26).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project: str
    workspace: str
    review_policy: str
    principal: str = "human"
    """Kind of the caller. A client disables its mutation controls on `agent_host`."""

    actor: str = "human"
    next_decision_id: str = ""
    """Id the next `decision.accept` will write; an override is a Decision first (Product 38)."""

    counts: OverviewCounts = Field(default_factory=OverviewCounts)
    attention_summary: str = ""
    """One line naming what needs a researcher, composed from the groups below.

    The Overview's own description reads this. It is written here because deciding what
    counts as waiting — and in which words — is the same judgement that built `attention`.
    """

    attention: tuple[AttentionGroup, ...] = ()
    since_last_session: RecentChanges = Field(default_factory=RecentChanges)
    claim_health: tuple[CountEntry, ...] = ()
    open_questions: tuple[AttentionItem, ...] = ()
    conflicts: tuple[ConflictView, ...] = ()
    conflict_summary: str = ""
    """One line naming what is in dispute, for the Conflicts page's own description.

    Written here for the same reason `attention_summary` is: deciding that a disagreement
    is still open, and saying so in words, is one judgement and it is the daemon's.
    """

    conflict_groups: tuple[AttentionGroup, ...] = ()
    """The open conflicts grouped by the kind of disagreement they are (Product 25).

    Each group's `kind` is the conflict kind the store recorded, so a client reads the
    grouping instead of switching on `kind` to build it; each item's `route` is where that
    one disagreement is decided — the candidate's review screen, the object's own page, or
    nowhere when the cockpit has no screen for its subject.
    """

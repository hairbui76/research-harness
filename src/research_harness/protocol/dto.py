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

from typing import Any, Literal

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
    title: str = ""
    """The name a person reads for this object, when the label is a daemon identifier.

    A stale object is reported by the id the dependency graph knows it under — `C0001`,
    `S0001#W0001#tokenization`, `TX:traffic-shape` — and none of those is a name. The
    object's own name is composed here, once, so the Overview's "Gone stale" group and the
    Stale page read one title rather than each humanising an id its own way (Product 5
    P10). Empty when the label is already the name, which is what every other surface's
    items carry.
    """

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

    by: Literal["researcher", "daemon", ""] = ""
    """Who the record says did it: the researcher, the daemon, or nothing at all.

    Read off the record and never inferred from the kind of change. The semantic event log
    stores the actor of every mutation it describes — `human`/`human:<name>` is the
    researcher (Product 7.3), anything else is the daemon's own machinery — and a resolved
    conflict stores the researcher who answered it. The one change nothing attributes is a
    conflict *opening*: the conflict store keeps no actor for it, so an opening is the
    daemon's only when the record names the run that produced it, and otherwise carries the
    empty string. A client says "you" or "the daemon" for the two named values and leaves an
    unattributed change unattributed; it never fills the gap in (Product 5 P10).
    """


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


# -- the research pages that follow the Overview's pattern -------------------


class ResearchGroup(BaseModel):
    """One group of items a research page reads: what it is, its size, and where it leads.

    The Overview settled this shape: a line naming the group and stating its size in words,
    a sentence teaching what the objects in it are, and the items themselves indented under
    it. Which group an object belongs in is a scientific judgement, so the daemon draws
    every line and a client renders what it was handed (Product 5 P10).

    There is deliberately no count on this model that a client could print on its own:
    `summary` is the whole sentence a reader sees, and `count` exists so a client can tell
    an empty group from a full one, not so it can compose a number into words of its own.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = ""
    """Stable identifier for the group. Never rendered."""

    title: str = ""
    """What this group is, in the words a researcher reads."""

    summary: str = ""
    """The group's own line: its size stated inside a sentence, never a bare number."""

    detail: str = ""
    """What these objects are and where they come from — what an empty group teaches."""

    count: int = 0
    route: str = ""
    """The cockpit path this group's own page lives at, when it has one. Empty otherwise."""

    items: tuple[AttentionItem, ...] = ()


class StaleOverview(BaseModel):
    """`GET /stale`: what went out of date and why, grouped by scientific impact.

    Staleness is decay the daemon declares, never a client's guess: an object is here
    because something it rests on changed, and nothing is ever silently re-anchored
    (Product 37, ADR-008). The groups are the priority tiers Product 37 names, highest
    scientific impact first, and each item carries the daemon's own reason for it — the
    same `AttentionItem` the Overview's "Gone stale" group is built from, so the two
    surfaces cannot drift into two different accounts of the same decay.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = ""
    """One line: how much went stale, and why anything is here at all."""

    count: int = 0
    """Every mark recorded, including the ones beyond what this report carries."""

    reported: int = 0
    """How many marks the groups below hold."""

    more: str = ""
    """What the cap left out, in words. Empty when nothing was left out."""

    groups: tuple[ResearchGroup, ...] = ()


class TaxonomyTermView(BaseModel):
    """One approved term, its place in the tree, and the Decision standing behind it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    term: str
    parent: str = ""
    definition: str = ""
    decision: str = ""
    decision_status: str = ""
    """`accepted`, `proposed`, `superseded`, or empty when no Decision is named."""

    approved: bool = False
    """True only when an accepted Decision stands behind this term (Product 32)."""

    depth: int = 0
    """How deep in the classification this term sits. The daemon walks the tree, not a client."""


class TaxonomyView(BaseModel):
    """One project taxonomy, its terms already ordered as the tree they form."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    summary: str = ""
    """The taxonomy's own line: how many terms it holds and how many are approved."""

    count: int = 0
    approved: int = 0
    terms: tuple[TaxonomyTermView, ...] = ()


class TaxonomyReport(BaseModel):
    """`GET /taxonomy`: what needs a researcher first, then the classification itself.

    A taxonomy is a researcher-approved project decision rather than a universal domain
    fact (Product 32), so the question this page opens with is which terms no accepted
    Decision stands behind — a term with none, or one whose Decision has been superseded,
    classifies works on an authority the project never granted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = ""
    count: int = 0
    """Every term in every taxonomy of this project."""

    needs_decision: ResearchGroup = Field(default_factory=ResearchGroup)
    taxonomies: tuple[TaxonomyView, ...] = ()


class MatrixEvidenceView(BaseModel):
    """One accepted Evidence object a matrix cell rests on, as the grid opens it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str = ""
    """What the review queue called it — `field · work` — or "" when nothing answers to it."""

    route: str = ""
    quote: str = ""
    """The exact recorded span, never shortened: a span that is trimmed is not the span."""

    measurement: str = ""
    """The measured value with its metric and unit, when this evidence carries one."""

    found: bool = True
    """False when the workspace no longer holds the object the cell cites."""


class MatrixCellView(BaseModel):
    """One work/field cell of a matrix: what was recorded there, and what it rests on.

    `recorded` is false for a cell nobody has read yet. That is a gap in the record and
    never a reading of the work: no absence, no novelty and no confidence is derived from
    it anywhere (Product 7.1, 11, 33).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    work: str
    field: str
    recorded: bool = False
    reading: str = ""
    """The labels recorded in this cell, as one phrase. Empty when nothing was recorded."""

    measurement: str = ""
    """The number behind the reading, with its metric and unit, when there is one."""

    detail: str = ""
    """What this cell is, in words: what it was read from, or what a blank one means."""

    evidence: tuple[MatrixEvidenceView, ...] = ()


class MatrixColumnView(BaseModel):
    """One field of a matrix, read down the works: how much of it is recorded, and how."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    recorded: int = 0
    coverage: str = ""
    """How much of this column is recorded, in words. Never a claim about the works."""

    reading: str = ""
    """How the column reads across the works: which labels were recorded, and for how many."""


class MatrixRowView(BaseModel):
    """One work of a matrix, with the cell recorded for it under every declared field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    work: str
    title: str = ""
    route: str = ""
    summary: str = ""
    """How much of this row is recorded, in words."""

    cells: tuple[MatrixCellView, ...] = ()


class MatrixView(BaseModel):
    """One synthesis matrix as its page states it: what it reads, and how much it has read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    taxonomy: str = ""
    stale: str = "fresh"
    works: int = 0
    fields: tuple[str, ...] = ()
    cells: int = 0
    recorded: int = 0
    """Cells that carry at least one label. A cell with none has not been read yet."""

    shape: str = ""
    """What the matrix lines up, in words: the works it reads and the fields it reads them for."""

    coverage: str = ""
    """How much of the matrix has been recorded, in words. Never a claim about the works."""

    labels_from: str = ""
    """Which vocabulary the labels in this matrix come from, in words (Product 32)."""

    columns: tuple[MatrixColumnView, ...] = ()
    """The matrix's fields in its own declared order, each read down the works."""

    rows: tuple[MatrixRowView, ...] = ()
    """The matrix's works in its own declared order, each with a cell per declared field.

    The grid is the matrix, so it is composed here: which cell belongs where, which order
    the rows and the columns are read in, and the words every cell is stated in are the
    daemon's, not a client's (Product 5 P10).
    """


class SynthesisReport(BaseModel):
    """`GET /synthesis`: what the matrices cannot say yet, then the matrices themselves.

    A matrix reads one property across works and proposes nothing. An empty cell means
    "not recorded", never "the work lacks the property", and novelty is never inferred from
    a missing cell (Product 7.1, 33). So the gaps below are stated as gaps in the record:
    each one names a reading nobody has taken, and none of them says anything about a work.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = ""
    count: int = 0
    """How many matrices this project holds."""

    missing: int = 0
    """Readings the matrices declare and nobody has recorded yet."""

    gaps: tuple[ResearchGroup, ...] = ()
    matrices: tuple[MatrixView, ...] = ()

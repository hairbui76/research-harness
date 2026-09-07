"""Wave 3K: the three research pages the Overview's pattern reaches, composed server-side.

`GET /stale`, `GET /taxonomy` and `GET /synthesis` exist for the same reason `GET /overview`
does: which group an object belongs in, which order the groups are read in, and the words a
count is stated inside are scientific judgements, and a client that recomputed them could
disagree with the daemon about what the project holds (Product 5 P10).

Three properties are asserted hardest.

* **One account of decay.** The Stale page and the Overview's "Gone stale" group are built
  from the same items, so the two surfaces cannot report the same staleness in two different
  sets of words. Staleness is what the daemon declared; nothing here recomputes one.
* **A taxonomy is approved, not true.** A term with no Decision, one whose Decision was
  superseded, and one naming a Decision this project never recorded are three different
  gaps, and each says which it is (Product 32).
* **A matrix proposes nothing.** Every sentence about a gap is about the record, never about
  a work: no cell is read as an absence and no novelty is inferred from one (Product 7.1).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from research_harness.capabilities.context import open_context
from research_harness.capabilities.dto import (
    AcceptDecisionRequest,
    AcceptEvidenceRequest,
    InitProjectRequest,
    PutMatrixRequest,
    PutTaxonomyRequest,
)
from research_harness.capabilities.handlers import (
    accept_decision,
    accept_evidence,
    init_project,
    put_matrix,
    put_taxonomy,
)
from research_harness.capabilities.invalidation import DependencyInvalidation
from research_harness.capabilities.permissions import Principal
from research_harness.capabilities.registry import CapabilityRegistry
from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    DecisionStatus,
    DecisionType,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    ReviewAction,
    ReviewTier,
    StaleState,
    VerificationVerdict,
)
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    NumericValue,
    SourceAnchor,
)
from research_harness.domain.ids import BlockId, DecisionId, EvidenceId, SynthesisId, WorkId
from research_harness.domain.research import (
    Decision,
    MatrixCell,
    SynthesisMatrix,
    Taxonomy,
    TaxonomyTerm,
)
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.projection.rebuild import rebuild_workspace
from research_harness.protocol.dto import (
    OverviewReport,
    StaleOverview,
    SynthesisReport,
    TaxonomyReport,
)
from research_harness.server.app import (
    _matrix_columns,
    _matrix_gaps,
    _matrix_rows,
    _measured,
    _ordered_terms,
    _term_standing,
    create_app,
    ensure_token,
)
from research_harness.workspace.repository import WorkspaceRepository

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "synthetic_research_paper.pdf"
WORK = WorkId("W0001")
MATRIX = SynthesisId("S0001")
TAXONOMY = "traffic-shape"
APPROVAL = DecisionId("D0001")
UNRECORDED = DecisionId("D0404")
SPAN = EvidenceId("E0001")
SPAN_TEXT = "each record is padded to a fixed size before the flow is tokenised"
HUMAN = Provenance.human(HUMAN_ACTOR)


def _approval() -> Decision:
    """The accepted taxonomy Decision the classification below rests on (Product 32)."""
    return Decision(
        id=APPROVAL,
        type=DecisionType.TAXONOMY_REVISION,
        rationale="separate padded flows from unpadded ones",
        taxonomy_terms=("padded",),
        provenance=HUMAN,
    )


def _taxonomy() -> Taxonomy:
    """One approved term, one child nothing approves, and one naming a missing Decision."""
    return Taxonomy(
        name=TAXONOMY,
        terms=(
            TaxonomyTerm(
                term="padded", definition="records padded to a fixed size", decision=APPROVAL
            ),
            TaxonomyTerm(term="padded_fixed", parent="padded"),
            TaxonomyTerm(term="unpadded", decision=UNRECORDED),
        ),
        provenance=HUMAN,
    )


def _matrix(evidence: tuple[EvidenceId, ...] = ()) -> SynthesisMatrix:
    """One matrix that declares two readings for one work and has recorded one of them.

    The recorded cell cites the evidence it was read from, because a matrix cell is only
    as good as the span behind it (Product 9): the grid has to be able to open one.
    """
    return SynthesisMatrix(
        id=MATRIX,
        name="Traffic shape",
        taxonomy=TAXONOMY,
        works=(WORK,),
        fields=("tokenization", "dataset"),
        cells=(MatrixCell(work=WORK, field="tokenization", labels=("padded",), evidence=evidence),),
        stale=StaleState.FRESH,
        provenance=HUMAN,
    )


def _accept_span(root: Path) -> EvidenceId:
    """Accept one Evidence object anchored in the ingested paper, as the researcher.

    Written through `evidence.accept` rather than into the workspace, so the object the
    matrix cell cites is accepted state that arrived the way accepted state has to.
    """
    repo = WorkspaceRepository.open(root)
    work = repo.get_work(WORK)
    artifact = repo.get_artifact(work.artifacts[0])
    candidate = Evidence(
        id=SPAN,
        source=SourceAnchor(
            work=WORK,
            version=work.versions[0],
            artifact=artifact.id,
            file_hash=artifact.file_hash,
            block=BlockId("B0007"),
            text_hash=f"sha256:{hashlib.sha256(SPAN_TEXT.encode()).hexdigest()}",
            page=3,
            section_path=("Experiments",),
            char_start=0,
            char_end=len(SPAN_TEXT),
        ),
        content=EvidenceContent(exact_text=SPAN_TEXT, field="tokenization", labels=("padded",)),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.EXPERIMENTAL_SETUP,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_1,
        provenance=HUMAN,
    )
    accept_evidence(
        open_context(root, HUMAN_ACTOR),
        AcceptEvidenceRequest(
            candidate=candidate,
            review_action=ReviewAction.ACCEPT,
            verdict=VerificationVerdict.SUPPORTED,
            rationale="read the span in the source",
        ),
    )
    return SPAN


@pytest.fixture
def pages(tmp_path: Path, registry: CapabilityRegistry) -> Path:
    """A workspace with an approved classification, a half-read matrix, and real decay.

    Nothing here asks for a stale mark: the projection is rebuilt and the daemon's own
    invalidation hook is run over the Decision that approved the taxonomy, which is exactly
    what revising that Decision would have done (Product 37, ADR-008).
    """
    root = init_project(InitProjectRequest(root=tmp_path / "pages", name="pages")).root
    human = Principal.human()
    registry.invoke(
        "corpus.ingest", open_context(root, HUMAN_ACTOR), {"path": str(FIXTURE)}, principal=human
    )
    ctx = open_context(root, HUMAN_ACTOR)
    accept_decision(ctx, AcceptDecisionRequest(decision=_approval()))
    put_taxonomy(
        ctx,
        PutTaxonomyRequest(
            taxonomy=_taxonomy(), decision=_approval().touch(status=DecisionStatus.ACCEPTED)
        ),
    )
    put_matrix(ctx, PutMatrixRequest(matrix=_matrix((_accept_span(root),))))
    repo = WorkspaceRepository.open(root)
    rebuild_workspace(repo)
    DependencyInvalidation().invalidate(repo, [str(APPROVAL)])
    return root


@pytest.fixture
def reader(pages: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    """The daemon over that workspace, as the local researcher."""
    token = ensure_token(pages)
    with TestClient(create_app(pages, registry=registry)) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client


@pytest.fixture
def bare_reader(tmp_path: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    """The daemon over a project on its first day: no taxonomy, no matrix, no decay."""
    root = init_project(InitProjectRequest(root=tmp_path / "fresh", name="fresh")).root
    with TestClient(create_app(root, registry=registry)) as test_client:
        test_client.headers["Authorization"] = f"Bearer {ensure_token(root)}"
        yield test_client


# -- what went stale, and why ------------------------------------------------


def test_the_stale_page_groups_decay_by_the_scientific_impact_of_the_object(
    reader: TestClient,
) -> None:
    """Product 37 orders the stale set by impact; the groups are those tiers, in that order."""
    report = StaleOverview.model_validate(reader.get("/stale").json())

    assert report.count > 0
    assert [group.key for group in report.groups] == ["synthesis", "taxonomy"]
    assert [group.title for group in report.groups] == ["Synthesis matrices", "Classifications"]
    assert sum(group.count for group in report.groups) == report.reported
    assert all(group.detail for group in report.groups), "an empty group has to teach"


def test_the_stale_page_and_the_overview_report_one_decay_in_one_set_of_words(
    reader: TestClient,
) -> None:
    """Two surfaces, one account: the items are the same objects with the same reasons."""
    stale = StaleOverview.model_validate(reader.get("/stale").json())
    overview = OverviewReport.model_validate(reader.get("/overview").json())
    group = next(group for group in overview.attention if group.surface == "stale")

    first = stale.groups[0].items[0]
    assert first == group.items[0]
    assert first.detail, "a stale item without the daemon's reason is a bare id"
    assert stale.count == group.count


def test_a_stale_object_is_named_by_what_it_is_and_not_by_its_node_id(
    reader: TestClient,
) -> None:
    """A node id is how the graph holds an object, never what a researcher calls it.

    The dependency graph reports a matrix as `S0001`, one cell of it as
    `S0001#W0001#tokenization` and a classification scheme as `TX:traffic-shape`. Each of
    those is a code to decode, so the daemon composes the object's own name beside it and
    both surfaces that show stale objects read that one title (Product 5 P10).
    """
    report = StaleOverview.model_validate(reader.get("/stale").json())
    titles = {item.label: item.title for group in report.groups for item in group.items}

    assert titles["S0001"] == "Traffic shape", "a matrix is called what it was named"
    assert titles["TX:traffic-shape"] == TAXONOMY, "a scheme is called by its own name"
    assert titles["S0001#W0001#tokenization"] == (
        "tokenization · Deep Representations for Encrypted Network Traffic"
    ), "a cell is the field it reads, of the work it reads it for"
    # The id stays on the item: repairing a stale object is work done with the id.
    assert all(item.label == item.id for group in report.groups for item in group.items), (
        "the node id is still carried, as the label the page sets in mono"
    )


def test_the_reason_names_the_object_that_moved_rather_than_reporting_its_id(
    reader: TestClient,
) -> None:
    """`state.stale` records "upstream D0001 changed"; a researcher reads the Decision."""
    report = StaleOverview.model_validate(reader.get("/stale").json())
    reasons = {item.detail for group in report.groups for item in group.items}

    assert reasons == {"upstream Decision “separate padded flows from unpadded ones” changed"}
    assert str(APPROVAL) not in " ".join(reasons), "no page should have to decode D0001"


def test_the_stale_page_states_its_size_inside_a_sentence(reader: TestClient) -> None:
    report = StaleOverview.model_validate(reader.get("/stale").json())

    assert report.summary.endswith("changed.")
    assert str(report.count) in report.summary
    assert not report.summary.strip().isdigit()


def test_a_project_with_no_decay_says_so_rather_than_reporting_a_zero(
    bare_reader: TestClient,
) -> None:
    report = StaleOverview.model_validate(bare_reader.get("/stale").json())

    assert report.count == 0
    assert report.groups == ()
    assert report.summary == "Nothing in this project has gone out of date."


# -- the classification, and what nothing stands behind ----------------------


def test_the_taxonomy_page_leads_with_the_terms_no_accepted_decision_stands_behind(
    reader: TestClient,
) -> None:
    report = TaxonomyReport.model_validate(reader.get("/taxonomy").json())

    # Named for what the group is. "Waiting for a Decision" was the Overview's heading for
    # the review queue in a second capitalisation, and this group is not a queue.
    assert report.needs_decision.title == "Terms without a Decision"
    assert report.count == 3
    assert report.needs_decision.count == 2
    labels = [item.label for item in report.needs_decision.items]
    assert labels == [f"padded_fixed · {TAXONOMY}", f"unpadded · {TAXONOMY}"]
    details = [item.detail for item in report.needs_decision.items]
    assert details[0] == "no Decision approves it yet"
    assert details[1] == "D0404 is named as its approval but is not recorded here"
    assert report.summary.startswith("2 terms have no accepted Decision")


def test_the_taxonomy_page_walks_the_tree_so_no_client_rebuilds_it(reader: TestClient) -> None:
    """The classification is a tree; the daemon orders it and states each term's depth."""
    report = TaxonomyReport.model_validate(reader.get("/taxonomy").json())
    terms = report.taxonomies[0].terms

    assert [term.term for term in terms] == ["padded", "padded_fixed", "unpadded"]
    assert [term.depth for term in terms] == [0, 1, 0]
    assert [term.approved for term in terms] == [True, False, False]
    assert terms[0].decision_status == "accepted"
    assert report.taxonomies[0].summary == "3 terms, 2 of them without an accepted Decision"


def test_a_superseded_decision_no_longer_approves_the_term_it_approved() -> None:
    """A revision is a Decision, so a term it superseded needs a researcher again (ADR-008)."""
    superseded = _approval().touch(status=DecisionStatus.SUPERSEDED)
    proposed = _approval().touch(status=DecisionStatus.PROPOSED)
    term = TaxonomyTerm(term="padded", decision=APPROVAL)

    assert _term_standing(term, {str(APPROVAL): superseded}) == (
        False,
        "superseded",
        "D0001 approved it and has since been superseded",
    )
    assert _term_standing(term, {str(APPROVAL): proposed}) == (
        False,
        "proposed",
        "D0001 proposes it and has not been accepted",
    )


def test_a_term_the_tree_cannot_be_reached_from_is_still_reported() -> None:
    """A cycle is a broken classification, not a reason to drop a term off the page."""
    taxonomy = Taxonomy(
        name="cyclic",
        terms=(
            TaxonomyTerm(term="a", parent="b"),
            TaxonomyTerm(term="b", parent="a"),
            TaxonomyTerm(term="root"),
        ),
        provenance=HUMAN,
    )

    walked = _ordered_terms(taxonomy)

    assert sorted(str(term.term) for term, _ in walked) == ["a", "b", "root"]
    assert walked[0][0].term == "root"


def test_a_project_with_no_classification_says_it_has_agreed_none(
    bare_reader: TestClient,
) -> None:
    report = TaxonomyReport.model_validate(bare_reader.get("/taxonomy").json())

    assert report.taxonomies == ()
    assert report.summary == "This project has agreed no classification yet."
    assert report.needs_decision.detail, "an empty group still teaches what a Decision is for"


# -- the matrices, and what they cannot say yet ------------------------------


def test_the_synthesis_page_names_the_readings_nobody_has_recorded(reader: TestClient) -> None:
    report = SynthesisReport.model_validate(reader.get("/synthesis").json())

    assert report.count == 1
    assert report.missing == 1
    gap = report.gaps[0]
    assert gap.title == "Traffic shape"
    assert gap.summary == "1 reading this matrix declares has not been recorded"
    assert [item.label for item in gap.items] == ["dataset"]
    assert gap.items[0].detail == "no work in this matrix has been read for it yet"


def test_a_gap_is_stated_about_the_record_and_never_about_a_work(reader: TestClient) -> None:
    """An unread cell is not an absence, and novelty is never inferred from one (Product 33)."""
    report = SynthesisReport.model_validate(reader.get("/synthesis").json())
    # Every sentence a reader takes as a finding: the page's line, each gap's line, each
    # item's reason, and what each matrix says about how much of itself has been recorded.
    stated = [
        report.summary,
        *(group.summary for group in report.gaps),
        *(item.detail for group in report.gaps for item in group.items),
        *(matrix.coverage for matrix in report.matrices),
        *(matrix.shape for matrix in report.matrices),
        *(matrix.labels_from for matrix in report.matrices),
        *(column.coverage for matrix in report.matrices for column in matrix.columns),
        *(column.reading for matrix in report.matrices for column in matrix.columns),
        *(row.summary for matrix in report.matrices for row in matrix.rows),
        *(cell.detail for matrix in report.matrices for row in matrix.rows for cell in row.cells),
    ]
    for sentence in stated:
        lowered = sentence.lower()
        for forbidden in ("lacks", "absent", "novel", "first to", "does not have"):
            assert forbidden not in lowered, sentence

    # The rule itself is said out loud, once, where an empty cell is explained.
    assert "never means the work lacks the property" in report.gaps[0].detail


def test_the_synthesis_page_states_each_matrix_in_words(reader: TestClient) -> None:
    report = SynthesisReport.model_validate(reader.get("/synthesis").json())
    matrix = report.matrices[0]

    assert matrix.shape == "1 work read for 2 fields"
    assert matrix.coverage == "1 of 2 readings recorded"
    assert matrix.recorded == 1
    assert matrix.stale in {"fresh", "stale"}


def test_a_work_with_no_row_is_a_gap_in_the_matrix_not_a_gap_in_the_corpus() -> None:
    items = _matrix_gaps(
        "S0001", ("W0001",), ("tokenization",), {("W0001", "tokenization")}, ("W0002", "W0003")
    )

    assert [item.label for item in items] == ["W0002", "W0003"]
    assert all(item.detail == "this matrix has no row for it" for item in items)
    assert items[0].route == "/corpus/W0002"


def test_a_project_with_no_matrix_says_what_a_matrix_would_do(bare_reader: TestClient) -> None:
    report = SynthesisReport.model_validate(bare_reader.get("/synthesis").json())

    assert report.matrices == ()
    assert report.gaps == ()
    assert report.summary.startswith("No matrix has been built yet")


# -- the matrix as a grid ----------------------------------------------------


def test_a_matrix_arrives_as_the_grid_it_is_in_the_order_it_declares(reader: TestClient) -> None:
    """Rows are the matrix's works and columns its fields, both in its own declared order.

    Which cell belongs where is the matrix's own structure, so the daemon composes it. A
    client that paired works with fields itself could disagree with the record about what
    was read for what (Product 5 P10).
    """
    report = SynthesisReport.model_validate(reader.get("/synthesis").json())
    matrix = report.matrices[0]

    assert [column.field for column in matrix.columns] == ["tokenization", "dataset"]
    assert [row.work for row in matrix.rows] == [str(WORK)]
    row = matrix.rows[0]
    assert [cell.field for cell in row.cells] == ["tokenization", "dataset"]
    assert row.title, "a row is headed by the work's own title, not by its id alone"
    assert row.route == f"/corpus/{WORK}"
    assert row.summary == "1 of 2 readings recorded"


def test_a_cell_nobody_has_read_states_the_gap_and_reads_nothing_into_it(
    reader: TestClient,
) -> None:
    """A blank cell is a gap in the record: it says so in words and claims nothing."""
    report = SynthesisReport.model_validate(reader.get("/synthesis").json())
    blank = next(
        cell for row in report.matrices[0].rows for cell in row.cells if cell.field == "dataset"
    )

    assert blank.recorded is False
    assert blank.reading == ""
    assert blank.evidence == ()
    assert "gap in the record" in blank.detail
    assert "never a reading of the work" in blank.detail


def test_a_recorded_cell_carries_the_evidence_it_rests_on(reader: TestClient) -> None:
    """A reading is only as good as its source, so the cell opens onto the exact span."""
    report = SynthesisReport.model_validate(reader.get("/synthesis").json())
    cell = next(
        cell
        for row in report.matrices[0].rows
        for cell in row.cells
        if cell.field == "tokenization"
    )

    assert cell.recorded is True
    assert cell.reading == "padded"
    assert cell.detail == "Read from 1 accepted evidence span."
    span = cell.evidence[0]
    assert span.id == str(SPAN)
    assert span.found is True
    assert span.quote == SPAN_TEXT, "the recorded span is quoted exactly, never shortened"
    assert span.route == f"/evidence/{SPAN}"
    assert span.title, "the span is named the way the review queue named it"


def test_a_cell_citing_evidence_the_workspace_no_longer_holds_says_so() -> None:
    """An id nothing answers to is reported as unresolved rather than as a quotable span."""
    matrix = _matrix((EvidenceId("E0404"),))

    rows = _matrix_rows(matrix, {}, lambda _object_id: "")

    span = rows[0].cells[0].evidence[0]
    assert span.found is False
    assert span.quote == ""
    assert span.title == ""
    assert "no longer" in rows[0].cells[0].detail


def test_a_column_states_how_it_reads_across_the_works_without_preferring_one() -> None:
    """Two works read differently is a fact about the record, stated as counts of it."""
    matrix = SynthesisMatrix(
        id=MATRIX,
        name="Traffic shape",
        works=(WORK, WorkId("W0002"), WorkId("W0003")),
        fields=("dataset", "tokenization"),
        cells=(
            MatrixCell(work=WORK, field="dataset", labels=("cicids2017",)),
            MatrixCell(work=WorkId("W0002"), field="dataset", labels=("unsw_nb15",)),
        ),
        provenance=HUMAN,
    )

    dataset, tokenization = _matrix_columns(matrix)

    assert dataset.recorded == 2
    assert dataset.coverage == "2 of 3 works read for it"
    assert dataset.reading == (
        "2 of 3 works read for it. Recorded: cicids2017 (1 work), unsw_nb15 (1 work). "
        "The works read for it do not all record the same label."
    )
    assert tokenization.recorded == 0
    assert tokenization.coverage == "No work in this matrix has been read for it yet"
    assert tokenization.reading == (
        "No work in this matrix has been read for it yet, so there is nothing to read across it."
    )


def test_a_measured_reading_keeps_the_metric_and_the_unit_it_was_recorded_with() -> None:
    """Product 12: a number without its metric and its unit is not the number that was read."""
    numeric = NumericValue(
        raw="94.32",
        parsed=94.32,
        unit="percent",
        metric="F1",
        dataset="CICIDS2017",
        source_table="T004",
    )

    assert _measured(numeric) == "F1 94.32 percent"
    assert _measured(numeric.model_copy(update={"unit": None})) == "F1 94.32"


def test_the_grid_says_which_vocabulary_its_labels_come_from(reader: TestClient) -> None:
    """A taxonomy is a project's approved decision, so the grid names the one it used."""
    report = SynthesisReport.model_validate(reader.get("/synthesis").json())

    assert report.matrices[0].labels_from == "Its labels come from the traffic-shape taxonomy."


# -- the reads stay reads ----------------------------------------------------


@pytest.mark.parametrize("route", ["/stale", "/taxonomy", "/synthesis"])
def test_none_of_the_three_pages_has_a_route_that_writes(reader: TestClient, route: str) -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert reader.request(method, route).status_code == 405


@pytest.mark.parametrize("route", ["/stale", "/taxonomy", "/synthesis"])
def test_an_agent_host_may_read_what_it_is_asked_to_reason_about(
    pages: Path, registry: CapabilityRegistry, route: str
) -> None:
    with TestClient(create_app(pages, registry=registry)) as host:
        assert host.get(route).status_code == 200

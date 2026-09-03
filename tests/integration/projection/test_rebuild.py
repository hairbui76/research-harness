"""Rebuilding the projection: fail closed, never write canonical state, and be deterministic."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from research_harness.domain import (
    ArtifactId,
    ClaimEvidenceRelation,
    ClaimEvidenceRelationType,
    ClaimId,
    Coverage,
    DecisionId,
    DocumentBlockKind,
    EvidenceContent,
    EvidenceId,
    ManuscriptAnchor,
    MatrixCell,
    OverturnRisk,
    ParsedDocument,
    ResearchEvent,
    ResearchEventType,
    SearchRunId,
    StaleState,
    SynthesisId,
    SynthesisMatrix,
    TableCell,
    Taxonomy,
    TaxonomyTerm,
    VersionId,
    WorkId,
)
from research_harness.projection import (
    STALE_MARKS,
    StalePriority,
    create_all,
    create_engine_for,
    load_stale_marks,
)
from research_harness.projection.rebuild import (
    CANONICAL_STALE_REASON,
    UPSTREAM_UPDATED_REASON,
    canonical_digest,
    dump_projection,
    iter_canonical_files,
    rebuild_workspace,
    verify_rebuild,
)
from research_harness.workspace.events import verify_consistency
from research_harness.workspace.repository import WorkspaceRepository
from tests.unit.domain import strategies as sty

WORK = WorkId("W0017")
VERSION = VersionId("V0017-2")
ARTIFACT = ArtifactId("A0017-3")
CLAIM = ClaimId("C0041")
DECISION = DecisionId("D0027")
EVIDENCE_ID = EvidenceId("E0482")
MATRIX = SynthesisId("S0007")
SEARCH_RUN = SearchRunId("SR0019")
ANCHOR_FILE = "manuscript/main.tex"
NOTE_KEY = "note-20260105-000000-abcdef"
DATASET = "CICIDS2017"

PDF_BYTES = b"%PDF-1.7\nsynthetic artifact bytes\n"
PDF_HASH = f"sha256:{hashlib.sha256(PDF_BYTES).hexdigest()}"

# Timestamps ordered so that every dependency is older than what depends on it: a freshly
# built workspace must contain no staleness at all.
T0 = datetime(2026, 1, 1, tzinfo=UTC)  # work, version, artifact
T1 = datetime(2026, 1, 2, tzinfo=UTC)  # parsed blocks
T2 = datetime(2026, 1, 3, tzinfo=UTC)  # evidence, decision, search run
T3 = datetime(2026, 1, 4, tzinfo=UTC)  # taxonomy
T4 = datetime(2026, 1, 5, tzinfo=UTC)  # claim, matrix, note
T5 = datetime(2026, 1, 6, tzinfo=UTC)  # question, manuscript anchor
T6 = datetime(2026, 1, 7, tzinfo=UTC)  # a later revision of the decision


def _tracked(moment: datetime) -> dict[str, datetime]:
    return {"created_at": moment, "updated_at": moment}


def _event(kind: ResearchEventType, summary: str) -> ResearchEvent:
    return ResearchEvent(event=kind, actor="human:alice", summary=summary, occurred_at=T4)


def populated_workspace(root: Path) -> WorkspaceRepository:
    """A workspace holding one of every canonical object, in containment order.

    Shared with the Gate P3 end-to-end test so both exercise the same corpus.
    """
    repo = WorkspaceRepository.init(root, "structured-traffic")
    work = sty.make_work(versions=(VERSION,), artifacts=(ARTIFACT,), **_tracked(T0))
    version = sty.make_version(**_tracked(T0))
    artifact = sty.make_artifact(file_hash=PDF_HASH, size_bytes=len(PDF_BYTES), **_tracked(T0))
    paragraph = sty.make_block(
        text=f"We evaluate on {DATASET}. The {DATASET} split is standard.", **_tracked(T1)
    )
    table = sty.make_block(
        id="B0082",
        kind=DocumentBlockKind.TABLE,
        order=13,
        text="model F1",
        section_path=("Discussion", "Limitations"),
        cells=(TableCell(row=0, col=0, text="model"), TableCell(row=0, col=1, text="F1")),
        **_tracked(T1),
    )
    document = ParsedDocument(
        work=WORK,
        version=VERSION,
        artifact=ARTIFACT,
        file_hash=PDF_HASH,
        parser_name="pymupdf",
        parser_version="1.24.0",
        page_count=12,
        blocks=(paragraph, table),
        provenance=sty.SYSTEM,
        **_tracked(T1),
    )
    evidence = sty.make_evidence(
        content=EvidenceContent(exact_text=f"We evaluate on {DATASET}."), **_tracked(T2)
    )
    decision = sty.make_override_decision(**_tracked(T2))
    search_run = sty.make_search_run(**_tracked(T2))
    taxonomy = Taxonomy(
        name="representation",
        terms=(TaxonomyTerm(term="byte_level", decision=DECISION),),
        provenance=sty.HUMAN,
        **_tracked(T3),
    )
    claim = sty.make_claim(
        relations=(
            ClaimEvidenceRelation(
                evidence=EVIDENCE_ID, relation=ClaimEvidenceRelationType.SUPPORTS
            ),
        ),
        decisions=(DECISION,),
        coverage=Coverage(
            relevant_works=17,
            examined_works=14,
            unresolved_works=3,
            overturn_risk=OverturnRisk.LOW_MODERATE,
            search_runs=(SEARCH_RUN,),
        ),
        **_tracked(T4),
    )
    matrix = SynthesisMatrix(
        id=MATRIX,
        name="representation matrix",
        taxonomy="representation",
        works=(WORK,),
        fields=("tokenization",),
        cells=(
            MatrixCell(
                work=WORK,
                field="tokenization",
                labels=("byte_level",),
                evidence=(EVIDENCE_ID,),
            ),
        ),
        provenance=sty.HUMAN,
        **_tracked(T4),
    )
    note = sty.make_note(key=NOTE_KEY, **_tracked(T4))
    question = sty.make_question(claims=(CLAIM,), search_runs=(SEARCH_RUN,), **_tracked(T5))
    anchor = ManuscriptAnchor(
        file=ANCHOR_FILE,
        line_start=41,
        line_end=41,
        sentence="Representations differ in tokenization granularity.",
        sentence_fingerprint=sty.HASH_C,
        claim=CLAIM,
        provenance=sty.HUMAN,
        **_tracked(T5),
    )
    with repo.transaction(_event(ResearchEventType.WORK_INGESTED, "ingest W0017")) as tx:
        tx.put(work)
        tx.put(version)
        tx.put(artifact)
        tx.store_artifact_bytes(artifact, PDF_BYTES)
        tx.put(document)
        tx.put(evidence)
        tx.put(decision)
        tx.put(search_run)
        tx.put(taxonomy)
        tx.put(claim)
        tx.put(matrix)
        tx.put(note)
        tx.put(question)
        tx.put(anchor)
    return repo


def revise_the_decision(repo: WorkspaceRepository) -> None:
    """Accept a later revision of D0027, which everything below it predates."""
    revised = sty.make_override_decision(
        rationale="Revised after re-reading the coverage.", created_at=T2, updated_at=T6
    )
    with repo.transaction(_event(ResearchEventType.DECISION_ACCEPTED, "revise D0027")) as tx:
        tx.put(revised)


@pytest.fixture
def repo(tmp_path: Path) -> WorkspaceRepository:
    return populated_workspace(tmp_path / "project")


@pytest.fixture
def engine(repo: WorkspaceRepository) -> Iterator[Engine]:
    built = create_engine_for(repo.layout.database_file)
    yield built
    built.dispose()


def tree_digest(root: Path) -> str:
    """Digest of every file outside `.research/`, so a canonical write cannot hide."""
    material = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".research" in path.parts:
            continue
        material.append(f"{path.relative_to(root)}:{hashlib.sha256(path.read_bytes()).hexdigest()}")
    return hashlib.sha256("\n".join(material).encode()).hexdigest()


def _without_events(counts: dict[str, int]) -> dict[str, int]:
    """Counts minus the event log, whose size depends on how the workspace was built."""
    return {name: count for name, count in counts.items() if name != "ResearchEvent"}


def _count(built: Engine, table: object) -> int:
    with built.connect() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


# --- the happy path ---------------------------------------------------------


def test_rebuild_projects_every_canonical_object(repo: WorkspaceRepository) -> None:
    report = rebuild_workspace(repo)

    assert report.ok
    assert report.invalid_files == ()
    assert _without_events(report.objects_by_type) == {
        "Work": 1,
        "Version": 1,
        "Artifact": 1,
        "DocumentBlock": 2,
        "Evidence": 1,
        "Claim": 1,
        "Decision": 1,
        "ResearchQuestion": 1,
        "Taxonomy": 1,
        "SearchRun": 1,
        "SynthesisMatrix": 1,
        "ResearchNote": 1,
        "ManuscriptAnchor": 1,
    }
    assert report.objects_by_type["ResearchEvent"] >= 1
    assert report.fts_rows == 6  # 2 blocks + evidence + claim + work + note
    assert report.canonical_digest.startswith("sha256:")
    assert repo.layout.database_file.is_file()


def test_verify_rebuild_finds_no_discrepancy(repo: WorkspaceRepository, engine: Engine) -> None:
    rebuild_workspace(repo)

    assert verify_rebuild(repo, engine) == []


def test_verify_rebuild_reports_an_object_the_projection_never_saw(
    repo: WorkspaceRepository, engine: Engine
) -> None:
    rebuild_workspace(repo)
    with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "add C0042")) as tx:
        tx.put(sty.make_claim(id=ClaimId("C0042"), relations=(), **_tracked(T5)))

    issues = verify_rebuild(repo, engine)

    assert any("claims" in issue and "C0042" in issue for issue in issues)


def test_rebuild_writes_the_dependency_edges_and_projection_metadata(
    repo: WorkspaceRepository, engine: Engine
) -> None:
    from research_harness.projection import DEPENDENCIES, PROJECTION_META, PROJECTION_SCHEMA_VERSION

    report = rebuild_workspace(repo)

    assert _count(engine, DEPENDENCIES) > 0
    with engine.connect() as connection:
        meta = connection.execute(select(PROJECTION_META)).mappings().one()
    assert meta["schema_version"] == PROJECTION_SCHEMA_VERSION
    assert meta["canonical_digest"] == report.canonical_digest
    assert meta["fts_version"]


def test_rebuild_accepts_an_explicit_research_dir(
    repo: WorkspaceRepository, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "index"

    report = rebuild_workspace(repo, research_dir=elsewhere)

    assert report.ok
    assert (elsewhere / "research.db").is_file()


# --- fail closed ------------------------------------------------------------


def _corrupt_claim(repo: WorkspaceRepository) -> Path:
    path = repo.layout.claim_file(CLAIM)
    path.write_text(f"{path.read_text(encoding='utf-8')}not_a_claim_field: 1\n", encoding="utf-8")
    return path


def test_rebuild_reports_an_invalid_canonical_file_instead_of_projecting_it(
    repo: WorkspaceRepository,
) -> None:
    corrupted = _corrupt_claim(repo)

    report = rebuild_workspace(repo)

    assert not report.ok
    assert [invalid.path for invalid in report.invalid_files] == [
        str(repo.layout.relative(corrupted))
    ]
    assert "not_a_claim_field" in report.invalid_files[0].error
    assert not repo.layout.database_file.exists()


def test_an_invalid_file_leaves_an_existing_projection_byte_for_byte(
    repo: WorkspaceRepository,
) -> None:
    rebuild_workspace(repo)
    database = repo.layout.database_file
    before = (database.read_bytes(), database.stat().st_mtime_ns)
    _corrupt_claim(repo)

    report = rebuild_workspace(repo)

    assert not report.ok
    assert (database.read_bytes(), database.stat().st_mtime_ns) == before


def test_rebuild_leaves_no_temporary_database_behind(repo: WorkspaceRepository) -> None:
    rebuild_workspace(repo)
    _corrupt_claim(repo)
    rebuild_workspace(repo)

    leftovers = sorted(path.name for path in repo.layout.research_dir.glob("*rebuild-*"))
    assert leftovers == []


# --- canonical state is never written ---------------------------------------


def test_rebuild_never_changes_canonical_files(repo: WorkspaceRepository) -> None:
    before = tree_digest(repo.root)

    rebuild_workspace(repo)
    rebuild_workspace(repo)

    assert tree_digest(repo.root) == before


def test_the_canonical_digest_covers_canonical_files_and_ignores_the_projection(
    repo: WorkspaceRepository,
) -> None:
    covered = {str(repo.layout.relative(path)) for path in iter_canonical_files(repo.layout)}

    assert "research.yaml" in covered
    assert f"corpus/works/{WORK}/work.yaml" in covered
    assert f"corpus/works/{WORK}/artifacts/{ARTIFACT}.pdf" in covered
    assert "manuscript/anchors.jsonl" in covered
    assert not any(name.startswith(".research/") for name in covered)
    assert not any(name.startswith(".gitignore") for name in covered)


def test_the_canonical_digest_changes_only_when_canonical_state_changes(
    repo: WorkspaceRepository,
) -> None:
    before = canonical_digest(repo)
    rebuild_workspace(repo)
    assert canonical_digest(repo) == before

    revise_the_decision(repo)

    assert canonical_digest(repo) != before


def test_the_canonical_digest_is_sha256_over_each_file_s_bytes(repo: WorkspaceRepository) -> None:
    """It is derivable with `sha256sum`, without loading a single canonical object."""
    entries = sorted(
        f"{repo.layout.relative(path)}\tsha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        for path in iter_canonical_files(repo.layout)
    )
    expected = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()

    assert canonical_digest(repo) == f"sha256:{expected}"


def test_reformatting_a_file_moves_the_projection_digest_but_not_the_workspace(
    repo: WorkspaceRepository,
) -> None:
    """The trade Decision 2 makes, asserted from both sides.

    Digesting bytes instead of re-serializing every record is what brings a rebuild inside
    its budget, and the cost is that a hand-reformatted YAML file no longer keeps the same
    *projection* digest. It still does not fail the workspace closed: the event log records
    per-object digests, and `verify_consistency` re-derives those from the parsed object.
    """
    before = canonical_digest(repo)
    path = repo.layout.claim_file(CLAIM)
    path.write_text(path.read_text(encoding="utf-8") + "# a hand-written comment\n")

    assert canonical_digest(repo) != before
    assert verify_consistency(repo.layout).consistent


# --- determinism ------------------------------------------------------------


def test_two_rebuilds_produce_identical_tables_and_digest(repo: WorkspaceRepository) -> None:
    first = rebuild_workspace(repo)
    engine = create_engine_for(repo.layout.database_file)
    dump_one = dump_projection(engine)
    engine.dispose()

    second = rebuild_workspace(repo)
    engine = create_engine_for(repo.layout.database_file)
    dump_two = dump_projection(engine)
    engine.dispose()

    assert dump_one == dump_two
    assert dump_one != ""
    assert first.canonical_digest == second.canonical_digest
    assert first.objects_by_type == second.objects_by_type
    assert first.stale_marks == second.stale_marks


# --- staleness recomputed from canonical facts ------------------------------


def test_a_workspace_whose_dependencies_all_predate_it_has_no_stale_marks(
    repo: WorkspaceRepository, engine: Engine
) -> None:
    report = rebuild_workspace(repo)

    assert report.stale_marks == 0
    assert _count(engine, STALE_MARKS) == 0


def test_an_upstream_decision_updated_after_a_claim_marks_the_claim_and_its_anchor(
    repo: WorkspaceRepository, engine: Engine
) -> None:
    revise_the_decision(repo)

    report = rebuild_workspace(repo)

    assert report.stale_marks > 0
    with engine.connect() as connection:
        marks = load_stale_marks(connection)
    by_object = {mark.object_id: mark for mark in marks}
    claim_mark = by_object[str(CLAIM)]
    anchor_mark = by_object[f"MA:{ANCHOR_FILE}#{sty.HASH_C}"]
    assert claim_mark.priority is StalePriority.CLAIM
    assert anchor_mark.priority is StalePriority.MANUSCRIPT_ANCHOR
    assert claim_mark.reason == UPSTREAM_UPDATED_REASON
    assert claim_mark.source_change == str(DECISION)
    # PRODUCT 42 I: a revised taxonomy decision reaches the matrix and the manuscript.
    assert {str(MATRIX), "TX:representation"} <= set(by_object)


def test_stale_marks_are_dated_by_the_change_not_by_the_rebuild(
    repo: WorkspaceRepository, engine: Engine
) -> None:
    revise_the_decision(repo)

    rebuild_workspace(repo)

    with engine.connect() as connection:
        since = connection.execute(select(STALE_MARKS.c.since).distinct()).scalars().all()
    assert [str(value) for value in since] == [T6.isoformat()]


def test_a_canonical_stale_flag_becomes_a_stale_mark(
    repo: WorkspaceRepository, engine: Engine
) -> None:
    stale_question = sty.make_question(
        claims=(CLAIM,), search_runs=(SEARCH_RUN,), stale=StaleState.STALE, **_tracked(T5)
    )
    with repo.transaction(_event(ResearchEventType.QUESTION_UPDATED, "RQ0003 is stale")) as tx:
        tx.put(stale_question)

    rebuild_workspace(repo)

    with engine.connect() as connection:
        marks = {mark.object_id: mark for mark in load_stale_marks(connection)}
    assert marks[str(stale_question.id)].reason == CANONICAL_STALE_REASON
    assert marks[str(stale_question.id)].source_change == str(stale_question.id)


# --- an empty workspace -----------------------------------------------------


def test_rebuilding_an_empty_workspace_succeeds_with_nothing_to_project(tmp_path: Path) -> None:
    empty = WorkspaceRepository.init(tmp_path / "empty", "nothing yet")

    report = rebuild_workspace(empty)

    assert report.ok
    assert set(_without_events(report.objects_by_type).values()) == {0}
    assert report.fts_rows == 0
    assert report.stale_marks == 0
    engine = create_engine_for(empty.layout.database_file)
    try:
        assert verify_rebuild(empty, engine) == []
    finally:
        engine.dispose()


def test_verify_rebuild_flags_a_database_no_rebuild_ever_wrote(tmp_path: Path) -> None:
    empty = WorkspaceRepository.init(tmp_path / "bare", "bare")
    engine = create_engine_for(empty.layout.database_file)
    create_all(engine)
    try:
        assert any("projection_meta" in issue for issue in verify_rebuild(empty, engine))
    finally:
        engine.dispose()

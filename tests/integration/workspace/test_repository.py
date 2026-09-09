"""Canonical reads and writes: one transaction per accepted-state mutation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research_harness.domain import (
    Artifact,
    ArtifactId,
    ArtifactKind,
    ClaimId,
    DecisionId,
    ManuscriptAnchor,
    ParsedDocument,
    Provenance,
    QuestionId,
    ResearchEvent,
    ResearchEventType,
    ResearchNote,
    ReviewPolicy,
    SearchRunId,
    SynthesisId,
    SynthesisMatrix,
    Taxonomy,
    TaxonomyTerm,
    Version,
    VersionId,
    VersionKind,
    WorkId,
)
from research_harness.domain.errors import WorkspaceError
from research_harness.workspace.layout import NOTE_KEY_PATTERN, WorkspaceLayout
from research_harness.workspace.migrations import (
    CURRENT_SCHEMA_VERSION,
    UnsupportedSchemaVersionError,
)
from research_harness.workspace.repository import (
    STORED_PARSER_NAME,
    STORED_PARSER_VERSION,
    ArtifactImmutableError,
    ObjectNotFoundError,
    WorkspaceConfig,
    WorkspaceInconsistentError,
    WorkspaceNotFoundError,
    WorkspaceRepository,
)
from research_harness.workspace.serialization import dump_yaml, read_yaml
from tests.unit.domain.strategies import (
    HASH_B,
    HUMAN,
    SYSTEM,
    make_block,
    make_claim,
    make_evidence,
    make_note,
    make_override_decision,
    make_question,
    make_search_run,
    make_work,
)

WORK = WorkId("W0017")
VERSION = VersionId("V0017-2")
ARTIFACT = ArtifactId("A0017-3")
PDF_BYTES = b"%PDF-1.7\nsynthetic artifact bytes\n"
PDF_HASH = f"sha256:{hashlib.sha256(PDF_BYTES).hexdigest()}"


def _event(kind: ResearchEventType, summary: str) -> ResearchEvent:
    return ResearchEvent(event=kind, actor="human:alice", summary=summary)


def _kinds(repo: WorkspaceRepository) -> list[ResearchEventType]:
    """Every recorded event kind, oldest first; a fresh workspace already has one."""
    return [event.event for event in repo.iter_events()]


def _last_event(repo: WorkspaceRepository) -> ResearchEvent:
    """The newest event, i.e. the one the transaction under test wrote."""
    return list(repo.iter_events())[-1]


def _artifact(**overrides: object) -> Artifact:
    fields: dict[str, object] = {
        "id": ARTIFACT,
        "work": WORK,
        "version": VERSION,
        "kind": ArtifactKind.PDF,
        "file_hash": PDF_HASH,
        "original_filename": "paper.pdf",
        "mime_type": "application/pdf",
        "size_bytes": len(PDF_BYTES),
        "provenance": SYSTEM,
    }
    return Artifact(**{**fields, **overrides})  # type: ignore[arg-type]


@pytest.fixture
def repo(tmp_path: Path) -> WorkspaceRepository:
    return WorkspaceRepository.init(tmp_path / "project", "structured-traffic")


# -- lifecycle ---------------------------------------------------------------


def test_init_records_name_policy_and_schema_version(repo: WorkspaceRepository) -> None:
    config = read_yaml(repo.layout.research_file, WorkspaceConfig)
    assert config.name == "structured-traffic"
    assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert config.review_policy is ReviewPolicy.STRICT
    assert config.id_counters == {}
    assert config.created_at.tzinfo is not None


def test_init_accepts_an_explicit_review_policy(tmp_path: Path) -> None:
    repo = WorkspaceRepository.init(tmp_path, "batch project", policy="policy_batch")
    assert repo.review_policy is ReviewPolicy.POLICY_BATCH
    assert WorkspaceRepository.open(tmp_path).review_policy is ReviewPolicy.POLICY_BATCH


def test_open_reads_back_what_init_wrote(repo: WorkspaceRepository) -> None:
    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.config == repo.config
    assert reopened.consistency.consistent
    assert not reopened.recovery.changed


def test_open_without_a_workspace_fails_with_a_useful_error(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceNotFoundError, match=r"research\.yaml"):
        WorkspaceRepository.open(tmp_path / "nothing-here")


# -- typed put/get -----------------------------------------------------------


def test_put_and_get_round_trip_every_canonical_type(repo: WorkspaceRepository) -> None:
    work = make_work()
    version = Version(id=VERSION, work=WORK, kind=VersionKind.ARXIV, label="v2", provenance=SYSTEM)
    artifact = _artifact()
    claim = make_claim()
    decision = make_override_decision()
    question = make_question()
    matrix = SynthesisMatrix(id=SynthesisId("S0002"), name="coverage", provenance=HUMAN)
    search_run = make_search_run()
    taxonomy = Taxonomy(name="tokenization", terms=(TaxonomyTerm(term="byte"),), provenance=HUMAN)

    with repo.transaction(_event(ResearchEventType.WORK_INGESTED, "ingest W0017")) as tx:
        for obj in (
            work,
            version,
            artifact,
            claim,
            decision,
            question,
            matrix,
            search_run,
            taxonomy,
        ):
            tx.put(obj)

    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.get_work(WORK) == work
    assert reopened.get_version(VERSION) == version
    assert reopened.get_version(VERSION, work=WORK) == version
    assert reopened.get_artifact(ARTIFACT) == artifact
    assert reopened.get_claim(ClaimId("C0041")) == claim
    assert reopened.get_decision(DecisionId("D0027")) == decision
    assert reopened.get_question(QuestionId("RQ0003")) == question
    assert reopened.get_matrix(SynthesisId("S0002")) == matrix
    assert reopened.get_search_run(SearchRunId("SR0019")) == search_run
    assert reopened.get_taxonomy("tokenization") == taxonomy

    assert reopened.list_works() == [work]
    assert reopened.list_claims() == [claim]
    assert reopened.list_decisions() == [decision]
    assert reopened.list_questions() == [question]
    assert reopened.list_versions(WORK) == [version]
    assert reopened.list_artifacts(WORK) == [artifact]


def test_a_missing_object_raises_object_not_found(repo: WorkspaceRepository) -> None:
    with pytest.raises(ObjectNotFoundError, match="C9999"):
        repo.get_claim(ClaimId("C9999"))
    with pytest.raises(ObjectNotFoundError, match="tokenization"):
        repo.get_taxonomy("tokenization")


def test_an_empty_workspace_lists_nothing(repo: WorkspaceRepository) -> None:
    assert repo.list_works() == []
    assert repo.list_claims() == []
    assert list(repo.iter_notes()) == []
    assert list(repo.iter_anchors()) == []
    assert list(repo.iter_evidence(WORK)) == []


def test_init_opens_the_event_log_with_the_project_initialized_event(
    repo: WorkspaceRepository,
) -> None:
    """Creating the workspace is a state change, so the log says which project it is."""
    (event,) = list(repo.iter_events())

    assert event.event is ResearchEventType.PROJECT_INITIALIZED
    assert repo.config.name in event.summary
    assert event.subjects == ()
    assert event.objects == {}
    assert list(WorkspaceRepository.open(repo.root).iter_events()) == [event]


def test_the_initialization_event_lands_in_the_same_transaction_as_the_layout(
    tmp_path: Path,
) -> None:
    """No half-built workspace and no orphan event: both files land, or neither does."""
    root = tmp_path / "fresh"
    created = WorkspaceRepository.init(root, "fresh project")

    assert created.layout.research_file.is_file()
    assert created.layout.events_file.read_bytes().count(b"\n") == 1
    assert WorkspaceRepository.open(root).consistency.consistent


def test_a_note_captured_without_a_key_is_given_one(repo: WorkspaceRepository) -> None:
    with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "capture a note")) as tx:
        note, path = tx.put_note(make_note())

    assert note.key is not None
    assert NOTE_KEY_PATTERN.match(note.key)
    assert path.name == f"{note.key}.yaml"
    assert list(WorkspaceRepository.open(repo.root).iter_notes()) == [note]


def test_a_note_keeps_a_key_it_already_has(repo: WorkspaceRepository) -> None:
    with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "capture a note")) as tx:
        note, _ = tx.put_note(make_note(key="terminology-mismatch"))
    assert note.key == "terminology-mismatch"


# -- append-only collections -------------------------------------------------


def test_evidence_is_appended_to_its_work_and_read_back_latest_first(
    repo: WorkspaceRepository,
) -> None:
    evidence = make_evidence()
    with repo.transaction(_event(ResearchEventType.EVIDENCE_ACCEPTED, "accept E0482")) as tx:
        tx.append_evidence(evidence)

    reopened = WorkspaceRepository.open(repo.root)
    assert list(reopened.iter_evidence(WORK)) == [evidence]

    qualified = evidence.touch(qualification="test split only")
    with reopened.transaction(_event(ResearchEventType.CLAIM_QUALIFIED, "qualify E0482")) as tx:
        tx.append_evidence(qualified)

    final = WorkspaceRepository.open(repo.root)
    assert list(final.iter_evidence(WORK)) == [qualified]
    assert list(final.iter_evidence(WORK, latest_only=False)) == [evidence, qualified]


def test_manuscript_anchors_are_keyed_by_file_and_sentence_fingerprint(
    repo: WorkspaceRepository,
) -> None:
    anchor = ManuscriptAnchor(
        file="main.tex",
        line_start=12,
        line_end=12,
        sentence="Existing systems disagree on tokenization.",
        sentence_fingerprint=HASH_B,
        claim=ClaimId("C0041"),
        provenance=HUMAN,
    )
    with repo.transaction(
        _event(ResearchEventType.MANUSCRIPT_CLAIM_ATTACHED, "attach C0041")
    ) as tx:
        tx.put_anchor(anchor)

    reopened = WorkspaceRepository.open(repo.root)
    assert list(reopened.iter_anchors()) == [anchor]
    assert reopened.layout.anchors_file.parent == reopened.layout.manuscript_dir


def test_parsed_blocks_are_written_beside_the_artifact_they_came_from(
    repo: WorkspaceRepository,
) -> None:
    blocks = (make_block(), make_block(id="B0082", order=13, text="A second paragraph."))
    document = ParsedDocument(
        work=WORK,
        version=VERSION,
        artifact=ARTIFACT,
        file_hash=PDF_HASH,
        parser_name="synthetic",
        parser_version="1.0",
        page_count=9,
        blocks=blocks,
        provenance=SYSTEM,
    )
    with repo.transaction(_event(ResearchEventType.WORK_INGESTED, "parse A0017-3")) as tx:
        path = tx.put_blocks(document)

    assert path == repo.layout.blocks_file(WORK, ARTIFACT)
    reopened = WorkspaceRepository.open(repo.root)
    assert list(reopened.iter_blocks(ARTIFACT)) == list(blocks)
    assert list(reopened.iter_blocks(ARTIFACT, work=WORK)) == list(blocks)
    assert list(reopened.iter_blocks(ArtifactId("A9999-1"))) == []


def test_put_dispatches_append_only_types_to_their_collection(
    repo: WorkspaceRepository,
) -> None:
    evidence = make_evidence()
    with repo.transaction(_event(ResearchEventType.EVIDENCE_ACCEPTED, "accept")) as tx:
        assert tx.put(evidence) == repo.layout.evidence_file(WORK)
    assert list(WorkspaceRepository.open(repo.root).iter_evidence(WORK)) == [evidence]


# -- artifact immutability ---------------------------------------------------


def test_artifact_bytes_are_stored_beside_their_metadata(repo: WorkspaceRepository) -> None:
    artifact = _artifact()
    with repo.transaction(_event(ResearchEventType.WORK_INGESTED, "ingest A0017-3")) as tx:
        tx.put(artifact)
        tx.store_artifact_bytes(artifact, PDF_BYTES)

    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.read_artifact_bytes(artifact) == PDF_BYTES
    assert reopened.layout.artifact_bytes_file(artifact).suffix == ".pdf"


def test_storing_identical_artifact_bytes_again_is_idempotent(
    repo: WorkspaceRepository,
) -> None:
    artifact = _artifact()
    with repo.transaction(_event(ResearchEventType.WORK_INGESTED, "ingest")) as tx:
        tx.put(artifact)
        tx.store_artifact_bytes(artifact, PDF_BYTES)
    with repo.transaction(_event(ResearchEventType.WORK_INGESTED, "re-ingest")) as tx:
        tx.put(artifact)
        tx.store_artifact_bytes(artifact, PDF_BYTES)
    assert WorkspaceRepository.open(repo.root).read_artifact_bytes(artifact) == PDF_BYTES


def test_a_revision_never_overwrites_an_existing_artifact(repo: WorkspaceRepository) -> None:
    artifact = _artifact()
    with repo.transaction(_event(ResearchEventType.WORK_INGESTED, "ingest")) as tx:
        tx.put(artifact)
        tx.store_artifact_bytes(artifact, PDF_BYTES)

    revised = b"%PDF-1.7\nrevised bytes\n"
    reused_id = _artifact(file_hash=f"sha256:{hashlib.sha256(revised).hexdigest()}")
    with (
        pytest.raises(ArtifactImmutableError, match="new Artifact"),
        repo.transaction(_event(ResearchEventType.WORK_INGESTED, "overwrite")) as tx,
    ):
        tx.store_artifact_bytes(reused_id, revised)

    assert WorkspaceRepository.open(repo.root).read_artifact_bytes(artifact) == PDF_BYTES


def test_artifact_bytes_must_match_the_declared_file_hash(repo: WorkspaceRepository) -> None:
    artifact = _artifact(file_hash=f"sha256:{'0' * 64}")
    with (
        pytest.raises(ArtifactImmutableError, match="file_hash"),
        repo.transaction(_event(ResearchEventType.WORK_INGESTED, "ingest")) as tx,
    ):
        tx.store_artifact_bytes(artifact, PDF_BYTES)


def test_reading_bytes_that_were_never_stored_raises(repo: WorkspaceRepository) -> None:
    with pytest.raises(ObjectNotFoundError, match="no stored bytes"):
        repo.read_artifact_bytes(_artifact())


# -- id allocation -----------------------------------------------------------


def test_ids_are_allocated_sequentially_and_persisted(repo: WorkspaceRepository) -> None:
    with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "two claims")) as tx:
        first = tx.allocate_id(ClaimId)
        second = tx.allocate_id(ClaimId)
        tx.put(make_claim(id=first))
        tx.put(make_claim(id=second))

    assert (first, second) == (ClaimId("C0001"), ClaimId("C0002"))
    assert repo.config.id_counters["C"] == 2

    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.config.id_counters["C"] == 2
    with reopened.transaction(_event(ResearchEventType.CLAIM_CREATED, "third claim")) as tx:
        third = tx.allocate_id(ClaimId)
        tx.put(make_claim(id=third))
    assert third == ClaimId("C0003")


def test_allocation_cross_checks_ids_already_on_disk(repo: WorkspaceRepository) -> None:
    """A hand-created object must never have its id handed out a second time."""
    with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "hand-made C0009")) as tx:
        tx.put(make_claim(id=ClaimId("C0009")))

    with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "next claim")) as tx:
        allocated = tx.allocate_id(ClaimId)
        tx.put(make_claim(id=allocated))
    assert allocated == ClaimId("C0010")


def test_versions_and_artifacts_are_allocated_inside_their_work(
    repo: WorkspaceRepository,
) -> None:
    with repo.transaction(_event(ResearchEventType.WORK_INGESTED, "ingest a work")) as tx:
        work_id = tx.allocate_id(WorkId)
        tx.put(make_work(id=work_id))
        version_id = tx.allocate_id(VersionId, work=work_id)
        tx.put(Version(id=version_id, work=work_id, kind=VersionKind.ARXIV, provenance=SYSTEM))

    assert (work_id, version_id) == (WorkId("W0001"), VersionId("V0001-1"))

    reopened = WorkspaceRepository.open(repo.root)
    with reopened.transaction(_event(ResearchEventType.WORK_INGESTED, "second revision")) as tx:
        second = tx.allocate_id(VersionId, work=work_id)
        tx.put(Version(id=second, work=work_id, kind=VersionKind.CAMERA_READY, provenance=SYSTEM))
    assert second == VersionId("V0001-2")


def test_an_unscoped_id_type_cannot_be_allocated_inside_a_work(
    repo: WorkspaceRepository,
) -> None:
    with (
        pytest.raises(WorkspaceError, match="not allocated inside a work"),
        repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "bad allocation")) as tx,
    ):
        tx.allocate_id(ClaimId, work=WORK)


# -- the mutation is one unit ------------------------------------------------


def test_a_failure_inside_the_block_leaves_canonical_state_untouched(
    repo: WorkspaceRepository,
) -> None:
    before = sorted(p.name for p in repo.layout.claims_dir.iterdir())
    with (
        pytest.raises(RuntimeError, match="model outage"),
        repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "half a claim")) as tx,
    ):
        tx.put(make_claim())
        raise RuntimeError("model outage")

    assert sorted(p.name for p in repo.layout.claims_dir.iterdir()) == before
    assert _kinds(repo) == [ResearchEventType.PROJECT_INITIALIZED]
    assert WorkspaceRepository.open(repo.root).consistency.consistent


def test_an_event_without_a_mutation_is_refused(repo: WorkspaceRepository) -> None:
    with (
        pytest.raises(WorkspaceError, match="no canonical mutation"),
        repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "nothing to do")),
    ):
        pass
    assert _kinds(repo) == [ResearchEventType.PROJECT_INITIALIZED]


def test_the_event_records_a_digest_for_every_written_object(
    repo: WorkspaceRepository,
) -> None:
    from research_harness.workspace.events import event_object_digests, object_digest

    claim = make_claim()
    evidence = make_evidence()
    with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "claim + evidence")) as tx:
        tx.put(claim)
        tx.append_evidence(evidence)

    event = _last_event(WorkspaceRepository.open(repo.root))
    assert event_object_digests(event) == {
        "C0041": object_digest(claim),
        "E0482": object_digest(evidence),
    }
    assert event.actor == "human:alice"


def test_the_actor_argument_overrides_the_event_actor(repo: WorkspaceRepository) -> None:
    with repo.transaction(
        _event(ResearchEventType.CLAIM_CREATED, "created"), actor="human:bob"
    ) as tx:
        tx.put(make_claim())
    assert _last_event(repo).actor == "human:bob"


def test_an_outer_lock_is_reused_by_every_transaction_inside_it(
    repo: WorkspaceRepository,
) -> None:
    with repo.lock() as lock:
        assert lock.held
        with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "inside")) as tx:
            tx.put(make_claim())
        assert lock.held
    assert not lock.held
    assert WorkspaceRepository.open(repo.root).get_claim(ClaimId("C0041"))


def test_the_workspace_lock_nests_within_one_repository(repo: WorkspaceRepository) -> None:
    """An inner `lock()` reuses the held lock; only the outermost context releases it.

    The daemon serializes every mutation under `repo.lock()` and handlers that allocate
    ids take it again, so nesting must work; the OS-level `WorkspaceLock` stays
    non-reentrant (see test_locking.py).
    """
    with repo.lock() as outer:
        with repo.lock() as inner:
            assert inner is outer
            assert outer.held
        assert outer.held, "the inner context must not release the outer lock"
    assert not outer.held


def test_a_future_schema_version_fails_closed_naming_both_versions(
    repo: WorkspaceRepository,
) -> None:
    config = repo.config.model_copy(update={"schema_version": CURRENT_SCHEMA_VERSION + 7})
    repo.layout.research_file.write_text(dump_yaml(config), encoding="utf-8")

    with pytest.raises(UnsupportedSchemaVersionError) as caught:
        WorkspaceRepository.open(repo.root)
    message = str(caught.value)
    assert str(CURRENT_SCHEMA_VERSION + 7) in message
    assert str(CURRENT_SCHEMA_VERSION) in message
    assert "Upgrade the harness" in message


def test_probe_answers_the_declared_version_of_a_workspace_this_build_can_open(
    repo: WorkspaceRepository,
) -> None:
    assert WorkspaceRepository.probe(repo.root) == CURRENT_SCHEMA_VERSION


def test_probe_names_the_missing_file_when_a_folder_is_no_longer_a_workspace(
    repo: WorkspaceRepository,
) -> None:
    repo.layout.research_file.unlink()
    with pytest.raises(WorkspaceNotFoundError, match=r"research\.yaml"):
        WorkspaceRepository.probe(repo.root)


def test_probe_fails_closed_on_a_future_schema_version_with_the_same_words_as_open(
    repo: WorkspaceRepository,
) -> None:
    config = repo.config.model_copy(update={"schema_version": CURRENT_SCHEMA_VERSION + 7})
    repo.layout.research_file.write_text(dump_yaml(config), encoding="utf-8")
    with pytest.raises(UnsupportedSchemaVersionError, match="Upgrade the harness"):
        WorkspaceRepository.probe(repo.root)


def test_probe_does_not_verify_what_open_verifies(repo: WorkspaceRepository) -> None:
    """A listing says whether a project can be opened, not whether its record is intact.

    The consistency check is what opening is for; paying it once per registered project
    on every page load is what made a long registry on a slow disk unlistable.
    """
    with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "create C0041")) as tx:
        tx.put(make_claim())
    path = repo.layout.claim_file(ClaimId("C0041"))
    path.write_text(
        path.read_text(encoding="utf-8").replace("Existing systems employ", "Every system employs"),
        encoding="utf-8",
    )

    assert WorkspaceRepository.probe(repo.root) == CURRENT_SCHEMA_VERSION
    with pytest.raises(WorkspaceInconsistentError):
        WorkspaceRepository.open(repo.root)


def test_a_workspace_without_a_declared_schema_version_is_refused(
    repo: WorkspaceRepository,
) -> None:
    repo.layout.research_file.write_text("name: no version\n", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="schema_version"):
        WorkspaceRepository.open(repo.root)


def test_an_older_schema_version_needs_a_registered_migration(
    repo: WorkspaceRepository,
) -> None:
    """There is no version 0; asking for one proves the harness refuses to guess."""
    from research_harness.workspace import migrations

    layout = WorkspaceLayout(repo.root)
    with pytest.raises(UnsupportedSchemaVersionError, match="older than"):
        migrations.migrate(layout, 0)


# -- fail closed on event/canonical disagreement ------------------------------


def test_a_hand_edited_claim_makes_open_fail_closed(repo: WorkspaceRepository) -> None:
    with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "create C0041")) as tx:
        tx.put(make_claim())

    path = repo.layout.claim_file(ClaimId("C0041"))
    path.write_text(
        path.read_text(encoding="utf-8").replace("Existing systems employ", "Every system employs"),
        encoding="utf-8",
    )

    with pytest.raises(WorkspaceInconsistentError) as caught:
        WorkspaceRepository.open(repo.root)
    assert "C0041" in str(caught.value)
    assert caught.value.report.issues[0].key == "C0041"


def test_repair_reports_the_inconsistency_without_rewriting_science(
    repo: WorkspaceRepository,
) -> None:
    with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "create C0041")) as tx:
        tx.put(make_claim())

    path = repo.layout.claim_file(ClaimId("C0041"))
    edited = path.read_text(encoding="utf-8").replace(
        "Existing systems employ", "Every system employs"
    )
    path.write_text(edited, encoding="utf-8")

    reopened = WorkspaceRepository.open(repo.root, repair=True)
    assert not reopened.consistency.consistent
    assert reopened.consistency.issues[0].key == "C0041"
    assert path.read_text(encoding="utf-8") == edited
    assert reopened.get_claim(ClaimId("C0041")).statement.startswith("Every system employs")


def test_a_note_or_taxonomy_edit_is_caught_too(repo: WorkspaceRepository) -> None:
    with repo.transaction(_event(ResearchEventType.TAXONOMY_REVISED, "add taxonomy")) as tx:
        tx.put(Taxonomy(name="tokenization", terms=(TaxonomyTerm(term="byte"),), provenance=HUMAN))
        tx.put_note(ResearchNote(text="a captured thought", provenance=HUMAN))

    taxonomy_path = repo.layout.taxonomy_file("tokenization")
    taxonomy_path.write_text(
        taxonomy_path.read_text(encoding="utf-8").replace("byte", "field"), encoding="utf-8"
    )
    with pytest.raises(WorkspaceInconsistentError, match="taxonomy/tokenization"):
        WorkspaceRepository.open(repo.root)


# -- provenance of the layout -------------------------------------------------


def test_canonical_writes_never_touch_the_regenerable_directory(
    repo: WorkspaceRepository,
) -> None:
    from research_harness.workspace.journal import Transaction

    transaction = Transaction(repo.layout)
    with pytest.raises(WorkspaceError, match="regenerable state"):
        transaction.write(repo.layout.database_file, b"not allowed")


def test_deleting_the_research_directory_loses_no_conclusion(
    repo: WorkspaceRepository,
) -> None:
    import shutil

    claim = make_claim()
    with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "create C0041")) as tx:
        tx.put(claim)

    shutil.rmtree(repo.layout.research_dir)
    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.get_claim(claim.id) == claim
    assert reopened.consistency.consistent


def test_a_provenance_carrying_object_keeps_its_actor_through_the_round_trip(
    repo: WorkspaceRepository,
) -> None:
    provenance = Provenance.model("vendor-a/model-x", workflow="interrogate", run_id="run-7")
    evidence = make_evidence(provenance=provenance)
    with repo.transaction(_event(ResearchEventType.EVIDENCE_PROPOSED, "propose")) as tx:
        tx.append_evidence(evidence)
    (stored,) = list(WorkspaceRepository.open(repo.root).iter_evidence(WORK))
    assert stored.provenance == provenance


# -- parsed documents from stored blocks -------------------------------------


def _stored_parse(repo: WorkspaceRepository, *, blocks: bool = True) -> Artifact:
    """One registered Artifact, with or without a stored parse beside it."""
    artifact = _artifact()
    with repo.transaction(_event(ResearchEventType.ARTIFACT_REGISTERED, "register")) as tx:
        tx.put(artifact)
    if blocks:
        document = ParsedDocument(
            work=WORK,
            version=VERSION,
            artifact=ARTIFACT,
            file_hash=PDF_HASH,
            parser_name="synthetic",
            parser_version="1.0",
            page_count=9,
            blocks=(
                make_block(),
                make_block(id="B0082", order=13, page=9, text="A second paragraph."),
            ),
            provenance=SYSTEM,
        )
        with repo.transaction(_event(ResearchEventType.WORK_PARSED, "parse")) as tx:
            tx.put_blocks(document)
    return artifact


def test_stored_blocks_come_back_as_a_parsed_document(repo: WorkspaceRepository) -> None:
    """The blocks are canonical so an anchor replays without reopening the PDF (Product 8.1)."""
    artifact = _stored_parse(repo)

    document = repo.get_parsed_document(ARTIFACT, work=WORK)

    assert document is not None
    assert (document.work, document.version, document.artifact) == (WORK, VERSION, ARTIFACT)
    assert document.file_hash == artifact.file_hash
    assert document.parser_name == STORED_PARSER_NAME
    assert document.parser_version == STORED_PARSER_VERSION
    assert [str(block.id) for block in document.blocks] == ["B0081", "B0082"]
    assert document.page_count == 9


def test_a_parsed_document_is_found_without_naming_its_work(repo: WorkspaceRepository) -> None:
    _stored_parse(repo)
    unscoped = repo.get_parsed_document(ARTIFACT)
    scoped = repo.get_parsed_document(ARTIFACT, work=WORK)
    assert unscoped is not None and scoped is not None
    assert unscoped.blocks == scoped.blocks


def test_an_artifact_with_no_stored_blocks_has_no_parsed_document(
    repo: WorkspaceRepository,
) -> None:
    """An artifact that was never parsed has no document; that is an answer, not an error."""
    _stored_parse(repo, blocks=False)
    assert repo.get_parsed_document(ARTIFACT, work=WORK) is None


def test_iter_parsed_documents_skips_artifacts_that_were_never_parsed(
    repo: WorkspaceRepository,
) -> None:
    _stored_parse(repo)
    with repo.transaction(_event(ResearchEventType.ARTIFACT_REGISTERED, "register")) as tx:
        tx.put(_artifact(id=ArtifactId("A0017-4")))

    documents = list(repo.iter_parsed_documents(WORK))

    assert [document.artifact for document in documents] == [ARTIFACT]

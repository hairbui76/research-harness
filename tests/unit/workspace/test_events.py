"""Events record semantics, travel with their mutation, and fail closed on disagreement."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.domain import (
    ClaimId,
    EvidenceId,
    ResearchEvent,
    ResearchEventType,
    Taxonomy,
    TaxonomyTerm,
    WorkId,
)
from research_harness.domain.research import (
    EVENT_PAYLOAD_FORBIDDEN_KEYS,
    MAX_EVENT_PAYLOAD_KEYS,
)
from research_harness.workspace.events import (
    BLOCKS_KEY_PREFIX,
    EVENT_OBJECT_PREFIX,
    MAX_EVENT_OBJECTS,
    ConsistencyReport,
    EventLog,
    EventPayloadError,
    assert_semantic_event,
    content_digest,
    digest_key,
    event_object_digests,
    object_digest,
    verify_consistency,
    with_object_digests,
)
from research_harness.workspace.journal import Transaction
from research_harness.workspace.layout import WorkspaceLayout
from research_harness.workspace.serialization import canonical_bytes, dump_jsonl_line
from tests.unit.domain.strategies import (
    HASH_B,
    HUMAN,
    make_artifact,
    make_block,
    make_claim,
    make_evidence,
    make_note,
    make_version,
    make_work,
)


def _event(**overrides: object) -> ResearchEvent:
    fields: dict[str, object] = {
        "event": ResearchEventType.CLAIM_CREATED,
        "actor": "human:alice",
        "summary": "created C0041 from E0132",
        "subjects": (ClaimId("C0041"),),
    }
    return ResearchEvent(**{**fields, **overrides})  # type: ignore[arg-type]


# -- digests -----------------------------------------------------------------


def test_object_digest_is_the_hash_of_the_canonical_yaml() -> None:
    claim = make_claim()
    assert object_digest(claim) == content_digest(canonical_bytes(claim))
    assert object_digest(claim).startswith("sha256:")


def test_object_digest_changes_when_the_science_changes() -> None:
    claim = make_claim()
    reworded = claim.touch(statement="A different statement entirely.")
    assert object_digest(reworded) != object_digest(claim)


def test_digest_key_is_the_stable_id_or_the_file_coordinate() -> None:
    assert digest_key(make_work()) == "W0017"
    assert digest_key(make_claim()) == "C0041"
    assert digest_key(make_evidence()) == "E0482"
    assert digest_key(Taxonomy(name="tokenization", provenance=HUMAN)) == "taxonomy/tokenization"
    assert digest_key(make_note(key="note-1")) == "notes/note-1"


def test_digest_key_refuses_a_note_that_was_never_keyed() -> None:
    with pytest.raises(Exception, match="needs a key"):
        digest_key(make_note())


# -- payload -----------------------------------------------------------------


def test_object_digests_round_trip_through_the_event_objects_field() -> None:
    digests = {"C0041": object_digest(make_claim()), "W0017": object_digest(make_work())}
    event = with_object_digests(_event(), digests)
    assert event.objects == digests
    assert event_object_digests(event) == digests
    assert event.payload == {}, "digests are their own field, not payload entries"


def test_object_digests_do_not_disturb_the_caller_s_own_payload() -> None:
    claim = make_claim()
    event = _event(payload={"evidence_count": 2})
    enriched = with_object_digests(event, {"C0041": object_digest(claim)})
    assert enriched.payload == {"evidence_count": 2}
    assert event_object_digests(enriched) == {"C0041": object_digest(claim)}


def test_a_log_written_before_the_objects_field_is_still_reconciled() -> None:
    """Backward compatibility: the legacy `object:<key>` payload entries still read back."""
    digest = object_digest(make_claim())
    legacy = _event(payload={f"{EVENT_OBJECT_PREFIX}C0041": digest, "evidence_count": 2})

    assert legacy.objects == {}
    assert event_object_digests(legacy) == {"C0041": digest}


def test_a_mutation_may_record_far_more_objects_than_the_payload_budget() -> None:
    """Digests no longer compete with the audit narrative for payload keys."""
    digest = object_digest(make_claim())
    digests = {f"C{index:04d}": digest for index in range(MAX_EVENT_PAYLOAD_KEYS * 4)}

    event = with_object_digests(_event(payload={"evidence_count": 2}), digests)

    assert event_object_digests(event) == digests
    assert event.payload == {"evidence_count": 2}


def test_object_digest_keys_stay_short_enough_to_read() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        _event(objects={"C" * 201: object_digest(make_claim())})


def test_a_mutation_touching_too_many_objects_is_refused_with_a_useful_message() -> None:
    digest = object_digest(make_claim())
    digests = {f"C{index:06d}": digest for index in range(MAX_EVENT_OBJECTS + 1)}
    with pytest.raises(EventPayloadError, match="Split the mutation"):
        with_object_digests(_event(), digests)


@pytest.mark.parametrize("forbidden", sorted(EVENT_PAYLOAD_FORBIDDEN_KEYS))
def test_the_domain_refuses_prompts_and_hidden_reasoning_in_an_event(forbidden: str) -> None:
    with pytest.raises(ValueError, match=forbidden):
        _event(payload={forbidden: "you are a helpful assistant"})


def test_the_persistence_boundary_refuses_a_smuggled_prompt_payload() -> None:
    """A hand-built or externally supplied event never reaches the log either."""
    smuggled = ResearchEvent.model_construct(
        event=ResearchEventType.EVIDENCE_PROPOSED,
        actor="vendor-a/model-x",
        summary="proposed E0482",
        subjects=(),
        payload={"prompt": "extract every claim"},
    )
    with pytest.raises(EventPayloadError, match="traces"):
        assert_semantic_event(smuggled)


def test_a_semantic_event_carrying_only_ids_and_scalars_is_accepted() -> None:
    assert_semantic_event(_event(payload={"work": "W0017", "evidence_count": 3}))


# -- the log -----------------------------------------------------------------


def test_the_event_is_staged_into_the_same_transaction_as_the_mutation(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)
    layout.claims_dir.mkdir(parents=True)
    claim = make_claim()
    transaction = Transaction(layout)
    transaction.write(layout.claim_file(claim.id), canonical_bytes(claim))
    event = with_object_digests(_event(), {digest_key(claim): object_digest(claim)})
    EventLog(layout).stage(transaction, event)

    assert set(transaction.paths) == {layout.claim_file(claim.id), layout.events_file}

    transaction.commit()
    assert list(EventLog(layout).iter_events()) == [event]


def test_latest_digests_keeps_the_newest_event_per_object(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)
    layout.events_dir.mkdir(parents=True)
    claim = make_claim()
    audited = claim.touch(statement="An audited statement.")
    first = with_object_digests(_event(), {"C0041": object_digest(claim)})
    second = with_object_digests(
        _event(event=ResearchEventType.CLAIM_AUDITED), {"C0041": object_digest(audited)}
    )
    layout.events_file.write_text(
        dump_jsonl_line(first) + dump_jsonl_line(second), encoding="utf-8"
    )

    latest = EventLog(layout).latest_digests()
    assert latest["C0041"][0].event is ResearchEventType.CLAIM_AUDITED
    assert latest["C0041"][1] == object_digest(audited)


# -- consistency -------------------------------------------------------------


def _workspace_with_claim(tmp_path: Path) -> tuple[WorkspaceLayout, object]:
    layout = WorkspaceLayout(tmp_path)
    layout.claims_dir.mkdir(parents=True, exist_ok=True)
    layout.events_dir.mkdir(parents=True, exist_ok=True)
    claim = make_claim()
    layout.claim_file(claim.id).write_bytes(canonical_bytes(claim))
    event = with_object_digests(_event(), {digest_key(claim): object_digest(claim)})
    layout.events_file.write_text(dump_jsonl_line(event), encoding="utf-8")
    return layout, claim


def test_an_empty_workspace_is_consistent(tmp_path: Path) -> None:
    report = verify_consistency(WorkspaceLayout(tmp_path))
    assert report.consistent
    assert report.checked == 0


def test_matching_canonical_state_and_event_log_are_consistent(tmp_path: Path) -> None:
    layout, _ = _workspace_with_claim(tmp_path)
    report = verify_consistency(layout)
    assert report.consistent
    assert report.checked == 1
    assert "consistent" in report.summary()


def test_a_hand_edited_claim_makes_the_workspace_inconsistent(tmp_path: Path) -> None:
    layout, _ = _workspace_with_claim(tmp_path)
    path = layout.claim_file(ClaimId("C0041"))
    path.write_text(
        path.read_text(encoding="utf-8").replace("Existing systems employ", "Every system employs"),
        encoding="utf-8",
    )
    report = verify_consistency(layout)
    assert not report.consistent
    assert report.issues[0].key == "C0041"
    assert "does not match" in report.issues[0].reason


def test_a_deleted_object_the_log_recorded_makes_the_workspace_inconsistent(
    tmp_path: Path,
) -> None:
    layout, _ = _workspace_with_claim(tmp_path)
    layout.claim_file(ClaimId("C0041")).unlink()
    report = verify_consistency(layout)
    assert not report.consistent
    assert report.issues[0].found is None
    assert "not in canonical state" in report.summary()


def test_reformatting_a_file_by_hand_is_not_a_scientific_change(tmp_path: Path) -> None:
    """Product 36 allows direct editing; only content, not layout, may fail closed."""
    layout, _ = _workspace_with_claim(tmp_path)
    path = layout.claim_file(ClaimId("C0041"))
    path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
    assert verify_consistency(layout).consistent


def test_a_taxonomy_revision_is_reconciled_by_name(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)
    layout.taxonomy_dir.mkdir(parents=True)
    layout.events_dir.mkdir(parents=True)
    taxonomy = Taxonomy(name="tokenization", terms=(TaxonomyTerm(term="byte"),), provenance=HUMAN)
    layout.taxonomy_file("tokenization").write_bytes(canonical_bytes(taxonomy))
    event = with_object_digests(
        _event(event=ResearchEventType.TAXONOMY_REVISED),
        {digest_key(taxonomy): object_digest(taxonomy)},
    )
    layout.events_file.write_text(dump_jsonl_line(event), encoding="utf-8")

    assert verify_consistency(layout).consistent

    revised = taxonomy.touch(terms=(TaxonomyTerm(term="field"),))
    layout.taxonomy_file("tokenization").write_bytes(canonical_bytes(revised))
    assert not verify_consistency(layout).consistent


def test_an_evidence_line_is_reconciled_from_the_append_only_log(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)
    work = WorkId("W0017")
    layout.work_dir(work).mkdir(parents=True)
    layout.events_dir.mkdir(parents=True)
    evidence = make_evidence()
    layout.evidence_file(work).write_text(dump_jsonl_line(evidence), encoding="utf-8")
    event = with_object_digests(
        _event(event=ResearchEventType.EVIDENCE_ACCEPTED),
        {digest_key(evidence): object_digest(evidence)},
    )
    layout.events_file.write_text(dump_jsonl_line(event), encoding="utf-8")

    assert verify_consistency(layout).consistent

    superseded = evidence.touch(qualification="only for the test split")
    with layout.evidence_file(work).open("a", encoding="utf-8") as handle:
        handle.write(dump_jsonl_line(superseded))
    report = verify_consistency(layout)
    assert not report.consistent
    assert report.issues[0].key == "E0482"


def test_a_manuscript_anchor_is_reconciled_by_file_and_fingerprint(tmp_path: Path) -> None:
    from research_harness.domain import ManuscriptAnchor

    layout = WorkspaceLayout(tmp_path)
    layout.manuscript_dir.mkdir(parents=True)
    layout.events_dir.mkdir(parents=True)
    anchor = ManuscriptAnchor(
        file="main.tex",
        line_start=3,
        line_end=3,
        sentence="Existing systems disagree.",
        sentence_fingerprint=HASH_B,
        claim=ClaimId("C0041"),
        provenance=HUMAN,
    )
    layout.anchors_file.write_text(dump_jsonl_line(anchor), encoding="utf-8")
    event = with_object_digests(
        _event(event=ResearchEventType.MANUSCRIPT_CLAIM_ATTACHED),
        {digest_key(anchor): object_digest(anchor)},
    )
    layout.events_file.write_text(dump_jsonl_line(event), encoding="utf-8")

    assert verify_consistency(layout).consistent


def test_report_summary_names_every_disagreement() -> None:
    assert ConsistencyReport().consistent
    assert "0 objects consistent" in ConsistencyReport().summary()


# -- resolution is indexed, and resolves what the per-key scans resolved --------


def _evidence_workspace(tmp_path: Path, works: int, per_work: int) -> WorkspaceLayout:
    """A corpus whose evidence ids are spread over several `evidence.jsonl` files."""
    layout = WorkspaceLayout(tmp_path)
    layout.events_dir.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    number = 0
    for index in range(works):
        work = WorkId.make(index + 1)
        layout.work_dir(work).mkdir(parents=True, exist_ok=True)
        lines = []
        for _ in range(per_work):
            number += 1
            record = make_evidence(id=EvidenceId.make(number))
            lines.append(dump_jsonl_line(record))
            digests[digest_key(record)] = object_digest(record)
        layout.evidence_file(work).write_text("".join(lines), encoding="utf-8")
    event = with_object_digests(_event(event=ResearchEventType.EVIDENCE_ACCEPTED), digests)
    layout.events_file.write_text(dump_jsonl_line(event), encoding="utf-8")
    return layout


def test_verification_reads_each_evidence_file_once_however_many_ids_it_checks(
    tmp_path: Path,
) -> None:
    """Opening a project was quadratic: every evidence id re-read every `evidence.jsonl`."""
    layout = _evidence_workspace(tmp_path, works=5, per_work=4)
    files = sorted(layout.works_dir.glob("*/evidence.jsonl"))
    opened: list[Path] = []
    original = Path.open

    def counting_open(self: Path, *args: object, **kwargs: object) -> object:
        if self in files:
            opened.append(self)
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "open", counting_open)
        report = verify_consistency(layout)

    assert report.consistent
    assert report.checked == 20
    assert sorted(opened) == files


def test_an_evidence_id_resolves_to_the_first_file_holding_it(tmp_path: Path) -> None:
    """Two Works carrying one id resolve the way the per-file scan did: lowest Work wins."""
    layout = WorkspaceLayout(tmp_path)
    layout.events_dir.mkdir(parents=True)
    first, second = WorkId("W0001"), WorkId("W0002")
    for work in (first, second):
        layout.work_dir(work).mkdir(parents=True)
    early = make_evidence(qualification="in the earlier work")
    late = make_evidence(qualification="in the later work")
    layout.evidence_file(first).write_text(dump_jsonl_line(early), encoding="utf-8")
    layout.evidence_file(second).write_text(dump_jsonl_line(late), encoding="utf-8")
    event = with_object_digests(
        _event(event=ResearchEventType.EVIDENCE_ACCEPTED),
        {digest_key(early): object_digest(early)},
    )
    layout.events_file.write_text(dump_jsonl_line(event), encoding="utf-8")

    assert verify_consistency(layout).consistent


def test_the_newest_line_of_a_file_is_the_one_verified(tmp_path: Path) -> None:
    """Within one file the last record for an id is current, as the scan always held."""
    layout = WorkspaceLayout(tmp_path)
    layout.events_dir.mkdir(parents=True)
    work = WorkId("W0017")
    layout.work_dir(work).mkdir(parents=True)
    first = make_evidence()
    newest = first.touch(qualification="restated")
    layout.evidence_file(work).write_text(
        dump_jsonl_line(first) + dump_jsonl_line(newest), encoding="utf-8"
    )
    event = with_object_digests(
        _event(event=ResearchEventType.EVIDENCE_ACCEPTED),
        {digest_key(newest): object_digest(newest)},
    )
    layout.events_file.write_text(dump_jsonl_line(event), encoding="utf-8")

    assert verify_consistency(layout).consistent


def test_versions_and_artifacts_resolve_without_globbing_per_id(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)
    layout.events_dir.mkdir(parents=True)
    work = WorkId("W0017")
    layout.versions_dir(work).mkdir(parents=True)
    layout.artifacts_dir(work).mkdir(parents=True)
    version, artifact = make_version(), make_artifact()
    layout.version_file(work, version.id).write_bytes(canonical_bytes(version))
    layout.artifact_file(work, artifact.id).write_bytes(canonical_bytes(artifact))
    event = with_object_digests(
        _event(event=ResearchEventType.ARTIFACT_REGISTERED),
        {
            digest_key(version): object_digest(version),
            digest_key(artifact): object_digest(artifact),
        },
    )
    layout.events_file.write_text(dump_jsonl_line(event), encoding="utf-8")

    assert verify_consistency(layout).consistent

    layout.artifact_file(work, artifact.id).write_bytes(
        canonical_bytes(artifact.touch(size_bytes=99))
    )
    report = verify_consistency(layout)
    assert not report.consistent
    assert report.issues[0].key == str(artifact.id)


def test_a_blocks_file_is_reconciled_by_its_bytes(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path)
    layout.events_dir.mkdir(parents=True)
    work, block = WorkId("W0017"), make_block()
    layout.parsed_dir(work).mkdir(parents=True)
    path = layout.blocks_file(work, block.artifact)
    path.write_text(dump_jsonl_line(block), encoding="utf-8")
    event = with_object_digests(
        _event(event=ResearchEventType.WORK_PARSED),
        {f"{BLOCKS_KEY_PREFIX}{block.artifact}": content_digest(path.read_bytes())},
    )
    layout.events_file.write_text(dump_jsonl_line(event), encoding="utf-8")

    assert verify_consistency(layout).consistent

    path.write_text(dump_jsonl_line(block.touch(text="edited")), encoding="utf-8")
    assert not verify_consistency(layout).consistent

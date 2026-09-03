"""Interrupting a multi-file mutation leaves the whole prior state or the whole new one.

Product 42 K. Each test crashes the same three-file unit (a Claim, an Evidence line, and
the semantic event) at a different point in the commit protocol, then runs recovery and
asserts that every touched file is *entirely* old or *entirely* new, that the event never
lands without its mutation or twice, and that the workspace verifies consistent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from research_harness.domain import ClaimId, ResearchEvent, ResearchEventType, WorkId
from research_harness.workspace.events import (
    digest_key,
    object_digest,
    verify_consistency,
    with_object_digests,
)
from research_harness.workspace.journal import (
    COMMITTED_SUFFIX,
    RECORD_SUFFIX,
    Intent,
    JournalConflictError,
    JournalError,
    JournalRecord,
    Transaction,
    recover,
)
from research_harness.workspace.layout import WorkspaceLayout
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.serialization import canonical_bytes, dump_jsonl_line
from tests.unit.domain.strategies import make_claim, make_evidence

WORK = WorkId("W0017")
CLAIM = ClaimId("C0041")

INIT_EVENT_LINES = 1
"""`WorkspaceRepository.init` opens the log with `project.initialized`."""


@dataclass(frozen=True)
class Unit:
    """One accepted-state mutation, plus the bytes every touched file held before it."""

    layout: WorkspaceLayout
    transaction: Transaction
    expected: dict[Path, bytes]
    before: dict[Path, bytes | None]

    def state(self) -> dict[Path, str]:
        """`old` / `new` / `torn` per touched file, which is what atomicity is about."""
        verdicts: dict[Path, str] = {}
        for path, new in self.expected.items():
            current = path.read_bytes() if path.is_file() else None
            old = self.before[path]
            if current == new:
                verdicts[path] = "new"
            elif current == old:
                verdicts[path] = "old"
            else:
                verdicts[path] = "torn"
        return verdicts


@pytest.fixture
def repo(tmp_path: Path) -> WorkspaceRepository:
    return WorkspaceRepository.init(tmp_path / "project", "recovery")


def _event(summary: str, *objects: object) -> ResearchEvent:
    event = ResearchEvent(
        event=ResearchEventType.CLAIM_CREATED, actor="human:alice", summary=summary
    )
    return with_object_digests(event, {digest_key(obj): object_digest(obj) for obj in objects})


def _unit(repo: WorkspaceRepository, *, statement: str) -> Unit:
    """Stage claim + evidence + event as one journal transaction, without committing it."""
    layout = repo.layout
    claim = make_claim(statement=statement)
    evidence = make_evidence(content=make_evidence().content.touch(exact_text=statement))
    event = _event(statement, claim, evidence)

    claim_path = layout.claim_file(CLAIM)
    evidence_path = layout.evidence_file(WORK)
    events_path = layout.events_file

    before = {
        path: (path.read_bytes() if path.is_file() else None)
        for path in (claim_path, evidence_path, events_path)
    }
    expected = {
        claim_path: canonical_bytes(claim),
        evidence_path: (before[evidence_path] or b"") + dump_jsonl_line(evidence).encode("utf-8"),
        events_path: (before[events_path] or b"") + dump_jsonl_line(event).encode("utf-8"),
    }

    transaction = Transaction(layout)
    transaction.write(claim_path, canonical_bytes(claim))
    transaction.append(evidence_path, dump_jsonl_line(evidence).encode("utf-8"))
    transaction.append(events_path, dump_jsonl_line(event).encode("utf-8"))
    return Unit(layout=layout, transaction=transaction, expected=expected, before=before)


def _seed(repo: WorkspaceRepository) -> Unit:
    """Commit one unit so the next crash has real pre-images to restore."""
    unit = _unit(repo, statement="The first accepted statement.")
    unit.transaction.commit()
    assert verify_consistency(repo.layout).consistent
    return unit


def _crash(
    method: str, *, on_call: int = 1, once: bool = False
) -> Callable[[pytest.MonkeyPatch], None]:
    """Make the named `Transaction` phase raise, simulating a crash at that point.

    ``once`` models a transient crash: only the numbered call fails, so a later in-process
    or on-open recovery is allowed to succeed.
    """

    def apply(monkeypatch: pytest.MonkeyPatch) -> None:
        original = getattr(Transaction, method)
        calls = {"n": 0}

        def failing(*args: object, **kwargs: object) -> object:
            calls["n"] += 1
            crashing = calls["n"] == on_call if once else calls["n"] >= on_call
            if not crashing:
                return original(*args, **kwargs)
            raise RuntimeError(f"crash in {method} call {calls['n']}")

        monkeypatch.setattr(Transaction, method, failing)

    return apply


def _journal_entries(layout: WorkspaceLayout) -> list[str]:
    return sorted(path.name for path in layout.journal_dir.iterdir())


# -- crash points ------------------------------------------------------------


def test_a_crash_before_the_prepared_marker_rolls_back_to_the_prior_state(
    repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = _seed(repo)
    unit = _unit(repo, statement="A statement that never lands.")
    _crash("_write_record")(monkeypatch)

    with pytest.raises(RuntimeError, match="_write_record"):
        unit.transaction.commit()
    monkeypatch.undo()

    report = recover(unit.layout)
    assert report.rolled_back == (unit.transaction.tx_id,)
    assert set(unit.state().values()) == {"old"}
    assert _journal_entries(unit.layout) == []

    events = unit.layout.events_file.read_bytes()
    assert events == seed.expected[unit.layout.events_file]
    assert events.count(b"\n") == INIT_EVENT_LINES + 1
    assert verify_consistency(unit.layout).consistent


def test_a_crash_after_prepare_but_before_apply_completes_the_whole_unit(
    repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(repo)
    unit = _unit(repo, statement="A statement that recovery finishes.")
    _crash("_apply")(monkeypatch)

    with pytest.raises(RuntimeError, match="_apply"):
        unit.transaction.commit()
    monkeypatch.undo()

    report = recover(unit.layout)
    assert report.completed == (unit.transaction.tx_id,)
    assert set(unit.state().values()) == {"new"}
    assert unit.layout.events_file.read_bytes().count(b"\n") == INIT_EVENT_LINES + 2
    assert verify_consistency(unit.layout).consistent


def test_a_crash_midway_through_apply_completes_the_whole_unit(
    repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(repo)
    unit = _unit(repo, statement="A statement interrupted between files.")
    _crash("_apply_intent", on_call=2)(monkeypatch)

    with pytest.raises(RuntimeError, match="_apply_intent"):
        unit.transaction.commit()
    monkeypatch.undo()

    # The first file landed and the rest did not: exactly the half-written state the
    # journal exists to finish.
    assert sorted(unit.state().values()) == ["new", "old", "old"]

    report = recover(unit.layout)
    assert report.completed == (unit.transaction.tx_id,)
    assert set(unit.state().values()) == {"new"}
    assert verify_consistency(unit.layout).consistent


def test_a_crash_after_apply_but_before_the_commit_rename_redoes_idempotently(
    repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(repo)
    unit = _unit(repo, statement="A statement whose commit rename never happened.")
    _crash("_commit_record")(monkeypatch)

    with pytest.raises(RuntimeError, match="_commit_record"):
        unit.transaction.commit()
    monkeypatch.undo()

    assert set(unit.state().values()) == {"new"}  # applied, but not yet committed

    report = recover(unit.layout)
    assert report.completed == (unit.transaction.tx_id,)
    assert set(unit.state().values()) == {"new"}
    assert unit.layout.events_file.read_bytes().count(b"\n") == INIT_EVENT_LINES + 2, (
        "the event must not double"
    )
    assert verify_consistency(unit.layout).consistent


def test_a_crash_after_the_commit_point_only_cleans_leftovers(
    repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(repo)
    unit = _unit(repo, statement="A statement that was committed but not cleaned.")
    monkeypatch.setattr(
        "research_harness.workspace.journal._clean_transaction",
        lambda layout, tx_id: None,
    )
    unit.transaction.commit()
    monkeypatch.undo()

    assert f"{unit.transaction.tx_id}{COMMITTED_SUFFIX}" in _journal_entries(unit.layout)

    report = recover(unit.layout)
    assert report.cleaned == (unit.transaction.tx_id,)
    assert _journal_entries(unit.layout) == []
    assert set(unit.state().values()) == {"new"}
    assert verify_consistency(unit.layout).consistent


def test_a_torn_journal_record_is_discarded_and_pre_images_restored(
    repo: WorkspaceRepository,
) -> None:
    seed = _seed(repo)
    unit = _unit(repo, statement="A statement whose journal record was torn.")
    record = unit.transaction._prepare()

    # A half-written record: unparsable JSON, so recovery cannot know the intents and must
    # fall back on the self-describing staging tree.
    record_path = unit.layout.journal_dir / f"{record.tx_id}{RECORD_SUFFIX}"
    text = record_path.read_text(encoding="utf-8")
    record_path.write_text(text[: len(text) // 2], encoding="utf-8")

    report = recover(unit.layout)
    assert report.rolled_back == (record.tx_id,)
    assert set(unit.state().values()) == {"old"}
    assert unit.layout.events_file.read_bytes() == seed.expected[unit.layout.events_file]
    assert _journal_entries(unit.layout) == []
    assert verify_consistency(unit.layout).consistent


def test_a_prepared_transaction_with_no_record_at_all_rolls_back(
    repo: WorkspaceRepository,
) -> None:
    _seed(repo)
    unit = _unit(repo, statement="A statement whose record never landed.")
    record = unit.transaction._prepare()
    (unit.layout.journal_dir / f"{record.tx_id}{RECORD_SUFFIX}").unlink()

    report = recover(unit.layout)
    assert report.rolled_back == (record.tx_id,)
    assert set(unit.state().values()) == {"old"}
    assert verify_consistency(unit.layout).consistent


# -- recovery is repeatable --------------------------------------------------


def test_recovery_is_idempotent(repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(repo)
    unit = _unit(repo, statement="A statement recovered more than once.")
    _crash("_apply")(monkeypatch)
    with pytest.raises(RuntimeError):
        unit.transaction.commit()
    monkeypatch.undo()

    first = recover(unit.layout)
    after_first = {path: path.read_bytes() for path in unit.expected}
    second = recover(unit.layout)
    third = recover(unit.layout)

    assert first.changed
    assert not second.changed and not third.changed
    assert {path: path.read_bytes() for path in unit.expected} == after_first
    assert verify_consistency(unit.layout).consistent


def test_recovery_on_a_clean_workspace_does_nothing(repo: WorkspaceRepository) -> None:
    _seed(repo)
    assert not recover(repo.layout).changed


def test_opening_a_workspace_recovers_an_interrupted_mutation(
    repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The acceptance path: a crashed process is healed by the next `open`."""
    _seed(repo)
    unit = _unit(repo, statement="A statement healed on the next open.")
    _crash("_commit_record")(monkeypatch)
    with pytest.raises(RuntimeError):
        unit.transaction.commit()
    monkeypatch.undo()

    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.recovery.completed == (unit.transaction.tx_id,)
    assert reopened.consistency.consistent
    assert reopened.get_claim(CLAIM).statement == "A statement healed on the next open."
    assert len(list(reopened.iter_events())) == INIT_EVENT_LINES + 2


def test_a_repository_transaction_that_fails_at_the_commit_point_heals_itself(
    repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = ResearchEvent(
        event=ResearchEventType.CLAIM_CREATED, actor="human:alice", summary="create C0041"
    )
    _crash("_commit_record", once=True)(monkeypatch)
    with pytest.raises(RuntimeError, match="_commit_record"), repo.transaction(event) as tx:
        tx.put(make_claim())
    monkeypatch.undo()

    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.consistency.consistent
    assert reopened.get_claim(CLAIM).statement.startswith("Existing systems")
    assert len(list(reopened.iter_events())) == INIT_EVENT_LINES + 1
    assert not reopened.recovery.changed, "the failing transaction already healed itself"


def test_a_repository_transaction_whose_recovery_also_dies_is_healed_on_the_next_open(
    repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = ResearchEvent(
        event=ResearchEventType.CLAIM_CREATED, actor="human:alice", summary="create C0041"
    )
    _crash("_commit_record")(monkeypatch)
    with pytest.raises(RuntimeError), repo.transaction(event) as tx:
        tx.put(make_claim())
    monkeypatch.undo()

    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.recovery.changed
    assert reopened.consistency.consistent
    assert len(list(reopened.iter_events())) == INIT_EVENT_LINES + 1


# -- journal invariants ------------------------------------------------------


def test_an_append_target_that_moved_under_the_transaction_is_a_conflict(
    repo: WorkspaceRepository,
) -> None:
    """Only possible without the workspace lock; the journal still refuses to guess."""
    _seed(repo)
    unit = _unit(repo, statement="A statement raced by a second writer.")
    record = unit.transaction._prepare()
    with unit.layout.events_file.open("ab") as handle:
        handle.write(b"{}\n")

    with pytest.raises(JournalConflictError, match="changed under transaction"):
        unit.transaction._apply(record, redo=False)


def test_recovery_refuses_to_invent_data_for_a_truncated_append_target(
    repo: WorkspaceRepository,
) -> None:
    _seed(repo)
    unit = _unit(repo, statement="A statement whose log was truncated behind it.")
    record = unit.transaction._prepare()
    unit.layout.events_file.write_bytes(b"")

    with pytest.raises(JournalError, match="recovery would have to invent data"):
        unit.transaction._apply(record, redo=True)


def test_a_transaction_cannot_mix_write_and_append_on_one_path(
    repo: WorkspaceRepository,
) -> None:
    transaction = Transaction(repo.layout)
    transaction.append(repo.layout.events_file, b"{}\n")
    with pytest.raises(Exception, match="already staged as append"):
        transaction.write(repo.layout.events_file, b"{}\n")


def test_repeated_appends_to_one_path_concatenate_in_order(
    repo: WorkspaceRepository,
) -> None:
    path = repo.layout.evidence_file(WORK)
    transaction = Transaction(repo.layout)
    transaction.append(path, b"first\n")
    transaction.append(path, b"second\n")
    transaction.commit()
    assert path.read_bytes() == b"first\nsecond\n"


def test_a_deleted_file_is_restored_when_the_record_is_torn(
    repo: WorkspaceRepository,
) -> None:
    path = repo.layout.claim_file(CLAIM)
    seeded = Transaction(repo.layout)
    seeded.write(path, b"original: true\n")
    seeded.commit()

    transaction = Transaction(repo.layout)
    transaction.delete(path)
    record = transaction._prepare()
    (repo.layout.journal_dir / f"{record.tx_id}{RECORD_SUFFIX}").unlink()

    recover(repo.layout)
    assert path.read_bytes() == b"original: true\n"


def test_a_committed_delete_removes_the_file(repo: WorkspaceRepository) -> None:
    path = repo.layout.claim_file(CLAIM)
    seeded = Transaction(repo.layout)
    seeded.write(path, b"original: true\n")
    seeded.commit()

    transaction = Transaction(repo.layout)
    transaction.delete(path)
    transaction.commit()
    assert not path.exists()


def test_a_transaction_commits_only_once(repo: WorkspaceRepository) -> None:
    transaction = Transaction(repo.layout)
    transaction.write(repo.layout.claim_file(CLAIM), b"a: 1\n")
    transaction.commit()
    with pytest.raises(JournalError, match="already committed"):
        transaction.commit()


def test_the_journal_record_describes_every_intent(repo: WorkspaceRepository) -> None:
    unit = _unit(repo, statement="A statement describing its own journal record.")
    record = unit.transaction._prepare()
    assert record.prepared
    assert [intent.op.value for intent in record.intents] == ["write", "append", "append"]
    assert all(intent.expected_length_before is not None for intent in record.intents[1:])
    assert JournalRecord.from_dict(record.as_dict()) == record
    assert Intent.from_dict(record.intents[0].as_dict()) == record.intents[0]
    recover(unit.layout)


def _all_files(root: Path) -> Iterator[Path]:
    yield from (path for path in root.rglob("*") if path.is_file())


def test_a_rolled_back_transaction_leaves_no_trace_on_disk(
    repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(repo)
    before = {path: path.read_bytes() for path in _all_files(repo.root)}
    unit = _unit(repo, statement="A statement that leaves nothing behind.")
    _crash("_write_record")(monkeypatch)
    with pytest.raises(RuntimeError):
        unit.transaction.commit()
    monkeypatch.undo()
    recover(unit.layout)

    after = {path: path.read_bytes() for path in _all_files(repo.root)}
    assert set(after) - set(before) == set()
    assert {path: after[path] for path in before} == before


def test_artifact_bytes_and_parsed_blocks_recover_with_the_rest_of_the_unit(
    repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Binary originals and derived block files travel through the same journal."""
    import hashlib

    from research_harness.domain import (
        Artifact,
        ArtifactId,
        ArtifactKind,
        ParsedDocument,
        VersionId,
    )
    from tests.unit.domain.strategies import SYSTEM, make_block

    data = bytes(range(256)) * 40
    artifact = Artifact(
        id=ArtifactId("A0017-3"),
        work=WORK,
        version=VersionId("V0017-2"),
        kind=ArtifactKind.PDF,
        file_hash=f"sha256:{hashlib.sha256(data).hexdigest()}",
        original_filename="paper.pdf",
        mime_type="application/pdf",
        size_bytes=len(data),
        provenance=SYSTEM,
    )
    document = ParsedDocument(
        work=WORK,
        version=artifact.version,
        artifact=artifact.id,
        file_hash=artifact.file_hash,
        parser_name="synthetic",
        parser_version="1.0",
        page_count=9,
        blocks=(make_block(),),
        provenance=SYSTEM,
    )
    event = ResearchEvent(
        event=ResearchEventType.WORK_INGESTED, actor="human:alice", summary="ingest A0017-3"
    )

    _crash("_commit_record")(monkeypatch)
    with pytest.raises(RuntimeError), repo.transaction(event) as tx:
        tx.put(artifact)
        tx.store_artifact_bytes(artifact, data)
        tx.put_blocks(document)
    monkeypatch.undo()

    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.consistency.consistent
    assert reopened.read_artifact_bytes(artifact) == data
    assert list(reopened.iter_blocks(artifact.id)) == list(document.blocks)
    assert len(list(reopened.iter_events())) == INIT_EVENT_LINES + 1

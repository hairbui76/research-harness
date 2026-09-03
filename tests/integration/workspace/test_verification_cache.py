"""`.research/consistency-check.json`: skip the full check only when nothing moved.

Full verification stays the only thing that can call a workspace consistent (ADR-001,
ADR-014); the marker is a cache over that verdict and never a second authority. Every test
here asks the same question from a different angle: does the workspace re-verify when it
must, and does it still fail closed when the event log and canonical state disagree?
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.domain import ResearchEvent, ResearchEventType
from research_harness.workspace import events as events_module
from research_harness.workspace.events import (
    CONSISTENCY_MARKER_SCHEMA_VERSION,
    consistency_marker_path,
    read_consistency_marker,
    verify_consistency,
)
from research_harness.workspace.layout import WorkspaceLayout
from research_harness.workspace.repository import (
    WorkspaceConfig,
    WorkspaceInconsistentError,
    WorkspaceRepository,
)
from research_harness.workspace.serialization import read_yaml
from tests.unit.domain.strategies import make_claim, make_evidence, make_note, make_work

CLAIM_FILE = Path("claims") / "C0041.yaml"


def _event(kind: ResearchEventType, summary: str) -> ResearchEvent:
    return ResearchEvent(event=kind, actor="human:alice", summary=summary)


def _marker_path(root: Path) -> Path:
    return consistency_marker_path(WorkspaceLayout(root))


def _rewrite(path: Path, old: str, new: str) -> None:
    path.write_text(path.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A workspace with a Work, an Evidence record, and a Claim already committed."""
    repo = WorkspaceRepository.init(tmp_path / "project", "structured-traffic")
    with repo.transaction(_event(ResearchEventType.WORK_INGESTED, "ingest W0017")) as tx:
        tx.put(make_work())
        tx.append_evidence(make_evidence())
    with repo.transaction(_event(ResearchEventType.CLAIM_CREATED, "create C0041")) as tx:
        tx.put(make_claim())
    return repo.root


@pytest.fixture
def verified(root: Path) -> Path:
    """The same workspace, once opened so a full verification has left its marker."""
    assert WorkspaceRepository.open(root).consistency.skipped is False
    assert _marker_path(root).is_file()
    return root


@pytest.fixture
def full_checks(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Records every full `verify_consistency` run, which is what the cache exists to avoid."""
    calls: list[str] = []
    original = events_module.verify_consistency

    def counting(layout: WorkspaceLayout) -> events_module.ConsistencyReport:
        calls.append(str(layout.root))
        return original(layout)

    monkeypatch.setattr(events_module, "verify_consistency", counting)
    yield calls


# -- the cache hit -----------------------------------------------------------


def test_an_unchanged_workspace_skips_the_full_check(
    verified: Path, full_checks: list[str]
) -> None:
    repo = WorkspaceRepository.open(verified)

    assert repo.consistency.consistent
    assert repo.consistency.skipped_reason is not None
    assert repo.consistency.skipped_reason.startswith("unchanged since ")
    assert full_checks == []


def test_the_skipped_report_still_says_what_the_full_check_covered(verified: Path) -> None:
    full = WorkspaceRepository.open(verified, verify="full").consistency
    skipped = WorkspaceRepository.open(verified).consistency

    assert full.checked > 0
    assert skipped.checked == full.checked
    assert "verification skipped" in skipped.summary()
    assert f"{full.checked} objects consistent" in skipped.summary()


def test_verify_full_runs_the_whole_check_anyway(verified: Path, full_checks: list[str]) -> None:
    """`research doctor` asks for the guarantee, not for the answer it already had."""
    repo = WorkspaceRepository.open(verified, verify="full")

    assert repo.consistency.skipped is False
    assert repo.consistency.consistent
    assert len(full_checks) == 1


def test_repo_verify_always_re_derives_every_digest(verified: Path, full_checks: list[str]) -> None:
    repo = WorkspaceRepository.open(verified)
    assert full_checks == []

    report = repo.verify()

    assert report.skipped is False
    assert report.consistent
    assert len(full_checks) == 1


def test_the_cached_verdict_equals_the_full_one_on_a_healthy_workspace(verified: Path) -> None:
    full = verify_consistency(WorkspaceLayout(verified))
    cached = WorkspaceRepository.open(verified).consistency

    assert full.consistent and cached.consistent
    assert cached.checked == full.checked


# -- every way the workspace can move ----------------------------------------


def test_a_same_size_edit_to_a_canonical_file_re_verifies(
    verified: Path, full_checks: list[str]
) -> None:
    """The hard case: the file is exactly as long as it was, only its content moved."""
    path = verified / CLAIM_FILE
    before = path.read_text(encoding="utf-8")
    _rewrite(path, "heterogeneous traffic", "heterogeneous-traffic")
    assert len(path.read_text(encoding="utf-8")) == len(before)

    with pytest.raises(WorkspaceInconsistentError, match="C0041"):
        WorkspaceRepository.open(verified)
    assert len(full_checks) == 1


def test_a_yaml_edit_re_verifies_and_names_the_object(verified: Path) -> None:
    _rewrite(verified / CLAIM_FILE, "Existing systems", "Every system")

    repo = WorkspaceRepository.open(verified, repair=True)

    assert repo.consistency.skipped is False
    assert [issue.key for issue in repo.consistency.issues] == ["C0041"]


def test_a_hand_edited_event_log_re_verifies_and_fails_closed(
    verified: Path, full_checks: list[str]
) -> None:
    """The log is the account being reconciled, so it is the one file digested outright."""
    path = verified / "events" / "research.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[-1])
    payload["objects"]["C0041"] = f"sha256:{'0' * 64}"
    lines[-1] = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(WorkspaceInconsistentError, match="C0041"):
        WorkspaceRepository.open(verified)
    assert len(full_checks) == 1


def test_a_new_canonical_file_re_verifies(verified: Path, full_checks: list[str]) -> None:
    """A file the marker never saw is a change even though nothing recorded moved."""
    (verified / "notes" / "hand-written.yaml").write_text("text: hello\n", encoding="utf-8")

    repo = WorkspaceRepository.open(verified)

    assert repo.consistency.skipped is False
    assert len(full_checks) == 1


def test_a_removed_canonical_file_re_verifies(verified: Path) -> None:
    (verified / CLAIM_FILE).unlink()

    with pytest.raises(WorkspaceInconsistentError, match="C0041"):
        WorkspaceRepository.open(verified)


def test_a_deleted_marker_re_verifies(verified: Path, full_checks: list[str]) -> None:
    _marker_path(verified).unlink()

    repo = WorkspaceRepository.open(verified)

    assert repo.consistency.skipped is False
    assert repo.consistency.consistent
    assert len(full_checks) == 1


def test_deleting_the_research_directory_re_verifies_in_full(
    verified: Path, full_checks: list[str]
) -> None:
    """The marker is regenerable state and dies with the projection it sits beside."""
    shutil.rmtree(verified / ".research")

    repo = WorkspaceRepository.open(verified)

    assert repo.consistency.skipped is False
    assert repo.consistency.consistent
    assert len(full_checks) == 1


# -- markers this harness must not believe -----------------------------------


def test_a_forged_marker_with_a_changed_size_re_verifies(
    verified: Path, full_checks: list[str]
) -> None:
    """A marker is evidence about bytes, not a certificate: the bytes still decide.

    The comment appended here leaves every object digest untouched, so the workspace is
    still consistent; what is under test is that the marker did not get to say so.
    """
    path = verified / CLAIM_FILE
    path.write_text(path.read_text(encoding="utf-8") + "# a hand-written comment\n")
    marker_path = _marker_path(verified)
    forged = json.loads(marker_path.read_text(encoding="utf-8"))
    forged["manifest"]["claims/C0041.yaml"][1] = path.stat().st_mtime_ns
    assert forged["manifest"]["claims/C0041.yaml"][0] != path.stat().st_size
    marker_path.write_text(json.dumps(forged, sort_keys=True), encoding="utf-8")

    repo = WorkspaceRepository.open(verified)

    assert repo.consistency.skipped is False
    assert repo.consistency.consistent
    assert len(full_checks) == 1


def test_a_marker_from_another_schema_version_is_ignored(
    verified: Path, full_checks: list[str]
) -> None:
    marker_path = _marker_path(verified)
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    payload["schema_version"] = CONSISTENCY_MARKER_SCHEMA_VERSION + 1
    marker_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    assert WorkspaceRepository.open(verified).consistency.skipped is False
    assert len(full_checks) == 1


def test_an_unreadable_marker_is_ignored(verified: Path, full_checks: list[str]) -> None:
    _marker_path(verified).write_text("{oops", encoding="utf-8")

    assert WorkspaceRepository.open(verified).consistency.skipped is False
    assert len(full_checks) == 1


def test_a_marker_that_vouches_for_an_unsettled_file_is_ignored(verified: Path) -> None:
    """A file written in the tick the marker settled could still have moved inside it."""
    marker_path = _marker_path(verified)
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    payload["settled_at_ns"] = max(mtime for _, mtime in payload["manifest"].values())
    marker_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    assert WorkspaceRepository.open(verified).consistency.skipped is False


def test_a_failed_full_check_leaves_no_marker_to_lean_on(verified: Path) -> None:
    _rewrite(verified / CLAIM_FILE, "Existing systems", "Every system")

    WorkspaceRepository.open(verified, repair=True)

    assert not _marker_path(verified).exists()
    with pytest.raises(WorkspaceInconsistentError):
        WorkspaceRepository.open(verified)


# -- mutation keeps the marker honest ----------------------------------------


def test_a_commit_carries_the_marker_over_its_own_mutation(
    verified: Path, full_checks: list[str]
) -> None:
    repo = WorkspaceRepository.open(verified)
    with repo.transaction(_event(ResearchEventType.NOTE_CAPTURED, "capture a note")) as tx:
        tx.put_note(make_note())

    reopened = WorkspaceRepository.open(verified)

    assert reopened.consistency.consistent
    assert reopened.consistency.skipped is True
    assert full_checks == []


def test_the_carried_marker_describes_the_files_the_commit_wrote(verified: Path) -> None:
    repo = WorkspaceRepository.open(verified)
    with repo.transaction(_event(ResearchEventType.NOTE_CAPTURED, "capture a note")) as tx:
        _, path = tx.put_note(make_note())

    marker = read_consistency_marker(repo.layout)

    assert marker is not None
    info = path.stat()
    assert marker.manifest[str(repo.layout.relative(path))] == (info.st_size, info.st_mtime_ns)
    assert marker.event_log_bytes == repo.layout.events_file.stat().st_size


def test_a_commit_from_an_unverified_repository_invalidates_the_marker(
    verified: Path, full_checks: list[str]
) -> None:
    """Nothing inherits a verdict it did not earn, even with a valid marker on disk."""
    layout = WorkspaceLayout(verified)
    unverified = WorkspaceRepository(layout, read_yaml(layout.research_file, WorkspaceConfig))
    with unverified.transaction(_event(ResearchEventType.NOTE_CAPTURED, "capture")) as tx:
        tx.put_note(make_note())

    assert not _marker_path(verified).exists()
    assert WorkspaceRepository.open(verified).consistency.skipped is False
    assert len(full_checks) == 1


def test_a_carried_marker_still_catches_a_later_hand_edit(verified: Path) -> None:
    repo = WorkspaceRepository.open(verified)
    with repo.transaction(_event(ResearchEventType.CLAIM_AUDITED, "revise C0041")) as tx:
        tx.put(make_claim(statement="Existing systems employ one tokenization scheme."))

    _rewrite(verified / CLAIM_FILE, "one tokenization", "two tokenizations")

    with pytest.raises(WorkspaceInconsistentError, match="C0041"):
        WorkspaceRepository.open(verified)


def test_a_privacy_update_keeps_the_marker_honest(verified: Path) -> None:
    """`update_config` writes `research.yaml` through the journal, so it counts as a change."""
    from research_harness.privacy.policy import EgressPolicy

    repo = WorkspaceRepository.open(verified)
    repo.update_config(EgressPolicy())

    reopened = WorkspaceRepository.open(verified)

    assert reopened.consistency.consistent
    marker = read_consistency_marker(reopened.layout)
    assert marker is not None
    info = repo.layout.research_file.stat()
    assert marker.manifest["research.yaml"] == (info.st_size, info.st_mtime_ns)

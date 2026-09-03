"""Interrupting a manuscript attachment between the anchor and its event.

`manuscript.attach_claim` appends two lines: the anchor to `manuscript/anchors.jsonl` and
the semantic event to `events/research.jsonl`. They are two intents of one journalled
transaction, so the interesting crash is exactly between them - the moment where a
workspace could end up with a manuscript sentence bound to a Claim that no event records,
or an event describing a binding that is not there (Product §8.2, §30.1).

Both are checked, plus the retry: attaching again after an interruption must leave one
anchor, not two.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import open_context
from research_harness.domain.enums import ManuscriptAnchorStatus
from research_harness.domain.ids import ClaimId
from research_harness.manuscript.attach import ManuscriptService
from research_harness.workspace.events import object_digest
from research_harness.workspace.repository import WorkspaceRepository
from tests.e2e.crash.interrupts import PowerCutError, crash_at, reopen
from tests.e2e.invariants.workstation import (
    GHOST_LINE,
    HUMAN,
    MISMATCH_LINE,
    SUPPORTED_LINE,
    build_workstation,
    canonical_bytes_digest,
)

#: `put_anchor` stages the anchor append first and the event append second, so intent 1 is
#: the anchor and intent 2 is the event: crashing on each lands on either side of the pair.
ANCHOR_INTENT = 1
EVENT_INTENT = 2


#: A new substantive sentence the researcher just wrote, cited by nothing and anchored by
#: nothing. Appended after the fixture's own three so their line numbers do not move.
NEW_SENTENCE = "A deeper encoder improves the operating point more than the protocol does."


@pytest.fixture
def unattached(tmp_path: Path) -> Iterator[tuple[Path, ClaimId, int]]:
    """A finished workspace plus one freshly written sentence that is not yet anchored."""
    station = build_workstation(tmp_path / "project")
    main = station.root / "manuscript" / "main.tex"
    text = main.read_text(encoding="utf-8")
    main.write_text(
        text.replace("\\bibliographystyle", f"{NEW_SENTENCE}\n\n\\bibliographystyle", 1),
        encoding="utf-8",
    )
    ctx = open_context(station.root, HUMAN)
    project = ManuscriptService(ctx).load_project()
    anchored = {anchor.sentence_fingerprint for anchor in ctx.repo.iter_anchors()}
    free = next(
        sentence
        for sentence in project.sentences
        if sentence.fingerprint not in anchored and NEW_SENTENCE in sentence.text
    )
    assert free.line_start not in (SUPPORTED_LINE, MISMATCH_LINE, GHOST_LINE)
    yield station.root, station.claims[0], free.line_start


def anchors(root: Path) -> list[str]:
    repo = WorkspaceRepository.open(root)
    return [f"{anchor.file}:{anchor.line_start}" for anchor in repo.iter_anchors()]


def attach(root: Path, line: int, claim: ClaimId) -> None:
    ManuscriptService(open_context(root, HUMAN)).attach(("main.tex", line), claim)


# ------------------------------------------------------- crashing on either side of the pair


@pytest.mark.parametrize("intent", [ANCHOR_INTENT, EVENT_INTENT], ids=["anchor", "event"])
def test_a_crash_between_the_anchor_and_its_event_leaves_both_or_neither(
    unattached: tuple[Path, ClaimId, int], monkeypatch: pytest.MonkeyPatch, intent: int
) -> None:
    root, claim, line = unattached
    before = anchors(root)
    crash_at(monkeypatch, "_apply_intent", on_call=intent)

    with pytest.raises(PowerCutError):
        attach(root, line, claim)
    monkeypatch.undo()

    recovered = reopen(root)
    after = anchors(root)
    attached = f"main.tex:{line}" in after
    events = [
        summary
        for summary in recovered.summaries("manuscript.claim_attached")
        if summary.endswith(f"main.tex:{line}")
    ]

    assert attached == bool(events)
    assert after == (before if not attached else [*before, f"main.tex:{line}"])
    assert recovered.consistency.consistent, recovered.consistency.summary()
    assert recovered.rebuild_ok and recovered.rebuild_issues == ()
    assert recovered.journal == ()


def test_a_crash_before_the_record_lands_leaves_the_manuscript_graph_untouched(
    unattached: tuple[Path, ClaimId, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, claim, line = unattached
    before = canonical_bytes_digest(root)
    crash_at(monkeypatch, "_write_record")

    with pytest.raises(PowerCutError):
        attach(root, line, claim)
    monkeypatch.undo()

    recovered = reopen(root)

    assert canonical_bytes_digest(root) == before
    assert f"main.tex:{line}" not in anchors(root)
    assert recovered.consistency.consistent


def test_a_crash_at_the_commit_point_completes_the_attachment(
    unattached: tuple[Path, ClaimId, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Everything is on disk; only the rename is missing, so recovery rolls forward."""
    root, claim, line = unattached
    crash_at(monkeypatch, "_commit_record")

    with pytest.raises(PowerCutError):
        attach(root, line, claim)
    monkeypatch.undo()

    repo = WorkspaceRepository.open(root)
    anchor = next(item for item in repo.iter_anchors() if item.line_start == line)

    assert repo.recovery.completed
    assert anchor.claim == claim
    assert anchor.status is ManuscriptAnchorStatus.VALID
    assert repo.consistency.consistent


# ------------------------------------------------------------------------ the retry


def test_retrying_after_an_interruption_leaves_exactly_one_anchor(
    unattached: tuple[Path, ClaimId, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anchors are keyed by `(file, sentence fingerprint)`, so a retry replaces rather than
    duplicates."""
    root, claim, line = unattached
    crash_at(monkeypatch, "_apply_intent", on_call=ANCHOR_INTENT)
    with pytest.raises(PowerCutError):
        attach(root, line, claim)
    monkeypatch.undo()

    attach(root, line, claim)
    attach(root, line, claim)

    recovered = reopen(root)
    matching = [item for item in recovered.repo.iter_anchors() if item.line_start == line]

    assert len(matching) == 1
    assert recovered.consistency.consistent
    assert recovered.rebuild_ok and recovered.rebuild_issues == ()


def test_the_claim_the_sentence_points_at_is_never_touched_by_the_crash(
    unattached: tuple[Path, ClaimId, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attaching binds prose to a Claim; it does not change the Claim (Product §30.1)."""
    root, claim, line = unattached
    before = object_digest(WorkspaceRepository.open(root).get_claim(claim))
    crash_at(monkeypatch, "_apply_intent", on_call=EVENT_INTENT)

    with pytest.raises(PowerCutError):
        attach(root, line, claim)
    monkeypatch.undo()

    repo = reopen(root).repo
    assert object_digest(repo.get_claim(claim)) == before


def test_the_manuscript_source_file_is_never_written_by_an_attachment(
    unattached: tuple[Path, ClaimId, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The researcher's LaTeX is theirs; the harness owns only `anchors.jsonl`."""
    root, claim, line = unattached
    main = (root / "manuscript" / "main.tex").read_bytes()
    crash_at(monkeypatch, "_apply_intent", on_call=ANCHOR_INTENT)

    with pytest.raises(PowerCutError):
        attach(root, line, claim)
    monkeypatch.undo()
    attach(root, line, claim)

    assert (root / "manuscript" / "main.tex").read_bytes() == main


def test_an_interrupted_attachment_leaves_the_earlier_ones_alone(
    unattached: tuple[Path, ClaimId, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The three anchors the loop already wrote are not collateral damage."""
    root, claim, line = unattached
    before = [object_digest(anchor) for anchor in WorkspaceRepository.open(root).iter_anchors()]
    crash_at(monkeypatch, "_apply_intent", on_call=EVENT_INTENT)

    with pytest.raises(PowerCutError):
        attach(root, line, claim)
    monkeypatch.undo()

    repo = reopen(root).repo
    kept = [object_digest(anchor) for anchor in repo.iter_anchors() if anchor.line_start != line]
    assert kept == before
    assert len(before) == 3


def test_the_workstation_fixture_still_has_a_free_sentence(
    unattached: tuple[Path, ClaimId, int],
) -> None:
    """Guards the fixture itself: a test that anchors an already-anchored line proves nothing."""
    root, _, line = unattached
    assert f"main.tex:{line}" not in anchors(root)

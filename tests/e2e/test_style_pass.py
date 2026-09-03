"""Gate 42.L: a style pass cannot replace manuscript text until audit and review succeed.

Product 42.L is a behaviour, not a unit: a real manuscript on disk, the real
`academic-writing` humanizer policy loaded through the real plugin loader, and a rewriter
that does what a rewriter does. What the gate has to prove is that a rewrite which changes a
protected span or moves a proposition up or down the ladder is *held* - and that holding it
costs nothing, because the style pass never had the workspace in the first place.

The last test is the one that matters most and asserts the least: after every pass in this
module has run, every byte under the workspace is where it was.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

import pytest

from research_harness.domain.errors import AuthorityError
from research_harness.manuscript.audit import AuditContext, ManuscriptAuditReport, audit_manuscript
from research_harness.manuscript.latex import LatexProject
from research_harness.manuscript.protected import ProtectedSpanKind
from research_harness.manuscript.style import (
    ChangeReason,
    StylePolicy,
    accept_style_pass,
    run_style_pass,
)
from research_harness.plugins import load_plugin

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugins" / "academic-writing"

MAIN_TEX = r"""\documentclass{article}
\begin{document}
\section{Related work}

Several existing approaches classify application protocols from packet headers
\citep{smith2020}.
In order to measure recall, the system evaluates each flow separately
\citep{jones2021}.
The reported system reaches 94.32 F1 on the reviewed corpus \citep{smith2020}.
We identified no work that evaluates detection on fully encrypted traffic.

\end{document}
"""

REFS_BIB = """@article{smith2020,
  title = {Detecting protocols from headers},
  author = {Smith, Ada},
  year = {2020},
}
@article{jones2021,
  title = {Flow-level evaluation},
  author = {Jones, Bo},
  year = {2021},
}
"""


class _RecordingGateway:
    """An inner gateway that records what reached it, and never reaches the harness."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def call(self, name: str, request: object, *, actor: str) -> object:
        self.calls.append(name)
        return None


@pytest.fixture
def style_workspace(tmp_path: Path) -> Path:
    """A workspace with a manuscript, a bibliography, and a regenerable projection."""
    manuscript = tmp_path / "manuscript"
    manuscript.mkdir()
    (manuscript / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (manuscript / "refs.bib").write_text(REFS_BIB, encoding="utf-8")
    research = tmp_path / ".research"
    research.mkdir()
    (research / "index.sqlite").write_bytes(b"not a real projection")
    (tmp_path / "evidence.jsonl").write_text('{"id": "E0001"}\n', encoding="utf-8")
    return tmp_path


@pytest.fixture
def style_project(style_workspace: Path) -> LatexProject:
    """The manuscript as the harness reads it: sentences, citations, protected spans."""
    return LatexProject.load(style_workspace / "manuscript" / "main.tex")


@pytest.fixture
def style_passage(style_project: LatexProject) -> str:
    """The related-work paragraph, taken from the parsed manuscript rather than a literal."""
    return " ".join(sentence.text for sentence in style_project.sentences)


@pytest.fixture
def humanizer_policy() -> StylePolicy:
    """The real `writing.humanizer` policy, loaded through the real plugin loader."""
    runtime = load_plugin(PLUGIN_DIR, gateway=_RecordingGateway())
    return StylePolicy.from_contribution(runtime.writing_policies["writing.humanizer"])


def _snapshot(root: Path) -> Mapping[str, tuple[str, int]]:
    """Every file under `root`, by content hash and size."""
    return {
        str(path.relative_to(root)): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_size,
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# --------------------------------------------------------------------------- the gate


def test_a_strengthening_rewrite_is_held_until_review_and_audit(
    style_passage: str, humanizer_policy: StylePolicy
) -> None:
    """Widening "several existing approaches" to "all approaches" is an escalation."""
    candidate = run_style_pass(
        style_passage,
        humanizer_policy,
        rewriter=lambda text: text.replace("Several existing approaches", "All approaches"),
    )
    assert candidate.requires_review is True
    assert candidate.audit_required is True
    (change,) = candidate.diff.strengthened
    assert ChangeReason.SCOPE_ESCALATION in change.reasons

    with pytest.raises(AuthorityError):
        accept_style_pass(candidate)
    with pytest.raises(AuthorityError, match="manuscript audit"):
        accept_style_pass(candidate, human_approved=True)
    with pytest.raises(AuthorityError, match="human acceptance"):
        accept_style_pass(candidate, audit_ok=True)
    assert accept_style_pass(candidate, human_approved=True, audit_ok=True) == candidate.after


def test_a_rewrite_that_alters_a_protected_span_is_held(
    style_passage: str, humanizer_policy: StylePolicy
) -> None:
    """Rounding 94.32 to 94.3 is a style choice everywhere except in a manuscript."""
    candidate = run_style_pass(
        style_passage,
        humanizer_policy,
        rewriter=lambda text: text.replace("94.32 F1", "94.3 F1"),
    )
    (violation,) = candidate.diff.protected_violations
    assert violation.kind is ProtectedSpanKind.NUMBER_WITH_UNIT
    assert (violation.before, violation.after) == ("94.32 F1", "94.3 F1")
    assert candidate.requires_review is True
    with pytest.raises(AuthorityError, match="protected span"):
        accept_style_pass(candidate)


def test_a_rewrite_that_drops_a_citation_is_held(
    style_passage: str, humanizer_policy: StylePolicy
) -> None:
    candidate = run_style_pass(
        style_passage,
        humanizer_policy,
        rewriter=lambda text: text.replace("\\citep{jones2021}", "").rstrip(),
    )
    kinds = {violation.kind for violation in candidate.diff.protected_violations}
    assert kinds == {ProtectedSpanKind.CITATION}
    with pytest.raises(AuthorityError):
        accept_style_pass(candidate)


def test_dropping_the_search_bound_is_held_and_named(
    style_passage: str, humanizer_policy: StylePolicy
) -> None:
    """A recorded search result must not become a fact about the world (Product 42.F)."""
    candidate = run_style_pass(
        style_passage,
        humanizer_policy,
        rewriter=lambda text: text.replace("We identified no work that", "No work exists that"),
    )
    (change,) = candidate.diff.negative_evidence_changes
    assert ChangeReason.NEGATIVE_EVIDENCE_WORDING in change.reasons
    with pytest.raises(AuthorityError):
        accept_style_pass(candidate)


def test_a_meaning_preserving_rewrite_passes(
    style_passage: str, humanizer_policy: StylePolicy
) -> None:
    """Filler out, every claim, number, citation, hedge, and scope cue intact."""
    candidate = run_style_pass(
        style_passage,
        humanizer_policy,
        rewriter=lambda text: text.replace("In order to measure", "To measure"),
    )
    assert candidate.diff.is_meaning_preserving
    assert candidate.diff.protected_violations == ()
    assert candidate.requires_review is False
    assert candidate.audit_required is True
    assert "To measure recall" in accept_style_pass(candidate)


def test_the_pass_flags_the_filler_it_did_not_remove(
    style_passage: str, humanizer_policy: StylePolicy
) -> None:
    """With no rewriter the pass is a read-only report on the manuscript as it stands."""
    candidate = run_style_pass(style_passage, humanizer_policy)
    assert candidate.report.rule_ids == ("filler_phrases",)
    assert candidate.changed is False
    assert accept_style_pass(candidate) == style_passage


def test_the_manuscript_audit_is_what_supplies_audit_ok(
    style_project: LatexProject, style_passage: str, humanizer_policy: StylePolicy
) -> None:
    """`audit_ok` is a verdict from `manuscript.audit`, never something the pass computes."""
    report = audit_manuscript(AuditContext(project=style_project))
    assert isinstance(report, ManuscriptAuditReport)
    audit_ok = not report.errors

    candidate = run_style_pass(
        style_passage,
        humanizer_policy,
        rewriter=lambda text: text.replace("Several existing approaches", "All approaches"),
    )
    if audit_ok:
        assert accept_style_pass(candidate, human_approved=True, audit_ok=audit_ok)
    else:  # pragma: no cover - the fixture manuscript audits clean of errors
        with pytest.raises(AuthorityError):
            accept_style_pass(candidate, human_approved=True, audit_ok=audit_ok)


# ------------------------------------------------------------------ nothing is written


def test_the_style_pass_writes_nothing_under_the_workspace(
    style_workspace: Path, style_passage: str, humanizer_policy: StylePolicy
) -> None:
    """Every path the gate could have taken, and the workspace is byte-identical after."""
    before = _snapshot(style_workspace)

    held = run_style_pass(
        style_passage,
        humanizer_policy,
        rewriter=lambda text: text.replace("Several existing approaches", "All approaches"),
    )
    with pytest.raises(AuthorityError):
        accept_style_pass(held)
    accepted_after_review = accept_style_pass(held, human_approved=True, audit_ok=True)

    clean = run_style_pass(
        style_passage,
        humanizer_policy,
        rewriter=lambda text: text.replace("In order to measure", "To measure"),
    )
    accepted_clean = accept_style_pass(clean)

    assert _snapshot(style_workspace) == before
    assert "All approaches" in accepted_after_review
    assert "To measure" in accepted_clean
    assert "All approaches" not in (style_workspace / "manuscript" / "main.tex").read_text("utf-8")


def test_accepting_returns_text_rather_than_writing_it(
    style_workspace: Path, style_passage: str, humanizer_policy: StylePolicy
) -> None:
    """Acceptance is still a capability call; this function has no way to reach state."""
    candidate = run_style_pass(
        style_passage,
        humanizer_policy,
        rewriter=lambda text: text.replace("In order to measure", "To measure"),
    )
    result = accept_style_pass(candidate)
    assert isinstance(result, str)
    assert "In order to measure" in (style_workspace / "manuscript" / "main.tex").read_text("utf-8")

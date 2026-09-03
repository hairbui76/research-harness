"""Product §42.L - Style-pass semantic preservation.

"A humanization or venue-style pass that changes a protected span or strengthens/weakens a
proposition is prevented from replacing accepted manuscript text until semantic audit and
human review succeed."

The passage is the workstation's own manuscript, the policy is the real `academic-writing`
humanizer loaded through the real plugin loader, and the audit that has to bless a rewrite
is the same `manuscript audit` §42.J runs. The assertion that carries the most weight is
the quietest one: after every refused pass in this module, the manuscript on disk is
byte-identical (Product §30.4).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from research_harness.domain.errors import AuthorityError
from research_harness.manuscript.attach import ManuscriptService
from research_harness.manuscript.audit import ManuscriptAuditReport
from research_harness.manuscript.protected import ProtectedSpanKind
from research_harness.manuscript.style import (
    ChangeReason,
    StylePassCandidate,
    StylePolicy,
    accept_style_pass,
    run_style_pass,
)
from research_harness.plugins import load_plugin
from tests.e2e.invariants.workstation import (
    MEASURED_VALUE,
    SUPPORTING_KEY,
    Workstation,
    canonical_bytes_digest,
)

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugins" / "academic-writing"

Rewriter = Callable[[str], str]


class _RecordingGateway:
    """A plugin gateway that records what reached it and never touches the workspace."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def call(self, name: str, request: object, *, actor: str) -> object:
        self.calls.append(name)
        return None


@pytest.fixture(scope="module")
def policy() -> StylePolicy:
    """The real `writing.humanizer` policy, loaded through the real plugin loader."""
    runtime = load_plugin(PLUGIN_DIR, gateway=_RecordingGateway())
    return StylePolicy.from_contribution(runtime.writing_policies["writing.humanizer"])


@pytest.fixture(scope="module")
def passage(workstation: Workstation) -> str:
    """The accepted manuscript text, read from the workspace rather than from a literal."""
    project = ManuscriptService(workstation.context()).load_project()
    return " ".join(sentence.text for sentence in project.sentences)


@pytest.fixture(scope="module")
def audit(workstation: Workstation) -> ManuscriptAuditReport:
    return ManuscriptService(workstation.context()).audit()


def pass_with(passage: str, policy: StylePolicy, rewriter: Rewriter) -> StylePassCandidate:
    return run_style_pass(passage, policy, rewriter=rewriter)


# ------------------------------------------------------------------ strengthened meaning


def test_a_rewrite_that_widens_the_scope_is_held(passage: str, policy: StylePolicy) -> None:
    """Widening the corpus to every deployment is an escalation, not a style choice."""
    candidate = pass_with(
        passage,
        policy,
        lambda text: text.replace(
            "on the reviewed corpus", "in every deployment without exception"
        ),
    )

    (change,) = candidate.diff.strengthened
    assert ChangeReason.SCOPE_ESCALATION in change.reasons
    assert candidate.requires_review is True
    assert candidate.audit_required is True
    with pytest.raises(AuthorityError):
        accept_style_pass(candidate)


def test_a_rewrite_that_drops_a_hedge_is_held(passage: str, policy: StylePolicy) -> None:
    """Removing "degrades" -> "always degrades" strengthens the proposition."""
    candidate = pass_with(
        passage,
        policy,
        lambda text: text.replace(
            "Detection quality degrades", "Detection quality always degrades"
        ),
    )

    assert candidate.diff.is_meaning_preserving is False
    assert candidate.diff.strengthened
    with pytest.raises(AuthorityError, match="changed meaning"):
        accept_style_pass(candidate)


# -------------------------------------------------------------------- protected spans


def test_a_rewrite_that_rounds_a_measured_value_is_held(passage: str, policy: StylePolicy) -> None:
    """Rounding is a style choice everywhere except in a manuscript (Product §12, §30.4)."""
    candidate = pass_with(passage, policy, lambda text: text.replace(MEASURED_VALUE, "94.3"))

    (violation,) = candidate.diff.protected_violations
    assert violation.kind is ProtectedSpanKind.NUMBER_WITH_UNIT
    assert (violation.before, violation.after) == (MEASURED_VALUE, "94.3")
    with pytest.raises(AuthorityError, match="protected span"):
        accept_style_pass(candidate)


def test_a_rewrite_that_drops_a_citation_is_held(passage: str, policy: StylePolicy) -> None:
    """The key is what makes the sentence traceable, so removing it is never cosmetic."""
    candidate = pass_with(
        passage, policy, lambda text: text.replace(f"\\citep{{{SUPPORTING_KEY}}}", "").rstrip()
    )

    kinds = {violation.kind for violation in candidate.diff.protected_violations}
    assert kinds == {ProtectedSpanKind.CITATION}
    with pytest.raises(AuthorityError):
        accept_style_pass(candidate)


# ------------------------------------------------------------------- what unlocks a pass


def test_neither_gate_alone_lets_a_changed_meaning_through(
    passage: str, policy: StylePolicy
) -> None:
    """A human waving through an unaudited rewrite, and an audit standing in for a human."""
    candidate = pass_with(
        passage,
        policy,
        lambda text: text.replace("on the reviewed corpus", "in every deployment"),
    )

    with pytest.raises(AuthorityError, match="manuscript audit"):
        accept_style_pass(candidate, human_approved=True)
    with pytest.raises(AuthorityError, match="human acceptance"):
        accept_style_pass(candidate, audit_ok=True)

    assert accept_style_pass(candidate, human_approved=True, audit_ok=True) == candidate.after


def test_the_manuscript_audit_is_what_supplies_audit_ok(
    passage: str, policy: StylePolicy, audit: ManuscriptAuditReport
) -> None:
    """`audit_ok` is a verdict from `manuscript.audit`, never something the pass computes.

    This manuscript audits with errors (the two §42.J citations), so a researcher who
    approves the rewrite still cannot land it: the audit has to pass first.
    """
    audit_ok = not audit.errors
    assert audit_ok is False

    candidate = pass_with(
        passage,
        policy,
        lambda text: text.replace("on the reviewed corpus", "in every deployment"),
    )

    with pytest.raises(AuthorityError, match="manuscript audit"):
        accept_style_pass(candidate, human_approved=True, audit_ok=audit_ok)


def test_a_meaning_preserving_rewrite_needs_no_review(passage: str, policy: StylePolicy) -> None:
    """The gate is about meaning, not about change: a true copy-edit passes on its own."""
    candidate = pass_with(
        passage, policy, lambda text: text.replace("held-out protocol", "held out protocol")
    )

    assert candidate.changed is True
    assert candidate.diff.is_meaning_preserving is True
    assert candidate.requires_review is False
    assert candidate.audit_required is True
    assert "held out protocol" in accept_style_pass(candidate)


def test_a_candidate_cannot_be_built_with_its_gates_waived(
    passage: str, policy: StylePolicy
) -> None:
    """The gate is a construction invariant, so no caller can assemble its way past it."""
    held = pass_with(
        passage,
        policy,
        lambda text: text.replace("on the reviewed corpus", "in every deployment"),
    )

    with pytest.raises(ValueError, match="always requires human review"):
        StylePassCandidate(
            before=held.before,
            after=held.after,
            diff=held.diff,
            report=held.report,
            requires_review=False,
            audit_required=True,
        )


# --------------------------------------------------------------- nothing reaches disk


def test_no_style_pass_in_this_module_touched_the_manuscript(
    workstation: Workstation, passage: str, policy: StylePolicy
) -> None:
    """Every path the gate could take, and the workspace is byte-identical after."""
    before = canonical_bytes_digest(workstation.root)

    held = pass_with(
        passage,
        policy,
        lambda text: text.replace("on the reviewed corpus", "in every deployment"),
    )
    with pytest.raises(AuthorityError):
        accept_style_pass(held)
    accepted = accept_style_pass(held, human_approved=True, audit_ok=True)

    assert isinstance(accepted, str)
    assert "in every deployment" in accepted
    assert canonical_bytes_digest(workstation.root) == before
    main = (workstation.manuscript_dir / "main.tex").read_text(encoding="utf-8")
    assert "in every deployment" not in main
    assert MEASURED_VALUE in main


def test_accepting_returns_text_rather_than_writing_it(
    workstation: Workstation, passage: str, policy: StylePolicy
) -> None:
    """Acceptance is still a capability call; this function has no way to reach state."""
    candidate = pass_with(
        passage, policy, lambda text: text.replace("held-out protocol", "held out protocol")
    )

    result = accept_style_pass(candidate)

    assert isinstance(result, str)
    assert "held-out protocol" in (workstation.manuscript_dir / "main.tex").read_text("utf-8")

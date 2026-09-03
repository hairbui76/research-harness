"""The style pass and its semantic diff (Product 30.4, 42.L).

Every case here is a sentence pair a reviewer would recognize: the same claim reworded, the
same claim escalated, the same claim with its hedge removed, and the same sentence with a
number or a citation quietly gone. The diff has to tell them apart, and it has to say which
it saw, because "this rewrite changed something" is not a finding anyone can act on.
"""

from __future__ import annotations

import pytest

from research_harness.domain.enums import ClaimScope
from research_harness.domain.errors import AuthorityError
from research_harness.manuscript.protected import ProtectedSpanKind
from research_harness.manuscript.style import (
    CORE_PROTECTED_SPAN_KINDS,
    ChangeDirection,
    ChangeReason,
    Proposition,
    SemanticDiff,
    StylePassCandidate,
    StylePolicy,
    StyleReport,
    StyleRule,
    StyleSeverity,
    accept_style_pass,
    apply_style_rules,
    extract_propositions,
    run_style_pass,
    semantic_diff,
    split_sentences,
)

CITED = "The tokenizer improves recall \\citep{smith2020}."


@pytest.fixture
def policy() -> StylePolicy:
    """A two-rule policy, enough to show that rules fire and protected spans suppress."""
    return StylePolicy(
        name="test.house_style",
        description="A minimal policy for the tests.",
        rules=(
            StyleRule(
                rule_id="filler",
                pattern=r"(?i)\bin order to\b",
                message="Filler.",
                suggestion="to",
            ),
            StyleRule(
                rule_id="stock_phrase",
                pattern=r"(?i)\bdelve into\b",
                message="Stock AI phrasing.",
                suggestion="examine",
                severity=StyleSeverity.ERROR,
            ),
        ),
    )


# --------------------------------------------------------------------- sentence split


def test_sentences_split_on_terminators_but_not_inside_protected_spans() -> None:
    text = (
        "The model reaches 94.32 F1 \\citep{smith2020}. "
        "See Fig. 3 and e.g. Table 1 for the breakdown. "
        "The URL https://example.org/a.b ends the list."
    )
    assert split_sentences(text) == (
        "The model reaches 94.32 F1 \\citep{smith2020}.",
        "See Fig. 3 and e.g. Table 1 for the breakdown.",
        "The URL https://example.org/a.b ends the list.",
    )


def test_a_blank_line_separates_paragraphs() -> None:
    assert split_sentences("First claim here.\n\nSecond claim here.") == (
        "First claim here.",
        "Second claim here.",
    )


# ----------------------------------------------------------------------- propositions


def test_a_proposition_records_scope_numbers_citations_and_qualifiers() -> None:
    (proposition,) = extract_propositions(
        "Several systems may reach 94.3 F1 on the corpus \\citep{smith2020}."
    )
    assert proposition.scope_level is ClaimScope.OBSERVED_SUBSET
    assert proposition.numbers == ("94.3 F1",)
    assert proposition.citations == ("smith2020",)
    assert "may" in proposition.qualifiers
    assert proposition.negations == ()


def test_a_sentence_with_no_scope_cue_has_no_scope_level() -> None:
    """Asserting nothing about the literature is not the same as asserting L0."""
    (proposition,) = extract_propositions("The model tokenizes each header at the byte level.")
    assert proposition.scope_level is None
    assert proposition.effective_scope is ClaimScope.INDIVIDUAL


def test_a_bounded_absence_and_a_bare_one_read_differently() -> None:
    (bounded,) = extract_propositions("We identified no work that evaluates encrypted traffic.")
    (bare,) = extract_propositions("No work exists that evaluates encrypted traffic.")
    assert bounded.scope_level is None
    assert bare.scope_level is ClaimScope.UNIVERSAL_OR_ABSENCE
    assert "we identified no work that" in bounded.negations
    assert "no work exists" in bare.negations


def test_propositions_are_one_per_sentence() -> None:
    assert len(extract_propositions("First claim here. Second claim here.")) == 2


# ------------------------------------------------------------------- meaning preserved


def test_a_reworded_sentence_with_the_same_claim_is_meaning_preserving() -> None:
    diff = semantic_diff(
        "It is important to note that the system utilizes packet headers \\citep{smith2020}.",
        "The system uses packet headers \\citep{smith2020}.",
    )
    assert diff.is_meaning_preserving
    assert diff.unchanged == 1
    assert diff.summary().endswith("1 unchanged")


def test_an_identical_text_is_meaning_preserving() -> None:
    assert semantic_diff(CITED, CITED).is_meaning_preserving


def test_reflowing_whitespace_is_not_a_change() -> None:
    assert semantic_diff(
        "The tokenizer improves\nrecall \\citep{smith2020}.", CITED
    ).is_meaning_preserving


# ------------------------------------------------------------------------ strengthened


def test_several_to_all_is_a_scope_escalation() -> None:
    diff = semantic_diff(
        "Several systems report improved detection.",
        "All systems report improved detection.",
    )
    assert not diff.is_meaning_preserving
    (change,) = diff.strengthened
    assert change.direction is ChangeDirection.STRENGTHENED
    assert ChangeReason.SCOPE_ESCALATION in change.reasons
    assert change.before.scope_level is ClaimScope.OBSERVED_SUBSET
    assert change.after.scope_level is ClaimScope.UNIVERSAL_OR_ABSENCE


def test_removing_a_hedge_strengthens_the_sentence() -> None:
    diff = semantic_diff(
        "The model may improve detection accuracy on encrypted flows.",
        "The model improves detection accuracy on encrypted flows.",
    )
    (change,) = diff.strengthened
    assert change.reasons == (ChangeReason.HEDGE_REMOVED,)
    assert diff.weakened == ()


def test_adding_a_hedge_weakens_the_sentence() -> None:
    diff = semantic_diff(
        "The model improves detection accuracy on encrypted flows.",
        "The model may improve detection accuracy on encrypted flows.",
    )
    (change,) = diff.weakened
    assert change.direction is ChangeDirection.WEAKENED
    assert change.reasons == (ChangeReason.HEDGE_ADDED,)


def test_dropping_the_search_bound_from_an_absence_claim_is_flagged_twice() -> None:
    """Product 10.5 and 42.F: a search result must not become a fact about the world."""
    diff = semantic_diff(
        "We identified no work that evaluates detection on encrypted traffic.",
        "No work exists that evaluates detection on encrypted traffic.",
    )
    (change,) = diff.strengthened
    assert change.direction is ChangeDirection.STRENGTHENED
    assert ChangeReason.SCOPE_ESCALATION in change.reasons
    assert ChangeReason.HEDGE_REMOVED in change.reasons
    assert ChangeReason.NEGATIVE_EVIDENCE_WORDING in change.reasons
    assert change.touches_negative_evidence
    assert diff.negative_evidence_changes == (change,)


def test_restoring_the_search_bound_is_a_weakening_and_still_needs_review() -> None:
    diff = semantic_diff(
        "No work exists that evaluates detection on encrypted traffic.",
        "We identified no work that evaluates detection on encrypted traffic.",
    )
    (change,) = diff.weakened
    assert ChangeReason.NEGATIVE_EVIDENCE_WORDING in change.reasons
    assert not diff.is_meaning_preserving


# ------------------------------------------------------------------ protected spans


def test_a_changed_number_is_a_protected_violation() -> None:
    diff = semantic_diff(
        "The system reaches 94.3 F1 on the reviewed corpus.",
        "The system reaches 96.1 F1 on the reviewed corpus.",
    )
    (violation,) = diff.protected_violations
    assert violation.kind is ProtectedSpanKind.NUMBER_WITH_UNIT
    assert violation.before == "94.3 F1"
    assert violation.after == "96.1 F1"
    assert not diff.is_meaning_preserving
    assert diff.unchanged == 0, "a sentence whose number moved did not survive unchanged"


def test_a_dropped_citation_is_a_protected_violation() -> None:
    diff = semantic_diff(CITED, "The tokenizer improves recall.")
    (violation,) = diff.protected_violations
    assert violation.kind is ProtectedSpanKind.CITATION
    assert violation.before == "\\citep{smith2020}"
    assert violation.after is None


def test_an_invented_citation_is_a_protected_violation() -> None:
    """A style pass has no authority to cite anything (Product 30.2)."""
    diff = semantic_diff("The tokenizer improves recall.", CITED)
    (violation,) = diff.protected_violations
    assert violation.kind is ProtectedSpanKind.CITATION
    assert violation.before is None
    assert violation.after == "\\citep{smith2020}"


def test_an_altered_quotation_is_a_protected_violation() -> None:
    diff = semantic_diff(
        "The authors write ``the split is random'' in Section 4.",
        "The authors write ``the split was random'' in Section 4.",
    )
    kinds = {violation.kind for violation in diff.protected_violations}
    assert ProtectedSpanKind.QUOTATION in kinds


def test_a_dropped_sentence_is_a_removed_proposition() -> None:
    diff = semantic_diff(
        "Alpha uses headers \\citep{a}. Beta uses payloads \\citep{b}.",
        "Alpha uses headers \\citep{a}.",
    )
    assert [proposition.citations for proposition in diff.removed] == [("b",)]
    assert diff.added == ()
    assert not diff.is_meaning_preserving


def test_an_invented_sentence_is_an_added_proposition() -> None:
    diff = semantic_diff(
        "Alpha uses headers \\citep{a}.",
        "Alpha uses headers \\citep{a}. This is the first work to do so.",
    )
    assert len(diff.added) == 1
    assert diff.removed == ()


# ------------------------------------------------------------------------ style rules


def test_rules_fire_with_their_suggestion_and_severity(policy: StylePolicy) -> None:
    report = apply_style_rules("In order to delve into the data, we ran a sweep.", policy)
    assert report.rule_ids == ("filler", "stock_phrase")
    assert [finding.suggestion for finding in report.findings] == ["to", "examine"]
    assert [finding.rule_id for finding in report.errors] == ["stock_phrase"]
    assert report.of_rule("filler")[0].span.text == "In order to"


def test_a_match_inside_a_protected_span_is_not_reported(policy: StylePolicy) -> None:
    quoted = "The authors write ``in order to delve into the data'' in Section 2."
    assert apply_style_rules(quoted, policy).findings == ()


def test_a_policy_cannot_drop_a_core_protected_span() -> None:
    with pytest.raises(ValueError, match="drops core protected spans"):
        StylePolicy(name="test.loose", protected_spans=frozenset({ProtectedSpanKind.MATH}))


def test_a_policy_protects_every_core_span_by_default() -> None:
    assert StylePolicy(name="test.default").protected_spans == CORE_PROTECTED_SPAN_KINDS


def test_a_rule_with_a_broken_pattern_is_refused_at_load() -> None:
    with pytest.raises(ValueError, match="not a valid regex"):
        StyleRule(rule_id="bad", pattern="(unclosed", message="-")


# -------------------------------------------------------------------------- the pass


def test_a_pass_with_no_rewriter_reports_and_changes_nothing(policy: StylePolicy) -> None:
    candidate = run_style_pass("In order to run the sweep, we used two seeds.", policy)
    assert candidate.after == candidate.before
    assert candidate.changed is False
    assert candidate.audit_required is False
    assert candidate.requires_review is False
    assert candidate.report.rule_ids == ("filler",)


def test_a_meaning_preserving_rewrite_is_accepted_on_its_own(policy: StylePolicy) -> None:
    candidate = run_style_pass(
        "In order to measure recall, the system uses packet headers \\citep{smith2020}.",
        policy,
        rewriter=lambda text: text.replace("In order to measure", "To measure"),
    )
    assert candidate.diff.is_meaning_preserving
    assert candidate.requires_review is False
    assert candidate.audit_required is True
    assert accept_style_pass(candidate).startswith("To measure recall")


def test_a_strengthening_rewrite_is_refused_without_review(policy: StylePolicy) -> None:
    candidate = run_style_pass(
        "Several systems report improved detection.",
        policy,
        rewriter=lambda text: text.replace("Several", "All"),
    )
    assert candidate.requires_review is True
    with pytest.raises(AuthorityError, match="human acceptance"):
        accept_style_pass(candidate)
    with pytest.raises(AuthorityError, match="manuscript audit"):
        accept_style_pass(candidate, human_approved=True)
    with pytest.raises(AuthorityError, match="human acceptance"):
        accept_style_pass(candidate, audit_ok=True)
    assert accept_style_pass(candidate, human_approved=True, audit_ok=True) == candidate.after


def test_a_rewrite_that_alters_a_protected_span_is_refused_without_review(
    policy: StylePolicy,
) -> None:
    candidate = run_style_pass(
        "The system reaches 94.3 F1 on the reviewed corpus.",
        policy,
        rewriter=lambda text: text.replace("94.3", "94"),
    )
    assert candidate.diff.protected_violations
    with pytest.raises(AuthorityError):
        accept_style_pass(candidate)


def test_the_refusal_names_what_moved(policy: StylePolicy) -> None:
    candidate = run_style_pass(
        CITED, policy, rewriter=lambda text: text.replace(" \\citep{smith2020}", "")
    )
    with pytest.raises(AuthorityError, match="1 protected span"):
        accept_style_pass(candidate)


def test_a_style_finding_never_blocks_acceptance(policy: StylePolicy) -> None:
    """Style preferences never outrank scientific meaning or venue rules (Product 30.4)."""
    candidate = run_style_pass(
        "We delve into the data.",
        policy,
        rewriter=lambda text: text.replace("We delve", "We then delve"),
    )
    assert candidate.report.errors
    assert candidate.diff.is_meaning_preserving
    assert accept_style_pass(candidate) == candidate.after


def test_a_candidate_cannot_be_built_that_waives_its_own_gate() -> None:
    diff = semantic_diff("Several systems improved.", "All systems improved.")
    with pytest.raises(ValueError, match="always requires human review"):
        StylePassCandidate(
            before="Several systems improved.",
            after="All systems improved.",
            diff=diff,
            report=StyleReport(policy="test.house_style"),
            requires_review=False,
            audit_required=True,
        )


def test_a_changed_candidate_cannot_waive_the_manuscript_audit() -> None:
    with pytest.raises(ValueError, match="requires manuscript audit"):
        StylePassCandidate(
            before="a",
            after="b",
            diff=SemanticDiff(),
            report=StyleReport(policy="test.house_style"),
            requires_review=False,
            audit_required=False,
        )


def test_the_pass_reports_on_the_candidate_not_the_original(policy: StylePolicy) -> None:
    candidate = run_style_pass(
        "We delve into the data.", policy, rewriter=lambda _: "We examine the data."
    )
    assert candidate.report.findings == ()


def test_a_proposition_is_frozen() -> None:
    proposition = Proposition(text="x")
    with pytest.raises(ValueError, match="frozen"):
        proposition.text = "y"  # type: ignore[misc]

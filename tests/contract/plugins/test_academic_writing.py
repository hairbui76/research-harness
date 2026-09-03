"""ROADMAP Task 15.2: writing policies that constrain wording and grant no authority.

The plugin under test is the real one in `plugins/academic-writing`. Its four policies are
data - no code, no capability, no role, no host - so these tests are about what the data
says: every core protected span is preserved, authority is candidate-only, the adapted
humanizer patterns fire on prose that sounds like a chatbot, and none of them fires inside
a span a style pass may not touch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.manuscript.protected import ProtectedSpanKind
from research_harness.manuscript.style import (
    CORE_PROTECTED_SPAN_KINDS,
    StylePolicy,
    StyleSeverity,
    apply_style_rules,
)
from research_harness.plugins import (
    PluginBoundaryError,
    PluginRuntime,
    WritingPolicyContribution,
    load_plugin,
)

from .conftest import RecordingGateway, Request

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugins" / "academic-writing"

POLICIES: tuple[str, ...] = (
    "writing.citation_discipline",
    "writing.claim_language",
    "writing.humanizer",
    "writing.project_style",
)

#: A paragraph built out of the stock patterns humanizer names, one per family.
AI_PARAGRAPH = (
    "Nestled in the evolving landscape of network security, TrafficLM stands as a "
    "testament to modern detection, boasting a vibrant architecture. "
    "Experts argue that byte-level tokenization plays a crucial role, highlighting the "
    "importance of representation. "
    "It is important to note that, in order to achieve this, the model leverages the "
    "power of large-scale pretraining. "
    "Let us dive in. I hope this helps!"
)

#: The same prose after a rewrite that says the same thing without the tells.
PLAIN_PARAGRAPH = (
    "TrafficLM detects application protocols from packet headers. "
    "It tokenizes each header at the byte level. "
    "The encoder is pretrained on unlabelled captures and then fine-tuned."
)


@pytest.fixture
def runtime(gateway: RecordingGateway) -> PluginRuntime:
    """The real `plugins/academic-writing`, loaded against a gateway that reaches nothing."""
    return load_plugin(PLUGIN_DIR, gateway=gateway)


@pytest.fixture
def humanizer(runtime: PluginRuntime) -> StylePolicy:
    return StylePolicy.from_contribution(runtime.writing_policies["writing.humanizer"])


def test_the_plugin_loads_with_all_four_policies(runtime: PluginRuntime) -> None:
    assert runtime.name == "academic-writing"
    assert tuple(sorted(runtime.writing_policies)) == POLICIES


def test_the_plugin_asks_for_nothing(runtime: PluginRuntime) -> None:
    """No capability, no role, no egress: a writing policy needs none of them."""
    assert runtime.manifest.permissions.capabilities == frozenset()
    assert runtime.manifest.permissions.roles_used == frozenset()
    assert runtime.manifest.egress == ()
    assert runtime.validators == {}
    assert runtime.roles == {}
    assert runtime.search_providers == {}


def test_the_gateway_forwards_nothing_at_all(runtime: PluginRuntime) -> None:
    for capability in ("work.get", "evidence.extract", "evidence.accept"):
        with pytest.raises(PluginBoundaryError):
            runtime.gateway.call(capability, Request(), actor="plugin:academic-writing")


# ---------------------------------------------------------------------- the boundary


@pytest.mark.parametrize("name", POLICIES)
def test_every_policy_is_candidate_only(runtime: PluginRuntime, name: str) -> None:
    assert runtime.writing_policies[name].authority == "candidate_only"


@pytest.mark.parametrize("name", POLICIES)
def test_every_policy_protects_every_core_span_kind(runtime: PluginRuntime, name: str) -> None:
    policy = runtime.writing_policies[name]
    assert policy.protected_spans == frozenset(ProtectedSpanKind)
    assert policy.dropped_protections() == frozenset()


@pytest.mark.parametrize("name", POLICIES)
def test_a_loaded_policy_keeps_the_protection_set(runtime: PluginRuntime, name: str) -> None:
    policy = StylePolicy.from_contribution(runtime.writing_policies[name])
    assert policy.protected_spans == CORE_PROTECTED_SPAN_KINDS
    assert policy.authority == "candidate_only"


def test_a_policy_that_drops_a_protection_cannot_be_loaded() -> None:
    """The same refusal `validation.check_writing_policy` makes, at the model boundary."""
    with pytest.raises(ValueError, match="drops core protected spans"):
        StylePolicy(
            name="writing.loose",
            protected_spans=CORE_PROTECTED_SPAN_KINDS - {ProtectedSpanKind.CITATION},
        )


@pytest.mark.parametrize("name", POLICIES)
def test_every_rule_carries_a_suggestion(runtime: PluginRuntime, name: str) -> None:
    """The `"<rule>: <suggestion>"` convention of the README, checked file by file."""
    policy = StylePolicy.from_contribution(runtime.writing_policies[name])
    assert policy.rules, "a policy with no rules constrains nothing"
    assert [rule.rule_id for rule in policy.rules if not rule.suggestion] == []


@pytest.mark.parametrize("name", POLICIES)
def test_guidance_a_regex_cannot_express_is_kept_as_notes(
    runtime: PluginRuntime, name: str
) -> None:
    policy = StylePolicy.from_contribution(runtime.writing_policies[name])
    assert policy.notes, "the rules a machine cannot apply still bind a person"


def test_the_structural_citation_rules_are_notes_not_patterns(runtime: PluginRuntime) -> None:
    """A regex cannot tell whether a key resolves; `manuscript.audit` can (Product 42.J)."""
    policy = StylePolicy.from_contribution(runtime.writing_policies["writing.citation_discipline"])
    joined = "\n".join(policy.notes)
    assert "[NEEDS SOURCE]" in joined
    assert "UNREGISTERED_CLAIM" in joined
    assert "CITATION_MISMATCH" in joined
    assert "UNSUPPORTED_NUMERIC" in joined


def test_the_scope_ladder_of_product_10_5_is_recorded_verbatim(runtime: PluginRuntime) -> None:
    policy = StylePolicy.from_contribution(runtime.writing_policies["writing.claim_language"])
    joined = "\n".join(policy.notes)
    for phrase in (
        "in the work examined",
        "among the papers examined",
        "several existing approaches",
        "most systems in the reviewed corpus",
        "existing work generally",
        "we identified no work that",
    ):
        assert phrase in joined


# ------------------------------------------------------------------- humanizer rules


def test_the_humanizer_flags_a_paragraph_of_stock_phrases(humanizer: StylePolicy) -> None:
    report = apply_style_rules(AI_PARAGRAPH, humanizer)
    assert set(report.rule_ids) >= {
        "inflated_importance",
        "inflated_legacy",
        "sales_language",
        "vague_attribution",
        "stock_ai_phrases",
        "filler_phrases",
        "chatbot_artifacts",
        "announcing_the_point",
        "shallow_ing_analysis",
    }
    assert {finding.rule_id for finding in report.errors} == {
        "vague_attribution",
        "chatbot_artifacts",
    }


def test_every_finding_carries_a_span_a_message_and_a_suggestion(
    humanizer: StylePolicy,
) -> None:
    for finding in apply_style_rules(AI_PARAGRAPH, humanizer).findings:
        assert finding.span.char_end > finding.span.char_start
        assert finding.message and finding.suggestion
        assert finding.severity in (StyleSeverity.ERROR, StyleSeverity.WARNING)


def test_findings_are_deterministic_and_in_document_order(humanizer: StylePolicy) -> None:
    first = apply_style_rules(AI_PARAGRAPH, humanizer)
    second = apply_style_rules(AI_PARAGRAPH, humanizer)
    assert first == second
    starts = [finding.span.char_start for finding in first.findings]
    assert starts == sorted(starts)


def test_plain_prose_raises_nothing(humanizer: StylePolicy) -> None:
    """A pass that fires on ordinary writing is a pass someone switches off."""
    assert apply_style_rules(PLAIN_PARAGRAPH, humanizer).findings == ()


def test_a_stock_phrase_inside_a_quotation_is_not_flagged(humanizer: StylePolicy) -> None:
    """Humanizer 14: a protected span is never changed to remove a flagged pattern."""
    quoted = "The reviewers wrote ``Experts argue that it matters.'' and moved on."
    assert apply_style_rules(quoted, humanizer).findings == ()
    assert apply_style_rules(quoted.replace("``", "").replace("''", ""), humanizer).rule_ids == (
        "vague_attribution",
    )


def test_a_citation_key_that_reads_like_a_stock_phrase_is_not_flagged(
    humanizer: StylePolicy,
) -> None:
    cited = "The encoder is pretrained \\citep{nestled2020,vibrant2021}."
    assert apply_style_rules(cited, humanizer).findings == ()


def test_all_seven_required_pattern_families_are_present(runtime: PluginRuntime) -> None:
    """ROADMAP Task 15.2's list, each family represented by at least one rule."""
    policy = StylePolicy.from_contribution(runtime.writing_policies["writing.humanizer"])
    ids = {rule.rule_id for rule in policy.rules}
    families = {
        "inflated claims": {"inflated_importance", "inflated_legacy"},
        "sales language": {"sales_language", "commitment_language"},
        "vague attributions": {"vague_attribution"},
        "stock AI phrases": {"stock_ai_phrases", "avoiding_is_and_are", "pretend_deeper_truth"},
        "filler": {"filler_phrases", "qualifier_pileup", "generic_positive_ending"},
        "chatbot artifacts": {"chatbot_artifacts", "announcing_the_point", "emoji_decoration"},
        "repetitive structure": {"shallow_ing_analysis", "not_x_but_y", "false_range"},
    }
    for family, expected in families.items():
        assert expected <= ids, f"{family} is not represented"


# ------------------------------------------------------------------- the other policies


def test_claim_language_flags_escalation_but_not_a_bounded_statement(
    runtime: PluginRuntime,
) -> None:
    policy = StylePolicy.from_contribution(runtime.writing_policies["writing.claim_language"])
    escalated = "No prior work exists on encrypted-traffic detection, and we prove it."
    assert set(apply_style_rules(escalated, policy).rule_ids) == {
        "l4_universal_without_coverage",
        "proof_verbs",
    }
    bounded = (
        "We identified no work that evaluates detection on encrypted traffic in the "
        "searches recorded for this review."
    )
    assert apply_style_rules(bounded, policy).findings == ()


def test_citation_discipline_flags_a_hand_typed_citation_without_touching_the_year(
    runtime: PluginRuntime,
) -> None:
    policy = StylePolicy.from_contribution(runtime.writing_policies["writing.citation_discipline"])
    report = apply_style_rules("Smith et al. (2020) report a similar result.", policy)
    assert report.rule_ids == ("hand_typed_citation",)
    assert "2020" not in report.findings[0].span.text


def test_citation_discipline_accepts_a_properly_cited_sentence(runtime: PluginRuntime) -> None:
    policy = StylePolicy.from_contribution(runtime.writing_policies["writing.citation_discipline"])
    cited = "Several studies have reported the same effect \\citep{smith2020,jones2021}."
    assert apply_style_rules(cited, policy).findings == ()


def test_project_style_flags_stacked_hedges_and_future_tense(runtime: PluginRuntime) -> None:
    policy = StylePolicy.from_contribution(runtime.writing_policies["writing.project_style"])
    report = apply_style_rules(
        "We will show that the tokenizer may potentially improve recall.", policy
    )
    assert set(report.rule_ids) == {"future_tense_for_completed_work", "stacked_hedges"}


def test_a_writing_policy_contribution_is_what_the_loader_returns(
    runtime: PluginRuntime,
) -> None:
    for contribution in runtime.writing_policies.values():
        assert isinstance(contribution, WritingPolicyContribution)

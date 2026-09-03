"""The cue table: what a manuscript sentence claims, on the Product 10.2 ladder."""

from __future__ import annotations

import pytest

from research_harness.claims.strength import (
    FIELD_WORDING,
    INDIVIDUAL_WORDING,
    MAJORITY_WORDING,
    OBSERVED_SUBSET_WORDING,
    SEVERAL_WORDING,
    UNIVERSAL_WORDING,
)
from research_harness.domain.enums import ClaimScope
from research_harness.manuscript.wording import (
    CUE_TABLE,
    HEDGE_CUES,
    cues_in,
    stronger_than,
    wording_level,
)

L0 = ClaimScope.INDIVIDUAL
L1 = ClaimScope.OBSERVED_SUBSET
L2 = ClaimScope.CORPUS_PATTERN
L3 = ClaimScope.FIELD_GENERALIZATION
L4 = ClaimScope.UNIVERSAL_OR_ABSENCE


# -- the table ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "level"),
    [
        ("All existing detectors ignore load.", L4),
        ("Encrypted traffic always defeats signature detectors.", L4),
        ("Such a detector never recovers its operating point.", L4),
        ("No work exists on load-dependent degradation.", L4),
        ("No prior work reports the size of the gap.", L4),
        ("The effect holds universally across capture sites.", L4),
        ("Every classifier in this family degrades.", L4),
        (f"{FIELD_WORDING} relies on flow-level features.", L3),
        ("The field has settled on flow-level features.", L3),
        ("The literature reports the same degradation.", L3),
        ("In general the operating point moves.", L3),
        ("Existing systems ignore offered load.", L3),
        ("The state of the art ignores offered load.", L3),
        (f"{MAJORITY_WORDING} ignore offered load.", L2),
        ("Most detectors ignore offered load.", L2),
        ("The majority of detectors ignore offered load.", L2),
        ("Detectors typically ignore offered load.", L2),
        ("Detectors commonly ignore offered load.", L2),
        (f"{SEVERAL_WORDING} ignore offered load.", L2),
        ("Several detectors ignore offered load.", L1),
        ("Some detectors ignore offered load.", L1),
        (f"{OBSERVED_SUBSET_WORDING}, three ignore offered load.", L1),
        ("A number of detectors ignore offered load.", L1),
        ("This paper reports a load-dependent gap.", L0),
        ("The authors report a load-dependent gap.", L0),
        (f"The encoder wins {INDIVIDUAL_WORDING}.", L0),
        ("The tokenizer buckets inter-arrival times.", L0),
    ],
)
def test_each_documented_cue_scores_its_documented_level(sentence: str, level: ClaimScope) -> None:
    assert wording_level(sentence).level is level


def test_the_table_covers_every_ladder_level() -> None:
    assert set(CUE_TABLE) == set(ClaimScope)


def test_the_strongest_cue_in_a_sentence_decides_its_level() -> None:
    estimate = wording_level("Most detectors ignore load, and none of them ever recovers.")
    assert estimate.level is L4
    assert estimate.cues == ("none of",)


def test_a_sentence_with_no_cue_scores_the_ladder_floor() -> None:
    estimate = wording_level("We replay captured traffic through each classifier.")
    assert estimate.level is L0
    assert estimate.cues == ()
    assert not estimate.hedged


def test_cues_are_matched_as_whole_words() -> None:
    assert wording_level("Allocation of buffers is unchanged.").level is L0
    assert wording_level("The someone-else problem is out of scope.").level is L0


def test_citation_commands_and_markup_do_not_create_cues() -> None:
    assert wording_level("The gap is real \\citep{all2020,every2021}.").level is L0
    assert wording_level("\\textbf{Most} detectors ignore load.").level is L2


# -- the L1/L2 boundary ---------------------------------------------------------------


def test_several_existing_approaches_is_the_corpus_level_wording_not_the_subset_one() -> None:
    """Product 10.5 lists it as the wording for several independent supports, which the
    ladder emits at L2; a bare "several" stays at L1."""
    boundary = wording_level(f"{SEVERAL_WORDING} ignore offered load.")
    assert boundary.level is L2
    assert boundary.cues == (SEVERAL_WORDING,)
    assert wording_level("Several approaches ignore offered load.").level is L1


def test_a_quantifier_pulls_a_bare_plural_off_the_field_level() -> None:
    assert wording_level("Existing systems ignore load.").level is L3
    assert wording_level("Several existing systems ignore load.").level is L1
    assert wording_level("Most existing systems ignore load.").level is L2


# -- hedges ---------------------------------------------------------------------------


def test_a_hedge_lowers_the_level_by_one() -> None:
    plain = wording_level("No prior work reports the gap.")
    hedged = wording_level("To our knowledge, no prior work reports the gap.")
    assert plain.level is L4
    assert hedged.level is L3
    assert hedged.unhedged_level is L4
    assert hedged.hedged
    assert hedged.hedges == ("to our knowledge",)


def test_the_product_10_5_absence_hedge_never_reads_as_universal() -> None:
    assert wording_level("We identified no work that reports the gap.").level.level < L4.level
    assert wording_level(f"{UNIVERSAL_WORDING} reports the gap.").level is L4


def test_hedging_cannot_push_a_sentence_below_the_ladder_floor() -> None:
    estimate = wording_level("To our knowledge the tokenizer is unchanged.")
    assert estimate.level is L0
    assert estimate.unhedged_level is L0
    assert not estimate.hedged


@pytest.mark.parametrize("hedge", HEDGE_CUES)
def test_every_hedge_is_recognized(hedge: str) -> None:
    estimate = wording_level(f"Most detectors, {hedge} the setup, ignore load.")
    assert hedge in estimate.hedges
    assert estimate.level is L1


# -- comparison -----------------------------------------------------------------------


def test_stronger_than_compares_ladder_level_not_string_order() -> None:
    assert stronger_than(L4, L2)
    assert stronger_than(L2, L1)
    assert not stronger_than(L2, L2)
    assert not stronger_than(L0, L4)


def test_cues_in_reports_every_level_that_matched() -> None:
    found = cues_in("Most detectors ignore load, and the literature agrees.")
    assert found[L3] == ("the literature",)
    assert found[L2] == ("most",)
    assert L4 not in found

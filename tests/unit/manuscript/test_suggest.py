"""A model rewrite is a candidate: what it may say, what it may not, and what it may not do.

The property under test everywhere in this file is the one Product 42.L names: a style pass
that changes a protected span, moves a proposition, or makes a sentence claim more than its
accepted Claim allows is *held*, and holding it costs nothing because the pass never had
the file. Every test therefore checks two things at once - the verdict, and that the bytes
under `manuscript/` are exactly where they were.

The rewriter is a scripted provider, which is what a rewriter is from this module's point
of view: something that turns a passage into a passage and is not trusted with either.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import CreateClaimRequest
from research_harness.capabilities.handlers import create_claim
from research_harness.domain.base import Provenance
from research_harness.domain.claim import Claim, ClaimAssessment, ClaimScopeSpec, ClaimSemantics
from research_harness.domain.enums import (
    ClaimScope,
    ClaimStatus,
    ClaimType,
    ManuscriptAnchorStatus,
    ManuscriptFindingKind,
    ResearchEventType,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import ClaimId
from research_harness.manuscript.attach import ManuscriptService
from research_harness.manuscript.files import ManuscriptConflictError, ManuscriptFiles
from research_harness.manuscript.suggest import (
    STAGING_SUGGESTIONS_DIRNAME,
    AuditStatus,
    DiffLineKind,
    apply_suggestion,
    list_suggestions,
    policy_for,
    staged_suggestion,
    suggest_edit,
    unified_hunks,
)
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.workspace.repository import WorkspaceRepository

HUMAN = "human:alice"
CLAIM = ClaimId("C0001")

#: Line 8 is the anchored sentence, and every test rewrites lines 8-9.
MAIN_TEX = """\\documentclass{article}
\\usepackage{natbib}

\\begin{document}

\\section{Introduction}

Several existing classifiers degrade under sustained load, and the size of the gap is
rarely reported \\citep{kraus2019}.

We compile the manuscript from source the researcher owns.

\\end{document}
"""

ANCHOR_LINE = 8
SPAN = (8, 9)

REFERENCES_BIB = """@article{kraus2019,
  author = {Kraus, Anja},
  title  = {Measuring fairness under load},
  year   = {2019}
}
"""


def make_claim(level: ClaimScope = ClaimScope.CORPUS_PATTERN) -> Claim:
    """A claim whose allowed strength is what the anchored sentence is measured against."""
    return Claim(
        id=CLAIM,
        statement="classifiers in the reviewed corpus degrade under sustained load",
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(
            subject="classifiers", predicate="degrade", object="under sustained load"
        ),
        scope=ClaimScopeSpec(level=level, corpus="traffic classifiers"),
        assessment=ClaimAssessment(
            requested_strength=level,
            allowed_strength=level,
            status=ClaimStatus.SUPPORTED,
            maximum_defensible_wording="several classifiers in the reviewed corpus",
        ),
        provenance=Provenance.human(HUMAN),
    )


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[CapabilityContext]:
    """A workspace whose manuscript has one anchored sentence and one Claim."""
    root = tmp_path / "project"
    WorkspaceRepository.init(root, "suggest")
    context = open_context(root, HUMAN)
    create_claim(context, CreateClaimRequest(claim=make_claim()))

    manuscript = root / "manuscript"
    manuscript.mkdir(parents=True, exist_ok=True)
    (manuscript / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (manuscript / "references.bib").write_text(REFERENCES_BIB, encoding="utf-8")
    ManuscriptService(context).attach(("main.tex", ANCHOR_LINE), CLAIM)
    yield context


@pytest.fixture
def files(ctx: CapabilityContext) -> ManuscriptFiles:
    return ManuscriptFiles(ctx.repo.layout)


def rewriter(draft: str, **extra: Any) -> ScriptedProvider:
    """A provider that answers the writer role with one rewritten passage."""
    return ScriptedProvider([{"draft": draft, **extra}])


def suggest(ctx: CapabilityContext, draft: str, **kwargs: Any) -> Any:
    return suggest_edit(
        ctx,
        file="main.tex",
        line_start=SPAN[0],
        line_end=SPAN[1],
        provider=rewriter(draft),
        style=kwargs.pop("style", "humanize"),
        **kwargs,
    )


#: A rewrite that joins two lines: byte-different, meaning-identical, protected spans kept.
SAFE = (
    "Several existing classifiers degrade under sustained load, and the size of the gap "
    "is rarely reported \\citep{kraus2019}.\n"
)

#: The same sentence with the citation dropped - a protected span the pass may not touch.
DROPS_CITATION = (
    "Several existing classifiers degrade under sustained load, and the size of the gap "
    "is rarely reported.\n"
)

#: The same claim, escalated from "several" to "all": the wording ladder moves.
OVER_STRONG = (
    "All classifiers degrade under sustained load, and the size of the gap is never "
    "reported \\citep{kraus2019}.\n"
)


# -- the diff ----------------------------------------------------------------


def test_an_unchanged_text_has_no_hunks() -> None:
    assert unified_hunks("a\nb\nc\n", "a\nb\nc\n") == ()


def test_a_hunk_carries_context_removed_and_added_lines_with_both_line_numbers() -> None:
    hunks = unified_hunks("a\nb\nc\n", "a\nB\nc\n")

    assert len(hunks) == 1
    kinds = [line.kind for line in hunks[0].lines]
    assert DiffLineKind.REMOVED in kinds and DiffLineKind.ADDED in kinds
    removed = next(line for line in hunks[0].lines if line.kind is DiffLineKind.REMOVED)
    added = next(line for line in hunks[0].lines if line.kind is DiffLineKind.ADDED)
    assert (removed.text, removed.old_line, removed.new_line) == ("b", 2, None)
    assert (added.text, added.old_line, added.new_line) == ("B", None, 2)
    assert hunks[0].header.startswith("@@ -1,")


def test_context_lines_carry_the_line_number_on_both_sides() -> None:
    hunks = unified_hunks("a\nb\nc\n", "a\nB\nc\n")
    context = [line for line in hunks[0].lines if line.kind is DiffLineKind.CONTEXT]

    assert [(line.old_line, line.new_line) for line in context] == [(1, 1), (3, 3)]


# -- policies ----------------------------------------------------------------


@pytest.mark.parametrize("style", ["humanize", "venue", "copyedit"])
def test_every_offered_style_keeps_every_protected_span(style: str) -> None:
    """`StylePolicy` refuses a policy that drops one, so this is the whole guarantee."""
    from research_harness.manuscript.style import CORE_PROTECTED_SPAN_KINDS

    assert policy_for(style).protected_spans == CORE_PROTECTED_SPAN_KINDS


def test_an_unknown_style_is_refused_by_name() -> None:
    with pytest.raises(CapabilityError, match="unknown style"):
        policy_for("make it snappy")


def test_a_suggestion_needs_a_style_or_an_instruction(ctx: CapabilityContext) -> None:
    with pytest.raises(CapabilityError, match="style"):
        suggest_edit(
            ctx,
            file="main.tex",
            line_start=8,
            line_end=9,
            provider=rewriter(SAFE),
            style=None,
        )


# -- staging never writes source ---------------------------------------------


def test_producing_a_candidate_leaves_the_manuscript_byte_identical(
    ctx: CapabilityContext, files: ManuscriptFiles
) -> None:
    """LaTeX spec 10.5: a humanized paragraph cannot silently overwrite source."""
    before = files.hash_of("main.tex")

    candidate = suggest(ctx, OVER_STRONG)

    assert candidate.changed
    assert files.hash_of("main.tex") == before
    assert files.read("main.tex").content == MAIN_TEX


def test_the_candidate_is_staged_under_research_staging_manuscript(
    ctx: CapabilityContext,
) -> None:
    candidate = suggest(ctx, SAFE)

    assert candidate.path is not None
    assert candidate.path.startswith(f".research/{STAGING_SUGGESTIONS_DIRNAME}/")
    assert (ctx.repo.root / candidate.path).is_file()
    assert staged_suggestion(ctx, candidate.candidate_id) == candidate
    assert [item.candidate_id for item in list_suggestions(ctx)] == [candidate.candidate_id]


def test_the_candidate_records_the_hash_of_the_file_it_was_built_against(
    ctx: CapabilityContext, files: ManuscriptFiles
) -> None:
    candidate = suggest(ctx, SAFE)

    assert candidate.source_hash == files.hash_of("main.tex")
    assert candidate.original_text.startswith("Several existing classifiers")
    assert candidate.proposed_content.count("\\citep{kraus2019}") == 1


def test_the_originating_message_and_context_pack_are_kept_with_the_candidate(
    ctx: CapabilityContext,
) -> None:
    """LaTeX spec 8: a suggested edit is tied to the message and receipt that produced it."""
    candidate = suggest(
        ctx, SAFE, session_id="CS0001", message_id="M0042", context_pack_id="CP0007"
    )

    assert candidate.provenance.session_id == "CS0001"
    assert candidate.provenance.message_id == "M0042"
    assert candidate.provenance.context_pack_id == "CP0007"
    assert candidate.provenance.provenance.workflow == "manuscript.suggest"


# -- verdicts ----------------------------------------------------------------


def test_a_meaning_preserving_rewrite_passes(ctx: CapabilityContext) -> None:
    candidate = suggest(ctx, SAFE)

    assert candidate.audit_status is AuditStatus.PASSED
    assert candidate.blocked_reason is None
    assert candidate.protected_preserved
    assert candidate.applicable


def test_dropping_a_citation_fails_the_candidate_and_names_the_span(
    ctx: CapabilityContext,
) -> None:
    candidate = suggest(ctx, DROPS_CITATION)

    assert candidate.audit_status is AuditStatus.FAILED
    assert not candidate.protected_preserved
    assert [item.kind.value for item in candidate.protected_violations] == ["citation"]
    assert "protected span" in (candidate.blocked_reason or "")


def test_a_rewrite_that_outruns_the_claim_is_reported_as_over_strong_wording(
    ctx: CapabilityContext,
) -> None:
    """The check survives the rewrite breaking the anchor, which is the point of it."""
    candidate = suggest(ctx, OVER_STRONG)

    kinds = {finding.kind for finding in candidate.audit_findings}
    assert ManuscriptFindingKind.OVER_STRONG_WORDING in kinds
    assert candidate.audit_status is AuditStatus.FAILED
    over_strong = next(
        finding
        for finding in candidate.audit_findings
        if finding.kind is ManuscriptFindingKind.OVER_STRONG_WORDING
    )
    assert str(CLAIM) in over_strong.message
    assert over_strong.location is not None and over_strong.location.file == "main.tex"


def test_a_rewrite_of_an_anchored_sentence_reports_the_anchor_it_would_invalidate(
    ctx: CapabilityContext,
) -> None:
    """Reported, not blocking: revalidation is the answer, not a refusal to ever edit."""
    candidate = suggest(ctx, OVER_STRONG)

    impact = next(item for item in candidate.anchor_impacts if item.claim == CLAIM)
    assert impact.status is ManuscriptAnchorStatus.STALE
    assert impact.similarity is not None
    assert any(
        finding.kind is ManuscriptFindingKind.STALE_CLAIM for finding in candidate.audit_findings
    )


def test_a_line_range_outside_the_file_is_refused_before_the_model_runs(
    ctx: CapabilityContext,
) -> None:
    provider = rewriter(SAFE)
    with pytest.raises(CapabilityError, match="lines"):
        suggest_edit(
            ctx,
            file="main.tex",
            line_start=800,
            line_end=900,
            provider=provider,
            style="humanize",
        )
    assert provider.requests == []


# -- applying ----------------------------------------------------------------


def test_applying_a_passed_candidate_writes_the_file_and_records_an_event(
    ctx: CapabilityContext, files: ManuscriptFiles
) -> None:
    candidate = suggest(ctx, SAFE)

    applied = apply_suggestion(ctx, candidate.candidate_id)

    assert files.read("main.tex").content == candidate.proposed_content
    assert applied.snapshot.content_hash == files.hash_of("main.tex")
    assert applied.event.event is ResearchEventType.MANUSCRIPT_SOURCE_WRITTEN
    assert applied.event.payload["candidate_id"] == candidate.candidate_id
    assert applied.event.actor == HUMAN
    recorded = [item for item in ctx.repo.iter_events() if item.event is applied.event.event]
    assert len(recorded) == 1


def test_the_applied_candidate_is_marked_applied_and_cannot_be_applied_twice(
    ctx: CapabilityContext,
) -> None:
    candidate = suggest(ctx, SAFE)
    apply_suggestion(ctx, candidate.candidate_id)

    reread = staged_suggestion(ctx, candidate.candidate_id)
    assert reread is not None and reread.applied and reread.applied_at is not None
    with pytest.raises(CapabilityError, match="already applied"):
        apply_suggestion(ctx, candidate.candidate_id)


def test_applying_a_candidate_that_changed_a_protected_span_is_refused(
    ctx: CapabilityContext, files: ManuscriptFiles
) -> None:
    candidate = suggest(ctx, DROPS_CITATION)
    before = files.hash_of("main.tex")

    with pytest.raises(CapabilityError, match="protected span"):
        apply_suggestion(ctx, candidate.candidate_id)

    assert files.hash_of("main.tex") == before


def test_applying_a_candidate_that_failed_the_audit_is_refused(
    ctx: CapabilityContext, files: ManuscriptFiles
) -> None:
    candidate = suggest(ctx, OVER_STRONG)
    before = files.hash_of("main.tex")

    with pytest.raises(CapabilityError, match="failed"):
        apply_suggestion(ctx, candidate.candidate_id)

    assert files.hash_of("main.tex") == before


def test_applying_against_a_stale_hash_is_a_conflict_carrying_both_hashes(
    ctx: CapabilityContext, files: ManuscriptFiles
) -> None:
    candidate = suggest(ctx, SAFE)
    stale = f"sha256:{'0' * 64}"
    before = files.hash_of("main.tex")

    with pytest.raises(ManuscriptConflictError) as raised:
        apply_suggestion(ctx, candidate.candidate_id, expected_hash=stale)

    assert raised.value.expected_hash == stale
    assert raised.value.actual_hash == before
    assert files.hash_of("main.tex") == before


def test_applying_after_somebody_else_edited_the_file_is_refused(
    ctx: CapabilityContext, files: ManuscriptFiles
) -> None:
    """The candidate's own hash is the default, so an outside edit is a conflict."""
    candidate = suggest(ctx, SAFE)
    files.write("main.tex", MAIN_TEX + "\n% an external editor was here\n", candidate.source_hash)

    with pytest.raises(ManuscriptConflictError):
        apply_suggestion(ctx, candidate.candidate_id)


def test_applying_an_unknown_candidate_says_so(ctx: CapabilityContext) -> None:
    with pytest.raises(CapabilityError, match="no staged manuscript suggestion"):
        apply_suggestion(ctx, "run_20260101T000000Z_deadbeef")


def test_a_candidate_id_that_is_not_an_id_never_becomes_a_path(ctx: CapabilityContext) -> None:
    with pytest.raises(CapabilityError, match="candidate id"):
        staged_suggestion(ctx, "../../../etc/passwd")

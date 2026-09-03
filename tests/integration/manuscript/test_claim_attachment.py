"""Roadmap Task 9.2: substantive prose links to a Claim, and a reword breaks the link loudly.

The two acceptance requirements are one behaviour seen from both ends. Attaching is a
researcher act over prose that asserts something: a heading, a caption, and a signpost are
refused, and so is a model actor. Revalidating is the other end: a sentence that only moved
keeps its anchor and gains new line numbers, because its fingerprint proves it is the same
text, while a reworded or deleted one is recorded ``stale``/``missing`` rather than left
pointing confidently at text that no longer says what the Claim says (ADR-008).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

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
    ProvenanceSource,
    ResearchEventType,
    StaleState,
)
from research_harness.domain.errors import AuthorityError
from research_harness.domain.ids import ClaimId
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.manuscript import (
    ManuscriptError,
    ManuscriptService,
    anchor_key,
    sentence_fingerprint,
)
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workflows.manuscript_audit import report_path
from research_harness.workflows.models import RunStatus
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.runs import RunStore

CLAIM = ClaimId("C0001")
OTHER_CLAIM = ClaimId("C0002")
HUMAN = "human:alice"
MODEL = "vendor-a/model-x"

ANCHORED = (
    "Structured traffic classifiers degrade under sustained load, and several existing "
    "approaches never report it \\citep{hart2018}."
)
REWORDED = (
    "Structured traffic classifiers degrade sharply under sustained load, and several "
    "existing approaches never report the size of it \\citep{hart2018}."
)
SECOND = (
    "The corrected split changes the reported operating point for every model we "
    "measured \\citep{ostrom2020}."
)
SIGNPOST = "See Table 2."

BODY = """\\documentclass{{article}}
\\usepackage{{natbib}}

\\begin{{document}}

\\section{{Introduction}}
\\label{{sec:intro}}

{first}

{second}

\\begin{{figure}}
\\caption{{Throughput against offered load for the four classifiers we measured.}}
\\end{{figure}}

\\end{{document}}
"""

HEADING_LINE = 6
FIRST_LINE = 9
CAPTION_LINE = 14


def write_manuscript(root: Path, *, first: str = ANCHORED, second: str = SECOND) -> Path:
    """Write the fixture manuscript into the workspace's canonical `manuscript/` directory."""
    directory = root / "manuscript"
    directory.mkdir(parents=True, exist_ok=True)
    main = directory / "main.tex"
    main.write_text(BODY.format(first=first, second=second), encoding="utf-8")
    return main


def make_claim(claim_id: ClaimId, statement: str) -> Claim:
    """A minimal accepted claim; this test is about the anchor, not the claim engine."""
    return Claim(
        id=claim_id,
        statement=statement,
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(
            subject="structured traffic classifiers", predicate="degrade", object=statement[:40]
        ),
        scope=ClaimScopeSpec(level=ClaimScope.CORPUS_PATTERN, corpus="traffic classifiers"),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.CORPUS_PATTERN,
            allowed_strength=ClaimScope.CORPUS_PATTERN,
            status=ClaimStatus.SUPPORTED,
        ),
        provenance=Provenance.human(HUMAN),
    )


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[CapabilityContext]:
    root = tmp_path / "project"
    WorkspaceRepository.init(root, "attachment")
    context = open_context(root, HUMAN)
    create_claim(context, CreateClaimRequest(claim=make_claim(CLAIM, "Classifiers degrade")))
    create_claim(
        context, CreateClaimRequest(claim=make_claim(OTHER_CLAIM, "The split moves the point"))
    )
    write_manuscript(root)
    yield context


@pytest.fixture
def service(ctx: CapabilityContext) -> ManuscriptService:
    return ManuscriptService(ctx)


def stored(ctx: CapabilityContext) -> tuple[ManuscriptAnchor, ...]:
    return tuple(ctx.repo.iter_anchors())


def only_anchor(ctx: CapabilityContext) -> ManuscriptAnchor:
    anchors = stored(ctx)
    assert len(anchors) == 1, f"expected one stored anchor, got {len(anchors)}"
    return anchors[0]


# -- attaching --------------------------------------------------------------------------


def test_attaching_a_substantive_sentence_persists_the_anchor_and_its_event(
    ctx: CapabilityContext, service: ManuscriptService
) -> None:
    anchor, mutation = service.attach(("main.tex", FIRST_LINE), CLAIM)

    assert anchor.claim == CLAIM
    assert anchor.file == "main.tex"
    assert anchor.line_start == FIRST_LINE
    assert anchor.status is ManuscriptAnchorStatus.VALID
    assert anchor.stale is StaleState.FRESH
    assert anchor.citation_keys == ("hart2018",)
    assert anchor.sentence_fingerprint == sentence_fingerprint(anchor.sentence)
    assert anchor.provenance.source is ProvenanceSource.HUMAN

    persisted = only_anchor(ctx)
    assert persisted.model_dump() == anchor.model_dump()
    assert anchor_key(persisted) == f"main.tex#{anchor.sentence_fingerprint}"

    assert mutation.capability == "manuscript.attach_claim"
    assert mutation.event.event is ResearchEventType.MANUSCRIPT_CLAIM_ATTACHED
    assert mutation.event.event.value == "manuscript.claim_attached"
    assert CLAIM in mutation.event.subjects
    assert mutation.event.payload["sentence_fingerprint"] == anchor.sentence_fingerprint
    assert mutation.event.payload["citation_keys"] == "hart2018"
    assert mutation.validation.ok

    logged = [
        event for event in ctx.repo.iter_events() if event.event.value.startswith("manuscript")
    ]
    assert [event.event for event in logged] == [ResearchEventType.MANUSCRIPT_CLAIM_ATTACHED]


def test_attaching_by_text_finds_the_same_sentence(
    ctx: CapabilityContext, service: ManuscriptService
) -> None:
    by_text, _ = service.attach(
        service.find_sentence_by_text("The corrected split changes the reported operating point"),
        OTHER_CLAIM,
    )
    assert by_text.line_start == FIRST_LINE + 2
    assert by_text.citation_keys == ("ostrom2020",)
    assert only_anchor(ctx).claim == OTHER_CLAIM


def test_a_heading_is_not_attachable(service: ManuscriptService) -> None:
    with pytest.raises(ManuscriptError, match="heading"):
        service.attach(("main.tex", HEADING_LINE), CLAIM)


def test_a_float_and_its_caption_are_not_attachable(service: ManuscriptService) -> None:
    with pytest.raises(ManuscriptError, match="figure"):
        service.attach(("main.tex", CAPTION_LINE), CLAIM)


def test_a_signpost_sentence_is_not_substantive_enough_to_carry_a_claim(
    ctx: CapabilityContext,
) -> None:
    write_manuscript(ctx.root, first=SIGNPOST)
    service = ManuscriptService(ctx)

    with pytest.raises(ManuscriptError, match="not a substantive sentence"):
        service.attach(("main.tex", FIRST_LINE), CLAIM)
    assert stored(ctx) == ()


def test_a_model_actor_may_not_attach_a_claim_to_manuscript_text(ctx: CapabilityContext) -> None:
    as_model = ManuscriptService(open_context(ctx.root, MODEL))

    with pytest.raises(AuthorityError, match="only a human actor"):
        as_model.attach(("main.tex", FIRST_LINE), CLAIM)
    assert stored(ctx) == ()


def test_attaching_to_a_claim_the_workspace_does_not_hold_is_refused(
    ctx: CapabilityContext, service: ManuscriptService
) -> None:
    with pytest.raises(Exception, match="no claim C0404"):
        service.attach(("main.tex", FIRST_LINE), ClaimId("C0404"))
    assert stored(ctx) == ()


def test_a_location_outside_the_manuscript_is_refused(service: ManuscriptService) -> None:
    with pytest.raises(ManuscriptError, match="not part of this manuscript"):
        service.attach(("sections/nowhere.tex", 1), CLAIM)
    with pytest.raises(ManuscriptError, match="carries no manuscript sentence"):
        service.attach(("main.tex", 2), CLAIM)


# -- revalidation -----------------------------------------------------------------------


def test_an_unchanged_manuscript_revalidates_clean_and_rewrites_nothing(
    ctx: CapabilityContext, service: ManuscriptService
) -> None:
    anchor, _ = service.attach(("main.tex", FIRST_LINE), CLAIM)

    report = service.revalidate()

    assert [result.status for result in report.results] == [ManuscriptAnchorStatus.VALID]
    assert report.relocated == ()
    assert report.applied == ()
    assert report.mutations == ()
    assert only_anchor(ctx).model_dump() == anchor.model_dump()


def test_moving_a_sentence_relocates_the_anchor_and_re_records_its_lines(
    ctx: CapabilityContext, service: ManuscriptService
) -> None:
    anchor, _ = service.attach(("main.tex", FIRST_LINE), CLAIM)
    main = ctx.root / "manuscript" / "main.tex"
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            "\\section{Introduction}",
            "\\section{Introduction}\n\nA new opening paragraph pushes everything down the file.",
        ),
        encoding="utf-8",
    )

    report = service.revalidate()

    assert len(report.relocated) == 1
    moved = report.relocated[0]
    assert moved.status is ManuscriptAnchorStatus.VALID
    assert moved.similarity == 1.0
    assert moved.relocated is not None
    assert moved.relocated.line_start > FIRST_LINE

    recorded = only_anchor(ctx)
    assert recorded.line_start == moved.relocated.line_start
    assert recorded.line_end == moved.relocated.line_end
    assert recorded.status is ManuscriptAnchorStatus.VALID
    assert recorded.stale is StaleState.FRESH
    assert anchor_key(recorded) == anchor_key(anchor), "a relocation keeps the anchor's key"
    assert report.applied_keys == (anchor_key(anchor),)
    assert [mutation.capability for mutation in report.mutations] == ["manuscript.attach_claim"]


def test_rewording_a_sentence_makes_the_anchor_stale_rather_than_following_the_edit(
    ctx: CapabilityContext, service: ManuscriptService
) -> None:
    anchor, _ = service.attach(("main.tex", FIRST_LINE), CLAIM)
    write_manuscript(ctx.root, first=REWORDED)

    report = service.revalidate()

    assert len(report.stale) == 1
    verdict = report.stale[0]
    assert verdict.status is ManuscriptAnchorStatus.STALE
    assert verdict.similarity is not None and 0.75 <= verdict.similarity < 1.0
    assert verdict.relocated is not None, "the best rewrite candidate is reported"
    assert verdict.relocated.normalized_text != anchor.sentence
    assert "reworded" in verdict.reason

    recorded = only_anchor(ctx)
    assert recorded.status is ManuscriptAnchorStatus.STALE
    assert recorded.stale is StaleState.STALE
    assert recorded.sentence == anchor.sentence, "the anchor keeps pointing at what it recorded"
    assert recorded.sentence_fingerprint == anchor.sentence_fingerprint
    assert recorded.line_start == anchor.line_start, "a stale anchor is never silently moved"
    assert report.valid == ()


def test_a_stale_anchor_is_never_left_recorded_valid_even_without_applying(
    ctx: CapabilityContext, service: ManuscriptService
) -> None:
    service.attach(("main.tex", FIRST_LINE), CLAIM)
    write_manuscript(ctx.root, first=REWORDED)

    dry = service.revalidate(apply=False)

    assert [result.status for result in dry.results] == [ManuscriptAnchorStatus.STALE]
    assert dry.applied == () and dry.mutations == ()
    assert only_anchor(ctx).status is ManuscriptAnchorStatus.VALID, "a dry run records nothing"

    applied = service.revalidate()
    assert applied.applied_keys == (anchor_key(only_anchor(ctx)),)
    assert only_anchor(ctx).status is ManuscriptAnchorStatus.STALE


def test_deleting_a_sentence_makes_the_anchor_missing(
    ctx: CapabilityContext, service: ManuscriptService
) -> None:
    anchor, _ = service.attach(("main.tex", FIRST_LINE), CLAIM)
    write_manuscript(
        ctx.root, first="An unrelated paragraph about tooling replaces the anchored claim."
    )

    report = service.revalidate()

    assert len(report.missing) == 1
    assert report.missing[0].status is ManuscriptAnchorStatus.MISSING
    assert "no sentence" in report.missing[0].reason

    recorded = only_anchor(ctx)
    assert recorded.status is ManuscriptAnchorStatus.MISSING
    assert recorded.stale is StaleState.STALE
    assert recorded.claim == anchor.claim


def test_revalidation_is_idempotent_once_the_verdict_is_recorded(
    ctx: CapabilityContext, service: ManuscriptService
) -> None:
    service.attach(("main.tex", FIRST_LINE), CLAIM)
    write_manuscript(ctx.root, first=REWORDED)
    service.revalidate()
    before = only_anchor(ctx)

    again = service.revalidate()

    assert again.applied == (), "re-recording an unchanged verdict would be noise"
    assert only_anchor(ctx).model_dump() == before.model_dump()


def test_revalidation_reports_every_anchor_including_the_ones_that_still_hold(
    ctx: CapabilityContext, service: ManuscriptService
) -> None:
    service.attach(("main.tex", FIRST_LINE), CLAIM)
    service.attach(("main.tex", FIRST_LINE + 2), OTHER_CLAIM)
    write_manuscript(ctx.root, first=REWORDED)

    report = service.revalidate()

    assert len(report.results) == 2
    assert len(report.stale) == 1 and len(report.valid) == 1
    payload = report.as_dict()
    assert payload["checked"] == 2 and payload["stale"] == 1 and payload["valid"] == 1
    assert {str(item["claim"]) for item in payload["results"]} == {str(CLAIM), str(OTHER_CLAIM)}


# -- the audit the attachment feeds -----------------------------------------------------


def test_the_audit_sees_the_anchor_and_the_unanchored_sentence_beside_it(
    service: ManuscriptService,
) -> None:
    service.attach(("main.tex", FIRST_LINE), CLAIM)

    report = service.audit(parsed=False)

    assert report.anchored_sentences == 1
    assert report.unanchored_substantive == 1
    assert report.sentences_checked == 2
    assert [link.claim for link in report.trace] == [CLAIM]


def test_a_durable_audit_run_writes_its_report_under_the_research_directory(
    ctx: CapabilityContext, service: ManuscriptService
) -> None:
    service.attach(("main.tex", FIRST_LINE), CLAIM)
    engine = WorkflowEngine(RunStore(ctx.repo.layout.research_dir))

    run, report = service.audit_durable(engine, parsed=False)

    assert run.status is RunStatus.succeeded
    written = report_path(ctx.repo.layout.research_dir, run.run_id)
    assert written.is_file()
    assert written.is_relative_to(ctx.repo.layout.research_dir / "staging")
    assert len(json.loads(written.read_text(encoding="utf-8"))["findings"]) == len(report.findings)


def test_tracing_returns_none_until_a_sentence_carries_an_anchor(
    service: ManuscriptService,
) -> None:
    assert service.trace("main.tex", FIRST_LINE) is None
    service.attach(("main.tex", FIRST_LINE), CLAIM)
    link = service.trace("main.tex", FIRST_LINE)
    assert link is not None and link.claim == CLAIM

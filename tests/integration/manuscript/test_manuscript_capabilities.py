"""The manuscript capabilities the VS Code client had to work around (Product 28).

Four gaps are closed here, and each is asserted as the behaviour the editor needs:

* `manuscript.audit` takes a file and a line range, so auditing a selection does not audit
  (and re-parse the sources of) the whole project;
* every finding carries a structured `location`, so a diagnostic is placed by reading a
  field rather than by parsing the `"<file>:<line>: "` prefix off the message;
* `manuscript.anchors` reports every anchor with its verdict, and `manuscript.revalidate`
  is the mutation that records those verdicts - the editor no longer offers to run a
  terminal command;
* `manuscript.trace` answers for one sentence instead of costing a whole-project audit.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import CreateClaimRequest
from research_harness.capabilities.handlers import create_claim
from research_harness.capabilities.permissions import Permission, PermissionDenied, Principal
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.domain.enums import ManuscriptAnchorStatus
from research_harness.domain.errors import CapabilityError
from research_harness.manuscript import ManuscriptError, ManuscriptService, anchor_key
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.manuscript.test_claim_attachment import (
    ANCHORED,
    CLAIM,
    FIRST_LINE,
    HUMAN,
    OTHER_CLAIM,
    REWORDED,
    SECOND,
    make_claim,
    write_manuscript,
)

SECOND_LINE = 11


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    return build_default_registry()


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[CapabilityContext]:
    """A workspace with two claims and a manuscript whose first sentence is anchored."""
    root = tmp_path / "project"
    WorkspaceRepository.init(root, "manuscript-capabilities")
    context = open_context(root, HUMAN)
    create_claim(context, CreateClaimRequest(claim=make_claim(CLAIM, "Classifiers degrade")))
    create_claim(
        context, CreateClaimRequest(claim=make_claim(OTHER_CLAIM, "The split moves the point"))
    )
    write_manuscript(root)
    ManuscriptService(context).attach(("main.tex", FIRST_LINE), CLAIM)
    yield context


def call(
    registry: CapabilityRegistry, ctx: CapabilityContext, name: str, request: dict[str, Any]
) -> Any:
    return registry.invoke(name, ctx, request, principal=Principal.human())


# -- permissions -------------------------------------------------------------


def test_reading_the_manuscript_is_a_read_and_recording_it_is_not(
    registry: CapabilityRegistry,
) -> None:
    """Computing a verdict changes nothing; recording one is a change to accepted state."""
    assert registry.get("manuscript.anchors").permission is Permission.READ
    assert registry.get("manuscript.trace").permission is Permission.READ
    assert registry.get("manuscript.audit").permission is Permission.READ
    revalidate = registry.get("manuscript.revalidate")
    assert revalidate.permission is Permission.MUTATE
    assert revalidate.human_only


def test_an_agent_host_may_read_the_anchors_but_not_record_them(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    host = Principal.agent_host("some-host")
    answer = registry.invoke("manuscript.anchors", ctx, {}, principal=host)
    assert answer.count == 1

    with pytest.raises(PermissionDenied):
        registry.invoke("manuscript.revalidate", ctx, {}, principal=host)


# -- structured locations ----------------------------------------------------


def test_every_finding_carries_the_location_a_diagnostic_is_placed_at(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """The gap `report.ts::findingLocation` worked around: parsing prose for a line number."""
    report = call(registry, ctx, "manuscript.audit", {})

    assert report.findings, "the fixture manuscript raises findings"
    for finding in report.findings:
        assert finding.location is not None
        assert finding.location.file == "main.tex"
        assert finding.location.line_start >= 1
        assert finding.location.line_end >= finding.location.line_start
        assert finding.message.startswith(
            f"{finding.location.file}:{finding.location.line_start}: "
        )


def test_an_unanchored_sentence_still_carries_a_location(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """The finding with no anchor is exactly the one that needed a structured location."""
    report = call(registry, ctx, "manuscript.audit", {})
    unregistered = [
        finding for finding in report.findings if finding.kind.value == "unregistered_claim"
    ]

    assert unregistered, "the fixture leaves one substantive sentence unattached"
    for finding in unregistered:
        assert finding.anchor is None
        assert finding.location is not None


# -- narrowing the audit -----------------------------------------------------


def test_a_line_range_reports_only_the_sentences_inside_it(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    whole = call(registry, ctx, "manuscript.audit", {})
    narrowed = call(
        registry,
        ctx,
        "manuscript.audit",
        {"file": "main.tex", "line_start": SECOND_LINE, "line_end": SECOND_LINE},
    )

    assert narrowed.sentences_checked == 1
    assert narrowed.sentences_checked < whole.sentences_checked
    assert {finding.location.line_start for finding in narrowed.findings} == {SECOND_LINE}
    assert narrowed.revalidations == (), "the only anchor is outside the range"


def test_a_range_covering_the_anchor_keeps_its_verdict_and_its_trace(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    narrowed = call(
        registry,
        ctx,
        "manuscript.audit",
        {"file": "main.tex", "line_start": FIRST_LINE, "line_end": FIRST_LINE},
    )

    assert narrowed.anchored_sentences == 1
    assert narrowed.unanchored_substantive == 0
    assert [result.anchor.claim for result in narrowed.revalidations] == [CLAIM]
    assert [link.claim for link in narrowed.trace] == [CLAIM]


def test_a_line_range_without_a_file_is_refused_rather_than_guessed(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    with pytest.raises(CapabilityError, match="needs the file"):
        call(registry, ctx, "manuscript.audit", {"line_start": 1, "line_end": 5})


def test_a_whole_project_audit_is_unchanged_by_the_new_fields(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """Narrowing changes what is asked about, never what counts as a finding."""
    service_report = ManuscriptService(ctx).audit()
    capability_report = call(registry, ctx, "manuscript.audit", {})

    assert capability_report.sentences_checked == service_report.sentences_checked
    assert [item.kind for item in capability_report.findings] == [
        item.kind for item in service_report.findings
    ]


# -- anchors and revalidation ------------------------------------------------


def test_manuscript_anchors_reports_the_verdict_without_recording_it(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    write_manuscript(ctx.root, first=REWORDED, second=SECOND)

    answer = call(registry, ctx, "manuscript.anchors", {})

    assert [verdict.status for verdict in answer.verdicts] == [ManuscriptAnchorStatus.STALE.value]
    assert [anchor.status for anchor in answer.anchors] == [ManuscriptAnchorStatus.VALID.value]
    stored = next(iter(ctx.repo.iter_anchors()))
    assert stored.status is ManuscriptAnchorStatus.VALID, "a read records nothing"


def test_revalidate_records_the_reword_and_a_dry_run_does_not(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """ADR-008: a reworded sentence goes stale; it is never quietly reattached."""
    write_manuscript(ctx.root, first=REWORDED, second=SECOND)

    dry = call(registry, ctx, "manuscript.revalidate", {"dry_run": True})
    assert dry.dry_run is True
    assert dry.stale == 1
    assert dry.applied == ()
    assert next(iter(ctx.repo.iter_anchors())).status is ManuscriptAnchorStatus.VALID

    applied = call(registry, ctx, "manuscript.revalidate", {})
    stored = next(iter(ctx.repo.iter_anchors()))
    assert applied.dry_run is False
    assert applied.applied == (anchor_key(stored),)
    assert stored.status is ManuscriptAnchorStatus.STALE
    assert applied.mutations, "recording a verdict is a journalled mutation"


def test_revalidate_is_quiet_when_nothing_moved(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    first = call(registry, ctx, "manuscript.revalidate", {})
    second = call(registry, ctx, "manuscript.revalidate", {})

    assert first.applied == ()
    assert second.applied == ()
    assert second.valid == 1


# -- trace -------------------------------------------------------------------


def test_trace_answers_for_one_sentence(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    answer = call(registry, ctx, "manuscript.trace", {"file": "main.tex", "line": FIRST_LINE})

    assert answer.claim == str(CLAIM)
    assert answer.anchor == anchor_key(next(iter(ctx.repo.iter_anchors())))
    assert answer.sentence
    assert answer.link is not None
    assert answer.link["claim"] == str(CLAIM)


def test_trace_says_a_sentence_carries_no_claim_rather_than_failing(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """ "No first link" is a different answer from "the chain is broken"."""
    answer = call(registry, ctx, "manuscript.trace", {"file": "main.tex", "line": SECOND_LINE})

    assert answer.claim is None
    assert answer.anchor is None
    assert answer.link is None
    assert answer.sentence.startswith("The corrected split")


def test_trace_refuses_a_line_that_carries_no_sentence(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """A `ResearchHarnessError`, so every transport reports the same stable code."""
    with pytest.raises(ManuscriptError, match="carries no manuscript sentence"):
        call(registry, ctx, "manuscript.trace", {"file": "main.tex", "line": 1})


def test_the_anchored_sentence_is_the_one_the_fixture_wrote(ctx: CapabilityContext) -> None:
    """Guards the line constants above; a fixture drift would silently weaken every test."""
    sentence = ManuscriptService(ctx).find_sentence("main.tex", FIRST_LINE)
    assert sentence.normalized_text.startswith(ANCHORED[:40].split("\\")[0].strip())

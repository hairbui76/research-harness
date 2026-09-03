"""Gate P12: a reproducible SearchRun, a snowball, screening, and one audited absence claim.

The whole gate runs through the real `research` CLI against in-memory discovery sources: no
network, no keys, no recorded traffic. What it demonstrates is the thing Phase 12 exists
for -- that "we found nothing" becomes a checkable record rather than an impression:

1. a search that a broken source left incomplete, persisted with that gap on the record;
2. a snowball from one seed, recorded as its own run;
3. inclusion and exclusion decisions, the exclusion carrying its reason;
4. an absence claim asking for L4 that is **refused** while a source was never finished;
5. the same claim **permitted** the hedged wording once a rerun finishes that source, with
   the unresolved works and the overturn risk stated rather than rounded away.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import AcceptEvidenceRequest, CreateClaimRequest
from research_harness.capabilities.handlers import accept_evidence, create_claim
from research_harness.claims.coverage import CoverageUniverse
from research_harness.cli.app import app as cli_app
from research_harness.cli.commands import discover as discover_commands
from research_harness.discovery.absence import AbsenceAuditReport, audit_absence_claim
from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
)
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimType,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.evidence import Evidence, EvidenceContent, SourceAnchor
from research_harness.domain.ids import BlockId, ClaimId, EvidenceId, WorkId
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.domain.work import Work
from research_harness.providers.search.base import (
    ReferenceCandidates,
    SearchProviderRegistry,
    SearchRateLimitError,
)
from tests.integration.discovery.fakes import FakeSearchSource, record

runner = CliRunner()

SEED_DOI = "10.5555/seed"
INCLUDED_DOI = "10.5555/included"
EXCLUDED_DOI = "10.5555/excluded"
SNOWBALLED_DOI = "10.5555/snowballed"
UNIVERSE = "peer-reviewed work on structured traffic representation for LLM detection"
CUTOFF = "2026-08"
QUOTE = "No system in this survey represents traffic at the protocol-field level."
PDF_BYTES = b"%PDF-1.7\n% acquired source for the included candidate\n"


def digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


@pytest.fixture
def field_sources() -> tuple[FakeSearchSource, FakeSearchSource]:
    """A source that answers and publishes a reference list, and one that is rate limited."""
    answering = FakeSearchSource(
        "answering",
        pages=[
            [
                record("answering", doi=INCLUDED_DOI, title="A survey of traffic tokenization"),
                record("answering", doi=EXCLUDED_DOI, title="Image classification at scale"),
            ]
        ],
        references={
            SEED_DOI: ReferenceCandidates(
                [record("answering", doi=SNOWBALLED_DOI, title="Earlier flow representations")],
                # The publisher deposited 4 records; 3 are fragments of a segmented list.
                warnings=(
                    "reference_drops: answering deposited 4 record(s); "
                    "3 reference fragment(s) were not made into seeds",
                ),
            )
        },
    )
    throttled = FakeSearchSource(
        "throttled",
        pages=[[record("throttled", doi="10.5555/behind-the-limit", title="Unreachable")]],
        error=SearchRateLimitError("429 too many requests", source="throttled"),
    )
    return answering, throttled


@pytest.fixture
def workspace(
    tmp_path: Path, field_sources: tuple[FakeSearchSource, FakeSearchSource], monkeypatch: Any
) -> Iterator[Path]:
    """A workspace whose `research` CLI searches the in-memory sources and nothing else."""
    monkeypatch.setattr(
        discover_commands,
        "build_registry",
        lambda sources=None, policy=None: SearchProviderRegistry(field_sources),
    )
    root = tmp_path / "gate-p12"
    assert run("init", str(root), "--name", "gate-p12").exit_code == 0
    yield root


def app() -> typer.Typer:
    """The real CLI with the discovery family mounted.

    `cli/commands/__init__.py` is wired at the phase gate by the project manager; mounting
    here keeps the gate runnable either way and never registers the family twice.
    """
    names = {command.name for command in cli_app.registered_commands}
    if "discover" not in names:
        discover_commands.register(cli_app)
    return cli_app


def run(*args: str) -> Result:
    return runner.invoke(app(), list(args))


def payload(result: Result) -> Any:
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def context(root: Path) -> CapabilityContext:
    return open_context(root, HUMAN_ACTOR)


# -- the gate ----------------------------------------------------------------


def test_gate_p12_discovery_snowball_screening_and_one_audited_absence_claim(
    workspace: Path, field_sources: tuple[FakeSearchSource, FakeSearchSource], tmp_path: Path
) -> None:
    answering, throttled = field_sources
    space = ["-w", str(workspace)]

    # 1. A reproducible SearchRun, with the source that broke recorded as broken.
    first = payload(run("discover", "traffic tokenization", *space, "--cutoff", CUTOFF, "--json"))
    assert first["id"] == "SR0001"
    assert first["results"]["discovered"] == 2
    assert [failure["source"] for failure in first["failures"]] == ["throttled"]
    assert "rate_limit" in first["failures"][0]["reason"]
    stopped = {cursor["source"]: cursor["exhausted"] for cursor in first["cursors"]}
    assert stopped == {"answering": True, "throttled": False}

    # 2. Snowball from one seed; the walk is its own run, linked to the sources that answered.
    walked = payload(
        run("snowball", f"doi:{SEED_DOI}", *space, "--direction", "backward", "--json")
    )
    assert walked["id"] == "SR0002"
    assert walked["sources"] == ["answering"]
    assert walked["queries"] == [f"snowball:doi:{SEED_DOI}"]
    assert [entry["key"] for entry in walked["candidates"]] == [f"doi:{SNOWBALLED_DOI}"]
    # Dogfood F10: the fragments the adapter refused to seed from are on the run, so
    # `failures: []` cannot certify a denominator that quietly shrank.
    dropped = [entry for entry in walked["failures"] if "reference_drops" in entry["reason"]]
    assert dropped and dropped[0]["incomplete"] is False
    assert [cursor["exhausted"] for cursor in walked["cursors"]] == [True]

    # 3. Inclusion and exclusion, each persisting its reason (dogfood F9).
    included = payload(
        run(
            "screen",
            "SR0001",
            f"doi:{INCLUDED_DOI}",
            *space,
            "--include",
            "--reason",
            "tokenizes raw traffic",
            "--json",
        )
    )
    assert included["screening"] == "included"
    assert included["reason"] == "tokenizes raw traffic"
    assert included["matched_work"] is None, "inclusion alone must not create a Work"
    excluded = payload(
        run(
            "screen",
            "SR0001",
            f"doi:{EXCLUDED_DOI}",
            *space,
            "--exclude",
            "not about network traffic",
            "--json",
        )
    )
    assert excluded["screening"] == "excluded"
    listed = run("screen", "list", "SR0001", *space)
    assert listed.exit_code == 0
    assert "not about network traffic" in listed.stdout
    assert "tokenizes raw traffic" in listed.stdout, "an inclusion reason is readable too"

    # 4. Acquiring the source is what creates the Work; then it can be read and cited.
    source_file = tmp_path / "included.pdf"
    source_file.write_bytes(PDF_BYTES)
    acquired = payload(
        run("acquire", "SR0001", f"doi:{INCLUDED_DOI}", str(source_file), *space, "--json")
    )
    work = WorkId(acquired["work"])
    claim = _accepted_claim(context(workspace), work)

    # 5. The absence claim is refused while a source was never finished.
    before = _audit(workspace, claim.id)
    assert before.permitted is False
    assert before.wording is None
    assert any("never completed" in reason for reason in before.reasons)
    assert before.overturn_risk.value == "high"
    assert before.incomplete_runs == ("SR0001",)

    refused = run("coverage", "C0001", *space, "--universe", UNIVERSE, "--cutoff", CUTOFF)
    assert refused.exit_code == 0
    assert "NOT permitted" in refused.stdout
    assert "(refused)" in refused.stdout
    assert "overturn risk      high" in refused.stdout

    # 6. A rerun finishes the source that failed; the record now supports hedged wording.
    throttled.heal()
    again = payload(run("discover", "rerun", "SR0001", *space, "--json"))
    assert again["id"] == "SR0003"
    assert again["reproduces"] == "SR0001"
    assert again["failures"] == []
    assert all(cursor["exhausted"] for cursor in again["cursors"])
    assert {entry["key"] for entry in again["candidates"]} == {
        entry["key"] for entry in first["candidates"]
    } | {"doi:10.5555/behind-the-limit"}

    after = _audit(workspace, claim.id)
    assert after.permitted is True
    assert after.wording is not None
    assert after.wording.startswith("Within the")
    assert "we identified no work that" in after.wording
    assert CUTOFF in after.wording
    assert "no work exists" not in after.wording
    assert after.overturn_risk.value in {"low", "low_moderate"}
    assert after.incomplete_runs == ()
    assert after.allowed_scope < ClaimScope.UNIVERSAL_OR_ABSENCE

    # 7. The CLI says the same thing, with the unresolved works and the risk explicit.
    permitted = payload(
        run("coverage", "C0001", *space, "--universe", UNIVERSE, "--cutoff", CUTOFF, "--json")
    )
    assert permitted["permitted"] is True
    assert permitted["wording"] == after.wording
    assert permitted["overturn_risk"] == after.overturn_risk.value
    assert permitted["unresolved"] == list(after.unresolved)
    assert permitted["incomplete_runs"] == []
    assert permitted["funnel"]["relevant"] == 1
    assert permitted["funnel"]["examined"] == 1
    assert permitted["coverage"]["search_runs"] == ["SR0002", "SR0003"]

    human = run("coverage", "C0001", *space, "--universe", UNIVERSE, "--cutoff", CUTOFF)
    assert "absence audit: permitted" in human.stdout
    assert "we identified no work that" in human.stdout
    assert f"unresolved         {len(after.unresolved)}" in human.stdout
    assert "overturn risk      " in human.stdout
    assert answering.searches and throttled.searches


def test_an_empty_synthesis_cell_never_promotes_to_an_absence_claim(
    workspace: Path, field_sources: tuple[FakeSearchSource, FakeSearchSource], tmp_path: Path
) -> None:
    """ROADMAP 12.5: an empty cell means 'not recorded', and agreeing models are still models."""
    _, throttled = field_sources
    space = ["-w", str(workspace)]
    assert (
        run("discover", "traffic tokenization", *space, "--cutoff", CUTOFF, "--json").exit_code == 0
    )
    run("screen", "SR0001", f"doi:{INCLUDED_DOI}", *space, "--include")
    source_file = tmp_path / "included.pdf"
    source_file.write_bytes(PDF_BYTES)
    acquired = payload(
        run("acquire", "SR0001", f"doi:{INCLUDED_DOI}", str(source_file), *space, "--json")
    )
    claim = _accepted_claim(context(workspace), WorkId(acquired["work"]))
    throttled.heal()
    assert run("discover", "rerun", "SR0001", *space, "--json").exit_code == 0

    report = _audit(workspace, claim.id, matrix_cell_empty=True, models_agree=True)

    assert report.permitted is True, "coverage, not the cell, is what permits it"
    assert any("empty synthesis cell" in reason for reason in report.reasons)
    assert any("agreement between models" in reason for reason in report.reasons)
    assert any("coverage must be the stated basis" in reason for reason in report.reasons)

    result = run(
        "coverage",
        "C0001",
        *space,
        "--universe",
        UNIVERSE,
        "--cutoff",
        CUTOFF,
        "--matrix-cell-empty",
        "--models-agree",
    )
    assert result.exit_code == 0
    assert "not 'the work lacks it'" in result.stdout


# -- fixtures the gate builds through the capability layer --------------------


def _accepted_claim(ctx: CapabilityContext, work: WorkId) -> Claim:
    """One accepted Evidence read from the acquired artifact, and the absence Claim it bears on."""
    record_work: Work = ctx.repo.get_work(work)
    artifact = ctx.repo.list_artifacts(work)[0]
    evidence = Evidence(
        id=EvidenceId("E0001"),
        source=SourceAnchor(
            work=work,
            version=record_work.versions[0],
            artifact=artifact.id,
            file_hash=artifact.file_hash,
            block=BlockId("B0001"),
            text_hash=digest(QUOTE.encode()),
            page=7,
            section_path=("Discussion",),
            char_start=0,
            char_end=len(QUOTE),
        ),
        content=EvidenceContent(exact_text=QUOTE),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.AUTHOR_CONCLUSION,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_1,
        provenance=Provenance.human(),
    )
    accept_evidence(
        ctx,
        AcceptEvidenceRequest(candidate=evidence, verdict=VerificationVerdict.SUPPORTED),
    )
    claim = Claim(
        id=ClaimId("C0001"),
        statement="No surveyed system represents traffic at the protocol-field level.",
        type=ClaimType.ABSENCE,
        semantics=ClaimSemantics(
            subject="surveyed traffic representation systems",
            predicate="represents traffic at",
            object="the protocol-field level",
        ),
        scope=ClaimScopeSpec(
            level=ClaimScope.UNIVERSAL_OR_ABSENCE,
            corpus="structured traffic representation",
            publication_until=CUTOFF,
        ),
        relations=(
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0001"), relation=ClaimEvidenceRelationType.SUPPORTS
            ),
        ),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.UNIVERSAL_OR_ABSENCE,
            allowed_strength=ClaimScope.INDIVIDUAL,
        ),
        provenance=Provenance.human(),
    )
    create_claim(ctx, CreateClaimRequest(claim=claim))
    return claim


def _audit(root: Path, claim: ClaimId, **flags: bool) -> AbsenceAuditReport:
    """Audit the claim the way `research coverage` does, straight through the service."""
    ctx = context(root)
    works = {work.id: work for work in ctx.repo.list_works()}
    evidence = {item.id: item for work in works for item in ctx.repo.iter_evidence(work)}
    return audit_absence_claim(
        ctx.repo.get_claim(claim),
        ctx.repo.list_search_runs(),
        CoverageUniverse(definition=UNIVERSE, cutoff=CUTOFF),
        works,
        evidence,
        **flags,
    )

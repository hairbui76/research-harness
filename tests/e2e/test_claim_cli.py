"""Gate P7 through the CLI: a claim deliberately stronger than its evidence is cut down.

The gate (ROADMAP Phase 7): create a claim deliberately stronger than its evidence;
`research claim audit` must return a weaker maximum defensible wording, show
support/qualifiers/counter-evidence, and prevent silent strength escalation.

The workspace is the real one: the synthetic paper is ingested and parsed through
`research ingest` and `research parse`, the first Evidence object is anchored in a block that
parse actually produced, and the second artifact is a revision of the same Work, so the two
Evidence objects it carries are one unit of support rather than two (Product 17).

Everything below the claim commands runs through the capability layer, because there is no
evidence CLI in this family; everything from `claim create` on runs through `research`.
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
from research_harness.capabilities.dto import (
    AcceptEvidenceRequest,
    AddArtifactRequest,
    RegisterWorkRequest,
)
from research_harness.capabilities.handlers import (
    accept_evidence,
    add_version_artifact,
    register_work,
)
from research_harness.cli.app import app
from research_harness.cli.commands import COMMAND_MODULES
from research_harness.cli.commands import claim as claim_commands
from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    ArtifactKind,
    ClaimScope,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    ProvenanceSource,
    ReviewTier,
    VerificationVerdict,
    VersionKind,
)
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    SourceAnchor,
    VerificationRecord,
)
from research_harness.domain.ids import ArtifactId, BlockId, EvidenceId, WorkId
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.domain.work import CandidateMetadata, IdentifierField, WorkCandidate

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_research_paper.pdf"
STATEMENT = "Existing work generally tokenizes encrypted traffic heterogeneously."
ASPECT = "tokenizer granularity"
DEFAULT_BLOCK = BlockId("B0007")

# The claim family is not in `COMMAND_MODULES` until the project manager wires it there;
# registering it here keeps the gate running against the real `research` app either way.
if claim_commands not in COMMAND_MODULES:
    claim_commands.register(app)

runner = CliRunner()


def run(*args: str) -> Result:
    """Invoke the real `research` app with ``args``."""
    return runner.invoke(app, list(args))


def payload(result: Result) -> Any:
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


# -- workspace ---------------------------------------------------------------


def _accept(
    ctx: CapabilityContext,
    evidence_id: str,
    *,
    work: WorkId,
    artifact: ArtifactId,
    text: str,
    block: BlockId = DEFAULT_BLOCK,
    page: int = 3,
) -> EvidenceId:
    """Accepted, source-observed, direct Evidence anchored in registered bytes."""
    record = ctx.repo.get_artifact(artifact, work=work)
    candidate = Evidence(
        id=EvidenceId(evidence_id),
        source=SourceAnchor(
            work=work,
            version=record.version,
            artifact=record.id,
            file_hash=record.file_hash,
            block=block,
            text_hash=f"sha256:{hashlib.sha256(text.encode()).hexdigest()}",
            page=page,
            section_path=("Method",),
            char_start=0,
            char_end=len(text),
        ),
        content=EvidenceContent(exact_text=text),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.EXPERIMENTAL_SETUP,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_1,
        verification=VerificationRecord(
            status=EvidenceStatus.VERIFIED,
            verdict=VerificationVerdict.SUPPORTED,
            verifier="human:alice",
        ),
        provenance=Provenance.model("vendor-a/model-x"),
    )
    accept_evidence(ctx, AcceptEvidenceRequest(candidate=candidate))
    return candidate.id


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    """The synthetic paper ingested and parsed, a revision of it, a second Work, five Evidence.

    E0001 and E0002 sit in two versions of W0001, so independence accounting counts them
    once; E0003-E0005 sit in W0002. Two independent supporting works is exactly what makes a
    field-level generalization indefensible.
    """
    root = tmp_path / "project"
    assert run("init", str(root), "--name", "gate-p7").exit_code == 0
    ingested = payload(run("ingest", str(FIXTURE), "-w", str(root), "--json"))
    assert ingested["work"] == "W0001"
    parsed = payload(run("parse", "W0001", "-w", str(root), "--json"))
    assert parsed["blocks"] > 0

    ctx = open_context(root, HUMAN_ACTOR)
    first_artifact = ArtifactId(ingested["artifact"])
    block = next(iter(ctx.repo.iter_blocks(first_artifact, work=WorkId("W0001"))))

    revision = tmp_path / "revision.pdf"
    revision.write_bytes(FIXTURE.read_bytes() + b"\n% camera-ready revision\n")
    add_version_artifact(
        ctx,
        AddArtifactRequest(
            work=WorkId("W0001"),
            artifact_path=revision,
            version_kind=VersionKind.CAMERA_READY,
            version_label="v2",
            mime_type="application/pdf",
            artifact_kind=ArtifactKind.PDF,
        ),
    )
    second_artifact = ctx.repo.list_artifacts(WorkId("W0001"))[-1].id

    other = tmp_path / "other.pdf"
    other.write_bytes(b"%PDF-1.7\n% a second, unrelated paper\n")
    external = ProvenanceSource.EXTERNAL_METADATA
    register_work(
        ctx,
        RegisterWorkRequest(
            candidate=WorkCandidate(
                provenance=Provenance.system(actor="ingest"),
                metadata=CandidateMetadata(
                    title=IdentifierField(
                        value="Flow-level tokenization for traffic models",
                        source=external,
                        confidence=0.9,
                    ),
                    authors=(IdentifierField(value="Z. Other", source=external),),
                    year=IdentifierField(value="2025", source=external),
                ),
                candidate_file_hash=f"sha256:{hashlib.sha256(other.read_bytes()).hexdigest()}",
                original_filename=other.name,
            ),
            artifact_path=other,
            version_kind=VersionKind.PREPRINT,
            version_label="v1",
            mime_type="application/pdf",
            artifact_kind=ArtifactKind.PDF,
        ),
    )
    other_work = WorkId("W0002")
    other_artifact = ctx.repo.list_artifacts(other_work)[0].id

    _accept(
        ctx,
        "E0001",
        work=WorkId("W0001"),
        artifact=first_artifact,
        text=block.text[:120],
        block=block.id,
        page=block.page,
    )
    _accept(
        ctx,
        "E0002",
        work=WorkId("W0001"),
        artifact=second_artifact,
        text="The camera-ready keeps the byte-level tokenizer.",
    )
    _accept(
        ctx,
        "E0003",
        work=other_work,
        artifact=other_artifact,
        text="We tokenize traffic at flow granularity.",
    )
    _accept(
        ctx,
        "E0004",
        work=other_work,
        artifact=other_artifact,
        text="Granularity was chosen for throughput, not for accuracy.",
    )
    _accept(
        ctx,
        "E0005",
        work=other_work,
        artifact=other_artifact,
        text="Two of the surveyed systems share one tokenizer verbatim.",
    )
    yield root


def create_claim(root: Path, *, scope: str = "L3") -> dict[str, Any]:
    """`research claim create`, requested at ``scope`` with three supports and two others."""
    return payload(
        run(
            "claim",
            "create",
            STATEMENT,
            "-w",
            str(root),
            "--type",
            "prevalence",
            "--scope",
            scope,
            "--corpus",
            "structured-traffic-llm",
            "--until",
            "2026-08",
            "--subject",
            "existing_systems",
            "--predicate",
            "use",
            "--object",
            "traffic_tokenization",
            "--qualifier",
            "property=heterogeneous",
            "--supports",
            "E0001",
            "--supports",
            "E0002",
            "--supports",
            "E0003",
            "--qualifies",
            f"E0004:{ASPECT}",
            "--contradicts",
            "E0005",
            "--json",
        )
    )


# -- the gate ----------------------------------------------------------------


def test_creating_a_claim_records_the_ask_and_starts_at_l0(workspace: Path) -> None:
    created = create_claim(workspace)

    assert created["claim"] == "C0001"
    assert created["requested_strength"] == ClaimScope.FIELD_GENERALIZATION.value
    assert created["allowed_strength"] == ClaimScope.INDIVIDUAL.value
    assert created["status"] == "unverified"
    assert len(created["relations"]) == 5
    assert created["mutation"]["event"]["event"] == "claim.created"


def test_gate_p7_the_audit_returns_a_weaker_wording_and_refuses_the_escalation(
    workspace: Path,
) -> None:
    """Gate P7: a weaker maximum defensible wording, the three relation lists, no escalation."""
    create_claim(workspace)
    audited = payload(run("claim", "audit", "C0001", "-w", str(workspace), "--json"))

    assert audited["requested_strength"] == ClaimScope.FIELD_GENERALIZATION.value
    assert audited["allowed_level"] < audited["requested_level"]
    assert audited["allowed_level"] <= ClaimScope.CORPUS_PATTERN.level
    assert audited["escalation_prevented"] is True
    assert audited["status"] == "qualified"

    assert audited["maximum_defensible_wording"]
    assert audited["maximum_defensible_wording"] != "existing work generally"
    assert audited["support"] == ["E0001", "E0002", "E0003"]
    assert audited["qualifiers"] == ["E0004"]
    assert audited["counter_evidence"] == ["E0005"]
    assert audited["coverage_state"]
    assert audited["reasons"], "the audit must say why the requested scope was refused"
    assert audited["mutation"]["event"]["event"] == "claim.qualified"


def test_the_audit_prints_the_same_findings_for_a_human(workspace: Path) -> None:
    create_claim(workspace)
    result = run("claim", "audit", "C0001", "-w", str(workspace))

    assert result.exit_code == 0, result.stdout
    assert "maximum defensible wording:" in result.stdout
    assert "escalation prevented" in result.stdout
    assert "support:" in result.stdout
    assert "qualifiers:" in result.stdout
    assert "counter-evidence:" in result.stdout
    assert "coverage:" in result.stdout


def test_a_durable_audit_reaches_the_same_ceiling_and_leaves_a_resumable_run(
    workspace: Path,
) -> None:
    """`--durable` runs the audit as a checkpointed workflow; the ladder result is the same."""
    create_claim(workspace)
    direct = payload(run("claim", "audit", "C0001", "-w", str(workspace), "--json"))
    durable = payload(run("claim", "audit", "C0001", "-w", str(workspace), "--durable", "--json"))

    assert durable["allowed_strength"] == direct["allowed_strength"]
    assert durable["maximum_defensible_wording"] == direct["maximum_defensible_wording"]
    assert durable["support"] == direct["support"]
    runs = sorted((workspace / ".research" / "runs").iterdir())
    assert runs, "a durable audit leaves a run to resume"


def test_the_audit_goes_looking_for_counter_evidence_once_there_is_an_index(
    workspace: Path,
) -> None:
    """With a projection to search, the audit reports where a counter-example might be.

    The hits are proposals with no anchor and no authority: naming a place to look is the
    whole of what retrieval may do here (ADR-003, ADR-006).
    """
    create_claim(workspace)
    assert run("rebuild", "-w", str(workspace)).exit_code == 0

    audited = payload(run("claim", "audit", "C0001", "-w", str(workspace), "--json"))

    assert audited["counter_candidates"], "an indexed workspace must be searched"
    assert all(item["ref"] and item["source"] for item in audited["counter_candidates"])
    assert audited["allowed_level"] < audited["requested_level"]


def test_a_scripted_provider_may_narrow_the_ceiling_but_never_widen_it(
    workspace: Path, tmp_path: Path
) -> None:
    """`--script` runs the Skeptic and the Auditor offline; both may only lower the result."""
    create_claim(workspace)
    deterministic = payload(run("claim", "audit", "C0001", "-w", str(workspace), "--json"))

    script = tmp_path / "roles.json"
    script.write_text(
        json.dumps(
            {
                "skeptic": [
                    {
                        "counter_candidates": [],
                        "qualifiers": [{"text": "flow-level inputs only", "evidence_refs": []}],
                        "incomparability_notes": [],
                        "rationale": "Looked for a lower score under the same metric.",
                    }
                ],
                "claim_auditor": [
                    {
                        "support": ["E0001", "E0002", "E0003"],
                        "counter_evidence": ["E0005"],
                        "qualifiers": [],
                        "independence_warnings": [],
                        "coverage_state": "no coverage record",
                        "recommended_scope": ClaimScope.UNIVERSAL_OR_ABSENCE.value,
                        "maximum_defensible_wording": "existing work without exception",
                        "rationale": "Trying to widen the claim, which the audit must refuse.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    audited = payload(
        run("claim", "audit", "C0001", "-w", str(workspace), "--script", str(script), "--json")
    )

    assert audited["allowed_level"] <= deterministic["allowed_level"]
    assert audited["maximum_defensible_wording"] != "existing work without exception"
    assert audited["qualifier_notes"], "the Skeptic's qualifier must be reported"
    assert audited["escalation_prevented"] is True


def test_the_audit_never_raises_the_claim_above_what_was_asked_for(workspace: Path) -> None:
    """Product 42.G from the other side: a modest ask is not inflated by good evidence."""
    create_claim(workspace, scope="L0")
    audited = payload(run("claim", "audit", "C0001", "-w", str(workspace), "--json"))

    assert audited["requested_strength"] == ClaimScope.INDIVIDUAL.value
    assert audited["allowed_strength"] == ClaimScope.INDIVIDUAL.value
    assert audited["escalation_prevented"] is False


def test_the_researcher_can_override_the_auditor_and_the_decision_is_visible(
    workspace: Path,
) -> None:
    """Product 38: the override lands as an accepted Decision `claim show` displays."""
    create_claim(workspace)
    audited = payload(run("claim", "audit", "C0001", "-w", str(workspace), "--json"))

    overridden = payload(
        run(
            "claim",
            "override",
            "C0001",
            "-w",
            str(workspace),
            "--scope",
            "L3",
            "--rationale",
            "The unexamined works are out of scope; the corpus is complete enough.",
            "--json",
        )
    )

    assert overridden["decision"] == "D0001"
    assert overridden["allowed_strength"] == ClaimScope.FIELD_GENERALIZATION.value
    assert audited["allowed_strength"] in str(overridden["auditor_recommendation"])
    assert overridden["mutation"]["event"]["event"] == "claim.overridden"

    shown = run("claim", "show", "C0001", "-w", str(workspace))
    assert shown.exit_code == 0, shown.stdout
    assert "D0001 epistemic_override (accepted)" in shown.stdout
    assert "The unexamined works are out of scope" in shown.stdout

    detail = payload(run("claim", "show", "C0001", "-w", str(workspace), "--json"))
    assert [item["id"] for item in detail["decisions"]] == ["D0001"]
    assert detail["allowed_strength"] == ClaimScope.FIELD_GENERALIZATION.value


def test_an_override_without_a_rationale_is_refused_by_the_cli(workspace: Path) -> None:
    create_claim(workspace)
    run("claim", "audit", "C0001", "-w", str(workspace))

    refused = run("claim", "override", "C0001", "-w", str(workspace), "--scope", "L3")

    assert refused.exit_code == 1
    assert "rationale" in refused.stdout + refused.stderr


# -- the rest of the family --------------------------------------------------


def test_relations_can_be_added_and_removed_through_the_cli(workspace: Path) -> None:
    create_claim(workspace)

    related = payload(
        run(
            "claim",
            "relate",
            "C0001",
            "E0004",
            "supports",
            "-w",
            str(workspace),
            "--aspect",
            "throughput",
            "--json",
        )
    )
    assert len(related["relations"]) == 6
    assert {"evidence": "E0004", "relation": "supports", "aspect": "throughput", "note": None} in (
        related["relations"]
    )

    duplicate = run(
        "claim",
        "relate",
        "C0001",
        "E0004",
        "supports",
        "-w",
        str(workspace),
        "--aspect",
        "throughput",
    )
    assert duplicate.exit_code == 1
    assert "already records E0004" in duplicate.stdout + duplicate.stderr

    removed = payload(
        run(
            "claim",
            "unrelate",
            "C0001",
            "E0004",
            "supports",
            "-w",
            str(workspace),
            "--aspect",
            "throughput",
            "--json",
        )
    )
    assert len(removed["relations"]) == 5


def test_list_and_supersede_close_the_family(workspace: Path) -> None:
    create_claim(workspace)
    run("claim", "audit", "C0001", "-w", str(workspace))

    listed = run("claim", "list", "-w", str(workspace))
    assert listed.exit_code == 0
    assert "C0001" in listed.stdout and "qualified" in listed.stdout

    retired = payload(
        run(
            "claim",
            "supersede",
            "C0001",
            "-w",
            str(workspace),
            "--reason",
            "Replaced by a corpus-level statement.",
            "--json",
        )
    )
    assert retired["status"] == "superseded"
    assert retired["mutation"]["event"]["event"] == "claim.superseded"

    empty = payload(run("claim", "list", "-w", str(workspace), "--status", "supported", "--json"))
    assert empty["claims"] == []


def test_an_unknown_claim_is_one_line_and_exit_code_one(workspace: Path) -> None:
    missing = run("claim", "show", "C0404", "-w", str(workspace))

    assert missing.exit_code == 1
    assert (missing.stdout + missing.stderr).count("error:") == 1


def test_the_claim_family_is_mounted_on_a_bare_typer_app() -> None:
    """`register(app)` is the whole contract `cli/commands/__init__.py` needs."""
    bare = typer.Typer()
    claim_commands.register(bare)

    assert [group.name for group in bare.registered_groups] == ["claim"]

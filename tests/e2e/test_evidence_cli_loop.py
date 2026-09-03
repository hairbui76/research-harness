"""Gate P6 / v0.1: ingest -> parse -> interrogate -> verify -> review, then rebuild.

The whole evidence loop through the real CLI, with a scripted provider so the run is
deterministic, hermetic, and offline. The gate is the last assertion: delete `.research/`,
rebuild, and the accepted Evidence and its anchors come back byte-identical. That is the
property the product rests on — canonical files carry the science, `.research/` carries
nothing that cannot be recomputed.

The scripted extractor answers are derived from the fixture's own parse, so the anchors are
the ones a real extraction would produce, including the `94.32` table cell that Product §12
requires to arrive with its metric, unit, dataset, and table.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from research_harness.cli.app import app
from research_harness.cli.commands import evidence as evidence_commands
from research_harness.domain.ids import WorkId
from research_harness.evidence.staging import CandidateStatus, StagingStore
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.evidence.conftest import (
    DATASET_SENTENCE,
    dataset_candidate,
    extraction_dict,
    method_candidate,
    metric_candidate,
    parse_fixture,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_research_paper.pdf"
WORK = WorkId("W0001")

METHOD_QUOTE = "The encoder is a twelve layer transformer"
FIELDS = ("dataset", "metric_result", "method_summary")
QUOTES = {
    "dataset": DATASET_SENTENCE,
    "metric_result": "94.32",
    "method_summary": METHOD_QUOTE,
}
VERDICTS = {
    "dataset": "supported",
    "metric_result": "supported",
    "method_summary": "partially_supported",
}

runner = CliRunner()

if not any(command.name == "inbox" for command in app.registered_commands):
    # The PM wires `evidence` into `cli/commands/__init__.py`; until then the gate mounts it
    # itself, so this test exercises the same app object either way.
    evidence_commands.register(app)


def run(*args: str) -> Result:
    """Invoke the real `research` app, failing loudly with its own output."""
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, f"`research {' '.join(args)}` failed:\n{result.output}"
    return result


def payload(result: Result) -> Any:
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def parsed() -> Any:
    """The fixture parsed once, so scripted answers quote spans that really exist."""
    return parse_fixture()


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    """A workspace with the synthetic paper ingested and parsed."""
    root = tmp_path / "project"
    run("init", str(root), "--name", "gate-p6")
    run("ingest", str(FIXTURE), "-w", str(root))
    run("parse", "W0001", "-w", str(root))
    yield root


def extractor_script(path: Path, parsed: Any) -> Path:
    """One extraction reply per field, in the schema order the workflow asks in."""
    path.write_text(
        json.dumps(
            {
                "evidence_extractor": [
                    extraction_dict([dataset_candidate(parsed)]),
                    extraction_dict([metric_candidate(parsed)]),
                    extraction_dict([method_candidate(parsed)]),
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def verifier_script(path: Path, root: Path) -> Path:
    """One verification reply per staged candidate, in the order the workflow verifies them."""
    staging = StagingStore(WorkspaceRepository.open(root).layout.research_dir)
    pending = staging.list(work=WORK, status=CandidateStatus.PROPOSED)
    path.write_text(
        json.dumps(
            {
                "evidence_verifier": [
                    {
                        "verdict": VERDICTS[candidate.field],
                        "rationale": "read the span and the blocks around it",
                        "quoted_support": QUOTES[candidate.field],
                        "discrepancies": [],
                    }
                    for candidate in pending
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def interrogate_and_verify(project: Path, tmp_path: Path, parsed: Any) -> dict[str, Any]:
    """Run the two model stages and return the inbox items keyed by field."""
    run(
        "interrogate",
        "W0001",
        "-w",
        str(project),
        "--provider",
        "scripted",
        "--script",
        str(extractor_script(tmp_path / "extract.json", parsed)),
        *[argument for field in FIELDS for argument in ("--field", field)],
    )
    run(
        "verify",
        "W0001",
        "-w",
        str(project),
        "--provider",
        "scripted",
        "--script",
        str(verifier_script(tmp_path / "verify.json", project)),
    )
    items = payload(run("inbox", "-w", str(project), "--json"))["items"]
    return {item["field"]: item for item in items}


# -- the loop ----------------------------------------------------------------


def test_interrogation_stages_candidates_and_changes_no_canonical_state(
    project: Path, tmp_path: Path, parsed: Any
) -> None:
    before = _canonical_files(project)
    result = payload(
        run(
            "interrogate",
            "W0001",
            "-w",
            str(project),
            "--provider",
            "scripted",
            "--script",
            str(extractor_script(tmp_path / "extract.json", parsed)),
            "--field",
            "dataset",
            "--json",
        )
    )

    assert [candidate["field"] for candidate in result["candidates"]] == ["dataset"]
    assert _canonical_files(project) == before, "staging must not touch canonical state"


def test_the_inbox_orders_the_candidates_by_what_needs_attention_first(
    project: Path, tmp_path: Path, parsed: Any
) -> None:
    by_field = interrogate_and_verify(project, tmp_path, parsed)

    assert by_field["metric_result"]["category"] == "high_risk"
    assert by_field["metric_result"]["tier"] == 2
    assert by_field["metric_result"]["numeric"]["parsed"] == 94.32
    assert by_field["metric_result"]["numeric"]["metric"] == "F1"
    assert by_field["method_summary"]["category"] == "ambiguous"
    assert by_field["dataset"]["category"] == "routine"

    listed = run("inbox", "-w", str(project)).stdout
    assert listed.index("high_risk") < listed.index("ambiguous") < listed.index("routine")
    assert "confidence" not in listed.lower()


def test_review_accepts_qualifies_and_rejects_through_the_capability_layer(
    project: Path, tmp_path: Path, parsed: Any
) -> None:
    by_field = interrogate_and_verify(project, tmp_path, parsed)

    accepted = payload(
        run(
            "review",
            by_field["metric_result"]["candidate_id"],
            "-w",
            str(project),
            "--accept",
            "--json",
        )
    )
    qualified = payload(
        run(
            "review",
            by_field["dataset"]["candidate_id"],
            "-w",
            str(project),
            "--qualify",
            "holds for the CICIDS2017 capture only",
            "--json",
        )
    )
    rejected = payload(
        run(
            "review",
            by_field["method_summary"]["candidate_id"],
            "-w",
            str(project),
            "--reject",
            "the span describes the encoder, not the method",
            "--json",
        )
    )

    assert accepted["evidence"] == "E0001"
    assert accepted["mutation"]["event"]["event"] == "evidence.accepted"
    assert qualified["evidence"] == "E0002"
    assert qualified["action"] == "accept_with_qualification"
    assert rejected["mutation"]["event"]["event"] == "evidence.rejected"

    records = _evidence(project)
    assert [record["id"] for record in records] == ["E0001", "E0002"]
    assert {record["content"]["field"] for record in records} == {"metric_result", "dataset"}
    for record in records:
        anchor = record["source"]
        assert anchor["work"] == "W0001" and anchor["artifact"] == "A0001-1"
        assert anchor["block"].startswith("B") and anchor["text_hash"].startswith("sha256:")
        assert record["verification"]["accepted_by"] == "human"

    rejections = _rejections(project)
    assert len(rejections) == 1
    assert rejections[0]["field"] == "method_summary"
    assert rejections[0]["verdict"] == "partially_supported"
    assert rejections[0]["anchor"]["text_hash"].startswith("sha256:")

    assert payload(run("inbox", "-w", str(project), "--json"))["count"] == 0
    summary = payload(run("session", "-w", str(project), "--json"))
    assert summary["accepted"] == 2 and summary["rejected"] == 1 and summary["unreviewed"] == 0


def test_gate_p6_delete_research_rebuild_and_the_evidence_is_identical(
    project: Path, tmp_path: Path, parsed: Any
) -> None:
    """The v0.1 gate: `.research/` is disposable, accepted Evidence and anchors are not."""
    by_field = interrogate_and_verify(project, tmp_path, parsed)
    run("review", by_field["metric_result"]["candidate_id"], "-w", str(project), "--accept")
    run(
        "review",
        by_field["dataset"]["candidate_id"],
        "-w",
        str(project),
        "--qualify",
        "holds for the CICIDS2017 capture only",
    )
    run(
        "review",
        by_field["method_summary"]["candidate_id"],
        "-w",
        str(project),
        "--reject",
        "the span describes the encoder, not the method",
    )

    first = payload(run("rebuild", "-w", str(project), "--json"))
    evidence_before = _evidence(project)
    anchors_before = [record["source"] for record in evidence_before]
    rejections_before = _rejections(project)
    assert first["objects_by_type"]["Evidence"] == 2

    shutil.rmtree(project / ".research")
    assert not (project / ".research").exists()

    second = payload(run("rebuild", "-w", str(project), "--json"))

    assert second["canonical_digest"] == first["canonical_digest"]
    assert second["objects_by_type"] == first["objects_by_type"]
    assert second["invalid_files"] == []
    assert _evidence(project) == evidence_before
    assert [record["source"] for record in _evidence(project)] == anchors_before
    assert _rejections(project) == rejections_before
    assert WorkspaceRepository.open(project).consistency.consistent


# -- partial acceptance (Product 24.3) ---------------------------------------


def test_split_accepts_the_source_fact_and_stages_the_interpretation(
    project: Path, tmp_path: Path, parsed: Any
) -> None:
    """`--split` is the CLI face of `review.split`: one accepted fact, one staged reading."""
    by_field = interrogate_and_verify(project, tmp_path, parsed)

    outcome = payload(
        run(
            "review",
            by_field["dataset"]["candidate_id"],
            "-w",
            str(project),
            "--split",
            "--interpretation",
            "The corpus is therefore representative of enterprise traffic.",
            "--json",
        )
    )

    assert outcome["evidence"] == "E0001"
    assert outcome["interpretation_candidate"] is not None
    assert outcome["rejected"] is None
    assert [record["id"] for record in _evidence(project)] == ["E0001"]

    staging = StagingStore(project / ".research")
    staged = staging.get(outcome["interpretation_candidate"])
    original = staging.get(by_field["dataset"]["candidate_id"])
    assert staged.field == "dataset:interpretation"
    assert int(staged.evidence.review_tier) == 2
    assert staged.evidence.source == original.evidence.source
    assert str(outcome["evidence"]) in (staged.evidence.provenance.note or "")


def test_split_can_refuse_the_interpretation_and_still_accept_the_fact(
    project: Path, tmp_path: Path, parsed: Any
) -> None:
    by_field = interrogate_and_verify(project, tmp_path, parsed)

    outcome = payload(
        run(
            "review",
            by_field["dataset"]["candidate_id"],
            "-w",
            str(project),
            "--split",
            "--reject-interpretation",
            "the sentence names the corpus and claims nothing about representativeness",
            "--json",
        )
    )

    assert outcome["interpretation_candidate"] is None
    assert outcome["rejected"]["event"]["event"] == "evidence.rejected"
    assert [record["id"] for record in _evidence(project)] == ["E0001"]
    rejections = _rejections(project)
    assert [record["field"] for record in rejections] == ["dataset:interpretation"]


def test_split_without_a_destination_for_the_interpretation_is_refused(
    project: Path, tmp_path: Path, parsed: Any
) -> None:
    """Partial acceptance decides both halves or neither; the CLI says which is missing."""
    by_field = interrogate_and_verify(project, tmp_path, parsed)

    refused = runner.invoke(
        app, ["review", by_field["dataset"]["candidate_id"], "-w", str(project), "--split"]
    )

    assert refused.exit_code == 1
    assert "--interpretation" in refused.output
    assert _evidence(project) == []


# -- traces (Product 19.3, 34) -----------------------------------------------


def test_every_model_call_the_cli_makes_leaves_a_trace(
    project: Path, tmp_path: Path, parsed: Any
) -> None:
    """`research traces list` shows a run that happened, scripted provider included.

    The dogfood session ran entirely on the scripted provider and `.research/traces/` stayed
    empty, because no CLI command attached a sink. Selection attaches one now, so the trace
    is written wherever the request was routed.
    """
    assert payload(run("traces", "list", "-w", str(project), "--json"))["count"] == 0

    interrogate_and_verify(project, tmp_path, parsed)
    listed = payload(run("traces", "list", "-w", str(project), "--json"))

    assert listed["count"] > 0
    kinds = {record["kind"] for record in listed["traces"]}
    assert kinds == {"completion"}

    trace = json.loads(
        next((project / ".research" / "traces").rglob("*.json")).read_text(encoding="utf-8")
    )
    assert trace["provider"] == "scripted"
    assert trace["authority"].startswith("none")
    assert trace["redacted"] is False
    assert trace["payload"]["role"] in {"evidence_extractor", "evidence_verifier"}


def test_redact_traces_hashes_source_text_out_as_the_trace_is_written(
    project: Path, tmp_path: Path, parsed: Any
) -> None:
    """`redact_traces` is honoured at write time, so the plaintext never reaches the disk."""
    run("privacy", "set", "-w", str(project), "--redact-traces")

    interrogate_and_verify(project, tmp_path, parsed)

    traces = sorted((project / ".research" / "traces").rglob("*.json"))
    assert traces
    for path in traces:
        body = json.loads(path.read_text(encoding="utf-8"))
        assert body["redacted"] is True
        assert DATASET_SENTENCE not in path.read_text(encoding="utf-8")


def test_a_second_review_action_and_an_unknown_candidate_fail_loudly(
    project: Path, tmp_path: Path, parsed: Any
) -> None:
    by_field = interrogate_and_verify(project, tmp_path, parsed)
    candidate_id = by_field["dataset"]["candidate_id"]

    both = runner.invoke(
        app, ["review", candidate_id, "-w", str(project), "--accept", "--defer", "later"]
    )
    assert both.exit_code == 1
    assert "exactly one review action" in both.output

    unknown = ["review", "cand_0000000000000000", "-w", str(project), "--accept"]
    missing = runner.invoke(app, unknown)
    assert missing.exit_code == 1

    assert _evidence(project) == []


def test_batch_review_is_refused_under_the_default_strict_policy(
    project: Path, tmp_path: Path, parsed: Any
) -> None:
    interrogate_and_verify(project, tmp_path, parsed)

    refused = runner.invoke(app, ["review", "batch", "-w", str(project)])

    assert refused.exit_code == 1
    assert "strict" in refused.output
    assert _evidence(project) == []


def test_batch_review_under_a_policy_batch_workspace_accepts_only_low_risk_candidates(
    tmp_path: Path, parsed: Any
) -> None:
    """The exception a researcher declares: `--policy policy_batch` in `research init`."""
    root = tmp_path / "batched"
    run("init", str(root), "--name", "policy-batch", "--policy", "policy_batch")
    run("ingest", str(FIXTURE), "-w", str(root))
    run("parse", "W0001", "-w", str(root))
    by_field = interrogate_and_verify(root, tmp_path, parsed)

    dry = payload(run("review", "batch", "-w", str(root), "--dry-run", "--json"))
    assert dry["accepted"] == [by_field["dataset"]["candidate_id"]]
    assert _evidence(root) == []

    result = payload(run("review", "batch", "-w", str(root), "--json"))

    assert result["accepted"] == [by_field["dataset"]["candidate_id"]]
    assert set(result["skipped"]) == {
        by_field["metric_result"]["candidate_id"],
        by_field["method_summary"]["candidate_id"],
    }
    assert [record["content"]["field"] for record in _evidence(root)] == ["dataset"]


def test_a_provider_is_configuration_and_an_unknown_name_is_refused(project: Path) -> None:
    """`--provider` names an entry of `providers:` in research.yaml (Product §20.2)."""
    from research_harness.cli.commands.evidence import load_router

    repo = WorkspaceRepository.open(project)
    assert repo.config.providers == []

    missing = runner.invoke(app, ["interrogate", "W0001", "-w", str(project), "--provider", "fast"])
    assert missing.exit_code == 1
    assert "no model providers configured" in missing.output

    _add_providers(project)
    router = load_router(WorkspaceRepository.open(project), env={})
    assert [entry.model for entry in router.entries] == ["gpt-x", "qwen"]

    unknown = runner.invoke(app, ["interrogate", "W0001", "-w", str(project), "--provider", "nope"])
    assert unknown.exit_code == 1
    assert "no provider named 'nope'" in unknown.output


def test_a_scripted_run_needs_its_script_and_nothing_else(project: Path) -> None:
    both = runner.invoke(
        app, ["interrogate", "W0001", "-w", str(project), "--provider", "scripted"]
    )
    assert both.exit_code == 1
    assert "needs --script" in both.output


def test_conflicts_and_stale_report_an_empty_workspace_without_failing(project: Path) -> None:
    assert "no conflicts" in run("conflicts", "-w", str(project)).stdout
    assert "nothing stale" in run("stale", "-w", str(project)).stdout
    assert payload(run("session", "-w", str(project), "--json"))["added"] == 0


# -- helpers -----------------------------------------------------------------


def _evidence(root: Path) -> list[dict[str, Any]]:
    return _jsonl(root / "corpus" / "works" / "W0001" / "evidence.jsonl")


def _rejections(root: Path) -> list[dict[str, Any]]:
    return _jsonl(root / "corpus" / "works" / "W0001" / "rejections.jsonl")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _add_providers(root: Path) -> None:
    """Give the workspace a `providers:` section, the way a researcher would by hand."""
    import yaml

    path = root / "research.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["providers"] = [
        {"name": "fast", "kind": "openai", "model": "gpt-x", "api_key_env": "OPENAI_API_KEY"},
        {"name": "local", "kind": "local_openai_compatible", "model": "qwen", "priority": 200},
    ]
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _canonical_files(root: Path) -> dict[str, bytes]:
    """Every canonical file and its bytes; `.research/` is excluded by definition."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".research" not in path.relative_to(root).parts
    }

"""The dogfood friction log's CLI half: F8, F11, F12, F17, F19, F20.

Each of these cost the 2026-09-03 session real time or real trust, and each is small
enough that "we know" is not a fix. What is pinned here is the behaviour the report asked
for, in the words a researcher reads:

* **F8** — `research inbox` printed 20 of 39 items under a header saying `39 item(s) to
  review`, so working the list top to bottom looked like clearing the queue.
* **F11** — `research review candidate --help` documented a refusal the command does not
  make, which is worse than documenting nothing: the sentence promised a gate.
* **F12** — reviewing an item took two commands, and the one that changes state showed
  nothing about the span it was about to canonise.
* **F17** — `research egress` said nothing at all about model providers when none were
  configured, leaving a complete-looking table with the largest channel missing.
* **F19** — eight `--field` flags per invocation, and quoting them as one string failed.
* **F20** — ~1 s of import cost per command; the review loop spent 80 of 90 seconds on it.

The staging fixture is hand-built rather than run: what is under test is the presentation,
and a queue with a known shape is what makes "showing 5 of 12" assertable.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

from research_harness.cli.app import SHELL_EXIT, app
from research_harness.cli.commands.privacy import NO_MODEL_PROVIDERS
from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    SourceAnchor,
    VerificationRecord,
)
from research_harness.domain.ids import ArtifactId, BlockId, VersionId, WorkId
from research_harness.evidence.staging import (
    PROVISIONAL_EVIDENCE_ID,
    EvidenceCandidate,
    ExtractionProvenance,
    StagingStore,
)
from research_harness.roles.schemas import VerificationOutput
from research_harness.workspace.repository import WorkspaceRepository

runner = CliRunner()

QUEUE_SIZE = 12
DISCREPANCY = "the span names a different dataset from the one asserted"


def digest(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"


def candidate(index: int, *, field: str = "dataset") -> EvidenceCandidate:
    """One staged answer, anchored in its own block so nothing collides."""
    text = f"All experiments use CICIDS{2000 + index}"
    anchor = SourceAnchor(
        work=WorkId("W0001"),
        version=VersionId("V0001-1"),
        artifact=ArtifactId("A0001-1"),
        file_hash=digest("artifact"),
        block=BlockId(f"B{index:04d}"),
        text_hash=digest(text),
        page=3,
        section_path=("4 Evaluation",),
        char_start=0,
        char_end=len(text),
    )
    evidence = Evidence(
        id=PROVISIONAL_EVIDENCE_ID,
        source=anchor,
        content=EvidenceContent(exact_text=text, field=field),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.DATASET_DESCRIPTION,
        strength=EvidenceStrength.DIRECT,
        verification=VerificationRecord(
            status=EvidenceStatus.VERIFIED,
            verdict=VerificationVerdict.PARTIALLY_SUPPORTED,
            extractor="vendor-a/model-x",
            verifier="vendor-b/model-y",
        ),
        review_tier=ReviewTier.TIER_1,
        provenance=Provenance.model("vendor-a/model-x"),
    )
    return EvidenceCandidate(
        candidate_id=f"cand_{index:016x}",
        work=WorkId("W0001"),
        artifact=ArtifactId("A0001-1"),
        field=field,
        evidence=evidence,
        extraction=ExtractionProvenance(
            run_id="run_1",
            provider="vendor-a",
            model="model-x",
            template_version="1.0.0",
            request_fingerprint=digest("request"),
            response_schema_fingerprint=digest("schema"),
        ),
        verification=VerificationOutput(
            verdict=VerificationVerdict.PARTIALLY_SUPPORTED,
            rationale="the sentence supports part of the assertion",
            quoted_support=evidence.content.exact_text,
            discrepancies=[DISCREPANCY],
        ),
        verifier="vendor-b/model-y",
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A workspace holding a queue of `QUEUE_SIZE` unreviewed candidates."""
    root = (tmp_path / "project").resolve()
    WorkspaceRepository.init(root, "ergonomics")
    staging = StagingStore(WorkspaceRepository.open(root).layout.research_dir)
    staging.put_all([candidate(index) for index in range(1, QUEUE_SIZE + 1)])
    return root


def run(*args: str, expect: int = 0) -> Result:
    result = runner.invoke(app, list(args))
    assert result.exit_code == expect, f"`research {' '.join(args)}`:\n{result.output}"
    return result


def payload(result: Result) -> Any:
    return json.loads(result.stdout)


# -- F8: the inbox says how many of how many ---------------------------------


def test_the_inbox_header_says_how_many_of_how_many_are_on_screen(project: Path) -> None:
    output = run("inbox", "-w", str(project), "--limit", "5").stdout

    assert f"showing 5 of {QUEUE_SIZE} item(s) — use --limit 0 for all" in output
    assert "--limit 0 shows the whole queue" in output


def test_the_inbox_header_says_nothing_extra_when_the_whole_queue_fits(project: Path) -> None:
    output = run("inbox", "-w", str(project), "--limit", "50").stdout

    assert f"{QUEUE_SIZE} item(s) to review" in output
    assert "showing" not in output


def test_limit_zero_prints_the_whole_queue(project: Path) -> None:
    body = payload(run("inbox", "-w", str(project), "--limit", "0", "--json"))

    assert body["count"] == QUEUE_SIZE
    assert body["shown"] == QUEUE_SIZE
    assert len(body["items"]) == QUEUE_SIZE


def test_the_json_payload_says_how_many_it_actually_carries(project: Path) -> None:
    """`count: 39` beside 20 items is what made the queue look cleared (dogfood F8)."""
    body = payload(run("inbox", "-w", str(project), "--limit", "4", "--json"))

    assert body["count"] == QUEUE_SIZE
    assert body["shown"] == 4
    assert body["limit"] == 4
    assert len(body["items"]) == body["shown"]


# -- F11: the help text describes the command that exists --------------------


def test_review_candidate_help_no_longer_promises_a_gate_it_does_not_have(
    project: Path,
) -> None:
    # Typer renders help through rich. On a narrow terminal the sentence wraps across the
    # box-drawn lines and colour escapes can split a phrase, so the assertion is on the
    # prose: a wide terminal for this one call, and escapes stripped before collapsing.
    result = runner.invoke(app, ["review", "candidate", "--help"], env={"TERMINAL_WIDTH": "200"})
    assert result.exit_code == 0, result.output
    output = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    collapsed = " ".join(output.split())

    assert "accepts any tier" in collapsed
    assert "research review batch" in collapsed
    assert "not the researcher" in collapsed
    assert "Tier-2 candidate under every policy" not in collapsed


def test_review_batch_is_where_the_conditions_actually_are() -> None:
    collapsed = " ".join(run("review", "batch", "--help").stdout.split())

    assert "policy_batch" in collapsed
    assert "Refused outright" in collapsed


# -- F12: one command shows the item and its source --------------------------


def test_review_candidate_without_an_action_prints_the_item(project: Path) -> None:
    output = run("review", "candidate", "cand_0000000000000001", "-w", str(project)).stdout

    assert "cand_0000000000000001" in output
    assert "partially_supported" in output
    assert DISCREPANCY in output
    assert "All experiments use CICIDS2001" in output
    assert "page 3" in output
    assert "4 Evaluation" in output


def test_showing_an_item_changes_nothing(project: Path) -> None:
    before = payload(run("inbox", "-w", str(project), "--limit", "0", "--json"))

    run("review", "candidate", "cand_0000000000000001", "-w", str(project))

    assert payload(run("inbox", "-w", str(project), "--limit", "0", "--json")) == before


def test_review_next_walks_the_queue_in_product_24_2_order(project: Path) -> None:
    body = payload(run("review", "next", "-w", str(project), "--json"))
    top = payload(run("inbox", "-w", str(project), "--limit", "1", "--json"))["items"][0]

    assert body["remaining"] == QUEUE_SIZE
    assert body["item"]["candidate_id"] == top["candidate_id"]
    assert body["item"]["source_context"]["page"] == 3


def test_review_next_says_so_when_the_queue_is_empty(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    WorkspaceRepository.init(root, "empty")

    output = run("review", "next", "-w", str(root)).stdout

    assert "nothing left to review" in output


def test_review_next_is_a_reviewable_item_not_a_reviewed_one(project: Path) -> None:
    run(
        "review", "candidate", "cand_0000000000000001", "--reject", "wrong span", "-w", str(project)
    )

    body = payload(run("review", "next", "-w", str(project), "--json"))

    assert body["remaining"] == QUEUE_SIZE - 1
    assert body["item"]["candidate_id"] != "cand_0000000000000001"


def test_asking_to_show_a_candidate_that_is_not_reviewable_says_why(project: Path) -> None:
    run(
        "review", "candidate", "cand_0000000000000002", "--reject", "wrong span", "-w", str(project)
    )

    result = run("review", "candidate", "cand_0000000000000002", "-w", str(project), expect=1)

    assert "not in the review queue" in result.output
    assert "it is reviewed" in result.output


# -- F19: naming a set of fields ---------------------------------------------


def test_a_comma_separated_field_list_is_accepted(project: Path) -> None:
    """`--field "dataset baseline"` failed with `No such option:` and the whole flag list."""
    result = run(
        "interrogate", "W0001", "-w", str(project), "--field", "dataset,baseline", expect=1
    )

    assert "No such option" not in result.output
    assert "no model providers configured" in result.output, (
        "the field list was accepted; the command then failed for want of a backend"
    )


def test_an_unknown_field_is_refused_by_name(project: Path) -> None:
    result = run(
        "interrogate",
        "W0001",
        "-w",
        str(project),
        "--field",
        "dataset,not_a_field",
        expect=1,
    )

    assert "not_a_field" in result.output
    assert "generic-empirical" in result.output


def test_field_and_except_field_are_not_given_together(project: Path) -> None:
    result = run(
        "interrogate",
        "W0001",
        "-w",
        str(project),
        "--field",
        "dataset",
        "--except-field",
        "baseline",
        expect=1,
    )

    assert "not both" in result.output


def test_excluding_every_field_is_refused_rather_than_asking_nothing(project: Path) -> None:
    from research_harness.evidence.interrogation import DEFAULT_SCHEMA

    result = run(
        "interrogate",
        "W0001",
        "-w",
        str(project),
        "--except-field",
        ",".join(DEFAULT_SCHEMA.names),
        expect=1,
    )

    assert "excludes every field" in result.output


def test_the_field_selection_is_the_one_the_schema_declares() -> None:
    """The unit behind the flags, so the list is asserted rather than the error text."""
    from research_harness.cli.commands.evidence import _selected_fields
    from research_harness.evidence.interrogation import DEFAULT_SCHEMA

    assert _selected_fields(DEFAULT_SCHEMA, None, None) is None
    assert _selected_fields(DEFAULT_SCHEMA, ["dataset,baseline"], None) == ["dataset", "baseline"]
    assert _selected_fields(DEFAULT_SCHEMA, ["dataset", "dataset"], None) == ["dataset"]
    assert _selected_fields(DEFAULT_SCHEMA, None, ["dataset"]) == [
        name for name in DEFAULT_SCHEMA.names if name != "dataset"
    ]


# -- F17: the model row is always printed ------------------------------------


def test_egress_names_the_missing_model_providers(project: Path) -> None:
    output = run("egress", "-w", str(project)).stdout

    assert NO_MODEL_PROVIDERS in output
    assert "model stages will refuse" in output
    assert "--provider scripted" in output


def test_egress_json_says_whether_a_model_provider_is_configured(project: Path) -> None:
    assert payload(run("egress", "-w", str(project), "--json"))["model_providers_configured"] is (
        False
    )


def test_a_configured_model_provider_replaces_the_placeholder_row(project: Path) -> None:
    path = project / "research.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["providers"] = [{"name": "house", "kind": "openai", "model": "gpt-x"}]
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    output = run("egress", "-w", str(project)).stdout

    assert NO_MODEL_PROVIDERS not in output
    assert "house/gpt-x" in output
    assert payload(run("egress", "-w", str(project), "--json"))["model_providers_configured"]


def test_the_denied_filter_does_not_claim_the_models_are_unconfigured(project: Path) -> None:
    """`--denied` narrows the table; it must not turn an allowed model into a missing one."""
    path = project / "research.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["providers"] = [{"name": "house", "kind": "openai", "model": "gpt-x"}]
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    output = run("egress", "-w", str(project), "--denied").stdout

    assert NO_MODEL_PROVIDERS not in output


# -- F20: one process, many commands -----------------------------------------


def test_the_shell_runs_several_commands_in_one_process(project: Path) -> None:
    result = runner.invoke(
        app,
        ["shell", "-w", str(project)],
        input="inbox --limit 1\nsession\nexit\n",
    )

    assert result.exit_code == 0, result.output
    assert "research shell" in result.output
    assert f"showing 1 of {QUEUE_SIZE}" in result.output
    assert "session summary" in result.output


def test_a_failing_command_does_not_end_the_session(project: Path) -> None:
    result = runner.invoke(
        app,
        ["shell", "-w", str(project)],
        input="review candidate cand_ffffffffffffffff\nsession\nexit\n",
    )

    assert result.exit_code == 0, result.output
    assert "session summary" in result.output, "the shell survived the refusal"


def test_an_unknown_command_is_reported_and_the_session_continues(project: Path) -> None:
    result = runner.invoke(app, ["shell", "-w", str(project)], input="nope\nsession\nexit\n")

    assert result.exit_code == 0, result.output
    assert "No such command" in result.output
    assert "session summary" in result.output


def test_the_shell_ends_at_end_of_input_without_an_exit_word(project: Path) -> None:
    result = runner.invoke(app, ["shell", "-w", str(project)], input="session\n")

    assert result.exit_code == 0, result.output
    assert "session summary" in result.output


def test_blank_lines_and_comments_are_skipped(project: Path) -> None:
    result = runner.invoke(app, ["shell", "-w", str(project)], input="\n# a note\nsession\nexit\n")

    assert result.exit_code == 0, result.output
    assert result.output.count("session summary") == 1


def test_a_shell_does_not_start_a_shell(project: Path) -> None:
    result = runner.invoke(app, ["shell", "-w", str(project)], input="shell\nexit\n")

    assert "already in a shell" in result.output
    assert result.exit_code == 1, "a refused line is a failed line, and the session says so"


def test_the_session_exits_with_the_status_of_the_last_command(project: Path) -> None:
    """Like a shell, so `printf ... | research shell` still fails loudly in a script."""
    failed = runner.invoke(
        app, ["shell", "-w", str(project)], input="review next --category nope\n"
    )
    passed = runner.invoke(app, ["shell", "-w", str(project)], input="session\n")

    assert failed.exit_code == 1, failed.output
    assert passed.exit_code == 0, passed.output


@pytest.mark.parametrize("word", sorted(SHELL_EXIT))
def test_either_exit_word_leaves(project: Path, word: str) -> None:
    result = runner.invoke(app, ["shell", "-w", str(project)], input=f"{word}\nsession\n")

    assert result.exit_code == 0, result.output
    assert "session summary" not in result.output, "nothing after the exit word runs"


def test_the_session_workspace_saves_repeating_the_option(project: Path) -> None:
    """`-w` once, not on every line: the loop is the thing F20 is about."""
    import os

    from research_harness.cli.context import WORKSPACE_ENV

    before = os.environ.get(WORKSPACE_ENV)
    result = runner.invoke(app, ["shell", "-w", str(project)], input="inbox --limit 1\nexit\n")

    assert result.exit_code == 0, result.output
    assert f"showing 1 of {QUEUE_SIZE}" in result.output
    assert os.environ.get(WORKSPACE_ENV) == before, "the session's workspace is put back"

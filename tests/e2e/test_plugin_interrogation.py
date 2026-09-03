"""ROADMAP 15.1 through the CLI: a domain plugin's questions, asked by name.

`research interrogate --schema plugin:structured-traffic` is the whole gesture. What it has
to prove is that the plugin's *own* fields reach staging - the core schema alone has no
`traffic.*` field, so a candidate carrying one can only have come from
`plugins/structured-traffic` being loaded, checked, and merged beside the core schema.

Offline throughout: the provider is scripted and the answers quote spans that really exist
in the synthetic paper, so the anchors are the ones a real extraction would produce.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import open_context
from research_harness.cli.app import app
from research_harness.cli.commands import evidence as evidence_commands
from research_harness.cli.plugins import plugin_interrogation_schema
from research_harness.domain.enums import EvidenceType
from research_harness.domain.ids import WorkId
from research_harness.evidence.interrogation import DEFAULT_SCHEMA
from research_harness.evidence.staging import StagingStore
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.evidence.conftest import (
    DATASET_BLOCK,
    DATASET_SENTENCE,
    METHOD_BLOCK,
    candidate_dict,
    extraction_dict,
    parse_fixture,
    span_of,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_research_paper.pdf"
WORK = WorkId("W0001")
SCHEMA_REFERENCE = "plugin:structured-traffic"
PLUGIN_FIELDS = ("traffic.dataset", "traffic.traffic_unit")
METHOD_QUOTE = "The encoder is a twelve layer transformer"

runner = CliRunner()

if not any(command.name == "interrogate" for command in app.registered_commands):
    evidence_commands.register(app)


def run(*args: str) -> Result:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, f"`research {' '.join(args)}` failed:\n{result.output}"
    return result


@pytest.fixture(scope="module")
def parsed() -> Any:
    """The fixture parsed once, so scripted answers quote spans that really exist."""
    return parse_fixture()


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    """A workspace with the synthetic paper ingested and parsed."""
    root = tmp_path / "project"
    run("init", str(root), "--name", "plugin-interrogation")
    run("ingest", str(FIXTURE), "-w", str(root))
    run("parse", "W0001", "-w", str(root))
    yield root


def plugin_script(path: Path, parsed: Any) -> Path:
    """One extraction reply per plugin field, in schema order.

    The workflow asks the fields in the order the schema declares them, not the order the
    `--field` options were typed, and a reply that answers a different field than the one
    asked is rejected — so `traffic.traffic_unit` comes first, as it does in the plugin's
    `interrogation/paper.yaml`.
    """
    unit_start, unit_end = span_of(parsed, METHOD_BLOCK, METHOD_QUOTE)
    dataset_start, dataset_end = span_of(parsed, DATASET_BLOCK, DATASET_SENTENCE)
    path.write_text(
        json.dumps(
            {
                "evidence_extractor": [
                    extraction_dict(
                        [
                            candidate_dict(
                                block=METHOD_BLOCK,
                                char_start=unit_start,
                                char_end=unit_end,
                                exact_text=METHOD_QUOTE,
                                field="traffic.traffic_unit",
                                evidence_type=EvidenceType.METHOD_DESCRIPTION,
                            )
                        ]
                    ),
                    extraction_dict(
                        [
                            candidate_dict(
                                block=DATASET_BLOCK,
                                char_start=dataset_start,
                                char_end=dataset_end,
                                exact_text=DATASET_SENTENCE,
                                field="traffic.dataset",
                                evidence_type=EvidenceType.DATASET_DESCRIPTION,
                            )
                        ]
                    ),
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


# -- resolution --------------------------------------------------------------


def test_the_plugin_reference_resolves_to_the_merged_schema(project: Path) -> None:
    """`merge_interrogation` adds fields beside the core ones; it removes none."""
    schema = plugin_interrogation_schema(open_context(project), SCHEMA_REFERENCE)

    names = [field.name for field in schema.fields]
    assert schema.name == "structured-traffic:paper"
    assert names[: len(DEFAULT_SCHEMA.fields)] == [f.name for f in DEFAULT_SCHEMA.fields]
    assert set(PLUGIN_FIELDS) <= set(names)
    assert not any(name.startswith("traffic.") for name in (f.name for f in DEFAULT_SCHEMA.fields))


def test_naming_the_schema_explicitly_reaches_the_same_object(project: Path) -> None:
    ctx = open_context(project)
    assert plugin_interrogation_schema(ctx, f"{SCHEMA_REFERENCE}:paper") == (
        plugin_interrogation_schema(ctx, SCHEMA_REFERENCE)
    )


def test_loading_the_plugin_leaves_the_core_schema_untouched(project: Path) -> None:
    """The boundary Phase 14 exists to protect: `DEFAULT_SCHEMA` keeps its fingerprint."""
    before = DEFAULT_SCHEMA.fingerprint()
    plugin_interrogation_schema(open_context(project), SCHEMA_REFERENCE)
    assert DEFAULT_SCHEMA.fingerprint() == before


def test_an_unknown_plugin_says_where_it_looked(project: Path) -> None:
    from research_harness.domain.errors import ResearchHarnessError

    with pytest.raises(ResearchHarnessError, match="no plugin named 'not-a-plugin'"):
        plugin_interrogation_schema(open_context(project), "plugin:not-a-plugin")


def test_an_unknown_schema_inside_a_real_plugin_lists_what_there_is(project: Path) -> None:
    from research_harness.domain.errors import ResearchHarnessError

    with pytest.raises(ResearchHarnessError, match="structured-traffic:paper"):
        plugin_interrogation_schema(open_context(project), f"{SCHEMA_REFERENCE}:nonesuch")


# -- the CLI run -------------------------------------------------------------


def test_interrogating_with_a_plugin_schema_stages_the_plugins_own_fields(
    project: Path, tmp_path: Path, parsed: Any
) -> None:
    result = run(
        "interrogate",
        "W0001",
        "-w",
        str(project),
        "--schema",
        SCHEMA_REFERENCE,
        "--field",
        PLUGIN_FIELDS[0],
        "--field",
        PLUGIN_FIELDS[1],
        "--provider",
        "scripted",
        "--script",
        str(plugin_script(tmp_path / "traffic.json", parsed)),
        "--json",
    )
    payload = json.loads(result.stdout)
    assert sorted(payload["by_field"]) == sorted(PLUGIN_FIELDS)
    assert sorted(item["field"] for item in payload["candidates"]) == sorted(PLUGIN_FIELDS)

    staging = StagingStore(WorkspaceRepository.open(project).layout.research_dir)
    staged = staging.list(work=WORK)
    assert sorted(candidate.field for candidate in staged) == sorted(PLUGIN_FIELDS)
    assert all(candidate.field.startswith("traffic.") for candidate in staged)


def test_the_plugin_run_accepts_nothing(project: Path, tmp_path: Path, parsed: Any) -> None:
    """A plugin proposes; the researcher accepts. Interrogation writes no canonical evidence."""
    run(
        "interrogate",
        "W0001",
        "-w",
        str(project),
        "--schema",
        SCHEMA_REFERENCE,
        "--field",
        PLUGIN_FIELDS[0],
        "--field",
        PLUGIN_FIELDS[1],
        "--provider",
        "scripted",
        "--script",
        str(plugin_script(tmp_path / "traffic.json", parsed)),
        "--json",
    )
    repo = WorkspaceRepository.open(project)
    assert list(repo.iter_evidence(WORK)) == []

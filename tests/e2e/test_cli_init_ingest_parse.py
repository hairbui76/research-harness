"""`research init` -> `research ingest` -> `research parse` -> `research work show`.

The CLI is a transport: it must produce exactly the state the capability handlers produce,
report a harness failure as one line and exit code 1, and speak JSON on request.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from typer.testing import CliRunner, Result

from research_harness.cli.app import app
from research_harness.cli.context import WORKSPACE_ENV
from research_harness.workspace.repository import WorkspaceRepository
from tests.fixtures.make_synthetic_paper import CIPHER_SHIFT, caesar

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_research_paper.pdf"
#: A publication-quality PDF whose title font is displaced: the shape of dogfood F6.
QUIRKS = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_publisher_quirks.pdf"

runner = CliRunner()


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "project"
    assert run("init", str(root), "--name", "cli-gate").exit_code == 0
    yield root


def run(*args: str) -> Result:
    """Invoke the real `research` app with ``args``."""
    return runner.invoke(app, list(args))


def payload(result: Result) -> Any:
    return json.loads(result.stdout)


def test_init_creates_a_workspace_the_repository_can_open(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    result = run("init", str(root), "--name", "fresh project")

    assert result.exit_code == 0
    assert "initialized fresh project" in result.stdout
    assert WorkspaceRepository.open(root).config.name == "fresh project"


def test_init_ingest_parse_and_show_complete_the_loop(workspace: Path) -> None:
    ingested = run("ingest", str(FIXTURE), "-w", str(workspace))
    assert ingested.exit_code == 0, ingested.stdout
    assert "registered a new work" in ingested.stdout
    assert "W0001" in ingested.stdout

    parsed = run("parse", "W0001", "-w", str(workspace))
    assert parsed.exit_code == 0, parsed.stdout
    assert "parsed" in parsed.stdout and "blocks" in parsed.stdout

    shown = run("work", "show", "W0001", "-w", str(workspace))
    assert shown.exit_code == 0
    assert "Deep Representations for Encrypted Network Traffic" in shown.stdout
    blocks = _field(shown.stdout, "blocks")
    pages = _field(shown.stdout, "pages")
    assert int(blocks) > 0 and int(pages) > 0

    listed = run("work", "list", "-w", str(workspace))
    assert listed.exit_code == 0
    assert "W0001" in listed.stdout


def test_parse_and_work_show_report_what_the_parser_could_not_read(workspace: Path) -> None:
    """Dogfood F6: the diagnostics were recorded on every parse and shown by nothing.

    A researcher who is told `parsed 304 blocks across 11 pages` and nothing else will
    quote a Caesar-shifted span in good faith; `research parse` and `research work show`
    now print the same summary the provenance note has always carried.
    """
    assert run("ingest", str(QUIRKS), "-w", str(workspace)).exit_code == 0

    parsed = run("parse", "W0001", "-w", str(workspace), "--json")
    assert parsed.exit_code == 0, parsed.stdout
    diagnostics = payload(parsed)
    assert int(diagnostics["diagnostics"]["undecodable"]) > 0
    assert "undecodable" in diagnostics["diagnostics_summary"]
    assert "font shift" in diagnostics["diagnostics_summary"]

    printed = run("parse", "W0001", "-w", str(workspace))
    assert "text quality" in printed.stdout
    assert "undecodable" in printed.stdout

    shown = run("work", "show", "W0001", "-w", str(workspace))
    assert shown.exit_code == 0, shown.stdout
    assert "text quality" in shown.stdout, "a stored parse still reports its diagnostics"
    assert "undecodable" in shown.stdout


def test_ingest_says_when_a_field_was_dropped_because_the_font_did_not_decode(
    workspace: Path, tmp_path: Path
) -> None:
    """Dogfood F5/F6: an empty field is one discovery can fill, and must say why it is empty."""
    source = _shifted_title_pdf(tmp_path)

    ingested = run("ingest", str(source), "-w", str(workspace), "--json")
    assert ingested.exit_code == 0, ingested.stdout
    assert payload(ingested)["undecodable_fields"] == ["title"]

    printed = run("ingest", str(source), "-w", str(workspace))
    assert "text quality" in printed.stdout and "title unreadable" in printed.stdout
    assert "research discover" in printed.stdout


def _shifted_title_pdf(tmp_path: Path) -> Path:
    """A one-page paper whose title is drawn in a font displaced by `CIPHER_SHIFT`."""
    document = pymupdf.open()
    page = document.new_page()
    lines = (
        (caesar("Robust Encrypted Traffic Fingerprinting", CIPHER_SHIFT), 20.0),
        ("Abstract", 11.0),
        ("We study encrypted traffic fingerprinting under drift.", 9.0),
    )
    top = 90.0
    for text, size in lines:
        page.insert_text((72, top), text, fontsize=size)
        top += size * 1.8
    path = tmp_path / "broken-cmap.pdf"
    document.save(path)
    document.close()
    return path


def test_every_command_can_speak_json(workspace: Path) -> None:
    ingested = payload(run("ingest", str(FIXTURE), "-w", str(workspace), "--json"))
    assert ingested["created"] == "work"
    assert ingested["work"] == "W0001"
    assert ingested["mutation"]["event"]["event"] == "work.ingested"
    assert ingested["mutation"]["validation"]["ok"] is True
    assert ingested["mutation"]["diff"]["change"] == "created"

    parsed = payload(run("parse", "W0001", "-w", str(workspace), "--json"))
    assert parsed["blocks"] > 0 and parsed["pages"] > 0
    assert parsed["mutation"]["event"]["event"] == "work.parsed"

    shown = payload(run("work", "show", "W0001", "-w", str(workspace), "--json"))
    assert shown["blocks"] == parsed["blocks"]
    assert shown["pages"] == parsed["pages"]
    assert shown["artifacts"][0]["id"] == ingested["artifact"]

    listed = payload(run("work", "list", "-w", str(workspace), "--json"))
    assert [work["id"] for work in listed["works"]] == ["W0001"]


def test_re_ingesting_through_the_cli_writes_nothing(workspace: Path) -> None:
    run("ingest", str(FIXTURE), "-w", str(workspace))
    again = payload(run("ingest", str(FIXTURE), "-w", str(workspace), "--json"))

    assert again["created"] == "nothing"
    assert again["mutation"] is None
    assert again["resolution"] == "same_artifact"


def test_the_workspace_is_found_from_the_environment_and_the_working_directory(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    assert run("ingest", str(FIXTURE), "--json").exit_code == 0

    monkeypatch.delenv(WORKSPACE_ENV)
    monkeypatch.chdir(workspace / "corpus" / "works")
    listed = payload(run("work", "list", "--json"))
    assert [work["id"] for work in listed["works"]] == ["W0001"]


def test_a_harness_error_is_one_line_and_exit_code_one(workspace: Path, tmp_path: Path) -> None:
    missing = run("parse", "W0404", "-w", str(workspace))
    assert missing.exit_code == 1
    assert missing.stdout.count("error:") + missing.stderr.count("error:") == 1

    nowhere = run("work", "list", "-w", str(tmp_path / "not-a-workspace"))
    assert nowhere.exit_code == 1

    run("ingest", str(FIXTURE), "-w", str(workspace))
    ambiguous = run(
        "ingest", str(FIXTURE), "-w", str(workspace), "--as-new", "--attach-to", "W0001"
    )
    assert ambiguous.exit_code == 1


def test_as_new_and_attach_to_decide_an_identity_the_resolver_will_not(
    workspace: Path, tmp_path: Path
) -> None:
    revision = tmp_path / "revision.pdf"
    revision.write_bytes(FIXTURE.read_bytes() + b"\n%revision\n")
    run("ingest", str(FIXTURE), "-w", str(workspace))

    as_new = payload(run("ingest", str(revision), "-w", str(workspace), "--as-new", "--json"))
    assert as_new["created"] == "work" and as_new["work"] == "W0002"

    attached = payload(
        run("ingest", str(FIXTURE), "-w", str(workspace), "--attach-to", "W0002", "--json")
    )
    assert attached["created"] == "version" and attached["work"] == "W0002"


def _field(text: str, name: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(name):
            return stripped.removeprefix(name).strip()
    raise AssertionError(f"{name!r} is not in the output:\n{text}")

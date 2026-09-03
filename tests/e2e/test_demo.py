"""`research demo` builds a reviewable workspace offline (first-run experience)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from research_harness.cli.app import app
from research_harness.demo import DEMO_PDF, run_demo
from research_harness.evidence.staging import CandidateStatus, StagingStore
from research_harness.workspace.repository import WorkspaceRepository

runner = CliRunner()


def test_the_bundled_paper_ships_with_the_package() -> None:
    assert DEMO_PDF.is_file()
    assert DEMO_PDF.read_bytes()[:5] == b"%PDF-"


def test_run_demo_stages_and_verifies_three_proposals_without_accepting(tmp_path: Path) -> None:
    report = run_demo(tmp_path / "demo")

    assert report.staged == 3
    assert report.verified == {
        "dataset": "supported",
        "metric_result": "supported",
        "method_summary": "partially_supported",
    }
    repo = WorkspaceRepository.open(report.root)
    assert list(repo.iter_evidence(report.work)) == [], "nothing is accepted by the demo"
    staging = StagingStore(repo.layout.research_dir)
    assert len(staging.list(work=report.work, status=CandidateStatus.VERIFIED)) == 3
    assert report.rebuild is not None and report.rebuild.ok
    assert (report.root / ".research" / "research.db").is_file()


def test_cli_demo_prints_next_steps_and_the_inbox_shows_the_items(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    result = runner.invoke(app, ["demo", str(root), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["staged"] == 3 and payload["canonical_digest"].startswith("sha256:")

    inbox = runner.invoke(app, ["inbox", "-w", str(root), "--json"])
    assert inbox.exit_code == 0, inbox.output
    items = json.loads(inbox.stdout)
    listed = items["items"] if isinstance(items, dict) and "items" in items else items
    assert len(listed) == 3

    again = runner.invoke(app, ["demo", str(root)])
    assert again.exit_code != 0, "the demo never overwrites an existing workspace"

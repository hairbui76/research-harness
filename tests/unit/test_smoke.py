"""Phase 0 smoke tests: the package imports and the CLI answers without API keys."""

from typer.testing import CliRunner

import research_harness
from research_harness.cli.app import app, run_doctor

runner = CliRunner()


def test_package_exposes_version() -> None:
    assert research_harness.__version__
    assert research_harness.__version__ != "0.0.0+unknown"


def test_cli_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"research {research_harness.__version__}"


def test_doctor_checks_pass_locally() -> None:
    checks = run_doctor()
    assert {check.name for check in checks} >= {"research-harness", "python", "pydantic", "typer"}
    assert all(check.ok for check in checks), [c for c in checks if not c.ok]


def test_cli_doctor_exits_zero() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "[ok  ] python" in result.output
    assert "FAIL" not in result.output

"""Product §42.B - Host independence.

"A Claim created through CLI can be inspected through Web, VS Code, Claude, and ChatGPT
without duplication."

Every one of those clients is a thin client of the same capability layer: the Web cockpit
and VS Code speak HTTP, Claude and ChatGPT speak MCP (ADR-004, ADR-009). So the test is
three surfaces over one workspace - the CLI that wrote the Claim, the HTTP daemon, and the
in-process MCP bridge - plus the refusal that keeps a host from becoming a fourth author.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner, Result

from research_harness.capabilities.permissions import PrincipalKind
from research_harness.cli.app import app
from research_harness.protocol.mcp import HarnessMcpBridge
from research_harness.server.app import create_app, ensure_token

STATEMENT = "Byte-level tokenization improves recall on short encrypted flows."
CLAIM = "C0001"

runner = CliRunner()


def run(*args: str) -> Result:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, f"`research {' '.join(args)}` failed:\n{result.output}"
    return result


def events(root: Path) -> list[dict[str, Any]]:
    lines = (root / "events" / "research.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """One Claim, written by `research claim create` and by nothing else."""
    root = tmp_path / "project"
    run("init", str(root), "--name", "host-independence")
    run(
        "claim",
        "create",
        STATEMENT,
        "--workspace",
        str(root),
        "--scope",
        "L1",
        "--corpus",
        "encrypted traffic classifiers",
        "--json",
    )
    return root


@pytest.fixture
def http(workspace: Path) -> Iterator[TestClient]:
    """The local daemon over the same workspace, authenticated as the researcher."""
    with TestClient(create_app(workspace)) as client:
        client.headers["Authorization"] = f"Bearer {ensure_token(workspace)}"
        yield client


@pytest.fixture
def mcp(workspace: Path) -> HarnessMcpBridge:
    """The MCP bridge over the same workspace; a host is never the researcher."""
    return HarnessMcpBridge(workspace, host="claude")


# --------------------------------------------------------------------- one object


def test_the_cli_wrote_exactly_one_canonical_claim_file(workspace: Path) -> None:
    assert sorted(path.name for path in (workspace / "claims").glob("*.yaml")) == [f"{CLAIM}.yaml"]
    created = [event for event in events(workspace) if event["event"] == "claim.created"]
    assert len(created) == 1
    assert created[0]["subjects"] == [CLAIM]


def test_cli_http_and_mcp_report_the_same_claim(
    workspace: Path, http: TestClient, mcp: HarnessMcpBridge
) -> None:
    """One Claim object, three transports, no per-host copy (Product §42.B)."""
    from_cli = json.loads(
        run("claim", "show", CLAIM, "--workspace", str(workspace), "--json").stdout
    )
    from_http = http.get(f"/objects/{CLAIM}").json()["object"]
    from_mcp = mcp.call("claim.find_support", {"claim_id": CLAIM})
    assert from_mcp.ok, from_mcp.error
    assert from_mcp.result is not None

    identities = {
        "cli": (
            from_cli["claim"]["id"],
            from_cli["claim"]["statement"],
            from_cli["status"],
            from_cli["allowed_strength"],
        ),
        "http": (
            from_http["id"],
            from_http["statement"],
            from_http["assessment"]["status"],
            from_http["assessment"]["allowed_strength"],
        ),
        "mcp": (
            from_mcp.result["claim"],
            from_mcp.result["statement"],
            from_mcp.result["status"],
            from_mcp.result["allowed_strength"],
        ),
    }

    assert len(set(identities.values())) == 1, identities
    assert identities["cli"][1] == STATEMENT


def test_reading_through_three_transports_creates_no_second_object(
    workspace: Path, http: TestClient, mcp: HarnessMcpBridge
) -> None:
    """Reading is a read: the corpus after three inspections is the corpus before them."""
    before = sorted(path.name for path in (workspace / "claims").glob("*.yaml"))
    events_before = len(events(workspace))

    run("claim", "show", CLAIM, "--workspace", str(workspace), "--json")
    assert http.get(f"/objects/{CLAIM}").status_code == 200
    assert mcp.call("claim.find_support", {"claim_id": CLAIM}).ok

    assert sorted(path.name for path in (workspace / "claims").glob("*.yaml")) == before
    assert len(events(workspace)) == events_before


def test_the_two_daemons_offer_the_same_capability_names(
    http: TestClient, mcp: HarnessMcpBridge
) -> None:
    """A host and the cockpit see one registry, not two catalogs that can drift."""
    served = [item["name"] for item in http.get("/capabilities").json()["capabilities"]]
    bridged = [item.name for item in mcp.catalog().capabilities]

    assert served == bridged


# --------------------------------------------------------------------- the refusal


def test_an_agent_host_may_not_mutate_the_claim_it_can_read(
    workspace: Path, mcp: HarnessMcpBridge
) -> None:
    """Product §42.B is about inspection; ADR-009 is about who may write (Product §29)."""
    assert mcp.principal.kind is PrincipalKind.AGENT_HOST
    assert mcp.principal.is_human is False

    refused = mcp.call(
        "claim.audit",
        {
            "claim_id": CLAIM,
            "status": "supported",
            "allowed_strength": "universal_or_absence",
        },
    )

    assert refused.ok is False
    assert refused.error is not None
    assert refused.error.code == "permission_denied"
    assert [event for event in events(workspace) if event["event"].startswith("claim.audit")] == []


def test_every_mutating_capability_is_refused_over_mcp(mcp: HarnessMcpBridge) -> None:
    """The refusal is a property of the permission, not of one capability name."""
    mutating = [spec.name for spec in mcp.registry if spec.permission.value in {"mutate", "admin"}]
    assert "evidence.accept" in mutating

    for name in mutating:
        response = mcp.call(name, {})
        assert response.ok is False, name
        assert response.error is not None
        assert response.error.code == "permission_denied", name


def test_a_refusal_over_mcp_names_the_kind_and_not_the_host(
    workspace: Path, mcp: HarnessMcpBridge
) -> None:
    """Two hosts must be told the same thing, or the boundary is host-specific (ADR-009)."""
    refused = mcp.call("evidence.accept", {})
    other = HarnessMcpBridge(workspace, host="chatgpt").call("evidence.accept", {})

    assert refused.error is not None and other.error is not None
    assert refused.error.message == other.error.message
    assert "claude" not in refused.error.message

"""Gate P10: one Claim, created on the CLI, read and audited over HTTP and MCP.

The gate is the whole point of ADR-004 and ADR-009 made concrete: create a Claim through the
CLI, inspect and audit it through HTTP, inspect it through MCP, and verify there is exactly
*one* canonical Claim object behind all three. A second copy anywhere - a transport cache, a
per-host record, a duplicate file - would be the failure the product is built against.

The second half checks the other direction: the same operation issued on the CLI and over
HTTP produces the same state transition, the same canonical object, and the same event.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import typer
from starlette.testclient import TestClient
from typer.testing import CliRunner, Result

from research_harness.cli.commands import claim as claim_commands
from research_harness.cli.commands import init as init_commands
from research_harness.cli.commands import research as research_commands
from research_harness.cli.commands import serve as serve_commands
from research_harness.protocol.dto import CapabilityResponse
from research_harness.protocol.mcp import HarnessMcpBridge, create_mcp_server
from research_harness.server.app import create_app, ensure_token

STATEMENT = "Byte-level tokenization improves recall on short encrypted flows."
CLAIM = "C0001"

#: Written by whichever transport captured the note, and expected to differ: the CLI records
#: that the capture came from the CLI. It is provenance, not content (Product 31).
CAPTURE_PROVENANCE = "note"

runner = CliRunner()


@pytest.fixture
def cli() -> typer.Typer:
    """A `research` app with the command families this gate drives, registered by hand.

    The families are wired into `COMMAND_MODULES` by the project manager; registering them
    here keeps the gate honest about which commands it is actually exercising.
    """
    app = typer.Typer(name="research", no_args_is_help=True, add_completion=False)
    for module in (init_commands, claim_commands, research_commands, serve_commands):
        module.register(app)
    return app


def run(app: typer.Typer, *args: str) -> Result:
    result = runner.invoke(app, list(args))
    if result.exit_code != 0:  # pragma: no cover - surfaced only when the gate breaks
        raise AssertionError(f"`research {' '.join(args)}` failed: {result.output}")
    return result


def payload(result: Result) -> dict[str, Any]:
    """The `--json` body a command printed."""
    return json.loads(result.stdout)


def events(root: Path) -> list[dict[str, Any]]:
    lines = (root / "events" / "research.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture
def workspace(cli: typer.Typer, tmp_path: Path) -> Path:
    """A workspace created through `research init`, holding one Claim from `claim create`."""
    root = tmp_path / "project"
    run(cli, "init", str(root), "--name", "gate-p10")
    run(
        cli,
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
def client(workspace: Path) -> Iterator[TestClient]:
    """The daemon over the same workspace, as the local researcher."""
    with TestClient(create_app(workspace)) as test_client:
        test_client.headers["Authorization"] = f"Bearer {ensure_token(workspace)}"
        yield test_client


@pytest.fixture
def bridge(workspace: Path) -> HarnessMcpBridge:
    """The MCP side over the same workspace; always an agent host (Product 29)."""
    return HarnessMcpBridge(workspace)


# -- Gate P10 ----------------------------------------------------------------


def test_the_cli_writes_exactly_one_canonical_claim(workspace: Path) -> None:
    files = sorted(path.name for path in (workspace / "claims").glob("*.yaml"))
    assert files == [f"{CLAIM}.yaml"]


def test_the_event_log_records_exactly_one_claim_created(workspace: Path) -> None:
    created = [event for event in events(workspace) if event["event"] == "claim.created"]
    assert len(created) == 1
    assert created[0]["subjects"] == [CLAIM]


def test_cli_http_and_mcp_show_the_same_claim(
    cli: typer.Typer, workspace: Path, client: TestClient, bridge: HarnessMcpBridge
) -> None:
    """Product 42 B: one Claim object, four surfaces, no duplication."""
    from_cli = payload(run(cli, "claim", "show", CLAIM, "--workspace", str(workspace), "--json"))
    from_http = client.get(f"/objects/{CLAIM}").json()
    from_mcp = bridge.call("claim.find_support", {"claim_id": CLAIM})

    assert from_mcp.ok
    assert from_mcp.result is not None
    identities = {
        "cli": (
            from_cli["claim"]["id"],
            from_cli["claim"]["statement"],
            from_cli["status"],
            from_cli["allowed_strength"],
        ),
        "http": (
            from_http["object"]["id"],
            from_http["object"]["statement"],
            from_http["object"]["assessment"]["status"],
            from_http["object"]["assessment"]["allowed_strength"],
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


def test_the_claim_is_audited_over_http_and_every_surface_agrees(
    cli: typer.Typer, workspace: Path, client: TestClient, bridge: HarnessMcpBridge
) -> None:
    """The audit is a mutation, so it needs the local token; every reader then sees it."""
    response = client.post(
        "/capabilities/claim.audit",
        json={
            "claim_id": CLAIM,
            "status": "qualified",
            "allowed_strength": "individual",
            "maximum_defensible_wording": "in the two systems examined",
        },
    )
    assert response.status_code == 200
    audited = CapabilityResponse.model_validate(response.json())
    assert audited.ok
    assert audited.result is not None
    # A `qualified` audit logs `claim.qualified`; either way it is the audit event, and it
    # is the same event the CLI would have written (`handlers.audit_claim`).
    assert audited.result["event"]["event"] == "claim.qualified"

    from_cli = payload(run(cli, "claim", "show", CLAIM, "--workspace", str(workspace), "--json"))
    from_http = client.get(f"/objects/{CLAIM}").json()["object"]
    from_mcp = bridge.call("claim.find_support", {"claim_id": CLAIM}).result
    assert from_mcp is not None

    assert from_cli["status"] == from_http["assessment"]["status"] == from_mcp["status"]
    assert from_cli["status"] == "qualified"
    assert (
        from_cli["allowed_strength"]
        == from_http["assessment"]["allowed_strength"]
        == from_mcp["allowed_strength"]
        == "individual"
    )
    assert from_http["assessment"]["maximum_defensible_wording"] == "in the two systems examined"
    assert sorted(path.name for path in (workspace / "claims").glob("*.yaml")) == [f"{CLAIM}.yaml"]


def test_the_mcp_tool_list_covers_the_daemon_catalog(workspace: Path, client: TestClient) -> None:
    """A host and the Web cockpit are offered the same names over their own transports."""
    import asyncio

    from research_harness.protocol.mcp import mcp_tool_name

    catalog = client.get("/capabilities").json()
    tools = asyncio.run(create_mcp_server(workspace).list_tools())
    assert {tool.name for tool in tools} == {
        mcp_tool_name(item["name"]) for item in catalog["capabilities"]
    }


def test_an_agent_host_cannot_audit_the_claim(bridge: HarnessMcpBridge, workspace: Path) -> None:
    """The host may read the Claim and ask; the researcher is who audits it (ADR-007)."""
    refused = bridge.call(
        "claim.audit",
        {"claim_id": CLAIM, "status": "supported", "allowed_strength": "universal_or_absence"},
    )
    assert refused.ok is False
    assert refused.error is not None
    assert refused.error.code == "permission_denied"
    audited = [event for event in events(workspace) if event["event"] == "claim.audited"]
    assert audited == []


def test_the_cli_reports_the_same_catalog_the_daemon_serves(
    cli: typer.Typer, workspace: Path, client: TestClient
) -> None:
    """`research capabilities` is the CLI's view of the one registry, not a second list."""
    listed = payload(run(cli, "capabilities", "--workspace", str(workspace), "--json"))
    served = client.get("/capabilities").json()
    assert [item["name"] for item in listed["capabilities"]] == [
        item["name"] for item in served["capabilities"]
    ]
    assert [item["name"] for item in listed["planned"]] == [
        item["name"] for item in served["planned"]
    ]


def test_the_token_command_prints_a_path_and_not_the_secret(
    cli: typer.Typer, workspace: Path
) -> None:
    """Product 34: a local credential does not belong in a shell history or a log."""
    printed = run(cli, "token", "--workspace", str(workspace)).stdout.strip()
    path = Path(printed)
    assert path.is_file()
    assert path.parent.name == ".research"
    assert path.read_text(encoding="utf-8").strip() not in printed


# -- v1.1: every new capability is reachable from the terminal ----------------

#: Each v1.1 capability and the `research ...` command that reaches it. A capability with
#: no terminal counterpart is a capability the researcher can only use through a browser,
#: which is the thing ADR-004 exists to prevent: the CLI is a first-class client, not a
#: fallback (v1.1 plan SS0.4).
V11_CLI_COUNTERPARTS: dict[str, tuple[str, ...]] = {
    "session.create": ("chat", "new"),
    "session.rename": ("chat", "rename"),
    "session.list": ("chat", "list"),
    "session.get": ("chat", "show"),
    "session.search": ("chat", "search"),
    "session.send": ("chat", "send"),
    "session.stop": ("chat", "stop"),
    "session.retry": ("chat", "retry"),
    "session.promote": ("chat", "promote"),
    "session.summarize": ("chat", "summarize"),
    # One command, two capabilities: without `--pack` it previews, with `--pack` it reads
    # the receipt a past message already named.
    "context.preview": ("chat", "context"),
    "context.get": ("chat", "context"),
    "provider.list": ("providers", "list"),
    "attachment.add": ("attachment", "add"),
    "attachment.remove": ("attachment", "remove"),
    "attachment.check_send": ("attachment", "check"),
    "attachment.resolve_identity": ("attachment", "resolve"),
    "attachment.save_to_corpus": ("attachment", "save"),
    "graph.resolve": ("graph", "resolve"),
    "graph.autocomplete": ("graph", "complete"),
    "graph.neighbors": ("graph", "neighbors"),
    "graph.query": ("graph", "query"),
    "graph.provenance": ("graph", "provenance"),
    "graph.status": ("graph", "status"),
    "manuscript.files": ("manuscript", "files"),
    "manuscript.read_file": ("manuscript", "read"),
    "manuscript.write_file": ("manuscript", "write"),
    "manuscript.compile": ("manuscript", "compile"),
    "manuscript.build": ("manuscript", "build"),
    "manuscript.synctex": ("manuscript", "synctex"),
    "manuscript.suggest": ("manuscript", "suggest"),
    "manuscript.apply_suggestion": ("manuscript", "apply"),
}

#: The families v1.1 added. `manuscript.*` predates it, so only the workspace half counts.
V11_PREFIXES = ("session.", "context.", "attachment.", "graph.", "provider.")


def v11_capabilities() -> set[str]:
    """Every capability the v1.1 track registered, read off the registry itself."""
    from research_harness.capabilities.manuscript_workspace import (
        MANUSCRIPT_WORKSPACE_CAPABILITIES,
    )
    from research_harness.capabilities.registry import build_default_registry

    names = set(build_default_registry().names())
    return {name for name in names if name.startswith(V11_PREFIXES)} | set(
        MANUSCRIPT_WORKSPACE_CAPABILITIES
    )


def cli_commands(app: typer.Typer) -> set[tuple[str, ...]]:
    """Every `(group, command)` the full `research` app publishes."""
    found: set[tuple[str, ...]] = set()
    for group in app.registered_groups:
        instance = group.typer_instance
        if group.name is None or instance is None:  # pragma: no cover - every group is named
            continue
        for command in instance.registered_commands:
            found.add((group.name, command.name or command.callback.__name__))
    return found


def test_every_v11_capability_has_a_command_in_the_terminal() -> None:
    """ADR-004: the CLI reaches every capability the daemon and an MCP host reach."""
    from research_harness.cli.app import app as full_app

    published = cli_commands(full_app)
    missing = {
        name: command for name, command in V11_CLI_COUNTERPARTS.items() if command not in published
    }

    assert not missing, f"capabilities with no `research` command: {missing}"


def test_the_counterpart_table_covers_every_v11_capability() -> None:
    """The table above is the claim; this is what stops it going quietly out of date."""
    uncovered = v11_capabilities() - set(V11_CLI_COUNTERPARTS)

    assert not uncovered, f"v1.1 capabilities with no listed CLI counterpart: {sorted(uncovered)}"


def test_the_terminal_and_the_daemon_report_the_same_model_catalog(
    workspace: Path, client: TestClient
) -> None:
    """`research providers list` is the CLI's view of `provider.list`, not a second answer."""
    from research_harness.cli.app import app as full_app

    printed = json.loads(
        run(full_app, "providers", "list", "--workspace", str(workspace), "--json").stdout
    )
    served = client.post("/capabilities/provider.list", json={}).json()

    assert served["ok"] is True
    assert printed == served["result"]


def test_the_terminal_reads_back_the_receipt_the_daemon_recorded(
    workspace: Path, client: TestClient
) -> None:
    """`research chat context --pack` and `context.get` are one read (v1.1 plan SS0.4)."""
    from research_harness.cli.app import app as full_app

    session = client.post("/capabilities/session.create", json={"title": "parity"}).json()
    session_id = session["result"]["session"]["id"]
    preview = client.post(
        "/capabilities/context.preview",
        json={"session": session_id, "text": "what would this send"},
    ).json()
    pack_id = preview["result"]["pack"]["id"]

    printed = json.loads(
        run(
            full_app,
            "chat",
            "context",
            session_id,
            "--workspace",
            str(workspace),
            "--pack",
            pack_id,
            "--json",
        ).stdout
    )
    read = client.post(
        "/capabilities/context.get", json={"session": session_id, "pack": pack_id}
    ).json()

    assert read["ok"] is True
    assert printed["pack"] == read["result"]["pack"]
    assert printed["unresolved"] == list(read["result"]["unresolved"])
    assert read["result"] == preview["result"], "read back, the receipt is the one recorded"


def test_asking_a_receipt_for_a_draft_at_the_same_time_is_refused(workspace: Path) -> None:
    """`--pack` reads; without it the command assembles. Doing both would mean neither."""
    from research_harness.cli.app import app as full_app

    refused = runner.invoke(
        full_app,
        ["chat", "context", "CS0001", "-w", str(workspace), "--pack", "CP0001", "--text", "x"],
    )

    assert refused.exit_code == 1
    assert "recorded receipt" in refused.stderr


# -- CLI/HTTP transition parity ----------------------------------------------


def _note_state(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """The single note in ``root`` and the single `note.captured` event, both normalized."""
    files = sorted((root / "notes").glob("*.yaml"))
    assert len(files) == 1, f"expected one note under {root}, found {len(files)}"
    import yaml

    note = yaml.safe_load(files[0].read_text(encoding="utf-8"))
    captured = [event for event in events(root) if event["event"] == "note.captured"]
    assert len(captured) == 1
    return _without_volatile(note), _without_volatile(captured[0])


def _without_volatile(record: dict[str, Any]) -> dict[str, Any]:
    """Drop what two runs cannot share: clocks, generated keys, and the capture source."""
    volatile = {"created_at", "updated_at", "occurred_at", "key", "tx", "digest"}
    cleaned = {
        key: value for key, value in record.items() if key not in volatile and value is not None
    }
    provenance = cleaned.get("provenance")
    if isinstance(provenance, dict):
        cleaned["provenance"] = {
            key: value for key, value in provenance.items() if key != CAPTURE_PROVENANCE
        }
    payload_ = cleaned.get("payload")
    if isinstance(payload_, dict):
        cleaned["payload"] = {key: value for key, value in payload_.items() if key != "note"}
    written = cleaned.get("objects")
    if isinstance(written, dict):
        # The generated key and the content digest differ between two runs; which canonical
        # collection was written is the part that has to match.
        cleaned["objects"] = sorted(key.split("/")[0] for key in written)
    if isinstance(cleaned.get("summary"), str):
        cleaned["summary"] = cleaned["summary"].split(" note ")[0]
    return cleaned


def test_cli_and_http_produce_the_same_state_transition(cli: typer.Typer, tmp_path: Path) -> None:
    """`research note add` and `POST /capabilities/note.add` are the same mutation.

    They are compared on two freshly initialized workspaces, ignoring clocks, the generated
    note key, and the capture source the CLI stamps onto provenance - everything else, the
    canonical object and the journalled event alike, must match exactly (Task 10.4).
    """
    text = "byte-level tokenization keeps showing up in the corpus"
    through_cli = tmp_path / "via-cli"
    through_http = tmp_path / "via-http"
    run(cli, "init", str(through_cli), "--name", "parity")
    run(cli, "init", str(through_http), "--name", "parity")

    run(cli, "note", "add", text, "--workspace", str(through_cli), "--json")
    with TestClient(create_app(through_http)) as client:
        client.headers["Authorization"] = f"Bearer {ensure_token(through_http)}"
        response = client.post("/capabilities/note.add", json={"text": text})
    assert response.status_code == 200

    cli_note, cli_event = _note_state(through_cli)
    http_note, http_event = _note_state(through_http)
    assert cli_note == http_note
    assert cli_event == http_event
    assert cli_note["text"] == text
    assert cli_event["event"] == "note.captured"

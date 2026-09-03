"""The five ported runtimes answer the same contract and refuse a tool event (spec §9, §20).

Driven through fake executables replaying the sanitized stream fixtures. These cases
bypass the posture gate on purpose: the provider itself never checks posture -- the
capability layer does -- so the wire behaviour is pinned even for the runtimes that are
detected but never routed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_harness.providers.cli.errors import CliResponseError
from research_harness.providers.cli.provider import CliModelProvider
from research_harness.providers.models.base import ModelRequest
from tests.contract.providers.conftest import EXPECTED_VERDICT, Verdict
from tests.contract.providers.test_cli_provider import lines
from tests.fixtures.cli.fakes import FakeCli

RUNTIME_OF = {
    "cursor-agent": "cursor-agent",
    "amp": "amp",
    "opencode-cli": "opencode",
    "dsh": "deepseek-harness",
    "pi": "pi",
}

OTHERS: list[tuple[str, str, dict[str, object]]] = [
    ("cursor-agent", "cursor-success.jsonl", {"before_input": [], "read_stdin": True}),
    ("amp", "amp-success.jsonl", {}),
    ("opencode-cli", "opencode-success.jsonl", {}),
    (
        "dsh",
        "dsh-success.jsonl",
        {"before_input": [lines("dsh-success.jsonl")[0]], "read_one_line": True},
    ),
    ("pi", "pi-success.jsonl", {"read_one_line": True}),
]


@pytest.mark.parametrize(
    ("executable", "fixture", "extra"), OTHERS, ids=[case[0] for case in OTHERS]
)
def test_every_other_runtime_answers_the_same_contract(
    tmp_path: Path,
    model_request: ModelRequest[Verdict],
    executable: str,
    fixture: str,
    extra: dict[str, object],
) -> None:
    runtime = RUNTIME_OF[executable]
    body: list[object] = list(lines(fixture))
    if executable == "dsh":
        body = body[1:]  # `ready` is emitted before the execute command is read
    fake = FakeCli.install(tmp_path, executable, run={"lines": body, **extra})
    adapter = CliModelProvider(runtime, env=fake.env({"PATH": ""}), timeout=10)

    response = adapter.complete(model_request)

    assert response.parsed == EXPECTED_VERDICT and response.provider == f"local_cli:{runtime}"
    run = fake.runs()[0]
    assert "Table 3 reports" in (run["stdin"] or "")
    assert not any("Table 3" in arg for arg in run["argv"])
    if executable == "dsh":
        command = json.loads(run["stdin"])
        assert command["type"] == "execute" and command["mcp_servers"] == []
        assert "Table 3 reports" in command["prompt"]
    if executable == "pi":
        assert json.loads(run["stdin"])["type"] == "prompt"
    if executable == "opencode-cli":
        config = json.loads(run["env"]["OPENCODE_CONFIG_CONTENT"])
        assert config["permission"]["bash"] == "deny"


@pytest.mark.parametrize(
    ("executable", "fixture"),
    [
        ("cursor-agent", "cursor-tool.jsonl"),
        ("amp", "claude-tool.jsonl"),
        ("opencode-cli", "opencode-tool.jsonl"),
        ("dsh", "dsh-tool.jsonl"),
        ("pi", "pi-tool.jsonl"),
    ],
    ids=["cursor-agent", "amp", "opencode-cli", "dsh", "pi"],
)
def test_every_other_runtime_fails_on_a_tool_event(
    tmp_path: Path, model_request: ModelRequest[Verdict], executable: str, fixture: str
) -> None:
    runtime = RUNTIME_OF[executable]
    body: list[object] = list(lines(fixture))
    extra: dict[str, object] = {}
    if executable == "dsh":
        extra = {"before_input": [body[0]], "read_one_line": True}
        body = body[1:]
    if executable == "pi":
        extra = {"read_one_line": True}
    fake = FakeCli.install(
        tmp_path, executable, run={"lines": [*body, {"sleep": 30}], "hang": True, **extra}
    )

    with pytest.raises(CliResponseError) as caught:
        CliModelProvider(runtime, env=fake.env({"PATH": ""}), timeout=10).complete(model_request)

    assert caught.value.diagnostic == "bounded_authority_violation"

"""A run started over a transport leaves the same disposable trace a CLI run leaves.

`TracingRouter` used to live in `cli/providers.py`, so `.research/traces/` recorded exactly
the runs a researcher started from a terminal. The daemon and the MCP bridge build their own
router in `capabilities/extra_handlers.py::_router`, which means the runs a researcher is
*least* able to watch — the ones an agent host started — were the ones that left no record
at all. The wrapper now lives in `privacy/traces.py` and both callers use it.

Two properties, both from Product §19.3 and §34: a run over the capability layer writes a
trace, and the project's `redact_traces` is honoured *as it is written*, so source text
never reaches the disk in the first place.

The run is scripted and executed inline. `work.interrogate` answers with a run id and works
on a daemon thread, so the thread is replaced with one that runs on `start()` — a sleep-free
way to assert on what the run left behind (conventions.md: no sleeps).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

import research_harness.capabilities.extra_handlers as extra_handlers
import research_harness.providers.models.router as router_module
from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.permissions import Principal
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.cli.app import app
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.parsing.base import ParsedDocument
from research_harness.privacy.traces import TraceWriter, TracingRouter
from research_harness.providers.models.scripted import ScriptedProvider, scripted_router
from tests.integration.evidence.conftest import (
    DATASET_SENTENCE,
    dataset_candidate,
    extraction_dict,
    parse_fixture,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_research_paper.pdf"

#: A `providers:` list has to be non-empty for `_router` to build anything; the scripted
#: router replaces what it builds, so the entry is never contacted.
PLACEHOLDER: list[dict[str, Any]] = [
    {"name": "unused", "kind": "local_openai_compatible", "model": "qwen"}
]

runner = CliRunner()


class _Inline(threading.Thread):
    """A thread that runs its target on `start()`, so a background run is assertable."""

    def start(self) -> None:
        self.run()


@pytest.fixture(scope="module")
def parsed() -> ParsedDocument:
    """The fixture parsed once, so the scripted answer quotes a span that really exists."""
    return parse_fixture()


@pytest.fixture(autouse=True)
def inline_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Execute `_start_in_background` on the calling thread."""
    monkeypatch.setattr(extra_handlers.threading, "Thread", _Inline, raising=True)


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch, parsed: ParsedDocument) -> None:
    """Every router the capability layer builds answers from a script, offline."""
    replies = [extraction_dict([dataset_candidate(parsed)])] * 8

    def build(config: Any, env: Any = None, **kwargs: Any) -> Any:
        del config, env, kwargs
        return scripted_router(ScriptedProvider(list(replies)))

    monkeypatch.setattr(router_module, "build_router", build)


def workspace(tmp_path: Path, **privacy: Any) -> Path:
    """A workspace with the synthetic paper ingested and parsed, under `privacy`."""
    root = tmp_path / "project"
    for command in (
        ["init", str(root), "--name", "traces"],
        ["ingest", str(FIXTURE), "-w", str(root)],
        ["parse", "W0001", "-w", str(root)],
    ):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output
    path = root / "research.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["providers"] = PLACEHOLDER
    if privacy:
        config["privacy"] = privacy
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return root


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    yield open_context(workspace(tmp_path), HUMAN_ACTOR)


@pytest.fixture
def redacting(tmp_path: Path) -> Iterator[CapabilityContext]:
    yield open_context(workspace(tmp_path, redact_traces=True), HUMAN_ACTOR)


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    return build_default_registry()


def interrogate(ctx: CapabilityContext, registry: CapabilityRegistry) -> Any:
    return registry.invoke(
        "work.interrogate",
        ctx,
        {"work": "W0001", "provider": "scripted", "fields": ["dataset"]},
        principal=Principal.human(HUMAN_ACTOR),
    )


def traces_of(ctx: CapabilityContext) -> list[Any]:
    return TraceWriter(ctx.repo.layout.research_dir).list_traces()


# -- the router the capability layer hands a run -----------------------------


def test_the_capability_router_carries_the_workspaces_trace_sink(
    project: CapabilityContext, scripted: None
) -> None:
    """`_router` is the server path's provider selection, and selection owns the sink."""
    router = extra_handlers._router(project, "scripted")

    assert isinstance(router, TracingRouter)
    sink = router.sink
    assert isinstance(sink, TraceWriter)
    assert sink.traces_dir == project.repo.layout.research_dir / "traces"


# -- what a run over the registry leaves behind ------------------------------


def test_a_scripted_interrogation_over_the_registry_writes_a_trace(
    project: CapabilityContext, registry: CapabilityRegistry, scripted: None
) -> None:
    assert traces_of(project) == [], "nothing before the run"

    started = interrogate(project, registry)

    assert started.run_id
    records = traces_of(project)
    assert records, "a run driven over the capability layer records what it asked"
    assert all(record.path.is_file() for record in records)


def test_the_trace_carries_the_request_and_the_answer_verbatim_by_default(
    project: CapabilityContext, registry: CapabilityRegistry, scripted: None
) -> None:
    """The default policy does not redact, so a trace is debuggable (Product §19.3)."""
    interrogate(project, registry)

    document = json.loads(traces_of(project)[0].path.read_text(encoding="utf-8"))

    assert document["redacted"] is False
    assert document["authority"].startswith("none:")
    assert DATASET_SENTENCE in json.dumps(document["payload"])


def test_redact_traces_hashes_the_source_text_as_the_trace_is_written(
    redacting: CapabilityContext, registry: CapabilityRegistry, scripted: None
) -> None:
    """The policy is honoured on the server path too, not only on the CLI's (Product §34)."""
    interrogate(redacting, registry)

    records = traces_of(redacting)
    assert records
    body = json.dumps(json.loads(records[0].path.read_text(encoding="utf-8")))

    assert '"redacted": true' in body
    assert DATASET_SENTENCE not in body, "the plaintext never reached the disk"
    assert "sha256:" in body

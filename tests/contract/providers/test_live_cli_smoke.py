"""Opt-in live smoke through the CLIs installed and logged in on this workstation.

Never part of CI: skipped unless `RESEARCH_HARNESS_LIVE_CLI_TESTS=1`, and per runtime
unless the CLI is installed, logged in, and bounded. One minimal schema-validated
request per runtime; no project file is read; on failure nothing raw is printed.

    RESEARCH_HARNESS_LIVE_CLI_TESTS=1 uv run pytest tests/contract/providers/test_live_cli_smoke.py

Set `RESEARCH_HARNESS_LIVE_CLI_CAPTURE=<dir>` to also write a sanitized JSONL capture of
the event stream per runtime, for the parser fixtures.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from research_harness.providers.cli.detection import detect
from research_harness.providers.cli.errors import redact
from research_harness.providers.cli.process import BoundedProcess
from research_harness.providers.cli.provider import CliModelProvider, SpawnFactory
from research_harness.providers.cli.registry import RUNTIMES
from research_harness.providers.cli.types import CliRuntimeStatus
from research_harness.providers.models import (
    InputEnvelope,
    ModelRequest,
    ModelRequirements,
    ModelResponse,
    StructuredOutputError,
)
from tests.contract.providers.conftest import SOURCE_TEXT, Verdict

LIVE_FLAG = "RESEARCH_HARNESS_LIVE_CLI_TESTS"
CAPTURE = "RESEARCH_HARNESS_LIVE_CLI_CAPTURE"

live_only = pytest.mark.skipif(
    os.environ.get(LIVE_FLAG) != "1",
    reason=f"set {LIVE_FLAG}=1 to run live CLI smoke tests",
)

# Any key that names an identifier: `id`, `uuid`, or anything ending in `_id`/`ID`/`Id`
# (`session_id`, `thread_id`, `sessionID`, `toolCallId`, `parent_tool_use_id`, ...). The
# *value* is replaced and the key is kept, because the fixture's whole purpose is the
# event structure (spec §21). "valid" and friends are safe: a bare `id` must be the whole
# key, and the suffix forms need the underscore or the capital.
_ID_KEY = r"(?:id|uuid|[A-Za-z][A-Za-z0-9_]*?(?:_id|_uuid|ID|Id|UUID|Uuid))"
_ID_VALUE = re.compile(rf'"({_ID_KEY})"\s*:\s*"[^"]*"')
# A second, value-only pass for an opaque id under a key the rule above does not name.
# The tail must contain a digit and be six characters or more, so it cannot eat a key
# (`thread_id`, `call_id`) or a word in prose (`call_reference`); the lookahead keeps it
# off anything that is a JSON key.
_ID_TOKEN = re.compile(
    r"\b(?:sess|ses|msg|toolu|thread|conv|req|call|item|resp)"
    r'_(?=[A-Za-z0-9-]*\d)[A-Za-z0-9-]{6,}(?!"\s*:)'
)
_HOME = re.compile(r'/(?:home|Users)/[^/\s"]+')
_VERSION_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _request() -> ModelRequest[Verdict]:
    return ModelRequest(
        role="evidence_verifier",
        requirements=ModelRequirements(
            structured_output=True,
            context_tokens=20_000,
            reasoning="low",
            max_output_tokens=512,
        ),
        instructions=(
            "Decide whether the source text states the throughput figure. "
            "Answer only with the required structured object."
        ),
        inputs=[InputEnvelope(object_id="work:live", kind="source_text", content=SOURCE_TEXT)],
        response_schema=Verdict,
        temperature=0.0,
    )


class _Capturing(BoundedProcess):
    """A bounded process that also keeps the stdout lines, for the sanitized capture.

    The buffer is class-level because `spawn` is what the provider is handed: the test
    never sees the instance, so there is nowhere per-instance to read the lines back from.
    One runtime runs at a time, and each test resets the buffer before spawning.
    """

    captured: ClassVar[list[str]] = []

    def lines(self) -> Iterator[str]:
        for line in super().lines():
            type(self).captured.append(line)
            yield line


def _sanitize(line: str) -> str:
    """Keep the event structure; replace ids, home paths, e-mails and secrets (spec §21).

    Applied to the raw line rather than to a re-serialized object on purpose: a fixture is
    evidence of the wire format, so key order, spacing and duplicate keys must survive
    exactly as the runtime wrote them. `redact` is the engine's own scrubber (e-mails,
    `Bearer`, `sk-`/`gh*_`/`xox*` tokens, long opaque tokens, this workstation's home) and
    goes first; the two id passes then replace values only, never a key.
    """
    cleaned = _HOME.sub("~", redact(line))
    return _ID_TOKEN.sub("sess-x", _ID_VALUE.sub(r'"\1":"sess-x"', cleaned))


def _version_tag(version: str | None) -> str:
    """A file-name-safe version: it comes from a live CLI, so it never shapes the path."""
    return _VERSION_CHARS.sub("-", version or "unknown").strip("-") or "unknown"


def _write_capture(runtime: str, status: CliRuntimeStatus, lines: list[str]) -> Path:
    out = Path(os.environ[CAPTURE]) / f"{runtime}-live-{_version_tag(status.version)}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# source: live {runtime} {status.version or 'unknown'} "
        f"on {status.scanned_at.date().isoformat()}; sanitized"
    )
    body = "\n".join([header, *(_sanitize(line) for line in lines)])
    out.write_text(body + "\n", encoding="utf-8")
    return out


def _answer(runtime: str, provider: CliModelProvider) -> ModelResponse[Verdict]:
    """One turn; a schema failure is reported without echoing a word of the answer.

    `StructuredOutputError`'s own message embeds the pydantic `input_value` fragments --
    pieces of what the model said -- and spec §20 forbids printing those on failure. Only
    the exception's class name is reported (it carries `provider` and `raw_text`, no
    diagnostic code). `pytest.fail` is deliberately called *outside* the `except` block:
    inside it, the implicit exception chaining would put that message back in the report.
    """
    try:
        return provider.complete(_request())
    except StructuredOutputError as exc:
        kind = type(exc).__name__
    pytest.fail(f"{runtime}: the runtime answered, but not with the requested object ({kind})")


@live_only
@pytest.mark.parametrize("runtime", ["codex", "claude"])
def test_live_cli_smoke(runtime: str) -> None:
    status = detect(RUNTIMES[runtime])
    if not status.routable:
        detail = "; ".join(status.diagnostics)
        reason = status.unavailable_reason or f"auth {status.auth_status}"
        pytest.skip(f"{runtime}: {reason}" + (f" ({detail})" if detail else ""))
    capture = os.environ.get(CAPTURE)
    _Capturing.captured.clear()
    spawn: SpawnFactory = _Capturing.spawn if capture else BoundedProcess.spawn
    provider = CliModelProvider(runtime, timeout=180, spawn=spawn, version=status.version)

    # `complete()` has already validated the answer against `Verdict` by the time it
    # returns, so what is left to assert is the run's own metadata.
    response = _answer(runtime, provider)

    assert response.provider == f"local_cli:{runtime}"
    assert response.request_fingerprint
    assert response.model, "the completion must name the model that answered"
    assert response.usage.input_tokens > 0, "the runtime reported no token accounting"
    if capture:
        _write_capture(runtime, status, list(_Capturing.captured))


# -- the sanitizer itself, offline and always run ----------------------------

# Invented values only: no real id, user name, address or token appears here.
_FAKE_CODEX = '{"type":"thread.started","thread_id":"0199f0c1-dead-4000-b0b0-000000000000"}'
_FAKE_CLAUDE = (
    '{"type":"system","subtype":"init",'
    '"session_id":"9f1c2d3e-0000-4000-8000-abcdefabcdef",'
    '"uuid":"3b7f0a11-1111-4111-8111-222222222222",'
    '"cwd":"/Users/nobody/repo","account":{"email":"nobody@example.invalid"},"tools":[]}'
)
_FAKE_TOKEN = (
    '{"type":"debug","headers":'
    '{"Authorization":"Bearer sk-ant-api03-FAKEFAKEFAKEFAKEFAKEFAKEFAKE"}}'
)
_FAKE_UNKEYED = '{"type":"item.completed","item":{"payload":"resp_01FAKEfake0000 finished"}}'
_FAKE_LINES = (_FAKE_CODEX, _FAKE_CLAUDE, _FAKE_TOKEN, _FAKE_UNKEYED)
_MUST_NOT_SURVIVE = (
    "0199f0c1-dead-4000-b0b0-000000000000",
    "9f1c2d3e-0000-4000-8000-abcdefabcdef",
    "3b7f0a11-1111-4111-8111-222222222222",
    "/Users/nobody",
    "nobody@example.invalid",
    "sk-ant-api03-FAKEFAKEFAKEFAKEFAKEFAKEFAKE",
    "resp_01FAKEfake0000",
)


def _keys(value: object) -> set[str]:
    """Every key anywhere in a decoded event, however deeply nested."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def test_the_sanitizer_keeps_the_event_shape_and_drops_every_identifier() -> None:
    """Structure survives, identifiers do not (spec §21).

    Deliberately not gated behind the live flag: a capture is only safe to commit if this
    holds, so it is checked on every machine and in CI, where no CLI is ever run.
    """
    for line in _FAKE_LINES:
        cleaned = _sanitize(line)
        before, after = json.loads(line), json.loads(cleaned)

        assert _keys(after) == _keys(before), f"a key changed: {sorted(_keys(after))}"
        assert after["type"] == before["type"], "the event type must survive"
        for secret in _MUST_NOT_SURVIVE:
            assert secret not in cleaned, f"{secret[:16]}... survived sanitizing"

    codex, claude = json.loads(_sanitize(_FAKE_CODEX)), json.loads(_sanitize(_FAKE_CLAUDE))
    assert codex["thread_id"] == "sess-x"
    assert claude["session_id"] == "sess-x" and claude["uuid"] == "sess-x"
    assert claude["cwd"] == "~/repo"
    assert claude["account"]["email"] == "<email>"
    token = json.loads(_sanitize(_FAKE_TOKEN))["headers"]["Authorization"]
    assert token == "Bearer <redacted>"
    assert json.loads(_sanitize(_FAKE_UNKEYED))["item"]["payload"] == "sess-x finished"

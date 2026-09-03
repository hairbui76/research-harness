"""Opt-in live smoke tests against real provider endpoints.

Never part of CI: every test here is skipped unless
`RESEARCH_HARNESS_LIVE_PROVIDER_TESTS=1` *and* the provider's credential (or local
endpoint) is configured. They cost money and require network access; the deterministic
contract tests next to this file are the ones that must always pass.

    RESEARCH_HARNESS_LIVE_PROVIDER_TESTS=1 uv run pytest tests/contract/providers/test_live_smoke.py

Model ids can be overridden with `RESEARCH_HARNESS_LIVE_{OPENAI,ANTHROPIC,LOCAL}_MODEL`.
"""

from __future__ import annotations

import os

import pytest

from research_harness.providers.models import (
    AnthropicProvider,
    InputEnvelope,
    LocalOpenAICompatibleProvider,
    ModelRequest,
    ModelRequirements,
    OpenAIProvider,
)
from tests.contract.providers.conftest import SOURCE_TEXT, Verdict

LIVE_FLAG = "RESEARCH_HARNESS_LIVE_PROVIDER_TESTS"

live_only = pytest.mark.skipif(
    os.environ.get(LIVE_FLAG) != "1",
    reason=f"set {LIVE_FLAG}=1 to run live provider smoke tests",
)


def _live_request() -> ModelRequest[Verdict]:
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


def _assert_usable(
    provider: OpenAIProvider | AnthropicProvider | LocalOpenAICompatibleProvider,
) -> None:
    with provider:
        response = provider.complete(_live_request())
    assert isinstance(response.parsed, Verdict)
    assert response.raw_text
    assert response.usage.output_tokens > 0
    assert response.request_fingerprint


@live_only
@pytest.mark.skipif("OPENAI_API_KEY" not in os.environ, reason="OPENAI_API_KEY is not set")
def test_openai_live_smoke() -> None:
    model = os.environ.get("RESEARCH_HARNESS_LIVE_OPENAI_MODEL", "gpt-5")
    _assert_usable(OpenAIProvider(model))


@live_only
@pytest.mark.skipif("ANTHROPIC_API_KEY" not in os.environ, reason="ANTHROPIC_API_KEY is not set")
def test_anthropic_live_smoke() -> None:
    model = os.environ.get("RESEARCH_HARNESS_LIVE_ANTHROPIC_MODEL", "claude-opus-5")
    _assert_usable(AnthropicProvider(model))


@live_only
@pytest.mark.skipif(
    "RESEARCH_HARNESS_LIVE_LOCAL_MODEL" not in os.environ,
    reason="set RESEARCH_HARNESS_LIVE_LOCAL_MODEL to the model your local server serves",
)
def test_local_live_smoke() -> None:
    model = os.environ["RESEARCH_HARNESS_LIVE_LOCAL_MODEL"]
    base_url = os.environ.get("RESEARCH_HARNESS_LIVE_LOCAL_BASE_URL", "http://localhost:11434/v1")
    _assert_usable(LocalOpenAICompatibleProvider(model, base_url=base_url))

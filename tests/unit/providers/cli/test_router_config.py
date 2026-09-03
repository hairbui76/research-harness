"""`kind: local_cli` in research.yaml (spec §11)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from research_harness.providers.models.router import (
    RouterProviderConfig,
    entry_base_url,
    entry_capabilities,
)


def test_runtime_is_required_and_must_be_known() -> None:
    with pytest.raises(ValidationError, match="runtime is required"):
        RouterProviderConfig.model_validate({"name": "x", "kind": "local_cli", "model": "default"})
    with pytest.raises(ValidationError, match="unknown runtime 'nope'"):
        RouterProviderConfig.model_validate(
            {"name": "x", "kind": "local_cli", "runtime": "nope", "model": "default"}
        )


def test_base_url_and_api_key_env_are_forbidden_for_a_cli_entry() -> None:
    for field in ("base_url", "api_key_env"):
        with pytest.raises(ValidationError, match=f"{field} is not allowed"):
            RouterProviderConfig.model_validate(
                {
                    "name": "x",
                    "kind": "local_cli",
                    "runtime": "codex",
                    "model": "default",
                    field: "y",
                }
            )


def test_runtime_and_reasoning_are_forbidden_for_other_kinds() -> None:
    with pytest.raises(ValidationError, match="runtime is only for"):
        RouterProviderConfig.model_validate(
            {"name": "x", "kind": "openai", "model": "m", "runtime": "codex"}
        )


def test_a_cli_entry_needs_no_credential_and_declares_external_egress_without_spawning() -> None:
    entry = RouterProviderConfig.model_validate(
        {
            "name": "x",
            "kind": "local_cli",
            "runtime": "claude",
            "model": "opus",
            "capabilities": {"max_context_tokens": 100_000},
        }
    )
    caps = entry_capabilities(entry)
    assert caps.max_context_tokens == 100_000 and caps.egress.endpoint_host == "api.anthropic.com"
    assert entry_base_url(entry) == ""


def test_reasoning_must_be_an_effort_name_the_runtime_offers() -> None:
    with pytest.raises(ValidationError, match="low, medium, high, xhigh"):
        RouterProviderConfig.model_validate(
            {
                "name": "x",
                "kind": "local_cli",
                "runtime": "codex",
                "model": "gpt-5.5",
                "reasoning": "turbo",
            }
        )
    kept = RouterProviderConfig.model_validate(
        {"name": "x", "kind": "local_cli", "runtime": "codex", "model": "gpt-5.5"}
    )
    assert kept.reasoning is None, "no reasoning at all stays the runtime's own default"
    assert (
        RouterProviderConfig.model_validate(
            {
                "name": "x",
                "kind": "local_cli",
                "runtime": "claude",
                "model": "opus",
                "reasoning": "max",
            }
        ).reasoning
        == "max"
    )


def test_the_error_for_a_cli_field_on_another_kind_names_the_field() -> None:
    with pytest.raises(ValidationError, match="reasoning is only for kind local_cli"):
        RouterProviderConfig.model_validate(
            {"name": "x", "kind": "openai", "model": "m", "reasoning": "high"}
        )

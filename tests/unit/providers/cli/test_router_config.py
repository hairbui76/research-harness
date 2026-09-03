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

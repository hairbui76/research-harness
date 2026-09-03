"""Failure classification and redaction (CLI providers spec §15, §19)."""

from __future__ import annotations

import pytest

from research_harness.providers.cli.errors import (
    CliAuthError,
    CliRateLimitError,
    CliResponseError,
    CliTransportError,
    classify_failure,
    describe_runtime,
    redact,
)
from research_harness.providers.models.base import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTransportError,
)


def test_the_four_errors_are_the_existing_provider_errors_with_a_diagnostic() -> None:
    error = CliAuthError("x", runtime="codex", diagnostic="login_missing")
    assert isinstance(error, ProviderAuthError)
    assert error.diagnostic == "login_missing" and error.runtime == "codex"
    assert error.provider == "local_cli:codex"
    assert isinstance(
        CliRateLimitError("x", runtime="codex", diagnostic="rate_limited"), ProviderRateLimitError
    )
    assert isinstance(
        CliTransportError("x", runtime="codex", diagnostic="timeout"), ProviderTransportError
    )
    assert isinstance(
        CliResponseError("x", runtime="codex", diagnostic="refusal"), ProviderResponseError
    )


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("/home/alice/.codex/auth.json", "~/.codex/auth.json"),
        (
            "Authorization: Bearer abcdef0123456789abcdef0123456789abcdef01",
            "Authorization: Bearer <redacted>",
        ),
        ("key sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd", "key <redacted>"),
        ("mail alice.smith@example.org today", "mail <email> today"),
        ("https://x.test/a?X-Amz-Signature=abc&b=1", "https://x.test/a?<signed-query>"),
        ("token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij12", "token <redacted>"),
        ("plain words stay", "plain words stay"),
    ],
)
def test_redact_strips_credentials_paths_and_identities(raw: str, cleaned: str) -> None:
    assert redact(raw, home="/home/alice") == cleaned


def test_describe_runtime_names_runtime_model_and_version() -> None:
    assert describe_runtime("codex", "gpt-5.5", "0.150.1") == "codex/gpt-5.5 (0.150.1)"
    assert describe_runtime("codex", "default", None) == "codex/default (version unknown)"


def test_classify_failure_maps_conditions_onto_provider_errors() -> None:
    kwargs = {"runtime": "codex", "model": "default", "version": "0.150.1"}
    assert isinstance(classify_failure(os_error="ENOENT", **kwargs), CliTransportError)
    assert classify_failure(os_error="ENOENT", **kwargs).diagnostic == "executable_missing"
    assert classify_failure(timed_out=True, **kwargs).diagnostic == "timeout"
    assert classify_failure(output_limited=True, **kwargs).diagnostic == "output_limit"
    assert (
        classify_failure(
            exit_code=1, stderr_tail="error: not logged in, run codex login", **kwargs
        ).diagnostic
        == "login_missing"
    )
    assert isinstance(
        classify_failure(exit_code=1, stderr_tail="HTTP 429 rate limit exceeded", **kwargs),
        CliRateLimitError,
    )
    assert (
        classify_failure(exit_code=1, stderr_tail="unknown model 'gpt-nope'", **kwargs).diagnostic
        == "unsupported_model"
    )
    assert (
        classify_failure(
            exit_code=2, stderr_tail="error: unexpected argument '--nope'", **kwargs
        ).diagnostic
        == "invalid_invocation"
    )
    assert (
        classify_failure(exit_code=0, stderr_tail="", **kwargs).diagnostic
        == "missing_terminal_event"
    )
    assert classify_failure(exit_code=139, stderr_tail="", **kwargs).diagnostic == "crashed"
    assert (
        classify_failure(
            stream_error="model refused: cannot help", stream_code="refusal", **kwargs
        ).diagnostic
        == "refusal"
    )
    assert (
        classify_failure(
            stream_error="Not logged in · Please run /login",
            stream_code="authentication_failed",
            **kwargs,
        ).diagnostic
        == "login_missing"
    )


def test_messages_carry_identity_and_a_next_action_but_no_secret() -> None:
    error = classify_failure(
        runtime="codex",
        model="gpt-5.5",
        version="0.150.1",
        exit_code=1,
        stderr_tail=(
            "not logged in; token sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd "
            "in /home/alice/.codex"
        ),
        home="/home/alice",
    )
    assert "codex/gpt-5.5 (0.150.1)" in error.message
    assert "codex login" in error.message
    assert "sk-proj" not in error.message and "/home/alice" not in error.message

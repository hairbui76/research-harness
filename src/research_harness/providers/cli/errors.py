"""CLI failure classification and redaction (CLI providers spec §15, §19).

Runtime outcomes map onto the existing provider errors so nothing above `providers/`
learns a new exception; each carries a `diagnostic` code and the runtime id for triage.
Every message passes `redact()`: it names runtime, model, version and a next action, and
never a token, a credential path, a raw environment value, or a whole stderr transcript.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from research_harness.providers.models.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTransportError,
)

__all__ = [
    "PROVIDER_NAME_PREFIX",
    "CliAuthError",
    "CliRateLimitError",
    "CliResponseError",
    "CliTransportError",
    "DiagnosticCode",
    "classify_failure",
    "describe_runtime",
    "provider_name",
    "redact",
]

PROVIDER_NAME_PREFIX = "local_cli"

DiagnosticCode = Literal[
    "executable_missing",
    "not_executable",
    "login_missing",
    "rate_limited",
    "timeout",
    "crashed",
    "malformed_stream",
    "missing_terminal_event",
    "output_limit",
    "refusal",
    "unsupported_model",
    "invalid_invocation",
    "empty_response",
    "bounded_authority_violation",
    "bounded_mode_unsupported",
    "version_blocked",
    "cancelled",
    "protocol_error",
]


def provider_name(runtime: str) -> str:
    """`local_cli:<runtime>` — the adapter name provenance and `--provider` see."""
    return f"{PROVIDER_NAME_PREFIX}:{runtime}"


class CliAuthError(ProviderAuthError):
    """A CLI refused the request because it is not logged in (spec §15)."""

    def __init__(self, message: str, *, runtime: str, diagnostic: str) -> None:
        super().__init__(message, provider=provider_name(runtime))
        self.runtime = runtime
        self.diagnostic = diagnostic


class CliRateLimitError(ProviderRateLimitError):
    """The subscription behind a CLI is throttled or out of quota."""

    def __init__(
        self,
        message: str,
        *,
        runtime: str,
        diagnostic: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(
            message, provider=provider_name(runtime), retry_after_seconds=retry_after_seconds
        )
        self.runtime = runtime
        self.diagnostic = diagnostic


class CliTransportError(ProviderTransportError):
    """The process failed to start, timed out, or died before a completed turn."""

    def __init__(self, message: str, *, runtime: str, diagnostic: str) -> None:
        super().__init__(message, provider=provider_name(runtime))
        self.runtime = runtime
        self.diagnostic = diagnostic


class CliResponseError(ProviderResponseError):
    """The CLI answered, but not with a usable completion (refusal, bad model, bad argv)."""

    def __init__(self, message: str, *, runtime: str, diagnostic: str) -> None:
        super().__init__(message, provider=provider_name(runtime))
        self.runtime = runtime
        self.diagnostic = diagnostic


# -- redaction ---------------------------------------------------------------

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer <redacted>"),
    (re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}"), "<redacted>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "<redacted>"),
    (re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"), "<redacted>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"\?(?=[^\s]*(?:X-Amz-Signature|signature|sig|token)=)[^\s]*"), "?<signed-query>"),
    (re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/=_-]{40,}(?![A-Za-z0-9+/=])"), "<redacted>"),
)


def redact(text: str, *, home: str | None = None) -> str:
    """Strip home paths, tokens, e-mails, and signed URLs from a diagnostic string."""
    cleaned = text
    for candidate in (home, str(Path.home())):
        if candidate and candidate not in ("/", ""):
            cleaned = cleaned.replace(candidate, "~")
    for pattern, replacement in _PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def describe_runtime(runtime: str, model: str, version: str | None) -> str:
    """`codex/gpt-5.5 (0.150.1)` — the identity every message starts with."""
    return f"{runtime}/{model} ({version or 'version unknown'})"


# -- classification -----------------------------------------------------------

_AUTH = re.compile(
    r"not logged[ _-]?in|login required|please (?:sign|log)[ _-]?in|run (?:/login|`?\w+ login)"
    r"|unauthori[sz]ed|authenticat|invalid[ _-]?(?:api[ _-]?)?key|token (?:has )?expired"
    r"|session expired|\b401\b|credentials? (?:are )?(?:missing|invalid|required)",
    re.IGNORECASE,
)
_RATE = re.compile(
    r"rate[ _-]?limit|too many requests|\b429\b|quota|usage limit|over capacity|overloaded|\b503\b",
    re.IGNORECASE,
)
_MODEL = re.compile(
    r"unknown model|model not found|unsupported model|invalid model|no such model"
    # The upstream wording a Codex turn fails with when the account cannot reach the
    # requested model. Matched as the whole phrase, never a bare "does not exist", which
    # a missing file or a missing thread would also say.
    r"|does not exist or you do not have access"
    r"|not available for",
    re.IGNORECASE,
)
_INVOCATION = re.compile(
    r"unexpected argument|unknown option|unrecognized (?:option|argument)|invalid value|usage:",
    re.IGNORECASE,
)


def classify_failure(
    *,
    runtime: str,
    model: str,
    version: str | None,
    exit_code: int | None = None,
    stderr_tail: str = "",
    timed_out: bool = False,
    output_limited: bool = False,
    os_error: str | None = None,
    stream_error: str | None = None,
    stream_code: str | None = None,
    login_guidance: str | None = None,
    home: str | None = None,
) -> ProviderError:
    """Map one runtime outcome onto a provider error with a diagnostic code (spec §15).

    Structured evidence first (`os_error`, `timed_out`, `output_limited`, a stream error
    with a code), narrowly tested text patterns second, and a generic transport failure
    last. The message names the runtime, model, and version, and a safe next action.
    """
    who = describe_runtime(runtime, model, version)
    login = login_guidance or f"run `{runtime} login`"
    # Redact the whole tail, then truncate: truncating first would cut the anchor a pattern
    # needs (`/home/<user>`, `sk-proj-`) off the front of the window and let the rest of the
    # secret through (spec §19). The caller already bounds how much stderr it keeps.
    detail = redact(stderr_tail.strip(), home=home)[-400:]
    suffix = f": {detail}" if detail else ""

    if os_error is not None:
        denied = "EACCES" in os_error or "permission" in os_error.lower()
        code = "not_executable" if denied else "executable_missing"
        action = "check the file's permissions" if denied else f"install {runtime} or fix PATH"
        return CliTransportError(
            f"{who}: the executable could not be started ({redact(os_error, home=home)}); {action}",
            runtime=runtime,
            diagnostic=code,
        )
    if timed_out:
        return CliTransportError(
            f"{who}: the request timed out; raise `timeout_seconds` for this provider "
            f"or try a smaller model{suffix}",
            runtime=runtime,
            diagnostic="timeout",
        )
    if output_limited:
        return CliTransportError(
            f"{who}: the process wrote more output than the harness accepts and was stopped",
            runtime=runtime,
            diagnostic="output_limit",
        )

    evidence = f"{stream_error or ''}\n{stderr_tail}"
    if stream_code == "authentication_failed" or _AUTH.search(evidence):
        return CliAuthError(
            f"{who}: not logged in; {login}", runtime=runtime, diagnostic="login_missing"
        )
    if _RATE.search(evidence):
        return CliRateLimitError(
            f"{who}: the subscription is rate-limited or over quota; wait and retry{suffix}",
            runtime=runtime,
            diagnostic="rate_limited",
        )
    if _MODEL.search(evidence):
        return CliResponseError(
            f"{who}: the CLI does not offer this model; run `research providers scan` "
            f"for the models it lists{suffix}",
            runtime=runtime,
            diagnostic="unsupported_model",
        )
    if stream_error is not None:
        code = (
            stream_code if stream_code in ("refusal", "protocol_error", "cancelled") else "refusal"
        )
        return CliResponseError(
            f"{who}: the runtime reported an error: {redact(stream_error, home=home)}",
            runtime=runtime,
            diagnostic=code,
        )
    if _INVOCATION.search(evidence):
        return CliResponseError(
            f"{who}: the installed version rejected the harness's arguments; this version "
            f"is not compatible with the recorded definition{suffix}",
            runtime=runtime,
            diagnostic="invalid_invocation",
        )
    if exit_code == 0:
        return CliTransportError(
            f"{who}: the process exited before reporting a completed turn{suffix}",
            runtime=runtime,
            diagnostic="missing_terminal_event",
        )
    return CliTransportError(
        f"{who}: the process exited with status {exit_code}{suffix}",
        runtime=runtime,
        diagnostic="crashed",
    )

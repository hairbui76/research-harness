"""Subscription-backed local CLI providers (CLI providers spec).

Import the contract from here::

    from research_harness.providers.cli import CliRuntimeDef, RUNTIMES, get_runtime
"""

from __future__ import annotations

from research_harness.providers.cli.detection import detect, scan
from research_harness.providers.cli.errors import (
    CliAuthError,
    CliRateLimitError,
    CliResponseError,
    CliTransportError,
    provider_name,
    redact,
)
from research_harness.providers.cli.provider import (
    CliModelProvider,
    default_cli_capabilities,
)
from research_harness.providers.cli.registry import (
    RUNTIME_DEFS,
    RUNTIME_IDS,
    RUNTIMES,
    RegistryError,
    UnknownRuntimeError,
    get_runtime,
)
from research_harness.providers.cli.types import (
    DEFAULT_MODEL,
    UNKNOWN_EXTERNAL_HOST,
    CliModelView,
    CliRuntimeDef,
    CliRuntimeStatus,
    unavailable_reason,
)

__all__ = [
    "DEFAULT_MODEL",
    "RUNTIMES",
    "RUNTIME_DEFS",
    "RUNTIME_IDS",
    "UNKNOWN_EXTERNAL_HOST",
    "CliAuthError",
    "CliModelProvider",
    "CliModelView",
    "CliRateLimitError",
    "CliResponseError",
    "CliRuntimeDef",
    "CliRuntimeStatus",
    "CliTransportError",
    "RegistryError",
    "UnknownRuntimeError",
    "default_cli_capabilities",
    "detect",
    "get_runtime",
    "provider_name",
    "redact",
    "scan",
    "unavailable_reason",
]

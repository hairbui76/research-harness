"""Transports over the one capability layer: MCP first, local HTTP as the fallback.

`protocol/` holds no research rule (ADR-004, ADR-009). Both bindings read the same
:class:`~research_harness.capabilities.registry.CapabilityRegistry`, build the same
envelopes from :mod:`research_harness.protocol.dto`, and refuse the same calls, so a Claim
created on the CLI is the same object over HTTP, over MCP, and in the Web cockpit.
"""

from __future__ import annotations

from research_harness.protocol.dto import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResponse,
    ErrorBody,
    HealthReport,
    ObjectView,
    PlannedCapability,
    RunStatus,
    error_body,
)
from research_harness.protocol.http import DEFAULT_BASE_URL, HarnessHttpClient

__all__ = [
    "DEFAULT_BASE_URL",
    "CapabilityCatalog",
    "CapabilityDescriptor",
    "CapabilityRequest",
    "CapabilityResponse",
    "ErrorBody",
    "HarnessHttpClient",
    "HealthReport",
    "ObjectView",
    "PlannedCapability",
    "RunStatus",
    "error_body",
]

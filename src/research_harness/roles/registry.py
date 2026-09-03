"""The roles this runtime knows, looked up by name.

A workflow names a role, the registry returns its contract, and the contract decides what
that call may read, produce, and write. Nothing else creates a role: an unregistered name
is an error rather than an unbounded model call.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from research_harness.domain.errors import CapabilityError
from research_harness.roles.auditor import CLAIM_AUDITOR
from research_harness.roles.contracts import RoleContract
from research_harness.roles.extractor import EXTRACTOR
from research_harness.roles.skeptic import SKEPTIC
from research_harness.roles.synthesizer import SYNTHESIZER
from research_harness.roles.verifier import VERIFIER
from research_harness.roles.writer import WRITER

__all__ = ["ROLES", "get_role", "role_names"]

_CONTRACTS: tuple[RoleContract, ...] = (
    EXTRACTOR,
    VERIFIER,
    SKEPTIC,
    CLAIM_AUDITOR,
    SYNTHESIZER,
    WRITER,
)

ROLES: Mapping[str, RoleContract] = MappingProxyType(
    {contract.name: contract for contract in _CONTRACTS}
)
"""Every bounded role, keyed by the name that appears in `ModelRequest.role`."""


def get_role(name: str) -> RoleContract:
    """Return the contract for `name`, or raise `CapabilityError` if it is unknown."""
    try:
        return ROLES[name]
    except KeyError:
        known = ", ".join(role_names())
        raise CapabilityError(f"unknown role {name!r}; known roles: {known}") from None


def role_names() -> tuple[str, ...]:
    """Registered role names in declaration order."""
    return tuple(ROLES)

"""Look for a way back into canonical state, and report what it found.

This validator exists to be run, not to validate. It searches its own module namespace and
its argument for anything that would let plugin code reach the repository, the capability
context, a database connection, or a workspace path. Every name it finds is returned as a
finding, so the boundary test asserts an empty result: plugin code is handed data, and the
namespace it runs in holds nothing else (Product 32.2).
"""

from __future__ import annotations

from collections.abc import Mapping

SUSPICIOUS = (
    "repo",
    "repository",
    "workspace",
    "context",
    "ctx",
    "session",
    "connection",
    "conn",
    "engine",
    "journal",
    "handlers",
    "capability",
    "capabilities",
    "root",
    "sqlite3",
    "sqlalchemy",
)


def _reachable_names(namespace: Mapping[str, object]) -> list[str]:
    """Names in `namespace` that look like a handle on canonical state."""
    return sorted(
        name
        for name in namespace
        if any(marker in name.lower() for marker in SUSPICIOUS) and name != "SUSPICIOUS"
    )


def validate(candidate: Mapping[str, object]) -> list[dict[str, str]]:
    """Report any state handle reachable from this validator's namespace or argument."""
    findings: list[dict[str, str]] = []
    for source, names in (
        ("module globals", _reachable_names(globals())),
        ("candidate", _reachable_names(candidate)),
    ):
        findings.extend(
            {
                "field": "minimal.namespace_probe",
                "message": f"{source} exposes {name!r} to plugin code",
                "severity": "error",
            }
            for name in names
        )
    return findings

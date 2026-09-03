"""Reject a traffic-unit answer the project taxonomy does not contain.

A plugin validator is a pure function over a plain candidate dict. It has no repository,
no workspace path, and no capability handle; it reads the data it is given and returns
findings. Findings are plain mappings so this module needs no harness import at all.
"""

from __future__ import annotations

from collections.abc import Mapping

FIELD = "minimal.traffic_unit"
ALLOWED = ("packet", "flow", "session")


def validate(candidate: Mapping[str, object]) -> list[dict[str, str]]:
    """Return one finding per traffic-unit value outside the project taxonomy."""
    if candidate.get("field") != FIELD:
        return []
    value = candidate.get("value")
    if value is None or value == "":
        return [
            {
                "field": FIELD,
                "message": "no traffic unit was recorded for this candidate",
                "severity": "warning",
            }
        ]
    values = list(value) if isinstance(value, list | tuple) else [value]
    findings: list[dict[str, str]] = []
    for item in values:
        if item not in ALLOWED:
            findings.append(
                {
                    "field": FIELD,
                    "message": (
                        f"{item!r} is not a project traffic unit; the accepted taxonomy is "
                        f"{', '.join(ALLOWED)}"
                    ),
                    "severity": "error",
                }
            )
    return findings

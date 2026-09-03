"""Importing one package must not depend on which package was imported first.

`capabilities/` reaches into `discovery/`, `manuscript/`, and `evidence/` for their
handlers, and each of those reaches back into `capabilities/` to write. That is a cycle by
construction, and the convention that keeps it harmless is that every such reach is a
*deferred* import inside the function that needs it (conventions.md; the module docstrings
in `capabilities/extra_handlers.py` and `claims/service.py` say so).

A cycle broken only by import order is invisible in a test suite - `pytest` imports
`research_harness.claims` long before anything imports `research_harness.discovery`, so the
partially-initialized module never shows up. Each check below is therefore a *fresh
interpreter* importing exactly one module: that is the only way the failure appears.

The registry check is the one with teeth. `build_default_registry` records an unimportable
section as planned rather than raising, so a cycle here does not crash - it silently
un-registers `corpus.search`, and a host is told the capability "is not built yet".
"""

from __future__ import annotations

import subprocess
import sys

import pytest

#: One entry point per package that participates in the capability cycle.
ENTRY_POINTS: tuple[str, ...] = (
    "research_harness.capabilities.registry",
    "research_harness.claims.service",
    "research_harness.discovery",
    "research_harness.evidence.service",
    "research_harness.manuscript.attach",
    "research_harness.protocol.dto",
    "research_harness.server.app",
)


def run(source: str) -> subprocess.CompletedProcess[str]:
    """Run ``source`` in a fresh interpreter, so no earlier import can mask a cycle."""
    return subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize("module", ENTRY_POINTS)
def test_each_package_imports_on_its_own(module: str) -> None:
    result = run(f"import {module}")
    assert result.returncode == 0, (
        f"importing {module} first fails; some module-scope import in the capability cycle "
        f"needs to be deferred into the function that uses it:\n{result.stderr}"
    )


def test_the_registry_is_complete_however_it_was_reached() -> None:
    """A cycle would show up as a *planned* capability, not as a crash."""
    source = (
        "from research_harness.capabilities.registry import build_default_registry\n"
        "registry = build_default_registry()\n"
        "print(','.join(item.name for item in registry.planned()))\n"
    )
    result = run(source)

    assert result.returncode == 0, result.stderr
    planned = {name for name in result.stdout.strip().split(",") if name}
    assert planned == {"project.init", "synthesis.find_pattern"}, (
        "a capability section failed to import and was silently recorded as planned; the "
        "reason is in `describe().planned`"
    )

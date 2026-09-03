"""`graph/` is a projection: it may not reach providers, transports, or the mutation layer.

`docs/architecture/conventions.md` states the rule; importing the package in a fresh
interpreter is the only way to catch a violation that import order would hide from a suite
which always imports `capabilities` first.
"""

from __future__ import annotations

import json
import subprocess
import sys

FORBIDDEN = frozenset({"providers", "cli", "server", "protocol", "capabilities", "roles"})

_PROBE = """
import importlib
import json
import sys

before = set(sys.modules)
importlib.import_module("research_harness.graph")
loaded = {
    module.split(".")[1]
    for module in set(sys.modules) - before
    if module.startswith("research_harness.") and module.count(".") >= 1
}
print(json.dumps(sorted(loaded)))
"""


def test_importing_the_graph_pulls_in_no_forbidden_package() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=True
    )
    packages = set(json.loads(result.stdout))

    assert not packages & FORBIDDEN, sorted(packages & FORBIDDEN)
    assert {"domain", "graph", "projection", "workspace"} <= packages

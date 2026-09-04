"""The multi-project local app: registry, lifecycle, runtimes, pickers, and app auth.

Application state (which folders the researcher has opened) lives here; scientific state
never does. Nothing in this package widens a principal's authority: every workspace
operation still goes through `capabilities/` and the repositories.
"""

from __future__ import annotations

from research_harness.local_app.runtime import WorkspaceRuntime

__all__ = ["WorkspaceRuntime"]

"""The multi-project local app: registry, lifecycle, runtimes, pickers, and app auth.

Application state (which folders the researcher has opened) lives here; scientific state
never does. Nothing in this package widens a principal's authority: every workspace
operation still goes through `capabilities/` and the repositories.
"""

from __future__ import annotations

from research_harness.local_app.manager import ProjectManager, default_reveal, safe_folder_name
from research_harness.local_app.models import (
    ProjectActiveRunsError,
    ProjectAvailability,
    ProjectLifecycleError,
    ProjectNeedsInitializationError,
    ProjectNotFoundError,
    ProjectRecord,
    ProjectView,
    RegistryDocument,
    RuntimeStatus,
)
from research_harness.local_app.paths import (
    ProjectPathError,
    app_data_dir,
    assert_beneath,
    canonical_directory,
    registry_path,
)
from research_harness.local_app.registry import (
    DuplicateProjectError,
    ProjectRegistry,
    ProjectRegistryError,
)
from research_harness.local_app.runtime import (
    LEGACY_PROJECT_ID,
    ProjectRuntimePool,
    WorkspaceRuntime,
)

__all__ = [
    "LEGACY_PROJECT_ID",
    "DuplicateProjectError",
    "ProjectActiveRunsError",
    "ProjectAvailability",
    "ProjectLifecycleError",
    "ProjectManager",
    "ProjectNeedsInitializationError",
    "ProjectNotFoundError",
    "ProjectPathError",
    "ProjectRecord",
    "ProjectRegistry",
    "ProjectRegistryError",
    "ProjectRuntimePool",
    "ProjectView",
    "RegistryDocument",
    "RuntimeStatus",
    "WorkspaceRuntime",
    "app_data_dir",
    "assert_beneath",
    "canonical_directory",
    "default_reveal",
    "registry_path",
    "safe_folder_name",
]

"""The app's only OS-specific rules: where its data lives, and what counts as inside a root.

Every other module takes an already-canonical :class:`~pathlib.Path`, so platform branches
and containment proofs exist in exactly one place.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path

from research_harness.domain.errors import ResearchHarnessError

__all__ = [
    "APP_DIRECTORY_NAMES",
    "ProjectPathError",
    "app_data_dir",
    "assert_beneath",
    "canonical_directory",
    "registry_path",
]

APP_DIRECTORY_NAMES = {"Windows": "ResearchHarness", "Linux": "research-harness"}
"""Per-platform application directory name; Windows uses the product name, Linux the slug."""

REGISTRY_FILENAME = "projects.json"


class ProjectPathError(ResearchHarnessError):
    """A path is unusable as an application data location or as a project-relative target."""


def app_data_dir(
    *,
    system: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Where the app keeps its registry and token: `%LOCALAPPDATA%` or the XDG data home.

    The platform, environment, and home directory are injectable so the rule can be tested
    for both supported systems from either of them.
    """
    values: Mapping[str, str] = os.environ if env is None else env
    platform_name = platform.system() if system is None else system
    if platform_name == "Windows":
        base = values.get("LOCALAPPDATA")
        if not base:
            raise ProjectPathError("LOCALAPPDATA is not set; cannot locate the app data folder")
        return Path(base) / APP_DIRECTORY_NAMES["Windows"]
    if platform_name == "Linux":
        base = values.get("XDG_DATA_HOME")
        if base:
            return Path(base) / APP_DIRECTORY_NAMES["Linux"]
        return (home or Path.home()) / ".local" / "share" / APP_DIRECTORY_NAMES["Linux"]
    raise ProjectPathError(f"research app supports Windows and Linux, not {platform_name}")


def registry_path(data_dir: Path) -> Path:
    """The registry document inside an app data directory."""
    return Path(data_dir) / REGISTRY_FILENAME


def canonical_directory(path: Path | str) -> Path:
    """Resolve `path` to an existing directory, following symlinks and `..` first.

    Two spellings of the same folder resolve to one value, which is what makes the registry's
    deduplication by canonical root correct.
    """
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ProjectPathError(f"cannot resolve {candidate}: {exc}") from exc
    if not resolved.is_dir():
        raise ProjectPathError(f"not a directory: {resolved}")
    return resolved


def assert_beneath(root: Path | str, candidate: Path | str) -> Path:
    """Prove that `candidate` resolves to an existing path inside `root`, and return it.

    Resolution happens before the comparison, so `..`, an absolute path, and a symlink
    pointing outside the workspace are all rejected rather than followed.
    """
    resolved_root = canonical_directory(root)
    target = Path(candidate).expanduser()
    try:
        resolved = target.resolve(strict=True)
    except OSError as exc:
        raise ProjectPathError(f"cannot resolve {target}: {exc}") from exc
    if not resolved.is_relative_to(resolved_root):
        raise ProjectPathError(f"path escapes project root: {target}")
    return resolved

"""Research Harness: local-first, provider-neutral research workstation core."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("research-harness")
except PackageNotFoundError:  # pragma: no cover - only when running from an unbuilt tree
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]

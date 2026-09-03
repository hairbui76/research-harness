"""The environment a bounded CLI process receives (spec §12).

Allow-list first — enough to find the executable, load the user's existing CLI login, and
operate on the host — then a deny-list that always wins: provider API-key variables and
unrelated cloud credentials are removed so a subscription login never silently becomes
metered API-key access, and nothing unrelated to the run rides along.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from research_harness.providers.cli.types import CliRuntimeDef

__all__ = ["ALWAYS_DROP", "BASE_KEEP", "FIXED_ENV", "bounded_environment"]

BASE_KEEP: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LANGUAGE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_RUNTIME_DIR",
        "SYSTEMROOT",
        "SystemRoot",
        "COMSPEC",
        "ComSpec",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "ProgramData",
        "PATHEXT",
        "WINDIR",
        "windir",
    }
)

ALWAYS_DROP: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r".*_API_KEY$",
        r".*_TOKEN$",
        r".*_SECRET.*",
        r"^AWS_.*",
        r"^AZURE_.*",
        r"^OPENAI_.*",
        r"^ANTHROPIC_.*",
        r"^GEMINI_.*",
        r"^GOOGLE_APPLICATION_CREDENTIALS$",
        r"^CODEX_API_KEY$",
        r"^CURSOR_API_KEY$",
        r"^DEEPSEEK_API_KEY$",
        r"^OPENROUTER_API_KEY$",
    )
)

FIXED_ENV: Mapping[str, str] = {"NO_COLOR": "1", "TERM": "dumb", "RESEARCH_HARNESS_BOUNDED": "1"}


def _dropped(key: str) -> bool:
    return any(pattern.match(key) for pattern in ALWAYS_DROP)


def bounded_environment(
    definition: CliRuntimeDef, base: Mapping[str, str], *, executable: Path | None = None
) -> dict[str, str]:
    """Allow-list, then deny-list (which wins), then the fixed and per-runtime values.

    `executable` leads `PATH` only when it is absolute. A definition's `executable` is a
    bare name, and prepending its parent would put `.` at the head of the search path of
    the very process this module exists to bound; a relative path is therefore ignored
    rather than rejected, leaving `PATH` exactly as filtered.
    """
    keep = BASE_KEEP | set(definition.env_keep)
    env = {
        key: value
        for key, value in base.items()
        if (key in keep or key.startswith("LC_"))
        and key not in definition.env_drop
        and not _dropped(key)
    }
    env.update(FIXED_ENV)
    env.update({key: value for key, value in definition.env_set.items() if not _dropped(key)})
    if executable is not None and executable.is_absolute():
        parent = str(executable.parent)
        parts = [part for part in env.get("PATH", "").split(os.pathsep) if part and part != parent]
        env["PATH"] = os.pathsep.join([parent, *parts])
    return env

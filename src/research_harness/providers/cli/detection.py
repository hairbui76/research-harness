"""Detection: is the CLI here, which version, logged in, bounded, which models (spec §10).

A scan is fresh by default, bounded per probe, fault-isolated per runtime, ordered like
the registry, and free of secrets. It edits nothing and never sends a model request. A
short in-memory cache keeps a settings screen responsive; an explicit rescan bypasses it,
and nothing here is canonical state.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from research_harness.providers.cli.environment import bounded_environment
from research_harness.providers.cli.errors import redact
from research_harness.providers.cli.process import run_probe
from research_harness.providers.cli.types import (
    DEFAULT_MODEL,
    AuthStatus,
    BoundedMode,
    CliModelOption,
    CliModelView,
    CliRuntimeDef,
    CliRuntimeStatus,
    Compatibility,
    ModelSource,
    ProbeOutcome,
)

__all__ = [
    "DEFAULT_CACHE",
    "DEFAULT_MODEL_OPTION",
    "ProbeRunner",
    "ScanCache",
    "compatibility_of",
    "detect",
    "resolve_executable",
    "scan",
]

ProbeRunner = Callable[..., ProbeOutcome]
_Probe = Callable[[Sequence[str], float], ProbeOutcome]
VERSION_PROBE_TIMEOUT = 3.0
UNKNOWN_AUTH_GUIDANCE = "authentication is verified on the first request; {login} if it fails"


class _DefaultModelOption:
    """`default`: no `--model` flag; the CLI's own configured model answers."""

    id = DEFAULT_MODEL
    label = "Default (CLI configuration)"

    def as_option(self) -> CliModelOption:
        return CliModelOption(id=self.id, label=self.label)

    def as_view(self) -> CliModelView:
        return CliModelView(id=self.id, label=self.label)


DEFAULT_MODEL_OPTION = _DefaultModelOption()


# -- executables ---------------------------------------------------------------


def _candidates(name: str, env: Mapping[str, str], platform: str) -> list[str]:
    if platform == "win32":
        exts = [ext for ext in env.get("PATHEXT", ".EXE;.CMD;.BAT").split(";") if ext]
        return [name + ext for ext in exts] + [name]
    return [name]


def resolve_executable(
    definition: CliRuntimeDef, env: Mapping[str, str], *, platform: str = sys.platform
) -> Path | None:
    """The first executable file on the effective PATH, trying fallbacks in order."""
    directories = [part for part in env.get("PATH", "").split(os.pathsep) if part]
    for name in (definition.executable, *definition.fallback_executables):
        for directory in directories:
            for candidate in _candidates(name, env, platform):
                path = Path(directory) / candidate
                if not path.is_file():
                    continue
                if platform == "win32" or os.access(path, os.X_OK):
                    return path
    return None


def _display_path(path: Path, env: Mapping[str, str]) -> str:
    home = env.get("HOME") or env.get("USERPROFILE")
    text = str(path)
    if home and text.startswith(home):
        return "~" + text[len(home) :]
    return redact(text)


# -- versions ------------------------------------------------------------------


def _version_tuple(version: str) -> tuple[int, ...]:
    digits: list[int] = []
    for part in version.split("-")[0].split("+")[0].lstrip("v").split("."):
        if not part.isdigit():
            break
        digits.append(int(part))
    return tuple(digits)


def compatibility_of(definition: CliRuntimeDef, version: str | None) -> Compatibility:
    """`verified` with fixtures, `blocked` when known bad or below the floor, else `warning`."""
    if version is None:
        return "unknown"
    if version in definition.blocked_versions:
        return "blocked"
    minimum = definition.minimum_version
    if minimum and _version_tuple(version) < _version_tuple(minimum):
        return "blocked"
    if version in definition.verified_versions:
        return "verified"
    return "warning"


# -- one runtime ---------------------------------------------------------------


def detect(
    definition: CliRuntimeDef,
    *,
    env: Mapping[str, str] | None = None,
    runner: ProbeRunner = run_probe,
    platform: str = sys.platform,
    now: datetime | None = None,
) -> CliRuntimeStatus:
    """Probe one runtime: executable, version, then auth, help, and models (spec §10)."""
    base: Mapping[str, str] = os.environ if env is None else env
    home = base.get("HOME")
    scanned_at = now or datetime.now(UTC)
    diagnostics: list[str] = []
    fallback = (DEFAULT_MODEL_OPTION.as_option(), *definition.fallback_models)

    def status(**fields: object) -> CliRuntimeStatus:
        values: dict[str, object] = {
            "runtime": definition.id,
            "name": definition.name,
            "available": False,
            "executable": None,
            "version": None,
            "auth_status": "unknown",
            "auth_guidance": UNKNOWN_AUTH_GUIDANCE.format(login=definition.login_guidance),
            "bounded_mode": "unknown",
            "compatibility": "unknown",
            "models": tuple(_view(item) for item in fallback),
            "model_source": "fallback",
            "reasoning_choices": definition.reasoning_choices,
            "egress_kind": definition.egress,
            "egress_host": definition.egress_host,
            "diagnostics": tuple(diagnostics),
            "scanned_at": scanned_at,
        }
        values.update(fields)
        return CliRuntimeStatus.model_validate(values)

    executable = resolve_executable(definition, base, platform=platform)
    if executable is None:
        diagnostics.append(
            f"{definition.id} is not installed: no {definition.executable!r} on PATH"
        )
        return status()

    child_env = bounded_environment(definition, base, executable=executable)
    cwd = Path(tempfile.gettempdir())

    def probe(args: Sequence[str], timeout: float) -> ProbeOutcome:
        return runner((str(executable), *args), env=child_env, timeout=timeout, cwd=cwd)

    outcome = probe(definition.version_probe.args, definition.version_probe.timeout_seconds)
    if not outcome.started:
        started = redact(outcome.os_error or "", home=home)
        diagnostics.append(f"{definition.id} could not be started: {started}")
        return status(executable=_display_path(executable, base))
    version: str | None = None
    if outcome.timed_out or outcome.exit_code != 0:
        # Redact the whole text, then truncate: truncating first would cut the anchor a
        # pattern needs off the front of the window and let the rest through (spec §19).
        detail = redact(outcome.text.strip(), home=home)[:200]
        diagnostics.append(
            f"{definition.id} rejected {' '.join(definition.version_probe.args)} "
            f"(exit {outcome.exit_code}); the version is unknown: {detail}"
        )
    else:
        version = definition.parse_version(outcome)

    auth, guidance = _auth(definition, probe, home)
    bounded = _bounded(definition, probe, diagnostics)
    models, source = _models(definition, probe, fallback)
    return status(
        available=True,
        executable=_display_path(executable, base),
        version=version,
        auth_status=auth,
        auth_guidance=guidance,
        bounded_mode=bounded,
        compatibility=compatibility_of(definition, version),
        models=tuple(_view(item) for item in models),
        model_source=source,
    )


def _auth(definition: CliRuntimeDef, probe: _Probe, home: str | None) -> tuple[AuthStatus, str]:
    if definition.auth_probe is None or definition.classify_auth is None:
        return "unknown", UNKNOWN_AUTH_GUIDANCE.format(login=definition.login_guidance)
    outcome = probe(definition.auth_probe.args, definition.auth_probe.timeout_seconds)
    if not outcome.started or outcome.timed_out:
        return "unknown", UNKNOWN_AUTH_GUIDANCE.format(login=definition.login_guidance)
    verdict, guidance = definition.classify_auth(outcome)
    return verdict, redact(guidance, home=home)


def _bounded(definition: CliRuntimeDef, probe: _Probe, diagnostics: list[str]) -> BoundedMode:
    posture = definition.posture
    if posture.kind == "none" or posture.help_probe is None:
        # A scan must say why a runtime is not routable, not only that it is not.
        diagnostics.append(f"{definition.id}: {posture.note or 'no bounded mode is documented'}")
        return "unsupported"
    outcome = probe(posture.help_probe.args, posture.help_probe.timeout_seconds)
    # No text at all is not evidence about the flags: the probe did not answer.
    if not outcome.started or outcome.timed_out or not outcome.text.strip():
        diagnostics.append(
            f"{definition.id}: the help probe did not answer, so the bounded mode is unproven"
        )
        return "unknown"
    missing = [flag for flag in posture.required_help_flags if flag not in outcome.text]
    if missing:
        diagnostics.append(
            f"{definition.id}: this version does not offer {', '.join(missing)}, "
            f"which the bounded mode needs"
        )
        return "unsupported"
    return "safe"


def _models(
    definition: CliRuntimeDef,
    probe: _Probe,
    fallback: tuple[CliModelOption, ...],
) -> tuple[tuple[CliModelOption, ...], ModelSource]:
    if definition.model_probe is None or definition.parse_models is None:
        return fallback, "fallback"
    outcome = probe(definition.model_probe.args, definition.model_probe.timeout_seconds)
    answered = outcome.started and not outcome.timed_out and outcome.exit_code == 0
    live = definition.parse_models(outcome) if answered else None
    if not live:
        return fallback, "fallback"
    seen = {DEFAULT_MODEL}
    ordered = [DEFAULT_MODEL_OPTION.as_option()]
    for item in live:
        if item.id not in seen:
            seen.add(item.id)
            ordered.append(item)
    return tuple(ordered), "live"


def _view(option: CliModelOption) -> CliModelView:
    return CliModelView(
        id=option.id,
        label=option.label,
        reasoning=option.reasoning,
        context_tokens=option.context_tokens,
    )


# -- the scan ------------------------------------------------------------------


class ScanCache:
    """Recent scan results, keyed by runtime id and PATH; never canonical state."""

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[tuple[str, str], tuple[float, CliRuntimeStatus]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> CliRuntimeStatus | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or time.monotonic() - entry[0] > self._ttl:
                return None
            return entry[1]

    def put(self, key: tuple[str, str], value: CliRuntimeStatus) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


DEFAULT_CACHE = ScanCache()


def scan(
    definitions: Sequence[CliRuntimeDef] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    runner: ProbeRunner = run_probe,
    fresh: bool = False,
    max_workers: int = 4,
    cache: ScanCache | None = None,
    now: datetime | None = None,
) -> tuple[CliRuntimeStatus, ...]:
    """Detect every definition with bounded concurrency; results in the order given."""
    from research_harness.providers.cli.registry import RUNTIME_DEFS

    targets = tuple(RUNTIME_DEFS if definitions is None else definitions)
    base: Mapping[str, str] = os.environ if env is None else env
    home = base.get("HOME")
    store = DEFAULT_CACHE if cache is None else cache
    path_key = base.get("PATH", "")

    def one(definition: CliRuntimeDef) -> CliRuntimeStatus:
        key = (definition.id, path_key)
        if not fresh:
            cached = store.get(key)
            if cached is not None:
                return cached
        try:
            result = detect(definition, env=base, runner=runner, now=now)
        except Exception as exc:  # fault isolation: one broken CLI cannot empty the catalog
            failed = f"detection failed: {type(exc).__name__}: {redact(str(exc), home=home)}"
            result = CliRuntimeStatus(
                runtime=definition.id,
                name=definition.name,
                available=False,
                executable=None,
                version=None,
                auth_status="unknown",
                auth_guidance=UNKNOWN_AUTH_GUIDANCE.format(login=definition.login_guidance),
                bounded_mode="unknown",
                compatibility="unknown",
                models=(DEFAULT_MODEL_OPTION.as_view(),),
                model_source="fallback",
                reasoning_choices=definition.reasoning_choices,
                egress_kind=definition.egress,
                egress_host=definition.egress_host,
                diagnostics=(failed,),
                scanned_at=now or datetime.now(UTC),
            )
        store.put(key, result)
        return result

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(targets) or 1))) as pool:
        return tuple(pool.map(one, targets))

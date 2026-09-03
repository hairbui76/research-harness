"""Disposable provider traces under `.research/traces/`, optionally redacted.

**A trace has no scientific authority.** It records what a provider was asked and what it
answered so a run can be debugged; the accepted record lives in canonical files and the
semantic event log (Product SS19.3). Deleting the whole tree loses nothing scientific,
which is exactly why `.research/` is git-ignored and rebuildable (ADR-001, ADR-006).

Because a trace may contain source text, two controls sit on it (Product SS34):

* `EgressPolicy.redact_traces` replaces source-text fields with `sha256:<digest>` plus the
  original length *as the trace is written*, so the plaintext never reaches the disk;
* `EgressPolicy.trace_retention_days` bounds how long traces are kept, and `purge()`
  enforces it on demand.

Every write is atomic and confined to `.research/traces/`: the kind and fingerprint that
compose a filename are validated, and the resolved path is checked against the traces root
before anything is written.

:class:`TracingRouter` lives here rather than in `cli/`, because *which backend answers* and
*where the disposable record of the call goes* is one decision and every transport has to
make it. It used to be a CLI-only wrapper, so a run driven over HTTP or MCP left no trace at
all (the daemon and the MCP bridge build their own router); :func:`traced` is now what
`cli/providers.py` and `capabilities/extra_handlers.py` both call.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from research_harness.domain.errors import WorkspaceError
from research_harness.privacy.policy import EgressPolicy
from research_harness.providers.models.base import ModelRequest, ModelResponse, TraceSink
from research_harness.providers.models.router import ModelRouter
from research_harness.workspace.atomic import atomic_write_text

if TYPE_CHECKING:  # pragma: no cover - typing only; the helper takes any open workspace
    from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "REDACTED_FIELDS",
    "TRACES_DIRNAME",
    "PurgeResult",
    "TraceRecord",
    "TraceWriter",
    "TracingRouter",
    "redact_payload",
    "sink_of",
    "trace_writer_for",
    "traced",
]

logger = logging.getLogger(__name__)

TRACES_DIRNAME = "traces"

REDACTED_FIELDS = frozenset({"content", "exact_text", "quoted_support", "raw_text"})
"""Keys whose string values are source text wherever they appear, at any depth: the
`content` of an `InputEnvelope` (`inputs[*].content`), the `exact_text` of an evidence
span, the `quoted_support` a verifier quotes back out of the span, and the `raw_text` a
model answered with.

A role that quotes the source into a *new* field name has to be added here; a redacted
trace is only as honest as this list, which is why the role schemas keep quoted text in
named fields rather than in free prose."""

_DAY_FORMAT = "%Y-%m-%d"
_DAY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_FINGERPRINT_CHARS = 8


@dataclass(frozen=True, slots=True)
class TraceRecord:
    """One trace file on disk: where it is, what it was for, and how big it is."""

    path: Path
    day: str
    kind: str
    fingerprint: str
    size_bytes: int

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True, slots=True)
class PurgeResult:
    """What a purge removed; `days` counts trace directories that became empty."""

    files: int
    days: int
    freed_bytes: int

    @property
    def removed_anything(self) -> bool:
        return self.files > 0 or self.days > 0


class TraceWriter:
    """Writes, lists, and purges the disposable traces of one workspace.

    `research_dir` is the workspace's `.research/` directory; traces live in the `traces/`
    subdirectory of it and nowhere else.
    """

    def __init__(self, research_dir: Path | str, policy: EgressPolicy | None = None) -> None:
        self._research_dir = Path(research_dir)
        self._policy = policy if policy is not None else EgressPolicy()

    @property
    def policy(self) -> EgressPolicy:
        return self._policy

    @property
    def traces_dir(self) -> Path:
        """`.research/traces/` — the only directory this writer ever touches."""
        return self._research_dir / TRACES_DIRNAME

    # -- writing -------------------------------------------------------------

    def record(
        self,
        kind: str,
        *,
        provider: str,
        model: str,
        request_fingerprint: str,
        payload: Mapping[str, Any],
        recorded_at: datetime | None = None,
    ) -> Path:
        """Write one trace and return its path.

        The file is `traces/<yyyy-mm-dd>/<kind>-<first 8 of the fingerprint>.json`, so the
        same request recorded twice in a day lands on the same disposable file instead of
        accumulating duplicates. `payload` is the caller's own structure (request,
        response, timings); it is redacted first when the policy says so.
        """
        moment = recorded_at or datetime.now(UTC)
        day = moment.strftime(_DAY_FORMAT)
        safe_kind = _segment(kind, "trace kind")
        stub = _fingerprint_stub(request_fingerprint)
        redact = self._policy.redact_traces
        document: dict[str, Any] = {
            "kind": safe_kind,
            "provider": provider,
            "model": model,
            "request_fingerprint": request_fingerprint,
            "recorded_at": moment.isoformat(),
            "redacted": redact,
            "authority": "none: traces are disposable diagnostics, not scientific state",
            "payload": redact_payload(payload) if redact else _plain(payload),
        }
        path = self._checked(self.traces_dir / day / f"{safe_kind}-{stub}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(document, indent=2, sort_keys=True, default=str) + "\n")
        return path

    # -- reading -------------------------------------------------------------

    def list_traces(self, *, day: str | None = None) -> list[TraceRecord]:
        """Every trace on disk, oldest day first, then by filename."""
        root = self.traces_dir
        if not root.is_dir():
            return []
        records: list[TraceRecord] = []
        for directory in sorted(p for p in root.iterdir() if p.is_dir()):
            if not _DAY_PATTERN.match(directory.name):
                continue
            if day is not None and directory.name != day:
                continue
            for path in sorted(directory.glob("*.json")):
                records.append(_record_for(path, directory.name))
        return records

    def days(self) -> list[str]:
        """Trace days present on disk, oldest first."""
        root = self.traces_dir
        if not root.is_dir():
            return []
        return sorted(p.name for p in root.iterdir() if p.is_dir() and _DAY_PATTERN.match(p.name))

    # -- purging -------------------------------------------------------------

    def purge(
        self,
        *,
        older_than_days: int | None = None,
        all_traces: bool = False,
        now: datetime | None = None,
    ) -> PurgeResult:
        """Delete traces: everything (`all_traces`), or every day outside the retention window.

        The window is inclusive of today, so `older_than_days=3` keeps three days of traces
        and removes everything at least three days old. With neither argument the policy's
        `trace_retention_days` is used; when that is `null` too, nothing is removed and the
        caller is told so by an empty result.
        """
        root = self.traces_dir
        if not root.is_dir():
            return PurgeResult(files=0, days=0, freed_bytes=0)
        cutoff: str | None = None
        if not all_traces:
            window = older_than_days
            if window is None:
                window = self._policy.trace_retention_days
            if window is None:
                return PurgeResult(files=0, days=0, freed_bytes=0)
            moment = now or datetime.now(UTC)
            cutoff = (moment - timedelta(days=window)).strftime(_DAY_FORMAT)

        files = 0
        days = 0
        freed = 0
        for directory in sorted(p for p in root.iterdir() if p.is_dir()):
            if not _DAY_PATTERN.match(directory.name):
                continue
            if cutoff is not None and directory.name > cutoff:
                continue
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    freed += path.stat().st_size
                    path.unlink()
                    files += 1
            _remove_empty(directory)
            days += 1
        return PurgeResult(files=files, days=days, freed_bytes=freed)

    # -- helpers -------------------------------------------------------------

    def _checked(self, path: Path) -> Path:
        """Refuse any path that would escape `.research/traces/`."""
        root = self.traces_dir
        try:
            candidate = path.resolve()
            base = root.resolve()
        except OSError:  # pragma: no cover - unresolvable paths are refused below
            candidate, base = path, root
        if candidate != base and base not in candidate.parents:
            raise WorkspaceError(f"a trace may not be written outside {root}: {path}")
        return path

    def __repr__(self) -> str:
        return f"TraceWriter({str(self.traces_dir)!r}, redact={self._policy.redact_traces})"


# -- redaction ---------------------------------------------------------------


def redact_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Copy ``payload`` with every source-text field replaced by a digest and a length.

    A redacted string becomes `sha256:<hex>` and gains a sibling `<field>_length`, so a
    trace stays comparable (the same text hashes the same) and stays honest about how much
    text there was, while the text itself is gone.
    """
    redacted = _redact(dict(payload))
    if not isinstance(redacted, dict):  # pragma: no cover - a mapping stays a mapping
        raise TypeError("a trace payload must be a mapping")
    return redacted


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in REDACTED_FIELDS and isinstance(item, str):
                out[key] = _digest(item)
                out[f"{key}_length"] = len(item)
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, str | bytes):
        return value
    if isinstance(value, Sequence):
        return [_redact(item) for item in value]
    return value


def _plain(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A shallow copy, so the caller's mapping cannot change under the writer."""
    return dict(payload)


def _digest(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


# -- path safety -------------------------------------------------------------


def _segment(value: str, label: str) -> str:
    cleaned = value.strip()
    if not _SEGMENT.match(cleaned):
        raise WorkspaceError(
            f"unsafe {label} {value!r}: use letters, digits, dot, dash or underscore"
        )
    return cleaned


def _fingerprint_stub(fingerprint: str) -> str:
    """The first eight hex characters of a fingerprint, or a digest of whatever was given."""
    cleaned = fingerprint.strip().lower()
    if re.fullmatch(r"[0-9a-f]{8,}", cleaned):
        return cleaned[:_FINGERPRINT_CHARS]
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:_FINGERPRINT_CHARS]


def _record_for(path: Path, day: str) -> TraceRecord:
    stem = path.stem
    kind, _, fingerprint = stem.rpartition("-")
    return TraceRecord(
        path=path,
        day=day,
        kind=kind or stem,
        fingerprint=fingerprint,
        size_bytes=path.stat().st_size,
    )


def _remove_empty(directory: Path) -> None:
    try:
        directory.rmdir()
    except OSError:  # pragma: no cover - a non-empty day directory is simply kept
        logger.debug("trace directory %s not empty after purge", directory)


# -- routing that records itself ---------------------------------------------


class TracingRouter(ModelRouter):
    """A router that records every completion it routes, unless the caller names a sink.

    Routing and tracing are one decision - which backend, and where the disposable record
    of the call goes - so the sink rides on the router rather than on each of the dozen
    `provider.complete(...)` call sites in `workflows/`, `evidence/`, `claims/`, and
    `manuscript/`. A trace has no scientific authority and a failure to write one never
    fails the call: `ModelProvider._trace` swallows the error.
    """

    def __init__(self, router: ModelRouter, sink: TraceSink) -> None:
        super().__init__(router.entries, policy=router.policy)
        self._sink = sink

    @property
    def sink(self) -> TraceSink:
        """Where this router's completions are recorded."""
        return self._sink

    def with_policy(self, policy: EgressPolicy | None) -> ModelRouter:
        """The same entries and sink under a different policy (used when narrowing)."""
        return TracingRouter(ModelRouter(self.entries, policy=policy), self._sink)

    def complete[T: BaseModel](
        self, request: ModelRequest[T], *, trace: TraceSink | None = None
    ) -> ModelResponse[T]:
        """Route the request and trace it, honouring a sink the caller passed explicitly."""
        return super().complete(request, trace=self._sink if trace is None else trace)


def trace_writer_for(repo: WorkspaceRepository) -> TraceWriter:
    """The workspace's trace sink: `.research/traces/` under the project's privacy policy."""
    from research_harness.privacy.policy import load_policy

    return TraceWriter(repo.layout.research_dir, load_policy(repo))


def traced(router: ModelRouter, repo: WorkspaceRepository) -> TracingRouter:
    """`router`, recording every completion into this workspace's `.research/traces/`."""
    return TracingRouter(router, trace_writer_for(repo))


def sink_of(client: object) -> TraceSink | None:
    """The trace sink a model client carries, or `None` when it records nothing.

    Cross-verification pulls individual providers out of a router and calls them directly,
    so the router's own `complete` - the thing that attaches the sink - is bypassed. This
    is how the caller recovers the sink and forwards it as `trace=`.
    """
    return client.sink if isinstance(client, TracingRouter) else None

"""The Git-visible semantic event log, and the consistency check that makes it trustworthy.

Product 19.3: `events/research.jsonl` records *what changed*, never how a model was asked.
Product 8.2 and Product 42 K: an event and its canonical mutation are one unit, and if the
two disagree the workspace is inconsistent and must fail closed.

Both properties are structural rather than best-effort:

* the event is appended as an intent inside the *same* journal transaction as the canonical
  files it describes, so "mutation and event both persist or both fail" holds by
  construction — there is no code path that writes one without the other;
* every event carries an `objects` mapping holding the SHA-256 of each written object's
  canonical YAML, so :func:`verify_consistency` can compare the log's account of the
  workspace against the workspace itself.

The event log stays an audit companion: nothing here replays events to rebuild state.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
from functools import cached_property
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from research_harness.domain.base import utc_now
from research_harness.domain.claim import Claim
from research_harness.domain.document import ParsedDocument
from research_harness.domain.errors import DomainValidationError, WorkspaceError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import (
    ArtifactId,
    BlockId,
    ClaimId,
    DecisionId,
    EvidenceId,
    InterpretationId,
    QuestionId,
    ResearchId,
    SearchRunId,
    SynthesisId,
    VersionId,
    WorkId,
    parse_id,
)
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.domain.research import (
    EVENT_PAYLOAD_FORBIDDEN_KEYS,
    MAX_EVENT_OBJECT_KEYS,
    Decision,
    ResearchEvent,
    ResearchNote,
    ResearchQuestion,
    SearchRun,
    SynthesisMatrix,
    Taxonomy,
)
from research_harness.domain.work import Artifact, Version, Work
from research_harness.workspace.atomic import TEMP_PREFIX, atomic_write_bytes
from research_harness.workspace.journal import Transaction
from research_harness.workspace.layout import BLOCKS_SUFFIX, WorkspaceLayout
from research_harness.workspace.rejections import RejectionRecord
from research_harness.workspace.serialization import (
    canonical_bytes,
    dump_jsonl_line,
    iter_jsonl,
    read_yaml,
)

__all__ = [
    "ANCHOR_KEY_PREFIX",
    "BLOCKS_KEY_PREFIX",
    "CONSISTENCY_MARKER_FILENAME",
    "CONSISTENCY_MARKER_SCHEMA_VERSION",
    "EVENT_OBJECT_PREFIX",
    "MAX_EVENT_OBJECTS",
    "NOTE_KEY_PREFIX",
    "REJECTION_KEY_PREFIX",
    "TAXONOMY_KEY_PREFIX",
    "ConsistencyIssue",
    "ConsistencyMarker",
    "ConsistencyReport",
    "EventLog",
    "EventPayloadError",
    "assert_semantic_event",
    "canonical_relative",
    "capture_consistency_marker",
    "clear_consistency_marker",
    "consistency_marker_path",
    "content_digest",
    "digest_key",
    "event_object_digests",
    "file_digest",
    "iter_canonical_entries",
    "iter_canonical_files",
    "object_digest",
    "read_consistency_marker",
    "refresh_marker_after_commit",
    "stat_canonical_files",
    "verified_marker",
    "verify_consistency",
    "with_object_digests",
    "write_consistency_marker",
]

logger = logging.getLogger(__name__)

#: Legacy payload prefix for per-object digests, from before `ResearchEvent.objects`
#: existed: `object:C0041 -> sha256:...`. Digests are written to `objects` now, but events
#: already in a log are still read through this prefix.
EVENT_OBJECT_PREFIX = "object:"
TAXONOMY_KEY_PREFIX = "taxonomy/"
NOTE_KEY_PREFIX = "notes/"
BLOCKS_KEY_PREFIX = "blocks/"
ANCHOR_KEY_PREFIX = "anchor/"
REJECTION_KEY_PREFIX = "rejection/"

#: The domain caps `ResearchEvent.objects`; one mutation may not exceed it.
MAX_EVENT_OBJECTS = MAX_EVENT_OBJECT_KEYS


class EventPayloadError(WorkspaceError):
    """An event payload carries something that is not a semantic state change."""


# -- digests -----------------------------------------------------------------


def content_digest(data: bytes) -> str:
    """`sha256:<hex>` over raw bytes, matching the domain's `Sha256` shape."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def file_digest(path: Path) -> str:
    """`sha256:<hex>` over a file's bytes, read in chunks so a large artifact is not held."""
    with path.open("rb") as handle:
        return f"sha256:{hashlib.file_digest(handle, 'sha256').hexdigest()}"


def object_digest(model: BaseModel) -> str:
    """Digest of an object's canonical YAML.

    Canonical YAML rather than the stored bytes on purpose: reformatting a file by hand is
    not a scientific change and must not fail the workspace closed, while editing a value
    must.
    """
    return content_digest(canonical_bytes(model))


def digest_key(obj: object) -> str:
    """The stable key an object's digest is recorded under in an event payload.

    Objects with a stable research id use it directly. The rest are keyed by the coordinate
    that identifies their canonical file: taxonomy name, note key, artifact for a block
    file, and `(file, sentence_fingerprint)` for a manuscript anchor.
    """
    match obj:
        case Taxonomy():
            return f"{TAXONOMY_KEY_PREFIX}{obj.name}"
        case ResearchNote():
            if obj.key is None:
                raise WorkspaceError("a research note needs a key before it can be recorded")
            return f"{NOTE_KEY_PREFIX}{obj.key}"
        case ParsedDocument():
            return f"{BLOCKS_KEY_PREFIX}{obj.artifact}"
        case ManuscriptAnchor():
            return f"{ANCHOR_KEY_PREFIX}{obj.file}#{obj.sentence_fingerprint}"
        case RejectionRecord():
            return f"{REJECTION_KEY_PREFIX}{obj.work}#{obj.candidate_id}"
        case _:
            identifier = getattr(obj, "id", None)
            if isinstance(identifier, ResearchId):
                return str(identifier)
            raise WorkspaceError(f"no event digest key for {type(obj).__name__}")


def with_object_digests(event: ResearchEvent, digests: Mapping[str, str]) -> ResearchEvent:
    """Return ``event`` with one `objects` entry per written object.

    The payload is left untouched: an audit narrative and the list of written objects are
    different things and no longer share a budget.
    """
    if not digests:
        return event
    objects = {**event.objects, **digests}
    if len(objects) > MAX_EVENT_OBJECTS:
        raise EventPayloadError(
            f"event {event.event.value!r} would record {len(objects)} object digests "
            f"({len(digests)} of them new); the semantic event log holds at most "
            f"{MAX_EVENT_OBJECTS}. Split the mutation into smaller units."
        )
    return event.touch(objects=dict(sorted(objects.items())))


def event_object_digests(event: ResearchEvent) -> dict[str, str]:
    """The `key -> digest` mapping an event recorded for the objects it changed.

    Reads `objects`, plus the legacy `object:<key>` payload entries so that a log written
    before the field existed still reconciles.
    """
    digests: dict[str, str] = {
        key[len(EVENT_OBJECT_PREFIX) :]: value
        for key, value in event.payload.items()
        if key.startswith(EVENT_OBJECT_PREFIX) and isinstance(value, str)
    }
    digests.update(event.objects)
    return digests


def assert_semantic_event(event: ResearchEvent) -> None:
    """Refuse an event that carries prompts, hidden reasoning, or raw tool output.

    The domain model rejects those keys on construction; re-checking here keeps the
    guarantee at the persistence boundary, where a hand-written or externally supplied event
    could otherwise slip in.
    """
    for key in event.payload:
        if key.lower() in EVENT_PAYLOAD_FORBIDDEN_KEYS:
            raise EventPayloadError(
                f"event payload must not carry {key!r}; prompts, reasoning, and tool output "
                "belong in disposable .research/traces/"
            )


# -- the log -----------------------------------------------------------------


class EventLog:
    """Append-only view over `events/research.jsonl`.

    The log is never written on its own: :meth:`stage` adds the event to the same
    transaction as the canonical mutation it describes.
    """

    def __init__(self, layout: WorkspaceLayout) -> None:
        self._layout = layout

    @property
    def path(self) -> Path:
        return self._layout.events_file

    def stage(self, transaction: Transaction, event: ResearchEvent) -> ResearchEvent:
        """Add the event to ``transaction`` so it lands with the mutation, or not at all."""
        assert_semantic_event(event)
        transaction.append(self.path, dump_jsonl_line(event).encode("utf-8"))
        return event

    def iter_events(self) -> Iterator[ResearchEvent]:
        """Every recorded event, oldest first."""
        yield from iter_jsonl(self.path, ResearchEvent)

    def latest_digests(self) -> dict[str, tuple[ResearchEvent, str]]:
        """For each object key, the newest event that touched it and the digest it recorded."""
        latest: dict[str, tuple[ResearchEvent, str]] = {}
        for event in self.iter_events():
            for key, digest in event_object_digests(event).items():
                latest[key] = (event, digest)
        return latest


# -- consistency -------------------------------------------------------------


@dataclass(frozen=True)
class ConsistencyIssue:
    """One object whose canonical file disagrees with the event log."""

    key: str
    reason: str
    expected: str
    found: str | None
    event: str

    def describe(self) -> str:
        found = self.found or "no canonical object"
        return (
            f"{self.key}: {self.reason} "
            f"(event {self.event} recorded {self.expected}, found {found})"
        )


@dataclass(frozen=True)
class ConsistencyReport:
    """Result of comparing the event log's account of the workspace with the workspace."""

    checked: int = 0
    issues: tuple[ConsistencyIssue, ...] = ()
    skipped_reason: str | None = None
    """Why the full check was not re-run, when `.research/consistency-check.json` proved
    every canonical file and the event log byte-identical to the last successful one."""

    @property
    def consistent(self) -> bool:
        return not self.issues

    @property
    def skipped(self) -> bool:
        """True when this report repeats an earlier full verification instead of redoing it."""
        return self.skipped_reason is not None

    def summary(self) -> str:
        if self.skipped_reason is not None:
            return (
                f"verification skipped ({self.skipped_reason}); the last full check found "
                f"{self.checked} objects consistent with the event log"
            )
        if self.consistent:
            return f"{self.checked} objects consistent with the event log"
        details = "; ".join(issue.describe() for issue in self.issues)
        return (
            f"{len(self.issues)} of {self.checked} objects disagree with the event log: {details}"
        )


def verify_consistency(layout: WorkspaceLayout) -> ConsistencyReport:
    """Compare each object's newest recorded digest with its current canonical form.

    Only the latest event per object is checked: the log is an audit companion, and history
    is Git's job, not a state machine to replay.
    """
    issues: list[ConsistencyIssue] = []
    latest = EventLog(layout).latest_digests()
    canonical = _CanonicalIndex(layout)
    for key, (event, expected) in sorted(latest.items()):
        found = _current_digest(canonical, key)
        if found is None:
            reason = "the event log records an object that is not in canonical state"
        elif found != expected:
            reason = "canonical content does not match the digest recorded with the event"
        else:
            continue
        issues.append(
            ConsistencyIssue(
                key=key,
                reason=reason,
                expected=expected,
                found=found,
                event=event.event.value,
            )
        )
    return ConsistencyReport(checked=len(latest), issues=tuple(issues))


class _CanonicalIndex:
    """Every canonical object the event log can name, resolved with one read per file.

    Resolving a key on its own is what made opening a project quadratic: a Version or
    Artifact id globbed the whole corpus, and an Evidence id re-read and re-validated every
    `evidence.jsonl` in it, so a workspace with E evidence records paid O(E) file reads for
    each of its E ids. Each index below is built at most once per verification and reads
    each canonical file at most once; a key that needs no index (a Work, Claim, Question,
    Decision, Matrix, Search run, Taxonomy or Note) still goes straight to its own path.

    Indexes are built on first use, so a log that names no Evidence never opens an
    `evidence.jsonl`, and they resolve exactly what the per-key scans resolved: the first
    file in sorted order that holds an id, and within a file the last record for it.
    """

    def __init__(self, layout: WorkspaceLayout) -> None:
        self._layout = layout
        self._rejections: dict[str, Mapping[str, RejectionRecord]] = {}

    @property
    def layout(self) -> WorkspaceLayout:
        return self._layout

    @cached_property
    def versions(self) -> Mapping[str, Path]:
        return _first_by_key(self._layout.works_dir.glob("*/versions/*.yaml"), _stem)

    @cached_property
    def artifacts(self) -> Mapping[str, Path]:
        return _first_by_key(self._layout.works_dir.glob("*/artifacts/*.yaml"), _stem)

    @cached_property
    def blocks(self) -> Mapping[str, Path]:
        paths = self._layout.works_dir.glob(f"*/parsed/*{BLOCKS_SUFFIX}")
        return _first_by_key(paths, lambda path: path.name[: -len(BLOCKS_SUFFIX)])

    @cached_property
    def evidence(self) -> Mapping[str, Evidence]:
        """`evidence id -> newest record`, first `evidence.jsonl` holding the id winning."""
        newest: dict[str, Evidence] = {}
        for path in sorted(self._layout.works_dir.glob("*/evidence.jsonl")):
            in_file: dict[str, Evidence] = {}
            for record in iter_jsonl(path, Evidence):
                in_file[str(record.id)] = record
            for key, record in in_file.items():
                newest.setdefault(key, record)
        return newest

    @cached_property
    def anchors(self) -> Mapping[tuple[str, str], ManuscriptAnchor]:
        return {
            (anchor.file, anchor.sentence_fingerprint): anchor
            for anchor in iter_jsonl(self._layout.anchors_file, ManuscriptAnchor)
        }

    def rejections(self, work: WorkId) -> Mapping[str, RejectionRecord]:
        """`candidate id -> newest rejection` for one Work, read once."""
        cached = self._rejections.get(str(work))
        if cached is None:
            cached = {
                record.candidate_id: record
                for record in iter_jsonl(self._layout.rejections_path(work), RejectionRecord)
            }
            self._rejections[str(work)] = cached
        return cached


def _current_digest(canonical: _CanonicalIndex, key: str) -> str | None:
    """Digest of the object ``key`` currently names, or ``None`` when it is absent."""
    layout = canonical.layout
    if key.startswith(TAXONOMY_KEY_PREFIX):
        return _yaml_digest(layout.taxonomy_file(key[len(TAXONOMY_KEY_PREFIX) :]), Taxonomy)
    if key.startswith(NOTE_KEY_PREFIX):
        return _yaml_digest(layout.note_file(key[len(NOTE_KEY_PREFIX) :]), ResearchNote)
    if key.startswith(BLOCKS_KEY_PREFIX):
        return _blocks_digest(canonical, key[len(BLOCKS_KEY_PREFIX) :])
    if key.startswith(ANCHOR_KEY_PREFIX):
        return _anchor_digest(canonical, key[len(ANCHOR_KEY_PREFIX) :])
    if key.startswith(REJECTION_KEY_PREFIX):
        return _rejection_digest(canonical, key[len(REJECTION_KEY_PREFIX) :])
    return _canonical_object_digest(canonical, key)


def _canonical_object_digest(canonical: _CanonicalIndex, key: str) -> str | None:
    try:
        identifier = parse_id(key)
    except DomainValidationError:
        logger.debug("event log references an unrecognised object key %r", key)
        return None
    layout = canonical.layout
    match identifier:
        case WorkId():
            return _yaml_digest(layout.work_file(identifier), Work)
        case VersionId():
            return _yaml_digest(canonical.versions.get(key), Version)
        case ArtifactId():
            return _yaml_digest(canonical.artifacts.get(key), Artifact)
        case ClaimId():
            return _yaml_digest(layout.claim_file(identifier), Claim)
        case QuestionId():
            return _yaml_digest(layout.question_file(identifier), ResearchQuestion)
        case DecisionId():
            return _yaml_digest(layout.decision_file(identifier), Decision)
        case SynthesisId():
            return _yaml_digest(layout.matrix_file(identifier), SynthesisMatrix)
        case SearchRunId():
            return _yaml_digest(layout.search_run_file(identifier), SearchRun)
        case EvidenceId():
            return _evidence_digest(canonical, identifier)
        case BlockId() | InterpretationId():
            logger.debug("object key %r has no canonical file of its own", key)
            return None
        case _:  # pragma: no cover - every id family is handled above
            return None


def _yaml_digest(path: Path | None, model_type: type[BaseModel]) -> str | None:
    if path is None or not path.is_file():
        return None
    return object_digest(read_yaml(path, model_type))


def _evidence_digest(canonical: _CanonicalIndex, evidence_id: EvidenceId) -> str | None:
    """Digest of the newest record for this evidence id across the corpus."""
    record = canonical.evidence.get(str(evidence_id))
    return None if record is None else object_digest(record)


def _blocks_digest(canonical: _CanonicalIndex, artifact: str) -> str | None:
    """Blocks are a derived file with no single object form, so its bytes are the digest."""
    path = canonical.blocks.get(artifact)
    return None if path is None else content_digest(path.read_bytes())


def _rejection_digest(canonical: _CanonicalIndex, key: str) -> str | None:
    """Digest of the newest rejection recorded for `<work>#<candidate id>`."""
    work, _, candidate_id = key.partition("#")
    try:
        identifier = WorkId(work)
    except DomainValidationError:
        return None
    record = canonical.rejections(identifier).get(candidate_id)
    return None if record is None else object_digest(record)


def _anchor_digest(canonical: _CanonicalIndex, key: str) -> str | None:
    file, _, fingerprint = key.rpartition("#")
    anchor = canonical.anchors.get((file, fingerprint))
    return None if anchor is None else object_digest(anchor)


def _stem(path: Path) -> str:
    return path.stem


def _first_by_key(paths: Iterable[Path], key: Callable[[Path], str]) -> dict[str, Path]:
    """`key -> first path in sorted order`, matching what a per-key sorted glob returned."""
    found: dict[str, Path] = {}
    for path in sorted(paths):
        found.setdefault(key(path), path)
    return found


# -- the verification cache --------------------------------------------------

CONSISTENCY_MARKER_FILENAME = "consistency-check.json"
"""Where a successful full verification records what it saw.

The marker lives under `.research/`, which has no scientific authority (ADR-001): deleting
the projection directory throws it away and the next open verifies in full. It is a cache
and never a verdict — nothing but :func:`verify_consistency` can declare a workspace
consistent, and the marker only says "these bytes are the ones that check passed on".
"""

CONSISTENCY_MARKER_SCHEMA_VERSION = 1
"""Shape of the marker; a marker written by another version is ignored, not migrated."""

_SETTLE_SECONDS = 0.002
_SETTLE_ATTEMPTS = 5
"""How long to wait for the filesystem clock to move past the newest canonical mtime.

Two writes inside one filesystem clock tick share an `mtime_ns`, so an edit made in the
tick a file was last written in would be invisible to `(size, mtime_ns)`. A marker is
therefore only written once every recorded mtime is strictly older than the clock, which
on a millisecond-granularity filesystem costs one 2 ms wait after a commit and nothing
after a full verification of a real corpus. A filesystem whose timestamps are coarser than
these attempts allow simply never caches a verification, which is slow but always correct.
"""


def consistency_marker_path(layout: WorkspaceLayout) -> Path:
    """`.research/consistency-check.json` for this workspace."""
    return layout.research_dir / CONSISTENCY_MARKER_FILENAME


def iter_canonical_entries(layout: WorkspaceLayout) -> Iterator[tuple[str, Path]]:
    """`(workspace-relative path, absolute path)` for every file carrying authority.

    Excluded: everything under `.research/` (regenerable by definition), every dot-file and
    dot-directory (`.git/`, `.gitignore`), and the user's own manuscript sources — the
    harness owns only `manuscript/anchors.jsonl` there and must not fail a workspace
    because a researcher edited their LaTeX. Artifact binaries are included: their bytes
    are what an accepted evidence anchor was read from.
    """
    root = layout.root
    if not root.is_dir():
        return
    manuscript = layout.manuscript_dir.name
    anchors = str(layout.relative(layout.anchors_file))
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = sorted(
            name for name in subdirectories if not name.startswith(".") and name != "__pycache__"
        )
        prefix = os.path.relpath(directory, root).replace(os.sep, "/")
        prefix = "" if prefix == "." else f"{prefix}/"
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            relative = f"{prefix}{name}"
            if relative.startswith(f"{manuscript}/") and relative != anchors:
                continue
            yield relative, Path(directory) / name


def iter_canonical_files(layout: WorkspaceLayout) -> Iterator[Path]:
    """Every file the canonical digest covers, in a deterministic order."""
    for _, path in iter_canonical_entries(layout):
        yield path


@dataclass(frozen=True, slots=True)
class ConsistencyMarker:
    """The canonical bytes a full :func:`verify_consistency` was run against.

    `manifest` holds `(size_bytes, mtime_ns)` per canonical file rather than a content
    hash: proving the tree unchanged must cost one `stat` per file, not a read of every
    byte, or the cache would be as expensive as the check it replaces. The event log is the
    one file digested outright — it is the account being reconciled, it is small, and a
    hand-edited log is the failure this whole mechanism must never wave through.
    """

    checked_at: datetime
    """When the full verification finished; quoted back in the skipped report."""

    settled_at_ns: int
    """A filesystem timestamp strictly newer than every mtime in `manifest`."""

    checked: int
    """Objects that full verification reconciled, kept so the skipped report can say so."""

    event_log_bytes: int
    event_log_digest: str
    manifest: Mapping[str, tuple[int, int]]

    def as_json(self) -> bytes:
        """Serialize with sorted keys so a marker is diffable and reproducible."""
        payload = {
            "schema_version": CONSISTENCY_MARKER_SCHEMA_VERSION,
            "checked_at": self.checked_at.isoformat(),
            "settled_at_ns": self.settled_at_ns,
            "checked": self.checked,
            "event_log": {"size_bytes": self.event_log_bytes, "sha256": self.event_log_digest},
            "manifest": {name: list(entry) for name, entry in sorted(self.manifest.items())},
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=None).encode("utf-8")

    @classmethod
    def from_json(cls, data: bytes) -> ConsistencyMarker | None:
        """Parse a marker, returning ``None`` for anything this version cannot trust."""
        try:
            payload = json.loads(data)
            if payload["schema_version"] != CONSISTENCY_MARKER_SCHEMA_VERSION:
                return None
            log = payload["event_log"]
            manifest = {
                str(name): (int(entry[0]), int(entry[1]))
                for name, entry in payload["manifest"].items()
            }
            return cls(
                checked_at=datetime.fromisoformat(payload["checked_at"]),
                settled_at_ns=int(payload["settled_at_ns"]),
                checked=int(payload["checked"]),
                event_log_bytes=int(log["size_bytes"]),
                event_log_digest=str(log["sha256"]),
                manifest=manifest,
            )
        except (KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError):
            logger.debug("ignoring an unreadable consistency marker")
            return None

    @property
    def reason(self) -> str:
        """What the skipped :class:`ConsistencyReport` reports as its reason."""
        return f"unchanged since {self.checked_at.isoformat()}"

    def matches(self, layout: WorkspaceLayout) -> bool:
        """True when every canonical file and the event log are byte-for-byte as recorded.

        Fails closed on anything it cannot prove: an added or removed file, a size or
        `mtime_ns` that moved, an entry whose mtime is not strictly older than the moment
        the marker settled (so a same-tick edit cannot hide), or an unreadable tree.
        """
        if any(mtime >= self.settled_at_ns for _, mtime in self.manifest.values()):
            logger.debug("consistency marker has an unsettled entry; verifying in full")
            return False
        current = stat_canonical_files(layout)
        if current is None or current != self.manifest:
            return False
        size, digest = _event_log_fingerprint(layout)
        return size == self.event_log_bytes and digest == self.event_log_digest

    def updated_for(
        self, layout: WorkspaceLayout, paths: Iterable[Path]
    ) -> ConsistencyMarker | None:
        """This marker with ``paths`` re-stat'd, for the files a commit just landed.

        A committed transaction leaves the workspace consistent by construction — it
        revalidated every object, digested it into the event it appended, and wrote both as
        one journalled unit — so the verification this marker stands for still holds over
        the new bytes. Only the entries the transaction touched can have moved.
        """
        manifest = dict(self.manifest)
        for path in paths:
            relative = canonical_relative(layout, path)
            if relative is None:
                continue
            try:
                info = path.stat()
            except OSError:
                manifest.pop(relative, None)
                continue
            manifest[relative] = (info.st_size, info.st_mtime_ns)
        settled = _settled_stamp(layout, manifest)
        if settled is None:
            return None
        size, digest = _event_log_fingerprint(layout)
        return replace(
            self,
            checked_at=utc_now(),
            settled_at_ns=settled,
            event_log_bytes=size,
            event_log_digest=digest,
            manifest=manifest,
        )


def canonical_relative(layout: WorkspaceLayout, path: Path) -> str | None:
    """The manifest key for ``path``, or ``None`` when it carries no scientific authority."""
    try:
        relative = layout.relative(path)
    except WorkspaceError:
        return None
    parts = relative.parts
    if any(part.startswith(".") or part == "__pycache__" for part in parts):
        return None
    name = str(relative)
    anchors = str(layout.relative(layout.anchors_file))
    if name.startswith(f"{layout.manuscript_dir.name}/") and name != anchors:
        return None
    return name


def stat_canonical_files(layout: WorkspaceLayout) -> dict[str, tuple[int, int]] | None:
    """`relative path -> (size_bytes, mtime_ns)` for the whole canonical tree.

    ``None`` when the tree cannot be read; an unreadable workspace is never "unchanged".
    """
    manifest: dict[str, tuple[int, int]] = {}
    try:
        for relative, path in iter_canonical_entries(layout):
            info = path.stat()
            manifest[relative] = (info.st_size, info.st_mtime_ns)
    except OSError as error:
        logger.debug("cannot stat the canonical tree (%s); verifying in full", error)
        return None
    return manifest


def capture_consistency_marker(
    layout: WorkspaceLayout, *, checked: int
) -> ConsistencyMarker | None:
    """Snapshot the canonical tree a full verification just passed over.

    Returns ``None`` rather than a marker that cannot be trusted later: an unreadable tree,
    or a file whose mtime the filesystem clock has not yet moved past.
    """
    manifest = stat_canonical_files(layout)
    if manifest is None:
        return None
    settled = _settled_stamp(layout, manifest)
    if settled is None:
        return None
    size, digest = _event_log_fingerprint(layout)
    return ConsistencyMarker(
        checked_at=utc_now(),
        settled_at_ns=settled,
        checked=checked,
        event_log_bytes=size,
        event_log_digest=digest,
        manifest=manifest,
    )


def read_consistency_marker(layout: WorkspaceLayout) -> ConsistencyMarker | None:
    """The marker on disk, or ``None`` when there is none this version can read."""
    try:
        data = consistency_marker_path(layout).read_bytes()
    except OSError:
        return None
    return ConsistencyMarker.from_json(data)


def write_consistency_marker(layout: WorkspaceLayout, marker: ConsistencyMarker) -> bool:
    """Persist ``marker`` atomically; ``False`` when the workspace refuses the write.

    A read-only or full `.research/` costs the researcher a slower open, never an open that
    fails: the marker is an optimization and its absence is always safe.
    """
    try:
        atomic_write_bytes(consistency_marker_path(layout), marker.as_json())
    except OSError as error:
        logger.debug("cannot write the consistency marker (%s); the next open verifies", error)
        return False
    return True


def clear_consistency_marker(layout: WorkspaceLayout) -> None:
    """Drop the marker so the next open verifies in full."""
    with suppress(OSError):
        consistency_marker_path(layout).unlink(missing_ok=True)


def _event_log_fingerprint(layout: WorkspaceLayout) -> tuple[int, str]:
    """`(size, sha256)` of `events/research.jsonl`; `(0, "")` when there is no log yet."""
    path = layout.events_file
    try:
        size = path.stat().st_size
        return size, file_digest(path)
    except OSError:
        return 0, ""


def _settled_stamp(layout: WorkspaceLayout, manifest: Mapping[str, tuple[int, int]]) -> int | None:
    """A filesystem timestamp strictly newer than every mtime in ``manifest``.

    Waits for the filesystem clock to leave the tick the newest canonical file was written
    in, so no later edit can reuse a recorded `mtime_ns`. ``None`` when it will not settle,
    which simply means no marker is written this time.
    """
    newest = max((mtime for _, mtime in manifest.values()), default=0)
    for attempt in range(_SETTLE_ATTEMPTS):
        stamp = _filesystem_clock_ns(layout.research_dir)
        if stamp is None:
            return None
        if newest < stamp:
            return stamp
        if attempt + 1 < _SETTLE_ATTEMPTS:
            time.sleep(_SETTLE_SECONDS)
    logger.debug("the canonical tree is still being written; not caching this verification")
    return None


def _filesystem_clock_ns(directory: Path) -> int | None:
    """The `mtime_ns` this filesystem would stamp on a file written right now.

    Read by stamping a throwaway file rather than from `time.time_ns()`: file timestamps
    come from a coarse clock whose granularity varies by kernel and filesystem, and the
    only number that can be compared against a recorded `mtime_ns` without assuming that
    granularity is one the filesystem itself produced.
    """
    probe = directory / f"{TEMP_PREFIX}clock.{os.getpid()}.{uuid4().hex}"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.touch()
        return probe.stat().st_mtime_ns
    except OSError:
        return None
    finally:
        with suppress(OSError):
            probe.unlink(missing_ok=True)


def verified_marker(
    layout: WorkspaceLayout, *, verify_full: bool
) -> tuple[ConsistencyReport, ConsistencyMarker | None]:
    """Reconcile the event log with canonical state, skipping the walk when nothing moved.

    ``verify_full`` forces the whole check — what `research doctor` asks for, and the only
    path that can turn a workspace from unverified to verified. Otherwise a marker that
    still describes the tree byte-for-byte stands in for the check it recorded.
    """
    if not verify_full:
        marker = read_consistency_marker(layout)
        if marker is not None and marker.matches(layout):
            logger.debug("consistency verification skipped: %s", marker.reason)
            return ConsistencyReport(checked=marker.checked, skipped_reason=marker.reason), marker
    report = verify_consistency(layout)
    if not report.consistent:
        clear_consistency_marker(layout)
        return report, None
    marker = capture_consistency_marker(layout, checked=report.checked)
    if marker is None or not write_consistency_marker(layout, marker):
        clear_consistency_marker(layout)
        return report, None
    return report, marker


def refresh_marker_after_commit(
    layout: WorkspaceLayout, marker: ConsistencyMarker | None, paths: Sequence[Path]
) -> ConsistencyMarker | None:
    """Carry a marker across a committed mutation, or drop it when it cannot be carried.

    Dropping is always safe and never silent: without a marker the next open verifies in
    full. Carrying one is only sound when this process holds a marker it either wrote after
    a full verification or matched against the tree, because that is what makes "everything
    since then went through a journalled transaction" true.
    """
    if marker is None:
        clear_consistency_marker(layout)
        return None
    updated = marker.updated_for(layout, paths)
    if updated is None or not write_consistency_marker(layout, updated):
        clear_consistency_marker(layout)
        return None
    return updated

"""The durable transaction journal that makes a multi-file canonical mutation atomic.

Product 8.2 and Product 42 K require that interrupting an accepted-state mutation leaves
either the complete prior state or the complete new state with its matching event — never a
half-written object and never an event without its mutation. A single `os.replace` gives
that for one file; a Claim, its Evidence line, and the event line are three files, so they
need a journal.

Protocol (all fsynced)::

    prepare  stage the new content, back up every pre-image, then land the record
             `.research/journal/<tx>.json` carrying `prepared: true`
    apply    writes via temp+fsync+rename; appends verified against the recorded length
             then appended; deletes unlinked (their pre-image is already staged)
    commit   rename `<tx>.json` -> `<tx>.committed.json`   <-- the commit point
    clean    drop the staged content and the committed record

:func:`recover` runs on every workspace open and is idempotent:

* record present and ``prepared`` -> **redo** every intent and commit. Writes are naturally
  idempotent; an append truncates back to ``expected_length_before`` first, so recovery can
  never duplicate an event line.
* record missing or torn -> the apply phase never began, so **roll back** from the staged
  pre-images and discard the transaction.
* record already committed -> only the leftovers need cleaning.

The staged directory is self-describing (mirror trees of the workspace-relative paths), so
rollback works even when the record itself is unreadable.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from research_harness.domain.errors import WorkspaceError
from research_harness.workspace.atomic import (
    atomic_write_bytes,
    clean_partials,
    fsync_directory,
    write_bytes_durably,
)
from research_harness.workspace.layout import RESEARCH_DIRNAME, WorkspaceLayout

__all__ = [
    "JOURNAL_SCHEMA_VERSION",
    "Intent",
    "IntentOp",
    "JournalConflictError",
    "JournalError",
    "JournalRecord",
    "RecoveryReport",
    "Transaction",
    "TransactionOutcome",
    "recover",
]

logger = logging.getLogger(__name__)

JOURNAL_SCHEMA_VERSION = 1

RECORD_SUFFIX = ".json"
COMMITTED_SUFFIX = ".committed.json"

_NEW = "new"
_PRE = "pre"
_ABSENT = "absent"
_TRUNCATE = "truncate"


class JournalError(WorkspaceError):
    """A journalled transaction could not be prepared, applied, or recovered."""


class JournalConflictError(JournalError):
    """An append target changed under the transaction; the workspace lock was not honoured."""


class IntentOp(StrEnum):
    """The three ways a transaction can change a canonical file."""

    WRITE = "write"
    APPEND = "append"
    DELETE = "delete"


class TransactionOutcome(StrEnum):
    """What recovery did with one leftover transaction."""

    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"
    CLEANED = "cleaned"


@dataclass(frozen=True)
class Intent:
    """One file-level change, addressed by its workspace-relative POSIX path."""

    op: IntentOp
    path: str
    expected_length_before: int | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"op": self.op.value, "path": self.path}
        if self.expected_length_before is not None:
            payload["expected_length_before"] = self.expected_length_before
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Intent:
        try:
            op = IntentOp(payload["op"])
            path = str(payload["path"])
        except (KeyError, ValueError) as exc:
            raise JournalError(f"unreadable journal intent {payload!r}") from exc
        expected = payload.get("expected_length_before")
        return cls(
            op=op,
            path=path,
            expected_length_before=None if expected is None else int(expected),
        )


@dataclass(frozen=True)
class JournalRecord:
    """The on-disk description of one transaction."""

    tx_id: str
    prepared: bool
    intents: tuple[Intent, ...]
    created_at: str
    schema_version: int = JOURNAL_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tx_id": self.tx_id,
            "created_at": self.created_at,
            "prepared": self.prepared,
            "intents": [intent.as_dict() for intent in self.intents],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> JournalRecord:
        try:
            intents = tuple(Intent.from_dict(item) for item in payload["intents"])
            return cls(
                tx_id=str(payload["tx_id"]),
                prepared=bool(payload["prepared"]),
                intents=intents,
                created_at=str(payload.get("created_at", "")),
                schema_version=int(payload.get("schema_version", JOURNAL_SCHEMA_VERSION)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise JournalError(f"unreadable journal record: {exc}") from exc


@dataclass(frozen=True)
class RecoveryReport:
    """What :func:`recover` found and did, per leftover transaction."""

    completed: tuple[str, ...] = ()
    rolled_back: tuple[str, ...] = ()
    cleaned: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        """True when recovery had to touch the workspace."""
        return bool(self.completed or self.rolled_back or self.cleaned)

    def summary(self) -> str:
        return (
            f"{len(self.completed)} completed, {len(self.rolled_back)} rolled back, "
            f"{len(self.cleaned)} cleaned"
        )


@dataclass
class _Staged:
    """A pending change to one path, accumulated before prepare."""

    op: IntentOp
    payload: bytearray = field(default_factory=bytearray)


class Transaction:
    """Collects file intents and commits them as one recoverable unit.

    Intents are addressed by absolute path inside the workspace; `.research/` is refused so
    a transaction can never rewrite its own journal or a regenerable projection.
    """

    def __init__(self, layout: WorkspaceLayout, *, tx_id: str | None = None) -> None:
        self._layout = layout
        self._tx_id = tx_id or f"tx-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4().hex[:12]}"
        self._staged: dict[str, _Staged] = {}
        self._committed = False

    # -- identity ------------------------------------------------------------

    @property
    def tx_id(self) -> str:
        return self._tx_id

    @property
    def layout(self) -> WorkspaceLayout:
        return self._layout

    @property
    def is_empty(self) -> bool:
        return not self._staged

    @property
    def committed(self) -> bool:
        return self._committed

    @property
    def paths(self) -> tuple[Path, ...]:
        """Absolute paths this transaction will touch, in declaration order."""
        return tuple(self._layout.resolve(path) for path in self._staged)

    @property
    def record_path(self) -> Path:
        return self._layout.journal_dir / f"{self._tx_id}{RECORD_SUFFIX}"

    @property
    def staging_dir(self) -> Path:
        return self._layout.journal_dir / self._tx_id

    # -- intents -------------------------------------------------------------

    def write(self, path: Path | str, data: bytes) -> None:
        """Replace ``path`` with ``data``; the last write for a path wins."""
        key = self._key(path)
        staged = self._claim(key, IntentOp.WRITE)
        staged.payload[:] = data

    def append(self, path: Path | str, line: bytes) -> None:
        """Append ``line`` to ``path``; repeated appends to one path concatenate in order."""
        key = self._key(path)
        staged = self._claim(key, IntentOp.APPEND)
        staged.payload.extend(line)

    def delete(self, path: Path | str) -> None:
        """Remove ``path`` if it exists; the pre-image is kept until the commit point."""
        key = self._key(path)
        self._staged[key] = _Staged(op=IntentOp.DELETE)

    # -- commit --------------------------------------------------------------

    def commit(self) -> JournalRecord:
        """Prepare, apply, and commit every intent as one unit.

        On failure the workspace is left in a state :func:`recover` can finish or undo; the
        caller is expected to run recovery (`WorkspaceRepository` does this automatically).
        """
        if self._committed:
            raise JournalError(f"transaction {self._tx_id} was already committed")
        record = self._prepare()
        self._apply(record, redo=False)
        self._commit_record(record)
        self._committed = True
        _clean_transaction(self._layout, record.tx_id)
        return record

    # -- phases (separated so crash points are testable) ---------------------

    def _prepare(self) -> JournalRecord:
        """Stage new content and pre-images, then land the `prepared: true` record."""
        journal = self._layout.journal_dir
        journal.mkdir(parents=True, exist_ok=True)
        staging = self.staging_dir
        if staging.exists():
            raise JournalError(f"journal staging for {self._tx_id} already exists")
        staging.mkdir(parents=True)
        intents: list[Intent] = []
        try:
            for key, staged in self._staged.items():
                intents.append(self._stage(key, staged))
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        _fsync_tree(staging)
        record = JournalRecord(
            tx_id=self._tx_id,
            prepared=True,
            intents=tuple(intents),
            created_at=datetime.now(UTC).isoformat(),
        )
        self._write_record(record)
        return record

    def _write_record(self, record: JournalRecord) -> None:
        """Land the journal record; after this the transaction rolls *forward*."""
        atomic_write_bytes(self.record_path, _encode_record(record))

    def _stage(self, key: str, staged: _Staged) -> Intent:
        target = self._layout.resolve(key)
        expected: int | None = None
        if staged.op in (IntentOp.WRITE, IntentOp.APPEND):
            write_bytes_durably(self.staging_dir / _NEW / key, bytes(staged.payload))
        if staged.op is IntentOp.APPEND:
            if target.is_file():
                expected = target.stat().st_size
                write_bytes_durably(
                    self.staging_dir / _TRUNCATE / key, str(expected).encode("ascii")
                )
            else:
                expected = 0
                write_bytes_durably(self.staging_dir / _ABSENT / key, b"")
        elif target.is_file():
            write_bytes_durably(self.staging_dir / _PRE / key, target.read_bytes())
        elif staged.op is IntentOp.WRITE:
            write_bytes_durably(self.staging_dir / _ABSENT / key, b"")
        return Intent(op=staged.op, path=key, expected_length_before=expected)

    def _apply(self, record: JournalRecord, *, redo: bool) -> None:
        for intent in record.intents:
            self._apply_intent(record, intent, redo=redo)

    def _apply_intent(self, record: JournalRecord, intent: Intent, *, redo: bool) -> None:
        target = self._layout.resolve(intent.path)
        match intent.op:
            case IntentOp.WRITE:
                atomic_write_bytes(target, self._staged_bytes(record, _NEW, intent.path))
            case IntentOp.APPEND:
                self._apply_append(record, intent, target, redo=redo)
            case IntentOp.DELETE:
                target.unlink(missing_ok=True)
                fsync_directory(target.parent)

    def _apply_append(
        self, record: JournalRecord, intent: Intent, target: Path, *, redo: bool
    ) -> None:
        expected = intent.expected_length_before or 0
        data = self._staged_bytes(record, _NEW, intent.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
        try:
            size = os.fstat(fd).st_size
            if redo:
                # Truncating first makes the redo idempotent: an append that already landed
                # is not duplicated, and a torn tail is dropped.
                if size < expected:
                    raise JournalError(
                        f"{intent.path} is shorter than transaction {record.tx_id} recorded "
                        f"({size} < {expected} bytes); recovery would have to invent data"
                    )
                if size > expected:
                    os.ftruncate(fd, expected)
            elif size != expected:
                raise JournalConflictError(
                    f"{intent.path} changed under transaction {record.tx_id}: "
                    f"expected {expected} bytes before the append, found {size}"
                )
            os.lseek(fd, expected, os.SEEK_SET)
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        fsync_directory(target.parent)

    def _commit_record(self, record: JournalRecord) -> None:
        """The commit point: after this rename the mutation is durable."""
        committed = self._layout.journal_dir / f"{record.tx_id}{COMMITTED_SUFFIX}"
        os.replace(self.record_path, committed)
        fsync_directory(self._layout.journal_dir)

    def _staged_bytes(self, record: JournalRecord, tree: str, key: str) -> bytes:
        path = self._layout.journal_dir / record.tx_id / tree / key
        try:
            return path.read_bytes()
        except OSError as exc:
            raise JournalError(f"journal {record.tx_id} lost staged content for {key}") from exc

    # -- helpers -------------------------------------------------------------

    def _key(self, path: Path | str) -> str:
        relative = self._layout.relative(path)
        if relative.parts[0] == RESEARCH_DIRNAME:
            raise WorkspaceError(
                f"{relative} is regenerable state; a canonical transaction never writes it"
            )
        return str(relative)

    def _claim(self, key: str, op: IntentOp) -> _Staged:
        staged = self._staged.get(key)
        if staged is None:
            staged = _Staged(op=op)
            self._staged[key] = staged
        elif staged.op is not op:
            raise WorkspaceError(
                f"{key} is already staged as {staged.op.value} in this transaction"
            )
        return staged


# -- recovery ----------------------------------------------------------------


def recover(layout: WorkspaceLayout) -> RecoveryReport:
    """Finish or undo every leftover transaction. Safe to run repeatedly."""
    journal = layout.journal_dir
    if not journal.is_dir():
        return RecoveryReport()
    clean_partials(journal)
    completed: list[str] = []
    rolled_back: list[str] = []
    cleaned: list[str] = []
    for tx_id in _leftover_transactions(journal):
        outcome = _recover_transaction(layout, tx_id)
        match outcome:
            case TransactionOutcome.COMPLETED:
                completed.append(tx_id)
            case TransactionOutcome.ROLLED_BACK:
                rolled_back.append(tx_id)
            case TransactionOutcome.CLEANED:
                cleaned.append(tx_id)
    report = RecoveryReport(tuple(completed), tuple(rolled_back), tuple(cleaned))
    if report.changed:
        logger.info("workspace journal recovery: %s", report.summary())
    return report


def _leftover_transactions(journal: Path) -> list[str]:
    ids: set[str] = set()
    for entry in journal.iterdir():
        name = entry.name
        if name.endswith(COMMITTED_SUFFIX):
            ids.add(name[: -len(COMMITTED_SUFFIX)])
        elif name.endswith(RECORD_SUFFIX):
            ids.add(name[: -len(RECORD_SUFFIX)])
        elif entry.is_dir():
            ids.add(name)
    return sorted(ids)


def _recover_transaction(layout: WorkspaceLayout, tx_id: str) -> TransactionOutcome:
    journal = layout.journal_dir
    committed = journal / f"{tx_id}{COMMITTED_SUFFIX}"
    if committed.exists():
        _clean_transaction(layout, tx_id)
        return TransactionOutcome.CLEANED
    record = _read_record(journal / f"{tx_id}{RECORD_SUFFIX}")
    if record is None or not record.prepared:
        _roll_back(layout, tx_id)
        return TransactionOutcome.ROLLED_BACK
    transaction = Transaction(layout, tx_id=tx_id)
    transaction._apply(record, redo=True)
    transaction._commit_record(record)
    _clean_transaction(layout, tx_id)
    return TransactionOutcome.COMPLETED


def _read_record(path: Path) -> JournalRecord | None:
    """Parse a journal record, treating an unreadable or torn file as 'not prepared'."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return JournalRecord.from_dict(payload)
    except JournalError:
        return None


def _roll_back(layout: WorkspaceLayout, tx_id: str) -> None:
    """Restore pre-images from the self-describing staging tree, then drop the transaction.

    A transaction only reaches the apply phase after its record lands, so a missing or torn
    record means nothing was applied; restoring is therefore always safe and idempotent.
    """
    staging = layout.journal_dir / tx_id
    for key in _mirrored_keys(staging / _PRE):
        atomic_write_bytes(layout.resolve(key), (staging / _PRE / key).read_bytes())
    for key in _mirrored_keys(staging / _TRUNCATE):
        _truncate_to(layout.resolve(key), (staging / _TRUNCATE / key).read_bytes())
    for key in _mirrored_keys(staging / _ABSENT):
        target = layout.resolve(key)
        target.unlink(missing_ok=True)
        fsync_directory(target.parent)
    _clean_transaction(layout, tx_id)


def _truncate_to(target: Path, recorded: bytes) -> None:
    if not target.is_file():
        return
    try:
        length = int(recorded.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError):  # pragma: no cover - staged by this module only
        return
    if target.stat().st_size <= length:
        return
    fd = os.open(target, os.O_RDWR)
    try:
        os.ftruncate(fd, length)
        os.fsync(fd)
    finally:
        os.close(fd)


def _mirrored_keys(tree: Path) -> Iterator[str]:
    if not tree.is_dir():
        return
    for path in sorted(tree.rglob("*")):
        if path.is_file():
            yield str(PurePosixPath(path.relative_to(tree).as_posix()))


def _clean_transaction(layout: WorkspaceLayout, tx_id: str) -> None:
    journal = layout.journal_dir
    shutil.rmtree(journal / tx_id, ignore_errors=True)
    (journal / f"{tx_id}{RECORD_SUFFIX}").unlink(missing_ok=True)
    (journal / f"{tx_id}{COMMITTED_SUFFIX}").unlink(missing_ok=True)
    fsync_directory(journal)


def _fsync_tree(root: Path) -> None:
    """Persist every staged directory entry, deepest first.

    The redo path reads its content out of this tree, so the directories that hold it must
    survive the same crash the record does.
    """
    for directory in sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True):
        fsync_directory(directory)
    fsync_directory(root)


def _encode_record(record: JournalRecord) -> bytes:
    return (json.dumps(record.as_dict(), sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")

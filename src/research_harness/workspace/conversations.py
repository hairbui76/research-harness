"""Durable storage for conversation sessions, transcripts, attachments, and context packs.

`ConversationStore` is to `conversations/` what `WorkspaceRepository` is to canonical
scientific state, with one deliberate difference: a session is *durable working context*,
not accepted state, so nothing here appends a `ResearchEvent` and nothing here is written
through a canonical transaction. What it does share is the durability machinery — the
workspace lock serializes writers, and every write goes through the journal, so a
transcript line and the session record it advances land together or not at all, and an
interrupted write is finished or undone by `recover()` on the next open.

**Counters.** `CS`, `M`, `SA`, and `CP` numbers are derived from the durable files under
`conversations/` — session directory names, each session's `last_message`, the attachment
and context-pack filenames — and never from `.research/`, so deleting the projection
cannot hand out an id twice. They are deliberately *not* kept in `research.yaml`: a
canonical transaction rewrites that file wholesale from its own cached config, so a
counter bumped here would be silently dropped by the next accepted-state mutation, and a
committed file should not churn every time the researcher sends a chat message. The
consequence to know about: this store has no delete operation, and when session deletion
is designed it must leave a tombstone (or a durable ledger), because a scan cannot see an
id that was removed.

**Authority.** Summaries are derived: `summary.md` is regenerated from the transcript and
never outranks it, nor accepted Evidence, Claims, or Decisions (Product 8.2).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from research_harness.domain.base import Provenance, utc_now
from research_harness.domain.conversation import (
    ContextPack,
    ConversationSession,
    Message,
    MessageRole,
    SessionAttachment,
    SessionDefaults,
    Visibility,
)
from research_harness.domain.errors import WorkspaceError
from research_harness.domain.ids import (
    ContextPackId,
    ConversationSessionId,
    MessageId,
    SessionAttachmentId,
)
from research_harness.workspace.journal import Transaction, recover
from research_harness.workspace.layout import (
    MESSAGES_FILENAME,
    SESSION_FILENAME,
    WorkspaceLayout,
)
from research_harness.workspace.locking import DEFAULT_LOCK_TIMEOUT, WorkspaceLock
from research_harness.workspace.serialization import (
    WorkspaceSerializationError,
    canonical_bytes,
    dump_jsonl_line,
    iter_jsonl,
    read_yaml,
)

if TYPE_CHECKING:  # pragma: no cover - typing only; the store never imports the repository
    from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "DEFAULT_SEARCH_LIMIT",
    "ConversationNotFoundError",
    "ConversationStore",
    "LockFactory",
    "SessionMatch",
    "SessionTranscript",
    "derive_summary",
]

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_LIMIT = 20
SUMMARY_OUTLINE_LIMIT = 20
"""Messages listed individually in a derived summary before it says "and N more"."""
SNIPPET_CONTEXT_CHARS = 40

_SESSION_DIR = re.compile(ConversationSessionId.pattern())
_ATTACHMENT_STEM = re.compile(SessionAttachmentId.pattern())
_PACK_STEM = re.compile(ContextPackId.pattern())
_WHITESPACE = re.compile(r"\s+")

type LockFactory = Callable[[], AbstractContextManager[Any]]


class ConversationNotFoundError(WorkspaceError):
    """No such session, message, attachment, or context pack in this workspace."""


@dataclass(frozen=True, slots=True)
class SessionMatch:
    """One session that matched a search, with the messages that matched inside it."""

    session: ConversationSessionId
    title: str
    title_matched: bool
    messages: tuple[MessageId, ...]
    snippet: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SessionTranscript:
    """Everything needed to resume a session: its record, transcript, and attachments."""

    session: ConversationSession
    messages: tuple[Message, ...]
    attachments: tuple[SessionAttachment, ...]


class ConversationStore:
    """Reader and writer of `conversations/` for one workspace.

    Reads touch no lock. Every write takes the workspace lock and commits through the
    journal, so concurrent CLI, editor, and daemon processes cannot interleave two
    appends or hand out the same `M####` twice.
    """

    def __init__(
        self,
        layout: WorkspaceLayout,
        *,
        lock: LockFactory | None = None,
        lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
    ) -> None:
        self._layout = layout
        self._lock_factory = lock
        self._lock_timeout = lock_timeout

    @classmethod
    def for_repository(cls, repository: WorkspaceRepository) -> ConversationStore:
        """Store sharing a repository's layout *and* its lock.

        `WorkspaceRepository.lock` is reentrant within one repository object, so a caller
        that already holds the workspace open for a canonical mutation (a promotion, say)
        can write the session side of it without deadlocking against itself.
        """
        return cls(repository.layout, lock=repository.lock)

    @property
    def layout(self) -> WorkspaceLayout:
        return self._layout

    # -- sessions ------------------------------------------------------------

    def create_session(
        self,
        *,
        title: str,
        provenance: Provenance,
        visibility: Visibility = Visibility.PRIVATE,
        defaults: SessionDefaults | None = None,
    ) -> ConversationSession:
        """Open a new session, allocating the next project-scoped `CS####`."""
        with self._locked():
            session_id = ConversationSessionId.next(
                path.name for path in self._session_directories()
            )
            session = ConversationSession(
                id=session_id,
                title=title,
                visibility=visibility,
                defaults=defaults or SessionDefaults(),
                provenance=provenance,
            )
            transaction = Transaction(self._layout)
            transaction.write(self._layout.session_file(session_id), canonical_bytes(session))
            self._commit(transaction)
            self._layout.session_attachments_dir(session_id).mkdir(parents=True, exist_ok=True)
            self._layout.session_context_dir(session_id).mkdir(parents=True, exist_ok=True)
        logger.info("opened conversation session %s (%s)", session_id, title)
        return session

    def get_session(self, session: ConversationSessionId) -> ConversationSession:
        """The durable session record, or `ConversationNotFoundError`."""
        path = self._layout.session_file(session)
        if not path.is_file():
            raise ConversationNotFoundError(
                f"no conversation session {session} in {self._layout.root}"
            )
        return read_yaml(path, ConversationSession)

    def list_sessions(self) -> list[ConversationSession]:
        """Every session in the project, ordered by id."""
        return [
            read_yaml(path / SESSION_FILENAME, ConversationSession)
            for path in self._session_directories()
            if (path / SESSION_FILENAME).is_file()
        ]

    def rename_session(self, session: ConversationSessionId, title: str) -> ConversationSession:
        """Give a session a new title. Ids, transcript, and attachments are untouched."""
        return self.update_session(session, title=title)

    def update_session(
        self,
        session: ConversationSessionId,
        *,
        title: str | None = None,
        visibility: Visibility | None = None,
        defaults: SessionDefaults | None = None,
    ) -> ConversationSession:
        """Change the session record's editable fields; unnamed fields keep their value."""
        updates: dict[str, Any] = {}
        if title is not None:
            updates["title"] = title
        if visibility is not None:
            updates["visibility"] = visibility
        if defaults is not None:
            updates["defaults"] = defaults
        with self._locked():
            record = self.get_session(session)
            if not updates:
                return record
            updated = record.touch(**updates)
            transaction = Transaction(self._layout)
            transaction.write(self._layout.session_file(session), canonical_bytes(updated))
            self._commit(transaction)
        return updated

    def resume(self, session: ConversationSessionId) -> SessionTranscript:
        """Everything a client needs to continue a prior session."""
        return SessionTranscript(
            session=self.get_session(session),
            messages=tuple(self.iter_messages(session)),
            attachments=tuple(self.list_attachments(session)),
        )

    # -- messages ------------------------------------------------------------

    def append_message(
        self, session: ConversationSessionId, build: Callable[[MessageId], Message]
    ) -> Message:
        """Append one message, allocating its `M####` under the lock.

        The id is allocated and the message built inside the lock, so ``build`` receives
        an id nothing else can take. The transcript line and the session record's
        counters are one journalled unit: a reader never sees a message the session does
        not count, or a count without its message.
        """
        with self._locked():
            record = self.get_session(session)
            message_id = MessageId.next(self._durable_message_ids())
            message = build(message_id)
            self._check_built(message, message_id, session, "message")
            updated = record.touch(
                message_count=record.message_count + 1,
                last_message=message.id,
                last_message_at=message.created_at,
            )
            transaction = Transaction(self._layout)
            transaction.append(
                self._layout.messages_file(session),
                dump_jsonl_line(message).encode("utf-8"),
            )
            transaction.write(self._layout.session_file(session), canonical_bytes(updated))
            self._commit(transaction)
        return message

    def iter_messages(self, session: ConversationSessionId) -> Iterator[Message]:
        """Stream a transcript in append order; a session with no messages yields none."""
        yield from iter_jsonl(self._layout.messages_file(session), Message)

    def messages(self, session: ConversationSessionId) -> list[Message]:
        """The whole transcript, in append order."""
        return list(self.iter_messages(session))

    def get_message(self, session: ConversationSessionId, message: MessageId) -> Message:
        """One message of a session, or `ConversationNotFoundError`."""
        for record in self.iter_messages(session):
            if record.id == message:
                return record
        raise ConversationNotFoundError(f"no message {message} in session {session}")

    def find_message(self, message: MessageId) -> Message | None:
        """Locate a message anywhere in the project, or `None`.

        A linear scan of the durable transcripts: the fallback for resolving `@M0042`
        when the projection has been deleted, not the path a UI should call per message.
        """
        for directory in self._session_directories():
            for record in iter_jsonl(directory / MESSAGES_FILENAME, Message):
                if record.id == message:
                    return record
        return None

    # -- search --------------------------------------------------------------

    def search(self, query: str, *, limit: int = DEFAULT_SEARCH_LIMIT) -> list[SessionMatch]:
        """Sessions whose title or message text contains ``query``, case-insensitively.

        Direct transcript access, so it keeps working when the projection is gone
        (conversation design SS8); ranked retrieval belongs to the graph index.
        """
        needle = query.strip().casefold()
        if not needle:
            return []
        matches: list[SessionMatch] = []
        for session in self.list_sessions():
            title_matched = needle in session.title.casefold()
            hits: list[MessageId] = []
            snippet: str | None = None
            for message in self.iter_messages(session.id):
                text = message.text()
                position = text.casefold().find(needle)
                if position < 0:
                    continue
                hits.append(message.id)
                if snippet is None:
                    snippet = _snippet(text, position, len(needle))
            if title_matched or hits:
                matches.append(
                    SessionMatch(
                        session=session.id,
                        title=session.title,
                        title_matched=title_matched,
                        messages=tuple(hits),
                        snippet=snippet,
                        updated_at=session.updated_at,
                    )
                )
        matches.sort(key=lambda match: (-match.updated_at.timestamp(), str(match.session)))
        return matches[:limit]

    # -- attachments ---------------------------------------------------------

    def add_attachment(
        self,
        session: ConversationSessionId,
        build: Callable[[SessionAttachmentId], SessionAttachment],
        *,
        data: bytes | None = None,
    ) -> SessionAttachment:
        """Record a new attachment, allocating the next project-scoped `SA####`.

        Passing ``data`` writes the original bytes in the same journalled unit as the
        metadata, which is what makes "durably copied into the session" true the moment
        the id exists (attachments design SS2).
        """
        with self._locked():
            self.get_session(session)
            attachment_id = SessionAttachmentId.next(self._attachment_ids())
            attachment = build(attachment_id)
            self._check_built(attachment, attachment_id, session, "attachment")
            transaction = Transaction(self._layout)
            transaction.write(
                self._layout.session_attachment_file(session, attachment_id),
                canonical_bytes(attachment),
            )
            if data is not None:
                transaction.write(self._layout.session_attachment_bytes_file(attachment), data)
            self._commit(transaction)
        return attachment

    def put_attachment(self, attachment: SessionAttachment) -> SessionAttachment:
        """Persist an updated attachment record: a state transition, or a corpus link."""
        path = self._layout.session_attachment_file(attachment.session, attachment.id)
        with self._locked():
            if not path.is_file():
                raise ConversationNotFoundError(
                    f"no attachment {attachment.id} in session {attachment.session}"
                )
            transaction = Transaction(self._layout)
            transaction.write(path, canonical_bytes(attachment))
            self._commit(transaction)
        return attachment

    def get_attachment(
        self, session: ConversationSessionId, attachment: SessionAttachmentId
    ) -> SessionAttachment:
        path = self._layout.session_attachment_file(session, attachment)
        if not path.is_file():
            raise ConversationNotFoundError(f"no attachment {attachment} in session {session}")
        return read_yaml(path, SessionAttachment)

    def list_attachments(self, session: ConversationSessionId) -> list[SessionAttachment]:
        """Every attachment of a session, ordered by id."""
        return [
            read_yaml(path, SessionAttachment)
            for path in _members(
                self._layout.session_attachments_dir(session), _ATTACHMENT_STEM, ".yaml"
            )
        ]

    def attachment_bytes_path(self, attachment: SessionAttachment) -> Path:
        """Where this attachment's original bytes live."""
        return self._layout.session_attachment_bytes_file(attachment)

    def store_attachment_bytes(self, attachment: SessionAttachment, data: bytes) -> Path:
        """Write the original bytes; they are immutable once stored.

        Re-storing identical bytes succeeds (a retried intake is not a conflict); storing
        different bytes under an existing id is refused, because an `SA####` names one
        file and a preview or a promotion may already have read it.
        """
        path = self.attachment_bytes_path(attachment)
        with self._locked():
            if path.is_file():
                if path.read_bytes() == data:
                    return path
                raise WorkspaceError(
                    f"attachment {attachment.id} already stores different bytes at {path}; "
                    "original attachment bytes are immutable"
                )
            transaction = Transaction(self._layout)
            transaction.write(path, data)
            self._commit(transaction)
        return path

    def read_attachment_bytes(self, attachment: SessionAttachment) -> bytes:
        path = self.attachment_bytes_path(attachment)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise ConversationNotFoundError(
                f"attachment {attachment.id} has no stored bytes at {path}"
            ) from exc

    # -- context packs -------------------------------------------------------

    def write_context_pack(
        self, session: ConversationSessionId, build: Callable[[ContextPackId], ContextPack]
    ) -> ContextPack:
        """Record one call's `ContextPack` and receipt, allocating the next `CP####`."""
        with self._locked():
            self.get_session(session)
            pack_id = ContextPackId.next(self._context_pack_ids())
            pack = build(pack_id)
            self._check_built(pack, pack_id, session, "context pack")
            transaction = Transaction(self._layout)
            transaction.write(self._layout.context_pack_file(session, pack_id), _dump_json(pack))
            self._commit(transaction)
        return pack

    def read_context_pack(self, session: ConversationSessionId, pack: ContextPackId) -> ContextPack:
        """One recorded pack, so a researcher can explain what the model saw."""
        path = self._layout.context_pack_file(session, pack)
        if not path.is_file():
            raise ConversationNotFoundError(f"no context pack {pack} in session {session}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceSerializationError(f"invalid context pack: {exc}", source=path) from exc
        try:
            return ContextPack.model_validate(payload)
        except ValidationError as exc:
            raise WorkspaceSerializationError(
                f"not a valid ContextPack: {exc}", source=path
            ) from exc

    def list_context_packs(self, session: ConversationSessionId) -> list[ContextPackId]:
        """Ids of every pack recorded for a session, in order."""
        return [
            ContextPackId(path.stem)
            for path in _members(self._layout.session_context_dir(session), _PACK_STEM, ".json")
        ]

    # -- derived summaries ---------------------------------------------------

    def read_summary(self, session: ConversationSessionId) -> str | None:
        """The session's `summary.md`, or `None` when none has been written."""
        path = self._layout.session_summary_file(session)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def write_summary(
        self,
        session: ConversationSessionId,
        text: str,
        *,
        through: MessageId | None = None,
    ) -> str:
        """Replace the derived summary and record how far it covers the transcript.

        The file and the session record move together, so a summary is never silently
        older than the message the record says it covers.
        """
        with self._locked():
            record = self.get_session(session)
            written_at = utc_now()
            updated = record.touch(
                summarized_through=through if through is not None else record.last_message,
                summary_updated_at=written_at,
                updated_at=written_at,
            )
            transaction = Transaction(self._layout)
            transaction.write(self._layout.session_summary_file(session), text.encode("utf-8"))
            transaction.write(self._layout.session_file(session), canonical_bytes(updated))
            self._commit(transaction)
        return text

    def regenerate_summary(self, session: ConversationSessionId) -> str:
        """Rebuild `summary.md` from the transcript. Deterministic and repeatable."""
        transcript = self.resume(session)
        text = derive_summary(transcript.session, transcript.messages, transcript.attachments)
        return self.write_summary(session, text, through=transcript.session.last_message)

    # -- internals -----------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold the workspace lock, reusing the caller's when one was supplied."""
        if self._lock_factory is not None:
            with self._lock_factory():
                yield
            return
        with WorkspaceLock(self._layout, self._lock_timeout):
            yield

    def _commit(self, transaction: Transaction) -> None:
        """Commit one journalled unit, recovering the workspace if it fails mid-flight."""
        try:
            transaction.commit()
        except BaseException:
            recover(self._layout)
            raise

    def _session_directories(self) -> list[Path]:
        root = self._layout.conversations_dir
        if not root.is_dir():
            return []
        return sorted(
            path for path in root.iterdir() if path.is_dir() and _SESSION_DIR.fullmatch(path.name)
        )

    def _durable_message_ids(self) -> list[str]:
        """Every session's highest message id, read from the durable records.

        `session.yaml` and `messages.jsonl` are written in one journalled unit, so the
        session record is enough; a session whose record was lost falls back to its own
        transcript rather than restarting the numbering.
        """
        highest: list[str] = []
        for directory in self._session_directories():
            record = directory / SESSION_FILENAME
            if record.is_file():
                session = read_yaml(record, ConversationSession)
                if session.last_message is not None:
                    highest.append(str(session.last_message))
                continue
            highest.extend(
                str(message.id) for message in iter_jsonl(directory / MESSAGES_FILENAME, Message)
            )
        return highest

    def _attachment_ids(self) -> list[str]:
        return [
            path.stem
            for directory in self._session_directories()
            for path in _members(directory / "attachments", _ATTACHMENT_STEM, ".yaml")
        ]

    def _context_pack_ids(self) -> list[str]:
        return [
            path.stem
            for directory in self._session_directories()
            for path in _members(directory / "context", _PACK_STEM, ".json")
        ]

    def _check_built(
        self,
        built: Message | SessionAttachment | ContextPack,
        allocated: MessageId | SessionAttachmentId | ContextPackId,
        session: ConversationSessionId,
        what: str,
    ) -> None:
        if built.id != allocated:
            raise WorkspaceError(
                f"the {what} was built with id {built.id}, but {allocated} was allocated"
            )
        if built.session != session:
            raise WorkspaceError(f"{what} {built.id} names session {built.session}, not {session}")


# -- module helpers ----------------------------------------------------------


def derive_summary(
    session: ConversationSession,
    messages: Sequence[Message],
    attachments: Sequence[SessionAttachment] = (),
) -> str:
    """Build the derived `summary.md` for a session.

    Pure and deterministic: the same transcript always yields the same bytes, so
    regenerating a summary is a no-op diff. Nothing here is a conclusion — the footer
    says so, because a summary that reads like accepted state would be a lie.
    """
    counts = dict.fromkeys(MessageRole, 0)
    for message in messages:
        counts[message.role] += 1
    tally = ", ".join(f"{counts[role]} {role.value}" for role in MessageRole if counts[role])
    lines = [
        f"# {session.title}",
        "",
        f"- Session: `{session.id}`",
        f"- Opened: {session.created_at.isoformat()}",
        f"- Messages: {len(messages)}" + (f" ({tally})" if tally else ""),
        f"- Visibility: {session.visibility.value}",
    ]
    if session.last_message is not None and session.last_message_at is not None:
        lines.append(
            f"- Last message: `{session.last_message}` at {session.last_message_at.isoformat()}"
        )
    if attachments:
        listed = ", ".join(
            f"`{attachment.id}` {attachment.filename} ({attachment.state.value})"
            for attachment in attachments
        )
        lines.append(f"- Attachments: {listed}")
    lines.extend(["", "## Outline", ""])
    if not messages:
        lines.append("_No messages yet._")
    for index, message in enumerate(messages[:SUMMARY_OUTLINE_LIMIT], start=1):
        flag = " _(incomplete)_" if message.incomplete else ""
        lines.append(
            f"{index}. **{message.role.value}** `{message.id}`{flag} — {_one_line(message.text())}"
        )
    remaining = len(messages) - SUMMARY_OUTLINE_LIMIT
    if remaining > 0:
        lines.append(f"…and {remaining} more message(s) in the transcript.")
    lines.extend(
        [
            "",
            "---",
            "",
            f"Derived from `conversations/{session.id}/{MESSAGES_FILENAME}` and regenerable "
            "at any time. A summary never outranks the transcript, and neither outranks "
            "accepted Evidence, Claims, or Decisions.",
            "",
        ]
    )
    return "\n".join(lines)


def _members(directory: Path, stem: re.Pattern[str], suffix: str) -> list[Path]:
    """Files in ``directory`` whose stem is a well-formed id, ordered by name."""
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.glob(f"*{suffix}")
        if path.is_file() and stem.fullmatch(path.stem)
    )


def _dump_json(pack: ContextPack) -> bytes:
    """A context pack as deterministic, readable JSON (sorted keys, one trailing newline)."""
    payload = json.dumps(pack.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False)
    return (payload + "\n").encode("utf-8")


def _one_line(text: str, limit: int = 120) -> str:
    """Collapse a message to one readable line for an outline entry."""
    collapsed = _WHITESPACE.sub(" ", text).strip()
    if not collapsed:
        return "_(no text)_"
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _snippet(text: str, position: int, length: int) -> str:
    """A one-line excerpt around a search hit, with ellipses where it was cut."""
    start = max(position - SNIPPET_CONTEXT_CHARS, 0)
    end = min(position + length + SNIPPET_CONTEXT_CHARS, len(text))
    excerpt = _WHITESPACE.sub(" ", text[start:end]).strip()
    return f"{'…' if start > 0 else ''}{excerpt}{'…' if end < len(text) else ''}"

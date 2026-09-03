"""Manuscript source files: an honest tree, explicit reads, and conflict-checked writes.

Files under `manuscript/` are ordinary user-owned project files (LaTeX spec 4). Nothing
here rewrites one on the harness's own initiative: every mutation names the file, carries
the hash the caller believed it was editing, and is refused when the bytes on disk say
somebody else — an external editor, a `git checkout`, a co-author — changed it first. That
refusal is the whole point of :class:`ManuscriptConflictError`: a save that silently wins
over an outside edit is data loss, and a manuscript is the one place in the workspace where
the researcher, not the harness, is the author.

Confinement is the second rule. A relative POSIX path is the only thing this module
accepts, `..` and absolute paths are refused before they reach the filesystem, and a
symlink whose target leaves `manuscript/` is refused after resolution, so a path from a
transport can never read or write outside the manuscript tree.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from research_harness.domain.base import Sha256, UtcDatetime
from research_harness.domain.errors import ResearchHarnessError
from research_harness.workspace.atomic import atomic_write_bytes
from research_harness.workspace.layout import ANCHORS_FILENAME, WorkspaceLayout

__all__ = [
    "BIB_SUFFIXES",
    "BUILD_ARTEFACT_SUFFIXES",
    "IMAGE_SUFFIXES",
    "MAX_FILE_BYTES",
    "MAX_TEXT_BYTES",
    "TEX_SUFFIXES",
    "FileSnapshot",
    "ManuscriptBinaryFileError",
    "ManuscriptConflictError",
    "ManuscriptFile",
    "ManuscriptFileError",
    "ManuscriptFileExistsError",
    "ManuscriptFileKind",
    "ManuscriptFileNotFoundError",
    "ManuscriptFiles",
    "ManuscriptPathError",
    "content_hash",
    "normalize_relative_path",
]


# --------------------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------------------


class ManuscriptFileError(ResearchHarnessError):
    """A manuscript file operation was refused; the message names the file."""


class ManuscriptPathError(ManuscriptFileError, ValueError):
    """A path is unsafe: absolute, hidden, escaping `manuscript/`, or otherwise refused.

    Also a ``ValueError`` so a Pydantic field validator turns it into a normal validation
    error when a configured entry file is malformed.
    """


class ManuscriptFileNotFoundError(ManuscriptFileError):
    """The named manuscript file does not exist."""


class ManuscriptFileExistsError(ManuscriptFileError):
    """The target already exists and this operation refuses to overwrite it."""


class ManuscriptBinaryFileError(ManuscriptFileError):
    """The file is not decodable text (an image, a PDF figure, or a truncated file)."""


class ManuscriptConflictError(ManuscriptFileError):
    """The bytes on disk are not the ones the caller believed it was editing.

    Raised before anything is written, so the file keeps the content the other writer
    left. ``expected_hash`` is what the caller sent, ``actual_hash`` is what is on disk;
    a client resolves the conflict by re-reading and merging, never by retrying blind.
    """

    def __init__(self, path: str, *, expected_hash: str, actual_hash: str) -> None:
        self.path = path
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        super().__init__(
            f"{path} changed outside the harness: expected {expected_hash}, "
            f"found {actual_hash}; re-read the file before saving again"
        )


# --------------------------------------------------------------------------------------
# vocabulary and file classification
# --------------------------------------------------------------------------------------


class ManuscriptFileKind(StrEnum):
    """What a manuscript file is, which decides how a client offers to open it."""

    TEX = "tex"
    BIB = "bib"
    IMAGE = "image"
    OTHER = "other"


TEX_SUFFIXES: frozenset[str] = frozenset({".tex", ".ltx", ".sty", ".cls", ".clo", ".bst"})
BIB_SUFFIXES: frozenset[str] = frozenset({".bib"})
IMAGE_SUFFIXES: frozenset[str] = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".eps", ".ps", ".svg", ".tif", ".tiff"}
)

BUILD_ARTEFACT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".aux",
        ".bbl",
        ".bcf",
        ".blg",
        ".dvi",
        ".fdb_latexmk",
        ".fls",
        ".idx",
        ".ilg",
        ".ind",
        ".lof",
        ".log",
        ".lot",
        ".nav",
        ".out",
        ".snm",
        ".synctex",
        ".toc",
        ".vrb",
        ".xdv",
    }
)
"""Compiler leftovers a researcher may have next to their source; never listed as input.

`.gz` is handled separately so that `main.synctex.gz` is excluded too, and `.pdf` is
deliberately absent: under `manuscript/` a PDF is a figure, because the harness compiles
into `.research/build/` and never beside the source.
"""

MAX_TEXT_BYTES = 8 * 1024 * 1024
"""Refuse to load anything larger as editable text; a manuscript file is never this big."""

MAX_FILE_BYTES = 64 * 1024 * 1024
"""Ceiling for handing raw bytes to a caller; a figure is allowed to be much bigger than
an editable source file, but not unbounded, because a transport reads the result into
memory."""

_MAX_PATH_LENGTH = 1024
_FORBIDDEN_CHARS = frozenset({":", "\\", "\x00"})


def _kind_for(name: str) -> ManuscriptFileKind:
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in TEX_SUFFIXES:
        return ManuscriptFileKind.TEX
    if suffix in BIB_SUFFIXES:
        return ManuscriptFileKind.BIB
    if suffix in IMAGE_SUFFIXES:
        return ManuscriptFileKind.IMAGE
    return ManuscriptFileKind.OTHER


def _is_build_artefact(name: str) -> bool:
    lowered = name.lower()
    if lowered.endswith(".gz"):
        lowered = lowered[: -len(".gz")]
    return PurePosixPath(lowered).suffix in BUILD_ARTEFACT_SUFFIXES


def normalize_relative_path(value: str) -> PurePosixPath:
    """Validate a workspace-relative POSIX manuscript path, or refuse it.

    Refuses the empty path, absolute paths, Windows separators and drive letters, `..`
    segments, and any hidden component: a client sends the same string it was listed
    with, and anything else is a traversal attempt or a mistake, never a file to open.
    """
    text = value.strip()
    if not text:
        raise ManuscriptPathError("a manuscript path cannot be empty")
    if len(text) > _MAX_PATH_LENGTH:
        raise ManuscriptPathError(f"manuscript path is too long ({len(text)} characters)")
    if any(char in _FORBIDDEN_CHARS for char in text):
        raise ManuscriptPathError(
            f"unsafe manuscript path {value!r}: use relative POSIX paths without ':' or '\\'"
        )
    if any(ord(char) < 0x20 for char in text):
        raise ManuscriptPathError(f"unsafe manuscript path {value!r}: control characters")
    candidate = PurePosixPath(text)
    if candidate.is_absolute():
        raise ManuscriptPathError(f"{value!r} is absolute; manuscript paths are relative")
    parts = tuple(part for part in candidate.parts if part != ".")
    if not parts:
        raise ManuscriptPathError(f"{value!r} does not name a file")
    for part in parts:
        if part == "..":
            raise ManuscriptPathError(f"{value!r} escapes the manuscript directory")
        if part.startswith(".") or part == "~":
            raise ManuscriptPathError(
                f"{value!r} names a hidden entry, which is not manuscript source"
            )
    return PurePosixPath(*parts)


def content_hash(data: bytes) -> str:
    """`sha256:<hex>` over the exact bytes on disk; the token a save is checked against."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


# --------------------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------------------


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ManuscriptFile(_Record):
    """One entry of the manuscript tree, keyed by its relative POSIX path."""

    path: str
    kind: ManuscriptFileKind
    size_bytes: int = Field(ge=0)
    modified_at: UtcDatetime


class FileSnapshot(_Record):
    """A file's text plus the hash a later save must present to prove it saw this version."""

    path: str
    kind: ManuscriptFileKind
    content: str
    content_hash: Sha256
    size_bytes: int = Field(ge=0)
    modified_at: UtcDatetime


# --------------------------------------------------------------------------------------
# the service
# --------------------------------------------------------------------------------------


class ManuscriptFiles:
    """Read and write the user-owned source under `manuscript/`, and nothing else."""

    def __init__(self, workspace: WorkspaceLayout | Path | str) -> None:
        layout = workspace if isinstance(workspace, WorkspaceLayout) else WorkspaceLayout(workspace)
        self._layout = layout
        self._root = layout.manuscript_dir

    def __repr__(self) -> str:
        return f"ManuscriptFiles({str(self._root)!r})"

    @property
    def layout(self) -> WorkspaceLayout:
        return self._layout

    @property
    def root(self) -> Path:
        """The `manuscript/` directory; every path this service accepts is relative to it."""
        return self._root

    # -- confinement ---------------------------------------------------------

    def path_for(self, path: str | PurePosixPath) -> Path:
        """Absolute path of a manuscript-relative path, refusing anything that escapes.

        The syntactic check runs first (absolute, `..`, hidden, Windows separators), then
        the resolved path is compared against the resolved manuscript root so a symlink
        pointing outside the tree is refused even though its name looked innocent.
        """
        relative = normalize_relative_path(str(path))
        target = self._root.joinpath(*relative.parts)
        root = _resolve(self._root)
        resolved = _resolve(target)
        if resolved != root and root not in resolved.parents:
            raise ManuscriptPathError(
                f"{path} resolves to {resolved}, which is outside the manuscript directory"
            )
        if relative.parts == (ANCHORS_FILENAME,):
            raise ManuscriptPathError(
                f"{ANCHORS_FILENAME} is harness-managed anchor state, not manuscript source"
            )
        return target

    # -- reading -------------------------------------------------------------

    def tree(self) -> tuple[ManuscriptFile, ...]:
        """Every source file under `manuscript/`, sorted by path.

        Hidden entries, compiler leftovers, the harness's `anchors.jsonl`, and anything
        reachable only through a symlink that leaves the tree are excluded: the list is
        what a researcher can open and edit, not what happens to sit in the directory.
        """
        if not self._root.is_dir():
            return ()
        found: list[ManuscriptFile] = []
        for directory, subdirectories, filenames in os.walk(self._root):
            subdirectories[:] = sorted(name for name in subdirectories if not name.startswith("."))
            for filename in sorted(filenames):
                if filename.startswith(".") or _is_build_artefact(filename):
                    continue
                if filename == ANCHORS_FILENAME and Path(directory) == self._root:
                    continue
                absolute = Path(directory) / filename
                try:
                    relative = self._relative(absolute)
                    self.path_for(relative)
                    stat = absolute.stat()
                except (ManuscriptPathError, OSError):
                    continue
                found.append(
                    ManuscriptFile(
                        path=relative,
                        kind=_kind_for(filename),
                        size_bytes=stat.st_size,
                        modified_at=_mtime(stat.st_mtime),
                    )
                )
        return tuple(sorted(found, key=lambda entry: entry.path))

    def exists(self, path: str | PurePosixPath) -> bool:
        """True when the path is safe and names an existing regular file."""
        try:
            return self.path_for(path).is_file()
        except ManuscriptPathError:
            return False

    def read(self, path: str | PurePosixPath) -> FileSnapshot:
        """Load a file as text with the hash a later :meth:`write` must present."""
        target = self.path_for(path)
        data = self._read_bytes(target, str(path))
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ManuscriptBinaryFileError(
                f"{path} is not UTF-8 text and cannot be opened in the source editor"
            ) from error
        stat = target.stat()
        return FileSnapshot(
            path=self._relative(target),
            kind=_kind_for(target.name),
            content=content,
            content_hash=content_hash(data),
            size_bytes=stat.st_size,
            modified_at=_mtime(stat.st_mtime),
        )

    def read_bytes(self, path: str | PurePosixPath) -> bytes:
        """Raw bytes of a manuscript file — how a client fetches a figure."""
        target = self.path_for(path)
        self._require_file(target, str(path))
        if target.stat().st_size > MAX_FILE_BYTES:
            raise ManuscriptFileError(
                f"{path} is larger than the {MAX_FILE_BYTES}-byte manuscript file limit"
            )
        return target.read_bytes()

    def hash_of(self, path: str | PurePosixPath) -> str:
        """Current `sha256:` hash of a file's bytes, whatever its size or encoding."""
        target = self.path_for(path)
        self._require_file(target, str(path))
        return _digest_file(target)

    def fingerprint(self) -> str:
        """One `sha256:` digest over every listed source file's path and content.

        This is the inputs fingerprint a build records: it changes when any source file is
        added, removed, renamed, or edited, and it does not change when a build artefact
        appears beside the source.
        """
        digest = hashlib.sha256()
        for entry in self.tree():
            try:
                file_hash = _digest_file(self.path_for(entry.path))
            except OSError:  # pragma: no cover - the file vanished between walk and read
                continue
            digest.update(entry.path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_hash.encode("ascii"))
            digest.update(b"\n")
        return f"sha256:{digest.hexdigest()}"

    # -- writing -------------------------------------------------------------

    def write(self, path: str | PurePosixPath, content: str, expected_hash: str) -> FileSnapshot:
        """Replace a file's text, refusing when the bytes on disk are not ``expected_hash``.

        The write is atomic (temp file in the same directory, fsync, rename), so a reader
        or a compiler running concurrently sees either the old file or the new one.
        """
        target = self.path_for(path)
        self._require_current(target, str(path), expected_hash)
        return self._store(target, content)

    def create(self, path: str | PurePosixPath, content: str = "") -> FileSnapshot:
        """Create a new file, refusing to overwrite one that already exists."""
        target = self.path_for(path)
        if target.exists():
            raise ManuscriptFileExistsError(f"{path} already exists in the manuscript")
        return self._store(target, content)

    def rename(
        self,
        path: str | PurePosixPath,
        new_path: str | PurePosixPath,
        *,
        expected_hash: str | None = None,
    ) -> ManuscriptFile:
        """Move a file inside `manuscript/`, refusing to overwrite the destination.

        Returns the moved file's tree entry rather than its text, because a figure is
        renamed as often as a section and has no text to return.
        """
        source = self.path_for(path)
        destination = self.path_for(new_path)
        self._require_file(source, str(path))
        if expected_hash is not None:
            self._require_current(source, str(path), expected_hash)
        if destination.exists():
            raise ManuscriptFileExistsError(f"{new_path} already exists in the manuscript")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        stat = destination.stat()
        return ManuscriptFile(
            path=self._relative(destination),
            kind=_kind_for(destination.name),
            size_bytes=stat.st_size,
            modified_at=_mtime(stat.st_mtime),
        )

    def delete(self, path: str | PurePosixPath, expected_hash: str) -> None:
        """Delete a file, refusing when the bytes on disk are not ``expected_hash``."""
        target = self.path_for(path)
        self._require_current(target, str(path), expected_hash)
        target.unlink()

    # -- internals -----------------------------------------------------------

    def _store(self, target: Path, content: str) -> FileSnapshot:
        data = content.encode("utf-8")
        if len(data) > MAX_TEXT_BYTES:
            raise ManuscriptFileError(
                f"{self._relative(target)} would be {len(data)} bytes, "
                f"over the {MAX_TEXT_BYTES}-byte manuscript source limit"
            )
        atomic_write_bytes(target, data)
        stat = target.stat()
        return FileSnapshot(
            path=self._relative(target),
            kind=_kind_for(target.name),
            content=content,
            content_hash=content_hash(data),
            size_bytes=stat.st_size,
            modified_at=_mtime(stat.st_mtime),
        )

    def _require_file(self, target: Path, label: str) -> None:
        if not target.is_file():
            raise ManuscriptFileNotFoundError(f"no manuscript file at {label}")

    def _require_current(self, target: Path, label: str, expected_hash: str) -> None:
        """Refuse the mutation unless the bytes on disk are the ones the caller last saw."""
        self._require_file(target, label)
        actual = _digest_file(target)
        if actual != expected_hash:
            raise ManuscriptConflictError(
                self._relative(target), expected_hash=expected_hash, actual_hash=actual
            )

    def _read_bytes(self, target: Path, label: str) -> bytes:
        self._require_file(target, label)
        stat = target.stat()
        if stat.st_size > MAX_TEXT_BYTES:
            raise ManuscriptBinaryFileError(
                f"{label} is {stat.st_size} bytes, over the {MAX_TEXT_BYTES}-byte limit"
            )
        try:
            return target.read_bytes()
        except OSError as error:  # pragma: no cover - unreadable file
            raise ManuscriptFileError(f"cannot read {label}: {error}") from error

    def _relative(self, absolute: Path) -> str:
        try:
            return absolute.relative_to(self._root).as_posix()
        except ValueError:
            resolved = _resolve(absolute).relative_to(_resolve(self._root))
            return resolved.as_posix()


def _digest_file(path: Path) -> str:
    """`sha256:<hex>` over a file's bytes, read in chunks so size is never a limit."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - unresolvable paths simply stay outside the root
        return path


def _mtime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, UTC)

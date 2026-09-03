"""Content hashing and MIME sniffing for immutable source artifacts (Product 13, 34).

Artifact identity is the bytes, not the filename: the same file ingested twice hashes
identically however it is named, and a one-byte change yields a different hash so a
revision becomes a new Artifact instead of silently overwriting the registered one
(ADR-002).
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from pydantic import Field

from research_harness.domain.base import DomainModel, NonEmptyStr, Sha256
from research_harness.domain.enums import ArtifactKind

__all__ = [
    "ALGORITHM",
    "DEFAULT_MIME_TYPE",
    "ArtifactFingerprint",
    "artifact_kind_for_mime",
    "fingerprint_file",
    "sha256_bytes",
    "sha256_file",
    "sniff_mime_type",
]

ALGORITHM = "sha256"
DEFAULT_MIME_TYPE = "application/octet-stream"

_CHUNK_SIZE = 1024 * 1024
#: Enough bytes for every magic number below; the tar signature sits at offset 257.
_SNIFF_BYTES = 512
_ZIP_MAGIC = frozenset({b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"})
_HTML_MAGIC = (b"<!doctype html", b"<html")
_HTML_LEADING = b"\xef\xbb\xbf \t\r\n"

_MIME_ARTIFACT_KINDS: dict[str, ArtifactKind] = {
    "application/pdf": ArtifactKind.PDF,
    "text/html": ArtifactKind.HTML,
    "application/xhtml+xml": ArtifactKind.HTML,
    "application/zip": ArtifactKind.CODE,
    "application/gzip": ArtifactKind.CODE,
    "application/x-tar": ArtifactKind.CODE,
}


def sha256_bytes(data: bytes) -> Sha256:
    """Return ``sha256:<hex>`` over ``data``."""
    return f"{ALGORITHM}:{hashlib.sha256(data).hexdigest()}"


def sha256_file(path: Path | str) -> Sha256:
    """Return ``sha256:<hex>`` over a file's bytes, streamed so large PDFs stay cheap."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return f"{ALGORITHM}:{digest.hexdigest()}"


def sniff_mime_type(path: Path | str) -> str:
    """Best-effort MIME type from magic bytes, falling back to the filename extension."""
    file_path = Path(path)
    with file_path.open("rb") as handle:
        head = handle.read(_SNIFF_BYTES)
    sniffed = _mime_from_magic(head)
    if sniffed is not None:
        return sniffed
    guessed, _ = mimetypes.guess_type(file_path.name)
    return guessed or DEFAULT_MIME_TYPE


def artifact_kind_for_mime(mime_type: str) -> ArtifactKind:
    """Map a MIME type onto an :class:`ArtifactKind`; unknown types are ``other``."""
    base = mime_type.split(";")[0].strip().casefold()
    return _MIME_ARTIFACT_KINDS.get(base, ArtifactKind.OTHER)


def _mime_from_magic(head: bytes) -> str | None:
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head[:4] in _ZIP_MAGIC:
        return "application/zip"
    if head[:2] == b"\x1f\x8b":
        return "application/gzip"
    if head[257:262] == b"ustar":
        return "application/x-tar"
    leading = head.lstrip(_HTML_LEADING).lower()
    if leading.startswith(_HTML_MAGIC):
        return "text/html"
    return None


class ArtifactFingerprint(DomainModel):
    """Everything artifact identity and mutation detection depend on for one file."""

    sha256: Sha256
    size_bytes: int = Field(ge=0)
    mime_type: NonEmptyStr
    original_filename: NonEmptyStr

    @property
    def artifact_kind(self) -> ArtifactKind:
        """Artifact kind implied by the sniffed MIME type."""
        return artifact_kind_for_mime(self.mime_type)


def fingerprint_file(path: Path | str) -> ArtifactFingerprint:
    """Hash, measure, type, and name a local file without reading it into memory twice."""
    file_path = Path(path)
    return ArtifactFingerprint(
        sha256=sha256_file(file_path),
        size_bytes=file_path.stat().st_size,
        mime_type=sniff_mime_type(file_path),
        original_filename=file_path.name,
    )

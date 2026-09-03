"""Artifact hashing and MIME sniffing: identity is the bytes, not the filename."""

from __future__ import annotations

import gzip
import re
import tarfile
import zipfile
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from research_harness.domain.base import Sha256
from research_harness.domain.enums import ArtifactKind
from research_harness.ingest.hashing import (
    DEFAULT_MIME_TYPE,
    ArtifactFingerprint,
    artifact_kind_for_mime,
    fingerprint_file,
    sha256_bytes,
    sha256_file,
    sniff_mime_type,
)

KNOWN_BYTES = b"research harness"
KNOWN_DIGEST = "sha256:46bf83b21a24acb3247ddbb516f4299c47d8ac4ba6e714010f498bac0db7f589"
EMPTY_DIGEST = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

_SHA256 = TypeAdapter(Sha256)


def test_sha256_bytes_matches_the_known_digest_of_known_bytes() -> None:
    assert sha256_bytes(KNOWN_BYTES) == KNOWN_DIGEST
    assert sha256_bytes(b"") == EMPTY_DIGEST


def test_digests_are_valid_domain_sha256_values() -> None:
    assert _SHA256.validate_python(sha256_bytes(KNOWN_BYTES)) == KNOWN_DIGEST
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", sha256_bytes(KNOWN_BYTES))


def test_sha256_file_streams_to_the_same_digest_as_sha256_bytes(tmp_path: Path) -> None:
    payload = KNOWN_BYTES * 200_000  # larger than one read chunk
    path = tmp_path / "big.bin"
    path.write_bytes(payload)
    assert sha256_file(path) == sha256_bytes(payload)


def test_same_bytes_under_a_different_filename_hash_identically(tmp_path: Path) -> None:
    first = tmp_path / "downloaded.pdf"
    second = tmp_path / "renamed-by-the-researcher.pdf"
    first.write_bytes(b"%PDF-1.7\n" + KNOWN_BYTES)
    second.write_bytes(b"%PDF-1.7\n" + KNOWN_BYTES)

    left = fingerprint_file(first)
    right = fingerprint_file(second)

    assert left.sha256 == right.sha256
    assert left.original_filename != right.original_filename


def test_a_one_byte_change_changes_the_hash(tmp_path: Path) -> None:
    original = tmp_path / "v1.bin"
    revised = tmp_path / "v2.bin"
    original.write_bytes(b"research harness")
    revised.write_bytes(b"research harnesr")

    assert sha256_file(original) != sha256_file(revised)


def test_fingerprint_records_size_mime_type_and_original_filename(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    payload = b"%PDF-1.7\n% a tiny stub\n"
    path.write_bytes(payload)

    fingerprint = fingerprint_file(path)

    assert fingerprint.sha256 == sha256_bytes(payload)
    assert fingerprint.size_bytes == len(payload)
    assert fingerprint.mime_type == "application/pdf"
    assert fingerprint.original_filename == "paper.pdf"
    assert fingerprint.artifact_kind is ArtifactKind.PDF


def test_fingerprints_are_frozen() -> None:
    fingerprint = ArtifactFingerprint(
        sha256=KNOWN_DIGEST,
        size_bytes=len(KNOWN_BYTES),
        mime_type="application/pdf",
        original_filename="paper.pdf",
    )
    with pytest.raises(Exception, match="frozen"):
        fingerprint.size_bytes = 0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("name", "payload", "expected"),
    [
        ("paper.pdf", b"%PDF-1.7\nbody", "application/pdf"),
        ("mislabelled.txt", b"%PDF-1.4\nbody", "application/pdf"),
        ("page.html", b"<!DOCTYPE html>\n<html></html>", "text/html"),
        ("page.bin", b"\n  <html><body>hi</body></html>", "text/html"),
        ("page.bin", b"\xef\xbb\xbf<!doctype HTML>", "text/html"),
    ],
)
def test_magic_bytes_win_over_the_file_extension(
    tmp_path: Path, name: str, payload: bytes, expected: str
) -> None:
    path = tmp_path / name
    path.write_bytes(payload)
    assert sniff_mime_type(path) == expected


def test_zip_gzip_and_tar_are_sniffed_from_their_containers(tmp_path: Path) -> None:
    archive = tmp_path / "code"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("main.py", "print(1)\n")
    assert sniff_mime_type(archive) == "application/zip"

    compressed = tmp_path / "notes"
    compressed.write_bytes(gzip.compress(b"notes"))
    assert sniff_mime_type(compressed) == "application/gzip"

    bundle = tmp_path / "supplement"
    member = tmp_path / "member.txt"
    member.write_text("data\n", encoding="utf-8")
    with tarfile.open(bundle, "w") as handle:
        handle.add(member, arcname="member.txt")
    assert sniff_mime_type(bundle) == "application/x-tar"


def test_unrecognised_bytes_fall_back_to_the_extension_then_octet_stream(
    tmp_path: Path,
) -> None:
    text = tmp_path / "notes.txt"
    text.write_text("plain notes\n", encoding="utf-8")
    assert sniff_mime_type(text) == "text/plain"

    unknown = tmp_path / "blob.unknownext"
    unknown.write_bytes(b"\x00\x01\x02\x03")
    assert sniff_mime_type(unknown) == DEFAULT_MIME_TYPE


def test_empty_files_are_hashable_and_typed(tmp_path: Path) -> None:
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    fingerprint = fingerprint_file(path)
    assert fingerprint.sha256 == EMPTY_DIGEST
    assert fingerprint.size_bytes == 0
    assert fingerprint.mime_type == DEFAULT_MIME_TYPE


@pytest.mark.parametrize(
    ("mime_type", "expected"),
    [
        ("application/pdf", ArtifactKind.PDF),
        ("application/pdf; charset=binary", ArtifactKind.PDF),
        ("text/html", ArtifactKind.HTML),
        ("application/zip", ArtifactKind.CODE),
        ("audio/ogg", ArtifactKind.OTHER),
    ],
)
def test_artifact_kind_is_derived_from_the_mime_type(
    mime_type: str, expected: ArtifactKind
) -> None:
    assert artifact_kind_for_mime(mime_type) is expected

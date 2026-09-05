"""Deterministic fingerprints for workflow inputs, stage outputs, and files.

A fingerprint decides whether a stage may reuse a checkpoint, so it must be identical in
every process and on every machine: values are reduced to canonical JSON (sorted mapping
keys, no whitespace, UTF-8) and hashed with SHA-256, prefixed with the algorithm name.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path, PurePath
from typing import Any
from uuid import UUID

from pydantic import BaseModel

ALGORITHM = "sha256"
_CHUNK_SIZE = 1024 * 1024


class FingerprintError(TypeError):
    """A value has no canonical encoding, so it cannot take part in a fingerprint."""


def fingerprint(value: object) -> str:
    """Return `sha256:<hex>` over the canonical JSON encoding of `value`."""
    return f"{ALGORITHM}:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"


def fingerprint_file(path: Path | str) -> str:
    """Return `sha256:<hex>` of a file's bytes, read in chunks so large files stay cheap."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return f"{ALGORITHM}:{digest.hexdigest()}"


def canonical_bytes(value: object) -> bytes:
    """Canonical JSON bytes for `value`: sorted keys, no whitespace, UTF-8."""
    encoded = json.dumps(
        canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return encoded.encode("utf-8")


def canonical(value: object) -> Any:
    """Reduce `value` to JSON-encodable data with a single, stable representation."""
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return canonical(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return canonical(value.value)
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal | UUID):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = dataclasses.fields(value)
        return {field.name: canonical(getattr(value, field.name)) for field in fields}
    if isinstance(value, Mapping):
        return {str(key): canonical(item) for key, item in sorted(value.items(), key=_by_key)}
    if isinstance(value, set | frozenset):
        # Sets have no order, so encode them as their canonical members sorted by encoding.
        return sorted((canonical(item) for item in value), key=_encoded)
    if isinstance(value, Sequence):
        return [canonical(item) for item in value]
    raise FingerprintError(f"cannot fingerprint a value of type {type(value).__name__!r}")


def _by_key(item: tuple[Any, Any]) -> str:
    return str(item[0])


def _encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

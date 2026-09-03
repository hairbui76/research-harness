"""Semantic diffs over canonical objects: what a mutation actually changed (Product 36).

A diff is computed from ``model_dump(mode="json")`` so it describes the object as it is
written to canonical YAML/JSONL, not as it happens to be laid out in memory. ``updated_at``
is ignored because every frozen ``touch()`` bumps it and a timestamp is not a scientific
change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

__all__ = [
    "IGNORED_FIELDS",
    "PATH_SEPARATOR",
    "ChangeKind",
    "SemanticDiff",
    "semantic_diff",
]

PATH_SEPARATOR = "."

#: Field names excluded from every diff: bumped by construction, never a change of meaning.
IGNORED_FIELDS: frozenset[str] = frozenset({"updated_at"})


class ChangeKind(StrEnum):
    """Whether a mutation brought an object into existence or changed an existing one."""

    CREATED = "created"
    UPDATED = "updated"


@dataclass(frozen=True, slots=True)
class SemanticDiff:
    """The per-field change one mutation made to one object.

    ``fields`` maps a dotted path (``assessment.allowed_strength``, ``versions.0``) to the
    ``(old, new)`` pair of JSON values at that path. For a created object every path is
    reported with ``old`` of ``None``.
    """

    object_id: str
    change: ChangeKind
    fields: Mapping[str, tuple[Any, Any]]

    @property
    def paths(self) -> tuple[str, ...]:
        """Changed paths, in canonical order."""
        return tuple(self.fields)

    @property
    def is_empty(self) -> bool:
        """True when the mutation left the object's canonical content identical."""
        return not self.fields

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form for transports and human-readable output."""
        return {
            "object_id": self.object_id,
            "change": self.change.value,
            "fields": {path: {"old": old, "new": new} for path, (old, new) in self.fields.items()},
        }


def semantic_diff(
    before: BaseModel | None,
    after: BaseModel,
    *,
    object_id: str | None = None,
) -> SemanticDiff:
    """Diff ``after`` against ``before``; ``before is None`` means the object was created.

    ``object_id`` names objects that carry no research id of their own (a parsed document,
    a taxonomy, a note); everything else is keyed by its id.
    """
    after_fields = _flatten(after.model_dump(mode="json"))
    key = object_id if object_id is not None else _object_key(after)
    if before is None:
        return SemanticDiff(
            object_id=key,
            change=ChangeKind.CREATED,
            fields={path: (None, value) for path, value in after_fields.items()},
        )
    before_fields = _flatten(before.model_dump(mode="json"))
    changed: dict[str, tuple[Any, Any]] = {}
    for path in sorted(set(before_fields) | set(after_fields)):
        old = before_fields.get(path)
        new = after_fields.get(path)
        if old != new:
            changed[path] = (old, new)
    return SemanticDiff(object_id=key, change=ChangeKind.UPDATED, fields=changed)


def _object_key(model: BaseModel) -> str:
    identifier = getattr(model, "id", None)
    return str(identifier) if identifier is not None else type(model).__name__


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested JSON into dotted paths; lists are indexed by position."""
    match value:
        case dict():
            flat: dict[str, Any] = {}
            for name, item in value.items():
                if name in IGNORED_FIELDS:
                    continue
                flat.update(_flatten(item, _join(prefix, str(name))))
            return flat
        case list():
            indexed: dict[str, Any] = {}
            for index, item in enumerate(value):
                indexed.update(_flatten(item, _join(prefix, str(index))))
            return indexed
        case _:
            return {prefix: value}


def _join(prefix: str, name: str) -> str:
    return f"{prefix}{PATH_SEPARATOR}{name}" if prefix else name

"""Deterministic canonical serialization: YAML for objects, JSON Lines for append logs.

Canonical files are read by researchers and diffed by Git, so the byte layout is part of
the contract: field-declaration order (never alphabetical), block style, UTF-8, no line
wrapping, one trailing newline. Append-heavy collections use JSON Lines with sorted keys so
a new line is the only diff a new record produces.

Every document is JSON-shaped (`model_dump(mode="json")`), which is why the loader drops
YAML's implicit timestamp resolver: an ISO-8601 string must come back as a string for
Pydantic to validate it as an aware UTC datetime, whether or not a hand edit quoted it.

Dumping is the hot path — an object's digest is its canonical YAML, so every read of the
corpus serializes every object — and PyYAML's pure-Python emitter was most of a rebuild.
LibYAML emits the same bytes for almost everything a canonical document can hold, but not
quite everything: it escapes a handful of characters PyYAML calls printable, and it decides
differently whether a long mapping key still fits the ``key:`` form. :func:`dump_yaml`
therefore checks a document against both rules and falls back to the pure emitter whenever
it is outside them, so the byte layout is always the one PyYAML defines and the digest a
file gets never depends on which build happens to be installed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from research_harness.domain.errors import WorkspaceError

__all__ = [
    "CanonicalDumper",
    "CanonicalLoader",
    "WorkspaceSerializationError",
    "canonical_bytes",
    "dump_jsonl_line",
    "dump_yaml",
    "iter_jsonl",
    "iter_jsonl_dicts",
    "load_yaml",
    "read_yaml",
]

#: Wide enough that PyYAML never folds a long value onto a second line.
_YAML_WIDTH = 1_000_000


class WorkspaceSerializationError(WorkspaceError):
    """A canonical file could not be parsed or does not match its schema.

    The message always names the file so a researcher can open and fix it by hand.
    """

    def __init__(self, message: str, *, source: Path | str | None = None) -> None:
        self.source = str(source) if source is not None else None
        super().__init__(f"{self.source}: {message}" if self.source else message)


class CanonicalDumper(yaml.SafeDumper):
    """Block-style dumper that preserves insertion order and never emits anchors.

    Anchors/aliases would round-trip correctly but turn a repeated sub-object into
    ``&id001``/``*id001``, which is unreadable in a review diff.
    """

    def ignore_aliases(self, data: Any) -> bool:
        del data
        return True


if yaml.__with_libyaml__:

    class _FastCanonicalDumper(yaml.CSafeDumper):
        """LibYAML twin of :class:`CanonicalDumper`, used only where its bytes are identical."""

        def ignore_aliases(self, data: Any) -> bool:
            del data
            return True

    _FAST_DUMPER: type[yaml.CSafeDumper] | None = _FastCanonicalDumper
else:  # pragma: no cover - exercised on builds without the LibYAML extension
    _FAST_DUMPER = None


#: Characters PyYAML calls printable and LibYAML does not, so the two emit them
#: differently: ``\r`` (a line break to LibYAML only), ``\x85``, lone surrogates, and
#: everything above the BMP. None survives `parsing.text.normalize_text`.
_LIBYAML_DIVERGENT = re.compile("[\r\x85\ud800-\udfff\U00010000-\U0010ffff]")

#: Longest mapping key the two emitters certainly agree about. They disagree on whether a
#: long key still fits the ``key:`` form rather than YAML's explicit ``? key`` form, because
#: PyYAML measures the key in characters (plus its tag) against 128 and LibYAML measures it
#: in UTF-8 bytes; the two answers part company somewhere above 122 bytes. 64 ASCII
#: characters is comfortably below every threshold either applies, and is what a canonical
#: document's keys - Pydantic field names, and the short strings of `condition`,
#: `qualifier`, `filters` and `ranks` - look like.
_LIBYAML_MAX_KEY = 64


def _libyaml_emits_the_same_bytes(payload: object) -> bool:
    """True when LibYAML renders ``payload`` byte for byte as the pure-Python emitter does.

    Two things put a document outside the agreement: a character from
    `_LIBYAML_DIVERGENT` anywhere in it, and a mapping key that is empty, not ASCII, or
    longer than `_LIBYAML_MAX_KEY`. Both are conservative — a document refused here is
    still emitted correctly, only more slowly.
    """
    stack = [payload]
    search = _LIBYAML_DIVERGENT.search
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            if search(node) is not None:
                return False
        elif isinstance(node, dict):
            for key, value in node.items():
                if not isinstance(key, str) or not 0 < len(key) <= _LIBYAML_MAX_KEY:
                    return False
                if not key.isascii() or search(key) is not None:
                    return False
                stack.append(value)
        elif isinstance(node, list | tuple):
            stack.extend(node)
    return True


class CanonicalLoader(yaml.SafeLoader):
    """Safe loader that leaves ISO-8601 scalars as strings for Pydantic to validate."""


# Canonical documents carry timestamps as strings; PyYAML would otherwise hand back a
# naive datetime, which the domain rejects as not timezone-aware.
CanonicalLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in CanonicalLoader.yaml_implicit_resolvers.items()
}


def dump_yaml(model: BaseModel) -> str:
    """Canonical YAML text for one object, ending in exactly one newline.

    The pure-Python dumper defines the bytes; LibYAML is used only where
    :func:`_libyaml_emits_the_same_bytes` says the two agree.
    """
    payload = model.model_dump(mode="json")
    dumper: type[yaml.SafeDumper] | type[yaml.CSafeDumper] = CanonicalDumper
    if _FAST_DUMPER is not None and _libyaml_emits_the_same_bytes(payload):
        dumper = _FAST_DUMPER
    text: str = yaml.dump(
        payload,
        Dumper=dumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=_YAML_WIDTH,
    )
    return text if text.endswith("\n") else text + "\n"


def canonical_bytes(model: BaseModel) -> bytes:
    """UTF-8 bytes of :func:`dump_yaml`; this is what a canonical YAML file contains."""
    return dump_yaml(model).encode("utf-8")


def load_yaml[T: BaseModel](
    text: str, model_type: type[T], *, source: Path | str | None = None
) -> T:
    """Parse canonical YAML into ``model_type``, validating strictly."""
    try:
        # CanonicalLoader derives from SafeLoader; no arbitrary object construction.
        payload = yaml.load(text, Loader=CanonicalLoader)
    except yaml.YAMLError as exc:
        raise WorkspaceSerializationError(f"invalid YAML: {exc}", source=source) from exc
    if not isinstance(payload, dict):
        raise WorkspaceSerializationError(
            f"expected a {model_type.__name__} mapping, found {type(payload).__name__}",
            source=source,
        )
    return _validate(payload, model_type, source=source)


def read_yaml[T: BaseModel](path: Path, model_type: type[T]) -> T:
    """Load one canonical YAML file into ``model_type``."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkspaceSerializationError(f"cannot read file: {exc}", source=path) from exc
    return load_yaml(text, model_type, source=path)


def dump_jsonl_line(model: BaseModel) -> str:
    """One canonical JSON Lines record: sorted keys, unicode kept, no trailing whitespace."""
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, ensure_ascii=False) + "\n"


def iter_jsonl_dicts(path: Path) -> Iterator[dict[str, Any]]:
    """Yield the raw mappings of a JSON Lines file, skipping blank lines."""
    for _, payload in _iter_jsonl_lines(path):
        yield payload


def iter_jsonl[T: BaseModel](path: Path, model_type: type[T]) -> Iterator[T]:
    """Yield validated ``model_type`` records from a canonical JSON Lines file."""
    for number, payload in _iter_jsonl_lines(path):
        yield _validate(payload, model_type, source=path, line=number)


def _iter_jsonl_lines(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    if not path.is_file():
        return
    try:
        handle = path.open(encoding="utf-8")
    except OSError as exc:
        raise WorkspaceSerializationError(f"cannot read file: {exc}", source=path) from exc
    with handle:
        for number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise WorkspaceSerializationError(
                    f"line {number}: invalid JSON: {exc}", source=path
                ) from exc
            if not isinstance(payload, dict):
                raise WorkspaceSerializationError(
                    f"line {number}: expected a mapping, found {type(payload).__name__}",
                    source=path,
                )
            yield number, payload


def _validate[T: BaseModel](
    payload: dict[str, Any],
    model_type: type[T],
    *,
    source: Path | str | None,
    line: int | None = None,
) -> T:
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        where = f"line {line}: " if line is not None else ""
        raise WorkspaceSerializationError(
            f"{where}not a valid {model_type.__name__}: {exc}", source=source
        ) from exc

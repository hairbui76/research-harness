"""The embedded local vector index: disposable, per-provider, brute-force cosine.

Everything this module writes lives under `.research/index/semantic/<fingerprint>/` and
carries no scientific authority (Product SS15.1, P7, ADR-006). Three consequences shape
the design:

* **The embedding provider and model are recorded here, and only here.** `meta.json`
  names them so a stale or foreign index is detected; no canonical object ever mentions
  them, which is what makes swapping embedding models an operational act.
* **Deleting the index is safe.** `delete()` removes exactly one directory. Nothing
  outside it is touched, and a caller can rebuild from canonical state afterwards.
* **A damaged index degrades, it does not crash.** A missing, truncated or foreign file
  makes `needs_rebuild` true and leaves an empty, queryable index behind, because losing
  retrieval performance is an inconvenience and losing the session is not.

Search is `numpy` brute force over L2-normalized rows, so a dot product *is* cosine
similarity. A personal corpus is thousands of units, not millions; an ANN library would
add a dependency, an index format, and a recall-vs-speed knob for no demonstrated need.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from research_harness.domain.base import Sha256, UtcDatetime, utc_now
from research_harness.domain.ids import ArtifactId, WorkId
from research_harness.providers.models.embeddings import EmbeddingProvider
from research_harness.retrieval.units import IndexUnit, IndexUnitKind
from research_harness.workspace.atomic import atomic_write_bytes, atomic_write_text

__all__ = [
    "INDEX_VERSION",
    "META_FILENAME",
    "PREVIEW_CHARS",
    "SEMANTIC_DIRNAME",
    "UNITS_FILENAME",
    "VECTORS_FILENAME",
    "IndexMeta",
    "IndexStats",
    "IndexedUnit",
    "SemanticHit",
    "SemanticIndex",
    "fingerprint_slug",
    "semantic_index_dir",
]

logger = logging.getLogger(__name__)

INDEX_VERSION = 1
"""On-disk format version. A bump invalidates every stored index rather than migrating
it: the vectors are regenerable, so migration would be work with no payoff."""

SEMANTIC_DIRNAME = "semantic"
VECTORS_FILENAME = "vectors.npy"
UNITS_FILENAME = "units.jsonl"
META_FILENAME = "meta.json"

PREVIEW_CHARS = 200
"""How much unit text the index keeps. Enough to recognise a hit in a result list; the
full text is re-read from canonical state or the parsed blocks, never from here."""

_Matrix = np.ndarray[Any, np.dtype[np.float32]]


# ----------------------------------------------------------------------- records


class IndexedUnit(BaseModel):
    """What the index stores about a unit: its identity, not its content.

    The text itself is not kept — it belongs to the canonical object or the parsed block
    the unit came from. `text_hash` is what makes an incremental `upsert` possible, and
    `preview` exists so a result list is readable without a second read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    kind: IndexUnitKind
    work: WorkId | None = None
    artifact: ArtifactId | None = None
    page: int | None = Field(default=None, ge=1)
    section_path: tuple[str, ...] = ()
    text_hash: Sha256
    preview: str = ""

    @classmethod
    def of(cls, unit: IndexUnit) -> IndexedUnit:
        """Metadata record for `unit`, with a whitespace-collapsed preview."""
        return cls(
            id=unit.id,
            kind=unit.kind,
            work=unit.work,
            artifact=unit.artifact,
            page=unit.page,
            section_path=unit.section_path,
            text_hash=unit.text_hash,
            preview=" ".join(unit.text.split())[:PREVIEW_CHARS],
        )


class SemanticHit(BaseModel):
    """One search result: the stored unit metadata, its cosine score, and its rank."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit: IndexedUnit
    score: float
    rank: int = Field(ge=1)


class IndexMeta(BaseModel):
    """`meta.json`: the only place the embedding provider and model are recorded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    index_version: int
    provider: str
    model: str
    dimension: int = Field(gt=0)
    fingerprint: str
    unit_count: int = Field(ge=0)
    built_at: UtcDatetime


class IndexStats(BaseModel):
    """What an operator needs to answer "is this index usable, and whose vectors is it?"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    directory: Path
    provider: str
    model: str
    dimension: int
    unit_count: int
    index_version: int
    needs_rebuild: bool
    built_at: datetime | None = None


# ------------------------------------------------------------------- placement


def fingerprint_slug(fingerprint: str) -> str:
    """Filesystem-safe directory name for a provider fingerprint.

    The readable part is the fingerprint with unsafe characters folded to `-`; the
    trailing digest keeps two fingerprints that fold to the same text apart, so distinct
    providers can never share a directory of vectors.
    """
    safe = "".join(char if char.isalnum() or char in "._-" else "-" for char in fingerprint)
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:8]
    return f"{safe.strip('-')[:64]}-{digest}"


def semantic_index_dir(index_root: Path, provider: EmbeddingProvider) -> Path:
    """`<index_root>/semantic/<provider fingerprint>/` — one directory per fingerprint."""
    return Path(index_root) / SEMANTIC_DIRNAME / fingerprint_slug(provider.fingerprint())


# ----------------------------------------------------------------------- index


class SemanticIndex:
    """A vector index over retrieval units, stored per embedding-provider fingerprint."""

    def __init__(self, directory: Path, provider: EmbeddingProvider) -> None:
        self._directory = Path(directory)
        self._provider = provider
        self._units: list[IndexedUnit] = []
        self._positions: dict[str, int] = {}
        self._vectors: _Matrix = _empty_matrix(provider.dimension)
        self._built_at: datetime | None = None
        self._needs_rebuild = True
        self._load()

    @classmethod
    def open(cls, index_root: Path, provider: EmbeddingProvider) -> SemanticIndex:
        """Open (never create) the index for `provider` under `<index_root>/semantic/`.

        Nothing is written until something is indexed, and an absent or unreadable index
        opens empty with `needs_rebuild` set rather than raising.
        """
        return cls(semantic_index_dir(index_root, provider), provider)

    # -- placement -----------------------------------------------------------

    @property
    def directory(self) -> Path:
        """The one directory this index owns; `delete()` removes exactly this."""
        return self._directory

    @property
    def provider(self) -> EmbeddingProvider:
        return self._provider

    @property
    def vectors_file(self) -> Path:
        return self._directory / VECTORS_FILENAME

    @property
    def units_file(self) -> Path:
        return self._directory / UNITS_FILENAME

    @property
    def meta_file(self) -> Path:
        return self._directory / META_FILENAME

    @property
    def needs_rebuild(self) -> bool:
        """True while the stored index is absent, torn, or written by another provider.

        It is not an error state: the index answers queries with nothing until a caller
        rebuilds it from canonical state.
        """
        return self._needs_rebuild

    # -- writes --------------------------------------------------------------

    def upsert(self, units: Sequence[IndexUnit]) -> int:
        """Add or replace `units`; returns how many were embedded.

        A unit whose `text_hash` already matches the stored one is skipped, so re-indexing
        an unchanged corpus makes no provider call at all. Ordering is stable: units keep
        the position they were first given, new ones are appended in the order supplied.
        """
        incoming = _deduplicate(units)
        pending = [
            unit
            for unit in incoming
            if (position := self._positions.get(unit.id)) is None
            or self._units[position].text_hash != unit.text_hash
        ]
        if not pending and not self._needs_rebuild:
            return 0
        self._apply(pending, self._embed([unit.text for unit in pending]))
        self._persist()
        return len(pending)

    def rebuild(self, units: Sequence[IndexUnit]) -> int:
        """Re-embed everything from scratch; returns how many units were embedded."""
        incoming = _deduplicate(units)
        self._reset()
        self._apply(incoming, self._embed([unit.text for unit in incoming]))
        self._persist()
        return len(incoming)

    def remove(self, ids: Iterable[str]) -> int:
        """Drop units by id; returns how many were removed."""
        doomed = {str(unit_id) for unit_id in ids}
        keep = [index for index, unit in enumerate(self._units) if unit.id not in doomed]
        removed = len(self._units) - len(keep)
        if removed == 0:
            return 0
        self._units = [self._units[index] for index in keep]
        self._vectors = self._vectors[np.asarray(keep, dtype=np.int64)]
        self._positions = {unit.id: position for position, unit in enumerate(self._units)}
        self._persist()
        return removed

    def delete(self) -> None:
        """Remove this index's directory and nothing else, then reset to empty."""
        shutil.rmtree(self._directory, ignore_errors=True)
        self._reset()
        self._needs_rebuild = True

    # -- reads ---------------------------------------------------------------

    def query(
        self,
        text: str,
        *,
        k: int = 10,
        kinds: Collection[IndexUnitKind] | None = None,
        work: WorkId | None = None,
        exclude_ids: Collection[str] = (),
    ) -> list[SemanticHit]:
        """Top `k` units by cosine similarity, filtered before scoring.

        Filters are applied to the candidate set rather than to the results, so asking for
        five paragraphs of one Work returns five, not whatever survives a global top-five.
        """
        if k < 1 or not self._units or not text.strip():
            return []
        candidates = [
            position
            for position, unit in enumerate(self._units)
            if _matches(unit, kinds=kinds, work=work, exclude_ids=exclude_ids)
        ]
        if not candidates:
            return []
        scores = self._vectors @ self._query_vector(text)
        subset = scores[np.asarray(candidates, dtype=np.int64)]
        order = np.argsort(-subset, kind="stable")[:k]
        return [
            SemanticHit(
                unit=self._units[candidates[int(offset)]],
                score=float(subset[int(offset)]),
                rank=rank,
            )
            for rank, offset in enumerate(order, start=1)
        ]

    def stats(self) -> IndexStats:
        """Size, health, and whose vectors these are."""
        return IndexStats(
            directory=self._directory,
            provider=self._provider.name,
            model=self._provider.model,
            dimension=self._provider.dimension,
            unit_count=len(self._units),
            index_version=INDEX_VERSION,
            needs_rebuild=self._needs_rebuild,
            built_at=self._built_at,
        )

    def __repr__(self) -> str:
        return (
            f"SemanticIndex(directory={str(self._directory)!r}, "
            f"units={len(self._units)}, needs_rebuild={self._needs_rebuild})"
        )

    # -- internals -----------------------------------------------------------

    def _embed(self, texts: Sequence[str]) -> _Matrix:
        if not texts:
            return _empty_matrix(self._provider.dimension)
        vectors = self._provider.embed(texts)
        return _normalize(_as_matrix(vectors, self._provider.dimension))

    def _query_vector(self, text: str) -> _Matrix:
        matrix = _normalize(_as_matrix(self._provider.embed([text]), self._provider.dimension))
        return np.asarray(matrix[0], dtype=np.float32)

    def _apply(self, units: Sequence[IndexUnit], vectors: _Matrix) -> None:
        appended: list[IndexedUnit] = []
        appended_rows: list[_Matrix] = []
        for unit, row in zip(units, vectors, strict=True):
            record = IndexedUnit.of(unit)
            position = self._positions.get(record.id)
            if position is None:
                appended.append(record)
                appended_rows.append(row)
            else:
                self._units[position] = record
                self._vectors[position] = row
        if not appended:
            return
        self._vectors = np.vstack([self._vectors, np.asarray(appended_rows, dtype=np.float32)])
        for record in appended:
            self._positions[record.id] = len(self._units)
            self._units.append(record)

    def _reset(self) -> None:
        self._units = []
        self._positions = {}
        self._vectors = _empty_matrix(self._provider.dimension)
        self._built_at = None

    def _persist(self) -> None:
        """Write all three files atomically, `meta.json` last.

        Each file lands through a temp file and a rename, and the meta file is written
        only once the vectors and units are durable, so a crash mid-write leaves either
        the previous consistent index or a state that reports `needs_rebuild`.
        """
        meta = IndexMeta(
            index_version=INDEX_VERSION,
            provider=self._provider.name,
            model=self._provider.model,
            dimension=self._provider.dimension,
            fingerprint=self._provider.fingerprint(),
            unit_count=len(self._units),
            built_at=utc_now(),
        )
        self._directory.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(self.vectors_file, _vectors_bytes(self._vectors))
        atomic_write_text(self.units_file, _units_text(self._units))
        atomic_write_text(self.meta_file, _meta_text(meta))
        self._built_at = meta.built_at
        self._needs_rebuild = False

    def _load(self) -> None:
        meta = _read_meta(self.meta_file)
        units = _read_units(self.units_file)
        vectors = _read_vectors(self.vectors_file)
        if meta is None or units is None or vectors is None:
            self._needs_rebuild = True
            return
        problem = _inconsistency(meta, units, vectors, self._provider)
        if problem is not None:
            logger.warning("semantic index at %s needs a rebuild: %s", self._directory, problem)
            self._needs_rebuild = True
            return
        self._units = units
        self._positions = {unit.id: position for position, unit in enumerate(units)}
        self._vectors = vectors
        self._built_at = meta.built_at
        self._needs_rebuild = False


# ------------------------------------------------------------------- helpers


def _deduplicate(units: Sequence[IndexUnit]) -> list[IndexUnit]:
    """Last occurrence of each id wins, first occurrence fixes the order."""
    seen: dict[str, int] = {}
    result: list[IndexUnit] = []
    for unit in units:
        position = seen.get(unit.id)
        if position is None:
            seen[unit.id] = len(result)
            result.append(unit)
        else:
            result[position] = unit
    return result


def _matches(
    unit: IndexedUnit,
    *,
    kinds: Collection[IndexUnitKind] | None,
    work: WorkId | None,
    exclude_ids: Collection[str],
) -> bool:
    if kinds is not None and unit.kind not in kinds:
        return False
    if work is not None and unit.work != work:
        return False
    return unit.id not in exclude_ids


def _empty_matrix(dimension: int) -> _Matrix:
    return np.zeros((0, dimension), dtype=np.float32)


def _as_matrix(vectors: Sequence[Sequence[float]], dimension: int) -> _Matrix:
    matrix = np.asarray(vectors, dtype=np.float32)
    return matrix.reshape(len(vectors), dimension)


def _normalize(matrix: _Matrix) -> _Matrix:
    """L2-normalize every row, leaving all-zero rows alone so cosine stays defined."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.asarray(matrix / np.where(norms == 0.0, 1.0, norms), dtype=np.float32)


def _vectors_bytes(matrix: _Matrix) -> bytes:
    buffer = BytesIO()
    np.save(buffer, matrix, allow_pickle=False)
    return buffer.getvalue()


def _units_text(units: Sequence[IndexedUnit]) -> str:
    return "".join(
        json.dumps(unit.model_dump(mode="json"), sort_keys=True, ensure_ascii=False) + "\n"
        for unit in units
    )


def _meta_text(meta: IndexMeta) -> str:
    return json.dumps(meta.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"


def _read_meta(path: Path) -> IndexMeta | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return IndexMeta.model_validate(payload)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:  # pydantic ValidationError is a ValueError
        logger.warning("unreadable semantic index metadata at %s: %s", path, exc)
        return None


def _read_units(path: Path) -> list[IndexedUnit] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("unreadable semantic index units at %s: %s", path, exc)
        return None
    units: list[IndexedUnit] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            units.append(IndexedUnit.model_validate(json.loads(line)))
        except ValueError as exc:  # bad JSON or a record that fails validation
            logger.warning("torn semantic index units at %s: %s", path, exc)
            return None
    return units


def _read_vectors(path: Path) -> _Matrix | None:
    try:
        loaded = np.load(path, allow_pickle=False)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, EOFError) as exc:
        logger.warning("torn semantic index vectors at %s: %s", path, exc)
        return None
    if loaded.ndim != 2:
        logger.warning("semantic index vectors at %s are not a matrix", path)
        return None
    return np.asarray(loaded, dtype=np.float32)


def _inconsistency(
    meta: IndexMeta,
    units: Sequence[IndexedUnit],
    vectors: _Matrix,
    provider: EmbeddingProvider,
) -> str | None:
    """Why this stored index cannot be trusted, or `None` when it can."""
    if meta.index_version != INDEX_VERSION:
        return f"index version {meta.index_version}, expected {INDEX_VERSION}"
    if meta.fingerprint != provider.fingerprint():
        return f"built by {meta.fingerprint}, opened with {provider.fingerprint()}"
    if meta.unit_count != len(units):
        return f"metadata claims {meta.unit_count} units, {len(units)} are stored"
    if vectors.shape != (len(units), provider.dimension):
        return f"vector matrix is {vectors.shape}, expected {(len(units), provider.dimension)}"
    return None

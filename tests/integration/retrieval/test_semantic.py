"""The embedded semantic index over a real parsed paper (ROADMAP Task 5.2).

The corpus is the synthetic paper parsed by `PyMuPdfParser`, and the embedder is the
offline hashing provider, so the whole test is deterministic and needs no service. What
is asserted here is the ADR-006 bargain: the index is fast, per-provider, and completely
disposable, and no part of the scientific record depends on it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import ResearchEventType
from research_harness.domain.ids import ArtifactId, VersionId, WorkId
from research_harness.domain.research import ResearchEvent
from research_harness.parsing.base import ParseTarget
from research_harness.parsing.pymupdf_parser import PyMuPdfParser
from research_harness.providers.models.embeddings import HashingEmbeddingProvider
from research_harness.retrieval.semantic import (
    INDEX_VERSION,
    SEMANTIC_DIRNAME,
    SemanticIndex,
    semantic_index_dir,
)
from research_harness.retrieval.units import (
    IndexUnit,
    IndexUnitKind,
    unit_from_work,
    units_from_claim,
    units_from_document,
    units_from_evidence,
)
from research_harness.workspace.repository import WorkspaceRepository
from tests.fixtures.make_synthetic_paper import SINGLE_COLUMN_PDF
from tests.unit.domain.strategies import make_claim, make_evidence, make_work

WORK = WorkId("W0017")
ARTIFACT = ArtifactId("A0017-1")
DIMENSION = 256

#: A paragraph the parser produces, quoted so an assertion says which one it means.
CLASS_IMBALANCE = "Class imbalance is severe"
DATASET_PARAGRAPH = "All experiments use CICIDS2017"

#: Terminology mismatch by design: the paper says "class imbalance is severe", the
#: researcher asks about a "skewed class distribution". A hashing embedder is lexical, so
#: the query is written to share the *distinctive* tokens (benign, attack, flows) while
#: differing in the terms that name the concept. A trained embedding model would not need
#: that overlap; this one does, and the fixture is honest about it.
MISMATCH_QUERY = "skewed class distribution between benign and attack flows"


class CountingEmbeddingProvider(HashingEmbeddingProvider):
    """Hashing provider that counts its work, so "was this re-embedded?" is assertable.

    It deliberately inherits `name` and `model`, so a counted run lands in exactly the
    same index directory as an uncounted one.
    """

    def __init__(self, dimension: int = DIMENSION) -> None:
        super().__init__(dimension=dimension)
        self.calls = 0
        self.embedded = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        self.embedded += len(texts)
        return super().embed(texts)

    def reset(self) -> None:
        self.calls = 0
        self.embedded = 0


@pytest.fixture(scope="module")
def paper() -> ParsedDocument:
    digest = hashlib.sha256(Path(SINGLE_COLUMN_PDF).read_bytes()).hexdigest()
    return PyMuPdfParser().parse(
        ParseTarget(
            work=WORK,
            version=VersionId("V0017-1"),
            artifact=ARTIFACT,
            file_hash=f"sha256:{digest}",
            path=Path(SINGLE_COLUMN_PDF),
            mime_type="application/pdf",
        )
    )


@pytest.fixture(scope="module")
def units(paper: ParsedDocument) -> list[IndexUnit]:
    """Everything a Work contributes: its card, its blocks, its evidence and its claims."""
    return [
        unit_from_work(make_work(id=WORK)),
        *units_from_document(paper),
        *units_from_evidence(make_evidence()),
        *units_from_claim(make_claim()),
    ]


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceRepository:
    """A real canonical workspace, so "the index touched nothing" can be measured."""
    repo = WorkspaceRepository.init(tmp_path, "semantic index acceptance")
    event = ResearchEvent(
        event=ResearchEventType.WORK_INGESTED, actor="human:test", summary="ingest W0017"
    )
    with repo.transaction(event) as transaction:
        transaction.put(make_work(id=WORK))
    return repo


@pytest.fixture
def provider() -> CountingEmbeddingProvider:
    return CountingEmbeddingProvider()


@pytest.fixture
def index(
    workspace: WorkspaceRepository, provider: CountingEmbeddingProvider, units: list[IndexUnit]
) -> SemanticIndex:
    built = SemanticIndex.open(workspace.layout.index_dir, provider)
    built.rebuild(units)
    provider.reset()
    return built


# -- placement ----------------------------------------------------------------------


def test_the_index_lives_under_the_research_directory_named_for_its_provider(
    workspace: WorkspaceRepository, index: SemanticIndex
) -> None:
    relative = index.directory.relative_to(workspace.root)

    assert relative.parts[:3] == (".research", "index", SEMANTIC_DIRNAME)
    assert relative.parts[3].startswith("hashing-")
    assert workspace.layout.is_regenerable(index.directory)


def test_all_three_files_are_written_and_no_temporary_file_survives(
    index: SemanticIndex, units: list[IndexUnit]
) -> None:
    assert index.vectors_file.is_file()
    assert index.units_file.is_file()
    assert index.meta_file.is_file()
    assert not list(index.directory.glob(".tmp-*"))
    assert len(index.units_file.read_text(encoding="utf-8").splitlines()) == len(units)


# -- search -------------------------------------------------------------------------


def test_query_returns_ranked_scored_hits(index: SemanticIndex) -> None:
    hits = index.query("detection performance on CICIDS2017", k=3)

    assert [hit.rank for hit in hits] == [1, 2, 3]
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)
    assert all(-1.0 <= hit.score <= 1.0 for hit in hits)
    assert all(hit.unit.preview for hit in hits)


def test_the_top_hit_is_the_brute_force_cosine_argmax(
    index: SemanticIndex, units: list[IndexUnit]
) -> None:
    """No approximation: the index must agree with the naive computation exactly."""
    plain = HashingEmbeddingProvider(dimension=DIMENSION)
    query = "detection performance on CICIDS2017"
    matrix = np.asarray(plain.embed([unit.text for unit in units]), dtype=np.float32)
    scores = matrix @ np.asarray(plain.embed([query])[0], dtype=np.float32)

    hit = index.query(query, k=1)[0]

    assert hit.unit.id == units[int(np.argmax(scores))].id
    assert hit.score == pytest.approx(float(np.max(scores)), abs=1e-5)


def test_a_terminology_mismatch_query_reaches_the_paragraph_that_shares_its_terms(
    index: SemanticIndex,
) -> None:
    """Gate P5's semantic case, within the limits of a lexical embedder.

    The paper never says "skewed" or "distribution"; retrieval works because the query
    shares the paragraph's distinctive tokens. Swapping in a trained embedding model is a
    provider change and moves the index directory — it changes nothing canonical.
    """
    paragraphs = index.query(MISMATCH_QUERY, k=3, kinds=(IndexUnitKind.PARAGRAPH,))

    assert CLASS_IMBALANCE in paragraphs[0].unit.preview
    assert paragraphs[0].score > 1.5 * paragraphs[1].score

    unfiltered = index.query(MISMATCH_QUERY, k=1)[0]
    assert unfiltered.unit.section_path == ("3 Experiments", "3.1 Dataset")


def test_filters_are_applied_to_the_candidate_set_not_to_the_results(
    index: SemanticIndex,
) -> None:
    tables = index.query("F1 precision", k=5, kinds=(IndexUnitKind.TABLE,))
    other_work = index.query("F1 precision", k=5, work=WorkId("W0099"))

    assert tables and all(hit.unit.kind is IndexUnitKind.TABLE for hit in tables)
    assert other_work == []


def test_excluded_ids_never_come_back(index: SemanticIndex) -> None:
    first = index.query("detection performance on CICIDS2017", k=1)[0]

    hits = index.query("detection performance on CICIDS2017", k=1, exclude_ids=(first.unit.id,))

    assert hits and hits[0].unit.id != first.unit.id


def test_an_empty_index_answers_with_nothing_rather_than_failing(
    workspace: WorkspaceRepository, provider: CountingEmbeddingProvider
) -> None:
    empty = SemanticIndex.open(workspace.layout.index_dir, provider)

    assert empty.needs_rebuild
    assert empty.query("anything at all") == []
    assert empty.stats().unit_count == 0


# -- incremental maintenance --------------------------------------------------------


def test_reindexing_unchanged_text_embeds_nothing(
    index: SemanticIndex, provider: CountingEmbeddingProvider, units: list[IndexUnit]
) -> None:
    """The text hash is what makes a rebuild cheap; an unchanged corpus costs no calls."""
    assert index.upsert(units) == 0
    assert provider.calls == 0


def test_only_the_changed_unit_is_re_embedded(
    index: SemanticIndex, provider: CountingEmbeddingProvider, units: list[IndexUnit]
) -> None:
    edited = units[3].model_copy(update={"text": "a rewritten paragraph about tunnelling"})

    assert index.upsert([*units[:3], edited, *units[4:]]) == 1
    assert provider.embedded == 1
    assert index.stats().unit_count == len(units)
    assert "tunnelling" in index.query("tunnelling", k=1)[0].unit.preview


def test_new_units_are_appended_and_existing_positions_are_kept(
    index: SemanticIndex, units: list[IndexUnit]
) -> None:
    extra = IndexUnit(id="C0099", kind=IndexUnitKind.CLAIM, text="A late claim about domain shift.")

    index.upsert([extra])

    lines = index.units_file.read_text(encoding="utf-8").splitlines()
    stored = [json.loads(line)["id"] for line in lines]
    assert stored == [unit.id for unit in units] + ["C0099"]


def test_removing_units_leaves_the_rest_searchable(
    index: SemanticIndex, units: list[IndexUnit]
) -> None:
    doomed = index.query(DATASET_PARAGRAPH, k=1)[0].unit.id

    assert index.remove([doomed, "not-in-the-index"]) == 1

    assert index.stats().unit_count == len(units) - 1
    assert all(hit.unit.id != doomed for hit in index.query(DATASET_PARAGRAPH, k=5))
    assert index.query("detection performance on CICIDS2017", k=1)


def test_reopening_the_index_answers_from_disk(
    workspace: WorkspaceRepository, index: SemanticIndex, units: list[IndexUnit]
) -> None:
    fresh = CountingEmbeddingProvider()

    reopened = SemanticIndex.open(workspace.layout.index_dir, fresh)
    hits = reopened.query(DATASET_PARAGRAPH, k=1)

    assert not reopened.needs_rebuild
    assert reopened.stats().unit_count == len(units)
    assert hits[0].unit.id == index.query(DATASET_PARAGRAPH, k=1)[0].unit.id
    assert fresh.embedded == 1  # the query text, and nothing else


# -- disposability (ADR-006) --------------------------------------------------------


def test_meta_records_the_embedder_and_no_canonical_file_mentions_it(
    workspace: WorkspaceRepository, index: SemanticIndex, provider: CountingEmbeddingProvider
) -> None:
    """P7: the embedding provider lives in index metadata, never in the research record."""
    meta = json.loads(index.meta_file.read_text(encoding="utf-8"))

    assert meta["provider"] == provider.name
    assert meta["model"] == provider.model
    assert meta["dimension"] == DIMENSION
    assert meta["fingerprint"] == provider.fingerprint()
    assert meta["index_version"] == INDEX_VERSION
    assert meta["unit_count"] == index.stats().unit_count
    assert meta["built_at"]

    canonical = canonical_text(workspace.root)
    assert provider.name not in canonical
    assert provider.model not in canonical
    assert "embedding" not in canonical.lower()


def test_deleting_the_index_removes_nothing_outside_its_directory(
    workspace: WorkspaceRepository, index: SemanticIndex
) -> None:
    before = canonical_digest(workspace.root)

    index.delete()

    assert not index.directory.exists()
    assert canonical_digest(workspace.root) == before
    assert workspace.layout.index_dir.is_dir()
    assert workspace.layout.database_file.parent.is_dir()
    assert index.needs_rebuild
    assert index.query(DATASET_PARAGRAPH) == []


def test_a_deleted_index_can_be_rebuilt_from_the_same_units(
    index: SemanticIndex, units: list[IndexUnit]
) -> None:
    expected = index.query(DATASET_PARAGRAPH, k=3)

    index.delete()
    assert index.rebuild(units) == len(units)

    assert not index.needs_rebuild
    assert [hit.unit.id for hit in index.query(DATASET_PARAGRAPH, k=3)] == [
        hit.unit.id for hit in expected
    ]


def test_switching_provider_writes_a_separate_index_and_leaves_the_first_intact(
    workspace: WorkspaceRepository, index: SemanticIndex, units: list[IndexUnit]
) -> None:
    other = HashingEmbeddingProvider(dimension=64)

    second = SemanticIndex.open(workspace.layout.index_dir, other)
    second.rebuild(units)

    assert second.directory != index.directory
    assert second.directory.parent == index.directory.parent
    assert index.meta_file.is_file()
    assert not SemanticIndex.open(workspace.layout.index_dir, index.provider).needs_rebuild
    assert second.query(DATASET_PARAGRAPH, k=1)[0].unit.id


def test_semantic_index_dir_is_stable_for_a_fingerprint(tmp_path: Path) -> None:
    first = semantic_index_dir(tmp_path, HashingEmbeddingProvider(dimension=DIMENSION))
    again = semantic_index_dir(tmp_path, HashingEmbeddingProvider(dimension=DIMENSION))
    other = semantic_index_dir(tmp_path, HashingEmbeddingProvider(dimension=DIMENSION, ngrams=(1,)))

    assert first == again
    assert first != other


# -- damage tolerance ---------------------------------------------------------------


def test_a_truncated_vector_file_asks_for_a_rebuild_instead_of_crashing(
    workspace: WorkspaceRepository, index: SemanticIndex, units: list[IndexUnit]
) -> None:
    index.vectors_file.write_bytes(index.vectors_file.read_bytes()[:37])

    torn = SemanticIndex.open(workspace.layout.index_dir, HashingEmbeddingProvider(DIMENSION))

    assert torn.needs_rebuild
    assert torn.query(DATASET_PARAGRAPH) == []
    assert torn.rebuild(units) == len(units)
    assert not torn.needs_rebuild


@pytest.mark.parametrize("victim", ["units_file", "meta_file", "vectors_file"])
def test_a_missing_index_file_asks_for_a_rebuild(
    workspace: WorkspaceRepository, index: SemanticIndex, victim: str
) -> None:
    path: Path = getattr(index, victim)
    path.unlink()

    reopened = SemanticIndex.open(workspace.layout.index_dir, HashingEmbeddingProvider(DIMENSION))

    assert reopened.needs_rebuild


def test_a_half_written_units_file_asks_for_a_rebuild(
    workspace: WorkspaceRepository, index: SemanticIndex
) -> None:
    index.units_file.write_text('{"id": "B0001@A0017-1", "kind": ')

    reopened = SemanticIndex.open(workspace.layout.index_dir, HashingEmbeddingProvider(DIMENSION))

    assert reopened.needs_rebuild


def test_metadata_from_another_embedder_is_not_trusted(
    workspace: WorkspaceRepository, index: SemanticIndex
) -> None:
    """The directory is keyed by fingerprint, and the metadata is checked anyway."""
    meta = json.loads(index.meta_file.read_text(encoding="utf-8"))
    meta["fingerprint"] = "someone-else/model/256"
    index.meta_file.write_text(json.dumps(meta))

    reopened = SemanticIndex.open(workspace.layout.index_dir, HashingEmbeddingProvider(DIMENSION))

    assert reopened.needs_rebuild


def test_a_unit_count_that_disagrees_with_the_units_file_asks_for_a_rebuild(
    workspace: WorkspaceRepository, index: SemanticIndex
) -> None:
    meta = json.loads(index.meta_file.read_text(encoding="utf-8"))
    meta["unit_count"] = meta["unit_count"] + 1
    index.meta_file.write_text(json.dumps(meta))

    assert SemanticIndex.open(
        workspace.layout.index_dir, HashingEmbeddingProvider(DIMENSION)
    ).needs_rebuild


def test_stats_report_who_built_the_index_and_how_big_it_is(
    index: SemanticIndex, provider: CountingEmbeddingProvider, units: list[IndexUnit]
) -> None:
    stats = index.stats()

    assert stats.provider == provider.name
    assert stats.model == provider.model
    assert stats.dimension == DIMENSION
    assert stats.unit_count == len(units)
    assert stats.index_version == INDEX_VERSION
    assert stats.needs_rebuild is False
    assert stats.built_at is not None
    assert stats.directory == index.directory


# -- helpers ------------------------------------------------------------------------


def canonical_files(root: Path) -> list[Path]:
    """Every file with scientific authority: the whole tree except `.research/`."""
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and ".research" not in path.relative_to(root).parts
    )


def canonical_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in canonical_files(root):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def canonical_text(root: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in canonical_files(root))

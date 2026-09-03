"""Identity resolution: four distinct outcomes, deterministic rules, no erased provenance."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from hypothesis import given
from hypothesis import strategies as st

from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    ArtifactKind,
    IdentityResolutionOutcome,
    ProvenanceSource,
    VersionKind,
)
from research_harness.domain.ids import ArtifactId, VersionId, WorkId
from research_harness.domain.work import (
    Artifact,
    CandidateMetadata,
    IdentifierField,
    Version,
    Work,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.ingest.identity import (
    YEAR_TOLERANCE_WITH_AUTHORS,
    ExistingRecord,
    FieldConflict,
    IdentityResolution,
    MetadataLookup,
    NullMetadataLookup,
    arxiv_base_id,
    arxiv_version_label,
    arxiv_year,
    author_surnames,
    merge_identifiers,
    normalize_arxiv_id,
    normalize_doi,
    normalize_title,
    resolve_identity,
    surname_overlap,
    title_similarity,
)

RESNET_TITLE = "Deep Residual Learning for Image Recognition"
RESNET_DOI = "10.1109/CVPR.2016.90"
RESNET_ARXIV = "1512.03385"
ARTIFACT_HASH = "sha256:" + "a1" * 32
OTHER_HASH = "sha256:" + "b2" * 32


# -- builders ----------------------------------------------------------------


def field(value: str, source: ProvenanceSource = ProvenanceSource.HUMAN) -> IdentifierField:
    return IdentifierField(value=value, source=source)


def make_work(
    work_id: str = "W0001",
    *,
    title: str = RESNET_TITLE,
    authors: tuple[str, ...] = ("Kaiming He", "Xiangyu Zhang"),
    year: int | None = 2016,
    identifiers: WorkIdentifiers | None = None,
) -> Work:
    return Work(
        id=WorkId(work_id),
        title=title,
        authors=authors,
        year=year,
        identifiers=identifiers
        or WorkIdentifiers(doi=field(RESNET_DOI), arxiv=field(RESNET_ARXIV)),
        provenance=Provenance.human(),
    )


def make_version(
    version_id: str,
    work_id: str,
    *,
    kind: VersionKind = VersionKind.ARXIV,
    label: str | None = None,
    identifiers: WorkIdentifiers | None = None,
) -> Version:
    return Version(
        id=VersionId(version_id),
        work=WorkId(work_id),
        kind=kind,
        label=label,
        identifiers=identifiers or WorkIdentifiers(),
        provenance=Provenance.human(),
    )


def make_artifact(
    artifact_id: str,
    work_id: str,
    version_id: str,
    *,
    file_hash: str = ARTIFACT_HASH,
) -> Artifact:
    return Artifact(
        id=ArtifactId(artifact_id),
        work=WorkId(work_id),
        version=VersionId(version_id),
        kind=ArtifactKind.PDF,
        file_hash=file_hash,
        original_filename="resnet.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        provenance=Provenance.system(actor="ingest"),
    )


def make_candidate(
    *,
    title: str | None = None,
    authors: tuple[str, ...] = (),
    year: int | None = None,
    doi: str | None = None,
    arxiv: str | None = None,
    identifiers: WorkIdentifiers | None = None,
    file_hash: str | None = None,
) -> WorkCandidate:
    source = ProvenanceSource.SYSTEM
    return WorkCandidate(
        provenance=Provenance.system(actor="ingest"),
        metadata=CandidateMetadata(
            title=field(title, source) if title else None,
            authors=tuple(field(name, source) for name in authors),
            year=field(str(year), source) if year is not None else None,
            identifiers=identifiers
            or WorkIdentifiers(
                doi=field(doi, source) if doi else None,
                arxiv=field(arxiv, source) if arxiv else None,
            ),
        ),
        candidate_file_hash=file_hash,
    )


def resnet_corpus() -> tuple[ExistingRecord, ...]:
    """One work with an arXiv v1 and a camera-ready version, and one registered PDF."""
    return (
        ExistingRecord(
            work=make_work(),
            versions=(
                make_version(
                    "V0001-1",
                    "W0001",
                    kind=VersionKind.ARXIV,
                    label="v1",
                    identifiers=WorkIdentifiers(arxiv=field(f"{RESNET_ARXIV}v1")),
                ),
                make_version(
                    "V0001-2",
                    "W0001",
                    kind=VersionKind.CAMERA_READY,
                    label="camera-ready",
                    identifiers=WorkIdentifiers(doi=field(RESNET_DOI)),
                ),
            ),
            artifacts=(make_artifact("A0001-1", "W0001", "V0001-1"),),
        ),
    )


# -- outcomes ----------------------------------------------------------------


def test_same_artifact_when_the_exact_bytes_are_already_registered() -> None:
    resolution = resolve_identity(make_candidate(file_hash=ARTIFACT_HASH), resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.SAME_ARTIFACT
    assert resolution.work == WorkId("W0001")
    assert resolution.version == VersionId("V0001-1")
    assert resolution.artifact == ArtifactId("A0001-1")
    assert any("file hash" in reason for reason in resolution.reasons)


def test_same_version_when_the_arxiv_id_including_its_version_suffix_matches() -> None:
    resolution = resolve_identity(make_candidate(arxiv=f"arXiv:{RESNET_ARXIV}v1"), resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.SAME_VERSION
    assert resolution.work == WorkId("W0001")
    assert resolution.version == VersionId("V0001-1")
    assert resolution.artifact is None


def test_same_version_when_the_doi_pins_the_camera_ready_version() -> None:
    resolution = resolve_identity(make_candidate(doi=RESNET_DOI), resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.SAME_VERSION
    assert resolution.version == VersionId("V0001-2")


def test_same_work_when_only_the_arxiv_base_id_matches() -> None:
    resolution = resolve_identity(make_candidate(arxiv=f"{RESNET_ARXIV}v9"), resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.SAME_WORK
    assert resolution.work == WorkId("W0001")
    assert resolution.version is None
    assert resolution.artifact is None


def test_same_work_by_normalized_title_and_a_year_within_one() -> None:
    candidate = make_candidate(title="deep residual learning, for image recognition!", year=2015)

    resolution = resolve_identity(candidate, resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.SAME_WORK
    assert any("year within" in reason for reason in resolution.reasons)


def test_same_work_by_normalized_title_and_author_surname_overlap() -> None:
    candidate = make_candidate(title=RESNET_TITLE.upper(), authors=("He, Kaiming",))

    resolution = resolve_identity(candidate, resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.SAME_WORK
    assert any("surname overlap" in reason for reason in resolution.reasons)


def test_a_bare_title_match_without_corroboration_is_not_a_work_match() -> None:
    resolution = resolve_identity(make_candidate(title=RESNET_TITLE), resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.UNRESOLVED
    assert resolution.work is None


def test_distinct_work_when_nothing_matches() -> None:
    candidate = make_candidate(
        title="A Survey of Beekeeping Practices", authors=("Zoe Zeta",), year=1999
    )

    resolution = resolve_identity(candidate, resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.DISTINCT_WORK
    assert resolution.work is None
    assert resolution.merged_identifiers is None
    assert resolution.reasons


def test_the_four_matching_outcomes_are_distinct_for_the_same_corpus() -> None:
    corpus = resnet_corpus()
    resolutions = [
        resolve_identity(make_candidate(file_hash=ARTIFACT_HASH), corpus),
        resolve_identity(make_candidate(arxiv=f"{RESNET_ARXIV}v1"), corpus),
        resolve_identity(make_candidate(arxiv=f"{RESNET_ARXIV}v9"), corpus),
        resolve_identity(make_candidate(title="Beekeeping", year=1999), corpus),
    ]

    assert [resolution.outcome for resolution in resolutions] == [
        IdentityResolutionOutcome.SAME_ARTIFACT,
        IdentityResolutionOutcome.SAME_VERSION,
        IdentityResolutionOutcome.SAME_WORK,
        IdentityResolutionOutcome.DISTINCT_WORK,
    ]
    assert len({resolution.outcome for resolution in resolutions}) == 4


# -- ambiguity ---------------------------------------------------------------


def test_unresolved_when_titles_are_near_identical_but_the_dois_conflict() -> None:
    candidate = make_candidate(
        title=f"{RESNET_TITLE}s", authors=("Zoe Zeta",), year=1999, doi="10.2/other"
    )

    resolution = resolve_identity(candidate, resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.UNRESOLVED
    assert resolution.work is None
    assert any("title similarity" in reason for reason in resolution.reasons)
    assert any("doi differs" in reason for reason in resolution.reasons)
    assert [conflict.field for conflict in resolution.conflicts] == ["doi"]


def test_unresolved_when_the_candidate_matches_two_different_works() -> None:
    shared = WorkIdentifiers()
    corpus = (
        ExistingRecord(
            work=make_work("W0001", title="Scaling Laws", year=2020, identifiers=shared)
        ),
        ExistingRecord(
            work=make_work("W0002", title="scaling  laws!", year=2020, identifiers=shared)
        ),
    )

    resolution = resolve_identity(make_candidate(title="Scaling Laws", year=2020), corpus)

    assert resolution.outcome is IdentityResolutionOutcome.UNRESOLVED
    assert resolution.work is None
    assert any("multiple works" in reason for reason in resolution.reasons)


def test_unresolved_when_the_same_bytes_are_registered_under_two_works() -> None:
    corpus = (
        ExistingRecord(
            work=make_work("W0001"),
            artifacts=(make_artifact("A0001-1", "W0001", "V0001-1"),),
        ),
        ExistingRecord(
            work=make_work("W0002", identifiers=WorkIdentifiers()),
            artifacts=(make_artifact("A0002-1", "W0002", "V0002-1"),),
        ),
    )

    resolution = resolve_identity(make_candidate(file_hash=ARTIFACT_HASH), corpus)

    assert resolution.outcome is IdentityResolutionOutcome.UNRESOLVED
    assert resolution.artifact is None
    assert any("multiple works" in reason for reason in resolution.reasons)


# -- provenance and conflicts ------------------------------------------------


def test_a_conflicting_identifier_is_recorded_not_overwritten() -> None:
    existing = WorkIdentifiers(
        doi=IdentifierField(value="10.5555/registered", source=ProvenanceSource.HUMAN),
        arxiv=IdentifierField(value="1706.03762", source=ProvenanceSource.EXTERNAL_METADATA),
    )
    corpus = (
        ExistingRecord(
            work=make_work(
                title="Attention Is All You Need",
                authors=("Ashish Vaswani",),
                year=2017,
                identifiers=existing,
            )
        ),
    )
    candidate = make_candidate(
        title="attention is all you need!",
        year=2017,
        identifiers=WorkIdentifiers(
            doi=IdentifierField(value="10.48550/arXiv.1706.03762", source=ProvenanceSource.SYSTEM),
            openalex=IdentifierField(
                value="W2963403868", source=ProvenanceSource.EXTERNAL_METADATA
            ),
        ),
    )

    resolution = resolve_identity(candidate, corpus)

    assert resolution.outcome is IdentityResolutionOutcome.SAME_WORK
    merged = resolution.merged_identifiers
    assert merged is not None
    assert merged.doi == existing.doi
    assert merged.arxiv == existing.arxiv
    assert merged.openalex is not None
    assert merged.openalex.source is ProvenanceSource.EXTERNAL_METADATA
    assert resolution.conflicts == (
        FieldConflict(
            field="doi",
            existing=existing.doi,
            incoming=candidate.metadata.identifiers.doi,
        ),
    )


def test_merge_fills_absent_fields_and_keeps_their_provenance() -> None:
    incoming = WorkIdentifiers(
        dblp=IdentifierField(value="conf/cvpr/HeZRS16", source=ProvenanceSource.EXTERNAL_METADATA)
    )

    merged, conflicts = merge_identifiers(WorkIdentifiers(), incoming)

    assert merged.dblp == incoming.dblp
    assert conflicts == ()


def test_an_arxiv_version_suffix_is_not_a_work_level_conflict() -> None:
    existing = WorkIdentifiers(arxiv=field("1512.03385"))
    incoming = WorkIdentifiers(arxiv=field("arXiv:1512.03385v4", ProvenanceSource.SYSTEM))

    merged, conflicts = merge_identifiers(existing, incoming)

    assert merged.arxiv == existing.arxiv
    assert conflicts == ()


def test_a_differently_written_doi_is_not_a_conflict() -> None:
    existing = WorkIdentifiers(doi=field(RESNET_DOI))
    incoming = WorkIdentifiers(doi=field(f"https://doi.org/{RESNET_DOI.lower()}"))

    _, conflicts = merge_identifiers(existing, incoming)

    assert conflicts == ()


# -- normalization -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://doi.org/10.1109/CVPR.2016.90", "10.1109/cvpr.2016.90"),
        ("http://dx.doi.org/10.1109/CVPR.2016.90", "10.1109/cvpr.2016.90"),
        ("DOI: 10.1109/CVPR.2016.90", "10.1109/cvpr.2016.90"),
        ("doi:https://doi.org/10.1/A", "10.1/a"),
        ("  10.1109/CVPR.2016.90.  ", "10.1109/cvpr.2016.90"),
    ],
)
def test_normalize_doi(raw: str, expected: str) -> None:
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("The  Attention, Mechanism!", "the attention mechanism"),
        ("Deep-Residual   Learning", "deep residual learning"),
        ("Ünïcode Títles", "unicode titles"),
        ("   ", ""),
    ],
)
def test_normalize_title(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


@pytest.mark.parametrize(
    ("raw", "full", "base", "label"),
    [
        ("arXiv:2401.01234v2", "2401.01234v2", "2401.01234", "v2"),
        ("https://arxiv.org/abs/2401.01234V2", "2401.01234v2", "2401.01234", "v2"),
        ("https://arxiv.org/pdf/2401.01234v2.pdf", "2401.01234v2", "2401.01234", "v2"),
        ("2401.01234", "2401.01234", "2401.01234", None),
        # Dogfood F4: bibliography prose and PDF banners wrap the id in words.
        ("arXiv preprint arXiv:2304.09513", "2304.09513", "2304.09513", None),
        ("arXiv:2301.01234v3 [cs.CR] 12 Mar 2025", "2301.01234v3", "2301.01234", "v3"),
        ("cs/0101001v1", "cs/0101001v1", "cs/0101001", "v1"),
        ("http://arxiv.org/abs/math.GT/0309136", "math.gt/0309136", "math.gt/0309136", None),
    ],
)
def test_arxiv_normalization(raw: str, full: str, base: str, label: str | None) -> None:
    assert normalize_arxiv_id(raw) == full
    assert arxiv_base_id(raw) == base
    assert arxiv_version_label(raw) == label


@pytest.mark.parametrize(
    "raw",
    [
        "arXiv preprint",
        "Proceedings of the ACM Web Conference 2022",
        "10.1145/1234567.1234568",
        "2401.012345",
        "",
    ],
)
def test_text_holding_no_arxiv_id_normalizes_to_none(raw: str) -> None:
    """It must never lowercase prose into a key: `arxiv preprint arxiv:...` matched nothing."""
    assert normalize_arxiv_id(raw) is None
    assert arxiv_base_id(raw) is None
    assert arxiv_version_label(raw) is None
    assert arxiv_year(raw) is None


@pytest.mark.parametrize(
    ("raw", "year"),
    [
        ("arXiv:2304.09513v3", 2023),
        ("2202.06335", 2022),
        ("cs/0101001", 2001),
        ("astro-ph/9912345", 1999),
        ("2413.00001", None),
    ],
)
def test_arxiv_year_is_read_from_the_id_prefix(raw: str, year: int | None) -> None:
    assert arxiv_year(raw) == year


def test_author_surnames_handle_both_name_orders() -> None:
    assert author_surnames(("Jane Q. Roe", "Doe, John")) == frozenset({"roe", "doe"})


def test_surname_overlap_is_measured_against_the_shorter_list() -> None:
    assert surname_overlap(frozenset({"he", "zhang"}), frozenset({"he"})) == 1.0
    assert surname_overlap(frozenset({"he", "zhang"}), frozenset({"roe"})) == 0.0
    assert surname_overlap(frozenset(), frozenset({"he"})) == 0.0


def test_title_similarity_is_symmetric_and_normalized() -> None:
    left, right = RESNET_TITLE, f"{RESNET_TITLE.lower()}!"
    assert title_similarity(left, right) == title_similarity(right, left) == 1.0
    assert title_similarity(RESNET_TITLE, "Beekeeping") < 0.5


# -- determinism and application ---------------------------------------------


def test_resolving_the_same_candidate_twice_gives_the_same_result() -> None:
    candidate = make_candidate(arxiv=f"{RESNET_ARXIV}v1", file_hash=OTHER_HASH)
    corpus = resnet_corpus()

    assert resolve_identity(candidate, corpus) == resolve_identity(candidate, corpus)


def test_record_order_does_not_change_the_result() -> None:
    corpus = (
        ExistingRecord(work=make_work("W0002", identifiers=WorkIdentifiers())),
        *resnet_corpus(),
    )
    candidate = make_candidate(doi=RESNET_DOI)
    reversed_corpus = tuple(reversed(corpus))

    assert resolve_identity(candidate, corpus) == resolve_identity(candidate, reversed_corpus)


@pytest.mark.parametrize(
    "candidate",
    [
        make_candidate(file_hash=ARTIFACT_HASH),
        make_candidate(arxiv=f"{RESNET_ARXIV}v1"),
        make_candidate(arxiv=f"{RESNET_ARXIV}v9"),
        make_candidate(title="Beekeeping", year=1999),
    ],
)
def test_a_resolution_can_always_be_applied_back_to_its_candidate(
    candidate: WorkCandidate,
) -> None:
    resolution = resolve_identity(candidate, resnet_corpus())

    applied = resolution.applied_to(candidate)

    assert applied.resolution is resolution.outcome
    assert applied.matched_work == resolution.work
    assert applied.matched_version == resolution.version
    assert applied.matched_artifact == resolution.artifact


# -- external lookup hook ----------------------------------------------------


class _FixedLookup:
    """Fake adapter standing in for a discovery provider's metadata service."""

    def __init__(self, metadata: CandidateMetadata) -> None:
        self.metadata = metadata
        self.calls: list[WorkIdentifiers] = []

    def lookup(self, identifiers: WorkIdentifiers) -> CandidateMetadata | None:
        self.calls.append(identifiers)
        return self.metadata


def test_the_null_lookup_never_enriches() -> None:
    lookup = NullMetadataLookup()

    assert isinstance(lookup, MetadataLookup)
    assert lookup.lookup(WorkIdentifiers(doi=field(RESNET_DOI))) is None


def test_a_lookup_only_enriches_the_candidate_before_matching() -> None:
    candidate = make_candidate(title="scan-0001")
    lookup = _FixedLookup(CandidateMetadata(identifiers=WorkIdentifiers(doi=field(RESNET_DOI))))

    assert resolve_identity(candidate, resnet_corpus()).outcome is (
        IdentityResolutionOutcome.DISTINCT_WORK
    )

    enriched = resolve_identity(candidate, resnet_corpus(), lookup=lookup)

    assert enriched.outcome is IdentityResolutionOutcome.SAME_VERSION
    assert enriched.work == WorkId("W0001")
    assert lookup.calls == [candidate.metadata.identifiers]


def test_a_lookup_never_overwrites_a_value_the_candidate_already_has() -> None:
    candidate = make_candidate(doi=RESNET_DOI)
    lookup = _FixedLookup(
        CandidateMetadata(identifiers=WorkIdentifiers(doi=field("10.9999/wrong")))
    )

    resolution = resolve_identity(candidate, resnet_corpus(), lookup=lookup)

    assert resolution.outcome is IdentityResolutionOutcome.SAME_VERSION
    assert resolution.work == WorkId("W0001")


# -- invariants --------------------------------------------------------------

_TEXT = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=1, max_size=40
).filter(lambda value: bool(value.strip()))


@st.composite
def candidates(draw: st.DrawFn) -> WorkCandidate:
    return make_candidate(
        title=draw(st.none() | _TEXT),
        authors=tuple(draw(st.lists(_TEXT, max_size=3))),
        year=draw(st.none() | st.integers(min_value=1400, max_value=2200)),
        doi=draw(st.none() | _TEXT),
        arxiv=draw(st.none() | _TEXT),
        file_hash=draw(st.none() | st.just(ARTIFACT_HASH)),
    )


@given(candidate=candidates())
def test_any_candidate_resolves_to_distinct_work_against_an_empty_corpus(
    candidate: WorkCandidate,
) -> None:
    resolution = resolve_identity(candidate, [])

    assert resolution.outcome is IdentityResolutionOutcome.DISTINCT_WORK
    assert (resolution.work, resolution.version, resolution.artifact) == (None, None, None)
    assert resolution.merged_identifiers is None
    assert resolution.conflicts == ()


@given(candidate=candidates())
def test_resolution_against_an_empty_corpus_is_applicable_and_idempotent(
    candidate: WorkCandidate,
) -> None:
    corpus: Sequence[ExistingRecord] = ()
    first = resolve_identity(candidate, corpus)

    assert first == resolve_identity(candidate, corpus)
    assert isinstance(first, IdentityResolution)
    assert first.applied_to(candidate).resolution is first.outcome


# -- year rules (dogfood F4) -------------------------------------------------


def test_the_arxiv_id_supplies_the_year_when_the_metadata_contradicts_it() -> None:
    """A v3 banner stamped two years late must not defeat the title match it belongs to."""
    candidate = make_candidate(
        title=RESNET_TITLE,
        authors=("Someone Else",),
        year=2019,
        arxiv="1512.03385v3",
        identifiers=WorkIdentifiers(arxiv=field("1512.03385v3")),
    )

    resolution = resolve_identity(candidate, resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.SAME_WORK
    assert any("arxiv base id" in reason for reason in resolution.reasons)
    assert any("year within" in reason for reason in resolution.reasons)


def test_a_year_mismatch_never_defeats_a_doi_match() -> None:
    candidate = make_candidate(doi=RESNET_DOI, year=2024, title="An Unrelated Title")

    resolution = resolve_identity(candidate, resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.SAME_VERSION
    assert resolution.work == WorkId("W0001")


def test_a_year_mismatch_never_defeats_an_arxiv_identifier_match() -> None:
    candidate = make_candidate(arxiv=f"{RESNET_ARXIV}v9", year=2024)

    resolution = resolve_identity(candidate, resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.SAME_WORK
    assert resolution.work == WorkId("W0001")


def test_a_title_match_tolerates_two_years_once_the_authors_agree() -> None:
    candidate = make_candidate(title=RESNET_TITLE, authors=("Kaiming He",), year=2018)

    resolution = resolve_identity(candidate, resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.SAME_WORK
    assert any(
        f"year within {YEAR_TOLERANCE_WITH_AUTHORS}" in reason for reason in resolution.reasons
    )


def test_a_title_match_without_authors_keeps_the_narrow_year_tolerance() -> None:
    candidate = make_candidate(title=RESNET_TITLE, authors=("Nobody Relevant",), year=2018)

    resolution = resolve_identity(candidate, resnet_corpus())

    assert resolution.outcome is IdentityResolutionOutcome.UNRESOLVED
    assert any("title similarity" in reason for reason in resolution.reasons)

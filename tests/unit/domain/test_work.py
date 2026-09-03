"""Work / Version / Artifact identity, field-level provenance, and candidates."""

from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

from research_harness.domain import (
    Artifact,
    ArtifactId,
    CandidateMetadata,
    IdentifierField,
    IdentityResolutionOutcome,
    ProvenanceSource,
    ScreeningState,
    Version,
    VersionId,
    Work,
    WorkCandidate,
    WorkId,
    WorkIdentifiers,
)
from tests.unit.domain import strategies as sty


def test_canonical_objects_carry_schema_version_id_timestamps_and_provenance() -> None:
    for model in (sty.make_work(), sty.make_version(), sty.make_artifact()):
        assert model.schema_version >= 1
        assert model.id
        assert model.created_at.tzinfo is not None
        assert model.updated_at.tzinfo is not None
        assert model.provenance.actor


def test_canonical_field_order_starts_with_schema_version_and_id() -> None:
    assert list(Work.model_fields)[:2] == ["schema_version", "id"]


def test_works_are_frozen() -> None:
    work = sty.make_work()
    with pytest.raises(ValidationError):
        work.title = "changed"  # type: ignore[misc]


def test_touch_returns_a_new_object_with_a_newer_timestamp() -> None:
    work = sty.make_work()
    renamed = work.touch(title="A better title")
    assert renamed.title == "A better title"
    assert work.title != renamed.title
    assert renamed.updated_at >= work.updated_at
    assert renamed.created_at == work.created_at


def test_touch_revalidates() -> None:
    with pytest.raises(ValidationError):
        sty.make_work().touch(title="")


def test_identifiers_keep_field_level_provenance() -> None:
    work = sty.make_work(
        identifiers=WorkIdentifiers(
            doi=IdentifierField(
                value="10.1000/example",
                source=ProvenanceSource.EXTERNAL_METADATA,
                confidence=0.9,
                note="pdf_metadata:title",
            ),
            arxiv=IdentifierField(value="2601.00001", source=ProvenanceSource.HUMAN),
        )
    )
    assert work.identifiers.doi is not None
    assert work.identifiers.doi.source is ProvenanceSource.EXTERNAL_METADATA
    assert work.identifiers.doi.note == "pdf_metadata:title"
    assert work.identifiers.arxiv is not None
    assert work.identifiers.arxiv.confidence is None


def test_an_identifier_field_records_where_the_value_was_found() -> None:
    """The note says which part of the artifact the value came from, not who produced it."""
    found = IdentifierField(
        value="10.1000/example", source=ProvenanceSource.SYSTEM, note="page1:regex"
    )
    assert found.note == "page1:regex"
    assert IdentifierField(value="x", source=ProvenanceSource.HUMAN).note is None


def test_identifier_confidence_stays_in_range() -> None:
    with pytest.raises(ValidationError):
        IdentifierField(value="x", source=ProvenanceSource.MODEL, confidence=1.5)


def test_excluded_works_must_persist_a_reason() -> None:
    with pytest.raises(ValidationError, match="must persist a reason"):
        sty.make_work(screening=ScreeningState.EXCLUDED)
    excluded = sty.make_work(
        screening=ScreeningState.EXCLUDED, exclusion_reason="not about network traffic"
    )
    assert excluded.exclusion_reason
    assert excluded.screening_note == "not about network traffic"


def test_an_included_work_can_record_why_it_was_included() -> None:
    """Dogfood F9: inclusion carries a reason too, in its own field."""
    included = sty.make_work(
        screening=ScreeningState.INCLUDED, screening_reason="encrypted traffic classification"
    )
    assert included.screening_reason == "encrypted traffic classification"
    assert included.screening_note == "encrypted traffic classification"
    assert included.exclusion_reason is None

    with pytest.raises(ValidationError, match="has no screening reason"):
        sty.make_work(screening_reason="never screened")


def test_exclusion_reason_is_only_for_excluded_works() -> None:
    with pytest.raises(ValidationError):
        sty.make_work(screening=ScreeningState.INCLUDED, exclusion_reason="nope")


def test_a_work_lists_its_versions_and_artifacts() -> None:
    work = sty.make_work(
        versions=(VersionId("V0017-1"), VersionId("V0017-2")),
        artifacts=(ArtifactId("A0017-3"),),
    )
    assert work.versions == ("V0017-1", "V0017-2")
    assert work.artifacts == ("A0017-3",)


def test_versions_belong_to_a_work_and_may_carry_a_date() -> None:
    version = sty.make_version(date=datetime.date(2026, 3, 1))
    assert version.work == WorkId("W0017")
    assert version.date == datetime.date(2026, 3, 1)
    assert Version.model_validate(version.model_dump(mode="json")) == version


def test_artifacts_require_a_sha256_hash() -> None:
    with pytest.raises(ValidationError):
        sty.make_artifact(file_hash="deadbeef")
    with pytest.raises(ValidationError):
        sty.make_artifact(file_hash="sha256:NOTHEX" + "0" * 58)


def test_artifacts_reference_both_work_and_version() -> None:
    artifact = sty.make_artifact()
    assert artifact.work == WorkId("W0017")
    assert artifact.version == VersionId("V0017-2")
    assert artifact.size_bytes >= 0
    assert artifact.ingested_at.tzinfo is not None


def test_artifacts_have_no_mutable_scientific_fields() -> None:
    """An artifact is bytes on disk: identity, not opinion."""
    assert not set(Artifact.model_fields) & {"screening", "verification", "stale", "status"}
    with pytest.raises(ValidationError):
        sty.make_artifact().file_hash = sty.HASH_C  # type: ignore[misc]


def test_a_candidate_is_not_canonical_state() -> None:
    """Product 8.3: discovery output has no stable research id until it is accepted."""
    candidate = WorkCandidate(provenance=sty.MODEL)
    assert not hasattr(candidate, "id")
    assert candidate.screening is ScreeningState.DISCOVERED
    assert candidate.resolution is IdentityResolutionOutcome.UNRESOLVED


def test_candidate_metadata_carries_provenance_per_field() -> None:
    candidate = WorkCandidate(
        metadata=CandidateMetadata(
            title=IdentifierField(value="A paper", source=ProvenanceSource.EXTERNAL_METADATA),
            year=IdentifierField(value="2026", source=ProvenanceSource.MODEL, confidence=0.4),
        ),
        candidate_file_hash=sty.HASH_A,
        provenance=sty.MODEL,
    )
    assert candidate.metadata.title is not None
    assert candidate.metadata.title.source is ProvenanceSource.EXTERNAL_METADATA


@pytest.mark.parametrize(
    ("outcome", "links"),
    [
        (IdentityResolutionOutcome.SAME_WORK, {"matched_work": WorkId("W0017")}),
        (
            IdentityResolutionOutcome.SAME_VERSION,
            {"matched_work": WorkId("W0017"), "matched_version": VersionId("V0017-2")},
        ),
        (
            IdentityResolutionOutcome.SAME_ARTIFACT,
            {
                "matched_work": WorkId("W0017"),
                "matched_version": VersionId("V0017-2"),
                "matched_artifact": ArtifactId("A0017-3"),
            },
        ),
        (IdentityResolutionOutcome.DISTINCT_WORK, {}),
        (IdentityResolutionOutcome.UNRESOLVED, {}),
    ],
)
def test_resolution_outcomes_require_their_own_links(
    outcome: IdentityResolutionOutcome, links: dict[str, str]
) -> None:
    candidate = WorkCandidate(resolution=outcome, provenance=sty.MODEL, **links)
    assert candidate.resolution is outcome


def test_resolution_outcomes_are_distinct_and_validated() -> None:
    with pytest.raises(ValidationError, match="requires matched_work"):
        WorkCandidate(resolution=IdentityResolutionOutcome.SAME_WORK, provenance=sty.MODEL)
    with pytest.raises(ValidationError, match="must not set"):
        WorkCandidate(
            resolution=IdentityResolutionOutcome.DISTINCT_WORK,
            matched_work=WorkId("W0017"),
            provenance=sty.MODEL,
        )
    with pytest.raises(ValidationError, match="requires matched_version"):
        WorkCandidate(
            resolution=IdentityResolutionOutcome.SAME_VERSION,
            matched_work=WorkId("W0017"),
            provenance=sty.MODEL,
        )


def test_excluded_candidates_persist_a_reason() -> None:
    with pytest.raises(ValidationError):
        WorkCandidate(screening=ScreeningState.EXCLUDED, provenance=sty.MODEL)

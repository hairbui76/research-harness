"""Stable identifiers: prefix validation, string behaviour, and deterministic allocation."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from research_harness.domain.errors import DomainValidationError
from research_harness.domain.ids import (
    ID_TYPES,
    ArtifactId,
    BlockId,
    ClaimId,
    ContextPackId,
    ConversationSessionId,
    DecisionId,
    EvidenceId,
    InterpretationId,
    MessageId,
    QuestionId,
    ResearchId,
    SearchRunId,
    SessionAttachmentId,
    SynthesisId,
    VersionId,
    WorkId,
    parse_id,
)

ALL_PREFIXES = {
    WorkId: "W",
    VersionId: "V",
    ArtifactId: "A",
    BlockId: "B",
    EvidenceId: "E",
    InterpretationId: "I",
    ClaimId: "C",
    QuestionId: "RQ",
    DecisionId: "D",
    SearchRunId: "SR",
    SynthesisId: "S",
    ConversationSessionId: "CS",
    MessageId: "M",
    SessionAttachmentId: "SA",
    ContextPackId: "CP",
}


def test_every_product_prefix_has_an_id_type() -> None:
    assert set(ID_TYPES) == set(ALL_PREFIXES)
    assert {id_type.prefix for id_type in ID_TYPES} == set(ALL_PREFIXES.values())


@pytest.mark.parametrize(("id_type", "prefix"), list(ALL_PREFIXES.items()))
def test_id_accepts_its_own_prefix(id_type: type[ResearchId], prefix: str) -> None:
    identifier = id_type(f"{prefix}0001")
    assert identifier == f"{prefix}0001"
    assert identifier.number == 1


@pytest.mark.parametrize(("id_type", "prefix"), list(ALL_PREFIXES.items()))
def test_id_rejects_a_foreign_prefix(id_type: type[ResearchId], prefix: str) -> None:
    foreign = "Z" if prefix != "Z" else "Y"
    with pytest.raises(DomainValidationError):
        id_type(f"{foreign}0001")


@pytest.mark.parametrize("bad", ["W1", "W123", "W", "0001", "w0001", "W0001x", " W0001"])
def test_id_grammar_requires_prefix_and_four_digits(bad: str) -> None:
    with pytest.raises(DomainValidationError):
        WorkId(bad)


def test_search_run_prefix_wins_over_synthesis_prefix() -> None:
    assert isinstance(parse_id("SR0019"), SearchRunId)
    assert isinstance(parse_id("S0019"), SynthesisId)
    assert isinstance(parse_id("RQ0003"), QuestionId)
    assert not isinstance(parse_id("S0019"), SearchRunId)


def test_synthesis_id_rejects_a_search_run_id() -> None:
    with pytest.raises(DomainValidationError):
        SynthesisId("SR0019")


def test_parse_id_rejects_an_unknown_prefix() -> None:
    with pytest.raises(DomainValidationError):
        parse_id("X0001")


def test_work_scoped_ids_accept_a_suffix() -> None:
    version = VersionId("V0017-2")
    artifact = ArtifactId("A0017-3")
    assert (version.number, version.suffix) == (17, 2)
    assert (artifact.number, artifact.suffix) == (17, 3)


def test_unscoped_ids_reject_a_suffix() -> None:
    with pytest.raises(DomainValidationError):
        EvidenceId("E0482-1")
    with pytest.raises(DomainValidationError):
        WorkId.make(17, 2)


def test_ids_behave_as_strings() -> None:
    identifier = WorkId("W0017")
    assert isinstance(identifier, str)
    assert {identifier: "value"}[identifier] == "value"
    assert {identifier: "value"}["W0017"] == "value"
    assert hash(identifier) == hash("W0017")
    assert identifier.startswith("W")


def test_ids_sort_by_sequence_number() -> None:
    ids = [WorkId("W0010"), WorkId("W0002"), WorkId("W0100")]
    assert sorted(ids) == ["W0002", "W0010", "W0100"]


def test_make_zero_pads_to_four_digits() -> None:
    assert WorkId.make(1) == "W0001"
    assert WorkId.make(12345) == "W12345"
    assert VersionId.make(17, 2) == "V0017-2"


def test_make_rejects_negative_numbers() -> None:
    with pytest.raises(DomainValidationError):
        WorkId.make(-1)


def test_next_allocates_after_the_highest_existing_number() -> None:
    assert WorkId.next([]) == "W0001"
    assert WorkId.next(["W0001", "W0009", "W0003"]) == "W0010"


def test_next_ignores_ids_of_other_types() -> None:
    assert WorkId.next(["W0001", "E0482", "SR0019"]) == "W0002"


def test_next_in_scope_allocates_inside_one_work() -> None:
    assert VersionId.next_in_scope(17, []) == "V0017-1"
    assert VersionId.next_in_scope(17, ["V0017-1", "V0018-9"]) == "V0017-2"
    assert VersionId.next_in_scope(17, ["V0017"]) == "V0017-1"
    assert ArtifactId.next_in_scope(17, ["A0017-3"]) == "A0017-4"


def test_next_in_scope_is_only_for_work_scoped_ids() -> None:
    with pytest.raises(DomainValidationError):
        EvidenceId.next_in_scope(1, [])


def test_research_id_is_abstract() -> None:
    with pytest.raises(DomainValidationError):
        ResearchId("W0001")


class Holder(BaseModel):
    """Model exercising id fields."""

    work: WorkId
    any_id: ResearchId


def test_ids_validate_and_serialize_inside_pydantic_models() -> None:
    holder = Holder(work=WorkId("W0017"), any_id=EvidenceId("E0482"))
    parsed = Holder.model_validate({"work": "W0017", "any_id": "SR0019"})
    assert isinstance(parsed.any_id, SearchRunId)
    dumped = holder.model_dump(mode="json")
    assert dumped == {"work": "W0017", "any_id": "E0482"}
    assert type(dumped["work"]) is str
    assert Holder.model_validate(dumped) == holder


def test_pydantic_rejects_a_wrong_prefix() -> None:
    with pytest.raises(ValidationError):
        Holder.model_validate({"work": "E0482", "any_id": "E0482"})


def test_id_json_schema_is_a_string() -> None:
    schema = Holder.model_json_schema()["properties"]["work"]
    assert schema["type"] == "string"
    assert schema["pattern"] == WorkId.pattern()


def test_each_id_class_compiles_its_grammar_once() -> None:
    """Ids are built millions of times per corpus read; the pattern must not be rebuilt."""
    assert WorkId._regex() is WorkId._regex()
    assert WorkId._regex() is not VersionId._regex()
    assert WorkId._regex().pattern == WorkId.pattern()
    assert VersionId._regex().pattern == VersionId.pattern()


def test_a_subclass_defined_later_still_gets_its_own_grammar() -> None:
    """`__init_subclass__` compiles from the class body, so a new id type needs no wiring."""

    class ProbeId(ResearchId):
        __slots__ = ()
        prefix = "ZZ"
        scoped = True

    assert ProbeId("ZZ0001-2").suffix == 2
    assert ProbeId._regex().pattern == ProbeId.pattern()
    with pytest.raises(DomainValidationError):
        ProbeId("W0001")

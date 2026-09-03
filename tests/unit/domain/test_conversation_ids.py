"""Conversation identifiers: prefix dispatch, ordering, allocation, and serialization."""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ConfigDict

from research_harness.domain.errors import DomainValidationError
from research_harness.domain.ids import (
    ID_TYPES,
    ClaimId,
    ContextPackId,
    ConversationSessionId,
    MessageId,
    ResearchId,
    SearchRunId,
    SessionAttachmentId,
    SynthesisId,
    parse_id,
)

CONVERSATION_PREFIXES = {
    ConversationSessionId: "CS",
    MessageId: "M",
    SessionAttachmentId: "SA",
    ContextPackId: "CP",
}


class Holder(BaseModel):
    """Model carrying one id of every conversation type, plus an open one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session: ConversationSessionId
    message: MessageId
    attachment: SessionAttachmentId
    pack: ContextPackId
    any_id: ResearchId


def make_holder() -> Holder:
    return Holder(
        session=ConversationSessionId("CS0001"),
        message=MessageId("M0042"),
        attachment=SessionAttachmentId("SA0003"),
        pack=ContextPackId("CP0007"),
        any_id=ClaimId("C0041"),
    )


@pytest.mark.parametrize(("id_type", "prefix"), list(CONVERSATION_PREFIXES.items()))
def test_conversation_id_accepts_its_own_prefix(id_type: type[ResearchId], prefix: str) -> None:
    identifier = id_type(f"{prefix}0001")
    assert identifier.number == 1
    assert identifier == f"{prefix}0001"


def test_every_conversation_prefix_is_registered_for_dispatch() -> None:
    for id_type in CONVERSATION_PREFIXES:
        assert id_type in ID_TYPES


def test_longer_prefixes_win_over_the_shorter_ones_they_start_with() -> None:
    assert isinstance(parse_id("CS0001"), ConversationSessionId)
    assert isinstance(parse_id("CP0001"), ContextPackId)
    assert isinstance(parse_id("C0001"), ClaimId)
    assert isinstance(parse_id("SA0001"), SessionAttachmentId)
    assert isinstance(parse_id("S0001"), SynthesisId)
    assert isinstance(parse_id("SR0001"), SearchRunId)
    assert isinstance(parse_id("M0001"), MessageId)


def test_claim_and_synthesis_ids_refuse_the_conversation_prefixes() -> None:
    for text in ("CS0001", "CP0001"):
        with pytest.raises(DomainValidationError):
            ClaimId(text)
    with pytest.raises(DomainValidationError):
        SynthesisId("SA0001")
    with pytest.raises(DomainValidationError):
        ConversationSessionId("C0001")
    with pytest.raises(DomainValidationError):
        SessionAttachmentId("S0001")


@given(st.sampled_from(ID_TYPES), st.integers(min_value=1, max_value=99999))
def test_parse_id_returns_the_type_that_minted_the_id(
    id_type: type[ResearchId], number: int
) -> None:
    """Dispatch must be exact for every registered type, not merely prefix-compatible."""
    assert type(parse_id(id_type.make(number))) is id_type


def test_conversation_ids_are_not_work_scoped() -> None:
    for id_type in CONVERSATION_PREFIXES:
        assert id_type.scoped is False
        with pytest.raises(DomainValidationError):
            id_type.make(1, 2)


def test_conversation_ids_sort_by_sequence_number() -> None:
    ids = [MessageId("M0010"), MessageId("M0002"), MessageId("M0100")]
    assert sorted(ids) == ["M0002", "M0010", "M0100"]


def test_allocation_ignores_ids_of_other_types() -> None:
    existing = ["CS0004", "M0009", "SA0002", "CP0005", "C0041", "S0003"]
    assert ConversationSessionId.next(existing) == "CS0005"
    assert MessageId.next(existing) == "M0010"
    assert SessionAttachmentId.next(existing) == "SA0003"
    assert ContextPackId.next(existing) == "CP0006"


def test_ids_round_trip_through_yaml() -> None:
    """Canonical YAML holds plain strings and comes back as the concrete id types."""
    holder = make_holder()
    payload = holder.model_dump(mode="json")
    assert all(type(value) is str for value in payload.values())
    reloaded = Holder.model_validate(yaml.safe_load(yaml.safe_dump(payload, sort_keys=False)))
    assert reloaded == holder
    assert isinstance(reloaded.session, ConversationSessionId)
    assert isinstance(reloaded.any_id, ClaimId)


def test_ids_round_trip_through_a_json_lines_record() -> None:
    holder = make_holder()
    line = json.dumps(holder.model_dump(mode="json"), sort_keys=True) + "\n"
    payload: dict[str, Any] = json.loads(line)
    assert Holder.model_validate(payload) == holder


def test_pydantic_refuses_a_foreign_prefix_in_a_typed_field() -> None:
    payload = make_holder().model_dump(mode="json")
    payload["session"] = "C0001"
    with pytest.raises(ValueError, match="session"):
        Holder.model_validate(payload)

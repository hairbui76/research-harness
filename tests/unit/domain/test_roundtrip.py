"""Serialization round-trips: canonical meaning survives JSON in both directions."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from pydantic import BaseModel

from research_harness.domain import Artifact, Claim, Decision, Evidence, Version, Work
from tests.unit.domain import strategies as sty

ROUNDTRIP = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


def assert_roundtrips[ModelT: BaseModel](model: ModelT) -> None:
    """A model must survive json-mode dumping and json serialization unchanged."""
    same_class = type(model)
    assert same_class.model_validate(model.model_dump(mode="json")) == model
    assert same_class.model_validate_json(model.model_dump_json()) == model
    assert same_class.model_validate(model.model_dump()) == model


@ROUNDTRIP
@given(sty.works())
def test_work_roundtrips(work: Work) -> None:
    assert_roundtrips(work)


@ROUNDTRIP
@given(sty.versions())
def test_version_roundtrips(version: Version) -> None:
    assert_roundtrips(version)


@ROUNDTRIP
@given(sty.artifacts())
def test_artifact_roundtrips(artifact: Artifact) -> None:
    assert_roundtrips(artifact)


@ROUNDTRIP
@given(sty.evidence_objects())
def test_evidence_roundtrips(evidence: Evidence) -> None:
    assert_roundtrips(evidence)


@ROUNDTRIP
@given(sty.claims())
def test_claim_roundtrips(claim: Claim) -> None:
    assert_roundtrips(claim)


@ROUNDTRIP
@given(sty.decisions())
def test_decision_roundtrips(decision: Decision) -> None:
    assert_roundtrips(decision)


@ROUNDTRIP
@given(sty.evidence_objects())
def test_ids_serialize_as_plain_strings(evidence: Evidence) -> None:
    """Canonical files hold plain strings, not a Python-specific id type."""
    dumped = evidence.model_dump(mode="json")
    assert type(dumped["id"]) is str
    assert type(dumped["source"]["work"]) is str


@ROUNDTRIP
@given(sty.claims())
def test_json_schema_describes_ids_as_strings(claim: Claim) -> None:
    schema = type(claim).model_json_schema()
    assert schema["properties"]["id"]["type"] == "string"


@pytest.mark.parametrize(
    "model",
    [
        sty.make_work(),
        sty.make_version(),
        sty.make_artifact(),
        sty.make_evidence(),
        sty.make_claim(),
        sty.make_override_decision(),
        sty.make_note(),
        sty.make_question(),
        sty.make_block(),
        sty.make_search_run(),
    ],
    ids=lambda model: type(model).__name__,
)
def test_hand_authored_fixtures_roundtrip(model: BaseModel) -> None:
    assert_roundtrips(model)

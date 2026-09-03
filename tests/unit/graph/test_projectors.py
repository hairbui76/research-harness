"""Pure projector helpers: identities, authority mapping, and the projector registry."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from research_harness.domain import ClaimStatus, EvidenceStatus, StaleState
from research_harness.domain.graph import GraphAuthority
from research_harness.graph.projectors import (
    Projector,
    anchor_identity,
    block_identity,
    candidate_identity,
    citation_identity,
    claim_authority,
    default_projectors,
    evidence_authority,
    graph_identity,
    manuscript_file_identity,
    project_identity,
)
from research_harness.projection.rows import manuscript_anchor_key, matrix_cell_node_id
from tests.unit.domain import strategies as sty

MOMENT = datetime(2026, 1, 1, tzinfo=UTC)
FINGERPRINT = "sha256:" + "c" * 64


# --- identities -------------------------------------------------------------


def test_identity_helpers_are_prefixed_and_self_describing() -> None:
    assert project_identity("structured-traffic") == "project:structured-traffic"
    assert block_identity("A0017-3", "B0081") == "block:A0017-3#B0081"
    assert manuscript_file_identity("manuscript/main.tex") == "file:manuscript/main.tex"
    assert citation_identity("smith2024") == "cite:smith2024"
    assert candidate_identity("cand_0011") == "candidate:cand_0011"
    assert anchor_identity("manuscript/main.tex", FINGERPRINT) == (
        f"anchor:manuscript/main.tex#{FINGERPRINT}"
    )


def test_a_block_identity_is_artifact_scoped_because_a_block_id_is() -> None:
    """`projection.schema.BLOCKS` keys on `(artifact, id)`; a bare `B0081` is ambiguous."""
    assert block_identity("A0017-3", "B0081") != block_identity("A0018-1", "B0081")


@pytest.mark.parametrize(
    ("dependency_node", "expected"),
    [
        ("W0017", "W0017"),
        ("V0017-2", "V0017-2"),
        ("A0017-3", "A0017-3"),
        ("E0482", "E0482"),
        ("C0041", "C0041"),
        ("D0027", "D0027"),
        ("RQ0003", "RQ0003"),
        ("S0007", "S0007"),
    ],
)
def test_dependency_nodes_the_graph_projects_keep_their_identity(
    dependency_node: str, expected: str
) -> None:
    assert graph_identity(dependency_node) == expected


def test_a_manuscript_anchor_dependency_node_becomes_an_anchor_identity() -> None:
    node = manuscript_anchor_key("manuscript/main.tex", FINGERPRINT)

    assert graph_identity(node) == anchor_identity("manuscript/main.tex", FINGERPRINT)


@pytest.mark.parametrize(
    "dependency_node",
    [
        "TX:representation",
        matrix_cell_node_id("S0007", "W0017", "tokenization"),
        "SR0019",
        "I0004",
        "B0081",
        "note-20260105-000000-abcdef",
        "",
    ],
)
def test_dependency_nodes_outside_the_graph_vocabulary_have_no_identity(
    dependency_node: str,
) -> None:
    """Taxonomies, matrix cells, search runs, interpretations, blocks and notes are not nodes."""
    assert graph_identity(dependency_node) is None


# --- authority --------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (EvidenceStatus.ACCEPTED, GraphAuthority.ACCEPTED),
        (EvidenceStatus.PROPOSED, GraphAuthority.CANDIDATE),
        (EvidenceStatus.VERIFIED, GraphAuthority.CANDIDATE),
        (EvidenceStatus.DEFERRED, GraphAuthority.CANDIDATE),
        (EvidenceStatus.REJECTED, GraphAuthority.CONTESTED),
        (EvidenceStatus.SUPERSEDED, GraphAuthority.CONTESTED),
    ],
)
def test_evidence_authority_follows_the_verification_record(
    status: EvidenceStatus, expected: GraphAuthority
) -> None:
    verification = sty.make_evidence().verification.model_copy(
        update={"status": status, "accepted_by": "human:alice"}
    )
    evidence = sty.make_evidence(verification=verification)

    assert evidence_authority(evidence) == expected


def test_stale_evidence_is_labelled_stale_whatever_its_status_says() -> None:
    evidence = sty.make_evidence(stale=StaleState.STALE)

    assert evidence_authority(evidence) is GraphAuthority.STALE


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ClaimStatus.UNVERIFIED, GraphAuthority.ACCEPTED),
        (ClaimStatus.SUPPORTED, GraphAuthority.ACCEPTED),
        (ClaimStatus.QUALIFIED, GraphAuthority.QUALIFIED),
        (ClaimStatus.CONTESTED, GraphAuthority.CONTESTED),
        (ClaimStatus.UNSUPPORTED, GraphAuthority.CONTESTED),
        (ClaimStatus.SUPERSEDED, GraphAuthority.CONTESTED),
    ],
)
def test_claim_authority_follows_the_assessment(
    status: ClaimStatus, expected: GraphAuthority
) -> None:
    claim = sty.make_claim()
    claim = claim.model_copy(
        update={"assessment": claim.assessment.model_copy(update={"status": status})}
    )

    assert claim_authority(claim) == expected


def test_a_stale_claim_is_labelled_stale() -> None:
    assert claim_authority(sty.make_claim(stale=StaleState.STALE)) is GraphAuthority.STALE


# --- the registry -----------------------------------------------------------


def test_every_default_projector_satisfies_the_protocol_and_is_named_once() -> None:
    projectors = default_projectors()
    names = [projector.name for projector in projectors]

    assert all(isinstance(projector, Projector) for projector in projectors)
    assert len(names) == len(set(names))
    assert "candidate" in names


def test_the_registry_is_a_value_so_a_later_namespace_slots_in() -> None:
    """G2 adds a sessions projector by passing a tuple; nothing in the package changes."""

    class SessionsProjector:
        name = "sessions"

        def project(self, ctx: object) -> list[object]:
            return []

    extended = (*default_projectors(), SessionsProjector())

    assert [projector.name for projector in extended][-1] == "sessions"
    assert isinstance(SessionsProjector(), Projector)

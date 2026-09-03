"""Role permissions are structural: a prompt cannot widen what a contract allows.

These tests state the invariants ADR-003 and Product 23 rely on, so a later edit that
lets the writer create evidence, or shows the verifier the extractor's reasoning, fails
here rather than in a manuscript.
"""

from __future__ import annotations

import pytest

from research_harness.domain.errors import AuthorityError, CapabilityError
from research_harness.roles import (
    CLAIM_AUDITOR,
    EXTRACTOR,
    ROLES,
    SKEPTIC,
    SYNTHESIZER,
    VERIFIER,
    WRITER,
    InputKind,
    RoleContract,
    WriteScope,
    assert_can_read,
    assert_can_write,
    assert_capability_allowed,
    get_role,
    role_names,
)

ALL_ROLES = (EXTRACTOR, VERIFIER, SKEPTIC, CLAIM_AUDITOR, SYNTHESIZER, WRITER)


# ------------------------------------------------------------------- write scopes


def test_no_write_scope_names_accepted_state() -> None:
    """Accepted evidence/claims/decisions are unreachable by construction (ADR-003)."""
    for scope in WriteScope:
        assert "accepted" not in scope.name.lower()
        assert "accepted" not in scope.value


@pytest.mark.parametrize("contract", ALL_ROLES, ids=lambda contract: contract.name)
def test_every_role_writes_one_non_accepted_scope(contract: RoleContract) -> None:
    assert contract.write_scope is not WriteScope.NONE
    assert contract.write_scope in set(WriteScope)


def test_writer_writes_manuscript_candidates_only() -> None:
    assert_can_write(WRITER, WriteScope.MANUSCRIPT_CANDIDATE)
    for scope in (
        WriteScope.STAGING_EVIDENCE,
        WriteScope.VERIFICATION_RESULT,
        WriteScope.AUDIT_RESULT,
        WriteScope.SYNTHESIS_CANDIDATE,
        WriteScope.NONE,
    ):
        with pytest.raises(AuthorityError, match="writer"):
            assert_can_write(WRITER, scope)


def test_extractor_writes_staging_only() -> None:
    assert_can_write(EXTRACTOR, WriteScope.STAGING_EVIDENCE)
    for scope in (
        WriteScope.VERIFICATION_RESULT,
        WriteScope.AUDIT_RESULT,
        WriteScope.SYNTHESIS_CANDIDATE,
        WriteScope.MANUSCRIPT_CANDIDATE,
        WriteScope.NONE,
    ):
        with pytest.raises(AuthorityError):
            assert_can_write(EXTRACTOR, scope)


def test_verifier_writes_verification_results_only() -> None:
    """A verifier records a verdict; it never rewrites the candidate or the manuscript."""
    assert_can_write(VERIFIER, WriteScope.VERIFICATION_RESULT)
    for scope in (WriteScope.STAGING_EVIDENCE, WriteScope.MANUSCRIPT_CANDIDATE):
        with pytest.raises(AuthorityError, match="evidence_verifier"):
            assert_can_write(VERIFIER, scope)


# ------------------------------------------------------------------ allowed inputs


def test_verifier_cannot_read_accepted_state() -> None:
    for kind in (InputKind.ACCEPTED_CLAIMS, InputKind.ACCEPTED_EVIDENCE, InputKind.TAXONOMY):
        with pytest.raises(AuthorityError, match="evidence_verifier"):
            assert_can_read(VERIFIER, kind)


def test_verifier_reads_only_the_candidate_and_its_source() -> None:
    """Extractor reasoning is kept away by the contract, not by a prompt (ADR-003)."""
    assert VERIFIER.allowed_inputs == frozenset(
        {InputKind.CANDIDATE_EVIDENCE, InputKind.DOCUMENT_BLOCKS, InputKind.SOURCE_DOCUMENT}
    )


def test_extractor_reads_the_document_and_the_interrogation_schema() -> None:
    assert_can_read(EXTRACTOR, InputKind.SOURCE_DOCUMENT)
    assert_can_read(EXTRACTOR, InputKind.DOCUMENT_BLOCKS)
    assert_can_read(EXTRACTOR, InputKind.INTERROGATION_SCHEMA)
    for kind in (InputKind.ACCEPTED_CLAIMS, InputKind.MANUSCRIPT_TEXT):
        with pytest.raises(AuthorityError, match="evidence_extractor"):
            assert_can_read(EXTRACTOR, kind)


def test_writer_reads_accepted_state_and_the_manuscript() -> None:
    for kind in (
        InputKind.ACCEPTED_CLAIMS,
        InputKind.ACCEPTED_EVIDENCE,
        InputKind.ACCEPTED_DECISIONS,
        InputKind.MANUSCRIPT_TEXT,
    ):
        assert_can_read(WRITER, kind)
    with pytest.raises(AuthorityError):
        assert_can_read(WRITER, InputKind.CANDIDATE_EVIDENCE)


# -------------------------------------------------------------------- capabilities


def test_writer_cannot_call_accepting_or_creating_capabilities() -> None:
    for capability in (
        "evidence.accept",
        "evidence.reject",
        "evidence.extract",
        "claim.create",
        "decision.record",
        "review.accept_batch",
    ):
        with pytest.raises(AuthorityError, match="writer"):
            assert_capability_allowed(WRITER, capability)


def test_writer_may_call_its_read_only_capabilities() -> None:
    assert_capability_allowed(WRITER, "claim.find_support")
    assert_capability_allowed(WRITER, "citation.verify")


def test_extractor_cannot_accept_reject_or_touch_claims() -> None:
    for capability in ("evidence.accept", "evidence.reject", "claim.create", "claim.audit"):
        with pytest.raises(AuthorityError, match="evidence_extractor"):
            assert_capability_allowed(EXTRACTOR, capability)


@pytest.mark.parametrize("contract", ALL_ROLES, ids=lambda contract: contract.name)
def test_no_role_can_accept_reject_or_review(contract: RoleContract) -> None:
    """Acceptance is a human act under strict policy (ADR-007, Product 24)."""
    for capability in (
        "evidence.accept",
        "evidence.reject",
        "review.accept_batch",
        "review.resolve_conflict",
    ):
        with pytest.raises(AuthorityError):
            assert_capability_allowed(contract, capability)


@pytest.mark.parametrize("contract", ALL_ROLES, ids=lambda contract: contract.name)
def test_unlisted_capabilities_are_denied_by_default(contract: RoleContract) -> None:
    with pytest.raises(AuthorityError, match=contract.name):
        assert_capability_allowed(contract, "state.rebuild")


def test_a_contract_cannot_allow_and_forbid_the_same_capability() -> None:
    with pytest.raises(ValueError, match="allows and forbids"):
        RoleContract(
            name="contradictory",
            objective="allow and deny the same thing",
            allowed_inputs=frozenset({InputKind.SOURCE_DOCUMENT}),
            allowed_capabilities=frozenset({"evidence.accept"}),
            forbidden=frozenset({"evidence.*"}),
            output_schema=EXTRACTOR.output_schema,
            write_scope=WriteScope.STAGING_EVIDENCE,
            requirements=EXTRACTOR.requirements,
            template_version="1.0.0",
            system_prompt="test",
        )


# ------------------------------------------------------------------------ registry


@pytest.mark.parametrize("contract", ALL_ROLES, ids=lambda contract: contract.name)
def test_every_role_carries_a_prompt_and_a_template_version(contract: RoleContract) -> None:
    """Both land in reproducibility metadata, so neither may be empty (Product 20.5)."""
    assert contract.system_prompt.strip()
    assert contract.template_version.strip()
    assert contract.objective.strip()
    assert contract.allowed_inputs
    assert contract.requirements.structured_output is True


def test_registry_holds_every_role_under_its_own_name() -> None:
    assert set(role_names()) == {contract.name for contract in ALL_ROLES}
    for contract in ALL_ROLES:
        assert get_role(contract.name) is contract
        assert ROLES[contract.name] is contract


def test_unknown_role_is_an_error_not_an_unbounded_call() -> None:
    with pytest.raises(CapabilityError, match="unknown role"):
        get_role("autonomous_researcher")


def test_contracts_are_frozen() -> None:
    with pytest.raises(ValueError, match="frozen"):
        WRITER.write_scope = WriteScope.STAGING_EVIDENCE  # type: ignore[misc]

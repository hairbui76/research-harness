"""Bounded semantic roles: configuration, not agents (Product 23).

Each role is a `RoleContract` naming its objective, the inputs it may read, the
capabilities it may call, the schema its answer must satisfy, the model requirements it
needs, and the single staging scope it may write. No contract can name accepted state:
Evidence, Claims, and Decisions become accepted only through human review in the
capability layer (ADR-003, ADR-007).

    from research_harness.roles import InputKind, RoleInput, build_request, get_role

    contract = get_role("evidence_verifier")
    built = build_request(contract, [RoleInput(InputKind.CANDIDATE_EVIDENCE, "E0007", candidate)])
    response = router.complete(built.request)
"""

from __future__ import annotations

from research_harness.roles.auditor import CLAIM_AUDITOR
from research_harness.roles.contracts import (
    HIDDEN_REASONING_FIELDS,
    HUMAN_ONLY_CAPABILITIES,
    RATIONALE_MAX_CHARS,
    InputKind,
    Rationale,
    RoleContract,
    RoleInput,
    RoleInputContent,
    RoleRequest,
    WriteScope,
    assert_can_read,
    assert_can_write,
    assert_capability_allowed,
    build_request,
    json_schema_fingerprint,
)
from research_harness.roles.extractor import EXTRACTOR
from research_harness.roles.registry import ROLES, get_role, role_names
from research_harness.roles.schemas import (
    EXTRACTOR_ALLOWED_NEGATIVE_STATES,
    EXTRACTOR_ALLOWED_ORIGINS,
    CellProposal,
    ClaimAuditOutput,
    EvidenceCandidateOutput,
    ExtractionOutput,
    QualifierNote,
    RoleOutput,
    SkepticOutput,
    SynthesisOutput,
    VerificationOutput,
    WriterOutput,
)
from research_harness.roles.skeptic import SKEPTIC
from research_harness.roles.synthesizer import SYNTHESIZER
from research_harness.roles.verifier import VERIFIER
from research_harness.roles.writer import WRITER

__all__ = [
    "CLAIM_AUDITOR",
    "EXTRACTOR",
    "EXTRACTOR_ALLOWED_NEGATIVE_STATES",
    "EXTRACTOR_ALLOWED_ORIGINS",
    "HIDDEN_REASONING_FIELDS",
    "HUMAN_ONLY_CAPABILITIES",
    "RATIONALE_MAX_CHARS",
    "ROLES",
    "SKEPTIC",
    "SYNTHESIZER",
    "VERIFIER",
    "WRITER",
    "CellProposal",
    "ClaimAuditOutput",
    "EvidenceCandidateOutput",
    "ExtractionOutput",
    "InputKind",
    "QualifierNote",
    "Rationale",
    "RoleContract",
    "RoleInput",
    "RoleInputContent",
    "RoleOutput",
    "RoleRequest",
    "SkepticOutput",
    "SynthesisOutput",
    "VerificationOutput",
    "WriteScope",
    "WriterOutput",
    "assert_can_read",
    "assert_can_write",
    "assert_capability_allowed",
    "build_request",
    "get_role",
    "json_schema_fingerprint",
    "role_names",
]

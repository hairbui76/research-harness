"""Product §42.H - Human review.

"A model cannot bypass the strict review gate for interpretive scientific state."

The gate is checked from every direction a model could reach it: the handler, the named
capability registry, the HTTP daemon, and the MCP bridge. Then the two ways the gate is
usually lost by accident - a policy batch under strict review, and a confidence number
sneaking into the acceptance input - are checked too (Product §24, ADR-007).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import AcceptEvidenceRequest
from research_harness.capabilities.handlers import accept_evidence
from research_harness.capabilities.permissions import (
    AGENT_HOST_PERMISSIONS,
    MODEL_PERMISSIONS,
    Permission,
    PermissionDenied,
    Principal,
)
from research_harness.capabilities.registry import build_default_registry
from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    ReviewPolicy,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.errors import AuthorityError
from research_harness.domain.evidence import Evidence, EvidenceContent, SourceAnchor
from research_harness.domain.ids import BlockId, EvidenceId
from research_harness.domain.transitions import BatchPolicyConditions
from research_harness.evidence.review import ReviewItem, ReviewQueue, SessionSummary
from research_harness.evidence.service import EvidenceReviewService
from research_harness.evidence.staging import EvidenceCandidate, StagingStore
from research_harness.protocol.mcp import HarnessMcpBridge
from research_harness.roles.schemas import VerificationOutput
from research_harness.server.app import create_app
from research_harness.workspace.repository import WorkspaceRepository
from tests.e2e.invariants.workstation import (
    HUMAN,
    MODEL_ACTOR,
    WORK,
    Workstation,
    init_and_ingest,
    interrogate_and_verify,
)

INTERPRETIVE = EvidenceId("E0001")

#: The DTOs a candidate passes through on its way to acceptance, and the queue a reviewer
#: sees. Product §24.4 and §43: model confidence is not an input to any of them.
ACCEPTANCE_MODELS = (
    AcceptEvidenceRequest,
    BatchPolicyConditions,
    Evidence,
    EvidenceContent,
    EvidenceCandidate,
    VerificationOutput,
)


def interpretive_candidate(ctx: CapabilityContext) -> Evidence:
    """A Tier-2 reading of a real span: exactly the object a model may not accept."""
    artifact = next(iter(ctx.repo.list_artifacts(WORK)))
    block = next(
        item
        for item in ctx.repo.iter_blocks(artifact.id, work=WORK)
        if "We do not claim transfer" in item.text
    )
    quoted = "We do not claim transfer to other networks"
    start = block.text.index(quoted)
    return Evidence(
        id=INTERPRETIVE,
        source=SourceAnchor(
            work=WORK,
            version=artifact.version,
            artifact=artifact.id,
            file_hash=artifact.file_hash,
            block=BlockId(str(block.id)),
            text_hash=block.text_hash,
            page=block.page,
            char_start=start,
            char_end=start + len(quoted),
        ),
        content=EvidenceContent(exact_text=quoted, field="author_limitation"),
        origin=EvidenceOrigin.AUTHOR_INTERPRETED,
        evidence_type=EvidenceType.LIMITATION,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_2,
        provenance=Provenance.model(MODEL_ACTOR),
    )


def acceptance_payload(candidate: Evidence) -> dict[str, Any]:
    return {
        "candidate": candidate.model_dump(mode="json"),
        "verdict": VerificationVerdict.SUPPORTED.value,
        "rationale": "a host trying to accept an interpretation",
    }


@pytest.fixture(scope="module")
def review_workspace(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A parsed workspace with staged candidates and no accepted evidence yet."""
    ctx = init_and_ingest(tmp_path_factory.mktemp("review") / "project", name="strict-review")
    interrogate_and_verify(ctx)
    yield ctx.root


@pytest.fixture
def candidate(review_workspace: Path) -> Evidence:
    return interpretive_candidate(open_context(review_workspace, HUMAN))


# ------------------------------------------------------------- the four ways to the gate


def test_the_handler_refuses_a_model_actor(review_workspace: Path, candidate: Evidence) -> None:
    """The capability layer itself, with no transport in the way (ADR-004)."""
    model = open_context(review_workspace, MODEL_ACTOR)

    with pytest.raises(AuthorityError, match="only a human actor may accept it"):
        accept_evidence(
            model,
            AcceptEvidenceRequest(candidate=candidate, verdict=VerificationVerdict.SUPPORTED),
        )


def test_the_registry_refuses_a_model_principal(
    review_workspace: Path, candidate: Evidence
) -> None:
    registry = build_default_registry()
    model = open_context(review_workspace, MODEL_ACTOR)

    with pytest.raises(PermissionDenied):
        registry.invoke(
            "evidence.accept",
            model,
            acceptance_payload(candidate),
            principal=Principal.model(MODEL_ACTOR),
        )


def test_the_registry_refuses_a_human_principal_acting_as_a_model(
    review_workspace: Path, candidate: Evidence
) -> None:
    """The principal says who asked; the context says whose authority is recorded."""
    registry = build_default_registry()
    model = open_context(review_workspace, MODEL_ACTOR)

    with pytest.raises(PermissionDenied, match="not the researcher"):
        registry.invoke(
            "evidence.accept",
            model,
            acceptance_payload(candidate),
            principal=Principal.human(HUMAN),
        )


def test_the_http_daemon_refuses_an_unauthenticated_caller(
    review_workspace: Path, candidate: Evidence
) -> None:
    """Without the local token a caller is an agent host, and hosts do not accept."""
    with TestClient(create_app(review_workspace)) as client:
        response = client.post("/capabilities/evidence.accept", json=acceptance_payload(candidate))

    assert response.status_code == 403
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "permission_denied"


def test_the_mcp_bridge_refuses_an_agent_host(review_workspace: Path, candidate: Evidence) -> None:
    bridge = HarnessMcpBridge(review_workspace, host="claude")

    refused = bridge.call("evidence.accept", acceptance_payload(candidate))

    assert refused.ok is False
    assert refused.error is not None
    assert refused.error.code == "permission_denied"


def test_no_refusal_left_accepted_evidence_behind(review_workspace: Path) -> None:
    """Four refusals, and `evidence.jsonl` is still empty (Product §8.3)."""
    repo = WorkspaceRepository.open(review_workspace)

    assert list(repo.iter_evidence(WORK)) == []
    assert repo.consistency.consistent


def test_the_researcher_can_accept_the_same_object(tmp_path: Path, review_workspace: Path) -> None:
    """The gate is about authority, not about the candidate: a person may accept it.

    On a private copy, so the shared workspace above stays the one the four refusals left.
    """
    root = tmp_path / "project"
    shutil.copytree(review_workspace, root)
    human = open_context(root, HUMAN)
    result = accept_evidence(
        human,
        AcceptEvidenceRequest(
            candidate=interpretive_candidate(human),
            verdict=VerificationVerdict.SUPPORTED,
            rationale="read the limitation myself",
        ),
    )

    assert result.objects == (str(INTERPRETIVE),)
    assert result.event.event.value == "evidence.accepted"


# ----------------------------------------------------------------------- batch review


def test_a_policy_batch_under_strict_review_is_refused(review_workspace: Path) -> None:
    """Strict is the default and a batch is an exception a researcher declares (ADR-007)."""
    ctx = open_context(review_workspace, HUMAN)
    service = EvidenceReviewService(ctx, StagingStore(ctx.repo.layout.research_dir))

    assert ctx.repo.review_policy is ReviewPolicy.STRICT
    with pytest.raises(AuthorityError, match="strict review is the default"):
        service.accept_batch()


def test_a_batch_with_unmet_conditions_is_refused_even_when_they_are_declared(
    review_workspace: Path,
) -> None:
    """Declaring the Product §24.4 conditions is not the same as satisfying them."""
    ctx = open_context(review_workspace, HUMAN)
    service = EvidenceReviewService(ctx, StagingStore(ctx.repo.layout.research_dir))

    with pytest.raises(AuthorityError, match="not declared"):
        service.accept_batch(conditions=BatchPolicyConditions(verifier_supported=True))


def test_the_batch_conditions_are_deterministic_facts_and_confidence_is_not_one(
    review_workspace: Path,
) -> None:
    fields = set(BatchPolicyConditions.model_fields)

    assert fields == {
        "anchor_valid",
        "low_risk_field",
        "no_accepted_state_conflict",
        "no_competing_candidate",
        "verifier_supported",
    }
    assert "confidence" not in fields


# ------------------------------------------------------------------- confidence is absent


def field_names(schema: Any) -> set[str]:
    """Every property name a JSON schema declares, `$defs` included.

    Property names rather than raw text: the docstrings of these models *say* that
    confidence is deliberately absent, and a text grep would fail on the sentence that
    promises the thing it is checking.
    """
    names: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                names.update(value)
            names.update(field_names(value))
    elif isinstance(schema, list):
        for item in schema:
            names.update(field_names(item))
    return names


@pytest.mark.parametrize("model", ACCEPTANCE_MODELS, ids=lambda item: item.__name__)
def test_confidence_appears_in_no_acceptance_input(model: type) -> None:
    """§24.4: "Model confidence alone is never sufficient" - so it is not an input at all."""
    names = field_names(model.model_json_schema())

    assert names, f"{model.__name__} declares no fields, so this proves nothing"
    assert not {name for name in names if "confidence" in name.lower()}


def test_confidence_appears_nowhere_in_the_review_inbox(review_workspace: Path) -> None:
    """The queue a researcher reads is built from facts, never from how sure a model was."""
    ctx = open_context(review_workspace, HUMAN)
    service = EvidenceReviewService(ctx, StagingStore(ctx.repo.layout.research_dir))

    queue: ReviewQueue = service.inbox()

    assert len(queue) > 0
    assert "confidence" not in json.dumps(queue.as_dict()).lower()
    for item in queue:
        assert isinstance(item, ReviewItem)
        assert "confidence" not in json.dumps(item.as_dict()).lower()


def test_confidence_appears_nowhere_in_the_review_capabilities(review_workspace: Path) -> None:
    """Including on the wire: the schemas a host reads before calling carry none either."""
    registry = build_default_registry()
    review = [spec for spec in registry if spec.name.startswith(("review.", "evidence."))]

    assert {spec.name for spec in review} >= {"review.inbox", "evidence.accept"}
    for spec in review:
        descriptor = spec.descriptor()
        for schema in (descriptor.request_schema, descriptor.response_schema):
            offending = {name for name in field_names(schema) if "confidence" in name.lower()}
            assert not offending, f"{spec.name}: {sorted(offending)}"


def test_the_session_summary_counts_states_rather_than_scores(review_workspace: Path) -> None:
    from research_harness.evidence.review import session_summary

    ctx = open_context(review_workspace, HUMAN)
    summary: SessionSummary = session_summary(ctx.repo, StagingStore(ctx.repo.layout.research_dir))

    assert "confidence" not in json.dumps(summary.as_dict()).lower()
    assert summary.unreviewed > 0


# ------------------------------------------------------------------ the permission model


def test_a_host_and_a_model_hold_the_same_narrow_permissions() -> None:
    """Neither may mutate, and the rule is one table rather than a per-transport check."""
    assert Permission.MUTATE not in AGENT_HOST_PERMISSIONS
    assert Permission.MUTATE not in MODEL_PERMISSIONS
    assert Principal.agent_host("claude").allows(Permission.MUTATE) is False
    assert Principal.model(MODEL_ACTOR).allows(Permission.MUTATE) is False
    assert Principal.human(HUMAN).allows(Permission.MUTATE) is True


def test_the_workstation_evidence_was_accepted_by_a_person(workstation: Workstation) -> None:
    """The loop's own accepted objects carry a human acceptor, not a model one."""
    ctx = workstation.context()

    for record in ctx.repo.iter_evidence(workstation.work):
        assert record.verification.accepted_by == HUMAN
        assert record.verification.review_action is not None

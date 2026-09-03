"""Product §42.A - Provider independence.

"The same Evidence verification workflow can run with Anthropic or OpenAI without changing
canonical schemas."

Both adapters are driven through `httpx.MockTransport`, so the wire format is the real one
and no network is involved. The claim under test is stronger than "it runs": the same
neutral `ModelRequest` fingerprints identically on both, both return the same validated
`VerificationOutput`, and the canonical Evidence the loop then accepts is identical in
everything except who answered and when (Product §20.1, ADR-005).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from research_harness.domain.enums import EvidenceStatus, VerificationVerdict
from research_harness.evidence.staging import CandidateStatus, StagingStore
from research_harness.evidence.verification import build_source_context
from research_harness.providers.models.anthropic_provider import AnthropicProvider
from research_harness.providers.models.base import ModelProvider, ModelResponse
from research_harness.roles.contracts import build_request
from research_harness.roles.schemas import VerificationOutput
from research_harness.roles.verifier import VERIFIER
from research_harness.workspace.repository import WorkspaceRepository
from tests.contract.providers.conftest import (
    API_KEY,
    anthropic_body,
    build_openai,
    openai_body,
)
from tests.e2e.invariants.workstation import (
    FIELDS,
    WORK,
    accept_candidates,
    digest,
    init_and_ingest,
    interrogate_and_verify,
    jsonl,
    verification_reply,
)
from tests.integration.evidence.conftest import parse_fixture

#: A field name that appears in one candidate's payload and in no instruction, so a fake
#: transport can answer the right verification question without depending on call order.
METRIC_FIELD = "metric_result"

BodyBuilder = Callable[[str], dict[str, Any]]


def _replying_transport(body: BodyBuilder) -> httpx.MockTransport:
    """A transport that answers each verification request for the candidate it is about."""

    def handle(request: httpx.Request) -> httpx.Response:
        sent = request.content.decode("utf-8")
        field = METRIC_FIELD if METRIC_FIELD in sent else "dataset"
        return httpx.Response(200, json=body(json.dumps(verification_reply(field))))

    return httpx.MockTransport(handle)


def openai_verifier() -> ModelProvider:
    """The real OpenAI adapter over a fake Responses API."""
    return build_openai(_replying_transport(lambda text: openai_body(text)))


def anthropic_verifier() -> ModelProvider:
    """The real Anthropic adapter over a fake Messages API."""
    return AnthropicProvider(
        "claude-test-1",
        api_key=API_KEY,
        transport=_replying_transport(lambda text: anthropic_body(text)),
        env={},
    )


@dataclass(frozen=True)
class Arm:
    """One run of the loop, verified by one provider."""

    provider: str
    root: Path
    evidence: list[dict[str, Any]]


def run_arm(root: Path, provider: ModelProvider) -> Arm:
    """Ingest, parse, extract, verify with ``provider``, and accept - the §42.A workflow."""
    ctx = init_and_ingest(root, name="provider-independence")
    candidates = interrogate_and_verify(ctx, verifier=provider)
    accept_candidates(ctx, candidates)
    work_dir = ctx.repo.layout.evidence_file(WORK)
    return Arm(provider=provider.name, root=ctx.root, evidence=jsonl(work_dir))


@pytest.fixture(scope="module")
def arms(tmp_path_factory: pytest.TempPathFactory) -> Mapping[str, Arm]:
    """The same loop, once per adapter, in two independent workspaces."""
    base = tmp_path_factory.mktemp("provider-independence")
    return {
        "openai": run_arm(base / "openai", openai_verifier()),
        "anthropic": run_arm(base / "anthropic", anthropic_verifier()),
    }


# ------------------------------------------------------------------- the neutral request


@pytest.fixture(scope="module")
def one_request(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The verifier request for one real staged candidate, built once and reused."""
    ctx = init_and_ingest(tmp_path_factory.mktemp("neutral") / "project", name="neutral")
    interrogate_and_verify(ctx, verifier=openai_verifier(), fields=(METRIC_FIELD,))
    staging = StagingStore(ctx.repo.layout.research_dir)
    candidate = next(iter(staging.list(work=WORK, status=CandidateStatus.VERIFIED)))
    return build_request(VERIFIER, build_source_context(parse_fixture(), candidate)).request


def test_the_same_neutral_request_reaches_both_providers_unchanged(one_request: Any) -> None:
    """A `ModelRequest` is provider-neutral, so its fingerprint cannot name a vendor."""
    openai_response: ModelResponse[VerificationOutput] = openai_verifier().complete(one_request)
    anthropic_response: ModelResponse[VerificationOutput] = anthropic_verifier().complete(
        one_request
    )

    assert openai_response.request_fingerprint == anthropic_response.request_fingerprint
    assert openai_response.provider == "openai"
    assert anthropic_response.provider == "anthropic"


def test_both_providers_return_the_same_parsed_verification(one_request: Any) -> None:
    """`ModelResponse.parsed` is the validated domain object, identical on both wires."""
    openai_response = openai_verifier().complete(one_request)
    anthropic_response = anthropic_verifier().complete(one_request)

    assert isinstance(openai_response.parsed, VerificationOutput)
    assert openai_response.parsed == anthropic_response.parsed
    assert openai_response.parsed.verdict is VerificationVerdict.SUPPORTED


# ------------------------------------------------------------------- the canonical result


def test_each_arm_accepted_the_evidence_the_loop_asked_for(arms: Mapping[str, Arm]) -> None:
    for arm in arms.values():
        assert [record["id"] for record in arm.evidence] == ["E0001", "E0002"]
        assert {record["content"]["field"] for record in arm.evidence} == set(FIELDS)
        assert all(
            record["verification"]["status"] == EvidenceStatus.ACCEPTED.value
            for record in arm.evidence
        )


def test_the_canonical_evidence_is_identical_across_providers(arms: Mapping[str, Arm]) -> None:
    """Product §42.A: same schemas, same anchors, same content - only the actor differs."""
    openai_arm, anthropic_arm = arms["openai"], arms["anthropic"]

    assert digest(openai_arm.evidence) == digest(anthropic_arm.evidence)
    for left, right in zip(openai_arm.evidence, anthropic_arm.evidence, strict=True):
        assert left["source"] == right["source"]
        assert left["content"] == right["content"]
        assert left["origin"] == right["origin"]
        assert left["evidence_type"] == right["evidence_type"]
        assert left["verification"]["verdict"] == right["verification"]["verdict"]


def test_only_the_backend_identity_differs_between_the_two_records(
    arms: Mapping[str, Arm],
) -> None:
    """The one thing that must differ is which model answered; it is recorded, not hidden."""
    verifiers = {
        name: {record["verification"]["verifier"] for record in arm.evidence}
        for name, arm in arms.items()
    }

    assert verifiers["openai"] == {"openai/gpt-test-1"}
    assert verifiers["anthropic"] == {"anthropic/claude-test-1"}


def test_the_canonical_schema_version_is_the_same_on_both_arms(arms: Mapping[str, Arm]) -> None:
    """Product §42.A says "without changing canonical schemas"; that is checked, not assumed."""
    versions = {record["schema_version"] for arm in arms.values() for record in arm.evidence}
    assert len(versions) == 1


def test_both_workspaces_open_consistent(arms: Mapping[str, Arm]) -> None:
    for arm in arms.values():
        assert WorkspaceRepository.open(arm.root).consistency.consistent

"""One workspace, one Claim, and both transports over it.

The fixtures deliberately build the workspace through the capability layer rather than by
writing files: a transport test that seeded canonical state by hand would not be testing
the same object the transports read.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import CreateClaimRequest, InitProjectRequest
from research_harness.capabilities.handlers import create_claim, init_project
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.domain.base import Provenance
from research_harness.domain.claim import Claim, ClaimAssessment, ClaimScopeSpec, ClaimSemantics
from research_harness.domain.enums import ClaimScope, ClaimType
from research_harness.domain.ids import ClaimId
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.protocol.mcp import HarnessMcpBridge
from research_harness.server.app import create_app, ensure_token

STATEMENT = "Byte-level tokenization improves recall on short encrypted flows."
CLAIM = ClaimId("C0001")


def make_claim(claim_id: ClaimId = CLAIM, statement: str = STATEMENT) -> Claim:
    """A structured claim at L0: the researcher's ask, with nothing audited yet."""
    return Claim(
        id=claim_id,
        statement=statement,
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(
            subject="byte-level tokenization", predicate="improves", object="recall"
        ),
        scope=ClaimScopeSpec(level=ClaimScope.INDIVIDUAL, corpus="encrypted traffic classifiers"),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.INDIVIDUAL, allowed_strength=ClaimScope.INDIVIDUAL
        ),
        provenance=Provenance.human(HUMAN_ACTOR),
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """An initialized workspace holding exactly one Claim."""
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="protocol-parity"))
    ctx = open_context(result.root, HUMAN_ACTOR)
    create_claim(ctx, CreateClaimRequest(claim=make_claim()))
    return result.root


@pytest.fixture
def project(workspace: Path) -> CapabilityContext:
    """The workspace opened as the researcher."""
    return open_context(workspace, HUMAN_ACTOR)


@pytest.fixture(scope="session")
def registry() -> CapabilityRegistry:
    """The registry both transports serve; building it once keeps the tests quick."""
    return build_default_registry()


@pytest.fixture
def token(workspace: Path) -> str:
    """The local daemon token: presenting it is what makes a caller the researcher."""
    return ensure_token(workspace)


@pytest.fixture
def client(workspace: Path, registry: CapabilityRegistry, token: str) -> Iterator[TestClient]:
    """The daemon as the local researcher."""
    with TestClient(create_app(workspace, registry=registry)) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client


@pytest.fixture
def host_client(workspace: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    """The daemon as an agent host: no token, so read and stage only."""
    with TestClient(create_app(workspace, registry=registry)) as test_client:
        yield test_client


@pytest.fixture
def bridge(workspace: Path, registry: CapabilityRegistry) -> HarnessMcpBridge:
    """The MCP side, which is always an agent host (Product 29)."""
    return HarnessMcpBridge(workspace, registry=registry)

"""The privacy policy holds on every transport, not only on the one that used to check it.

Product §34 and ADR-018 put the egress decision at *provider selection*: a project that
forbids external models refuses before a request exists, so a refused provider is never
contacted. `cli/providers.py` did that. The daemon and the MCP bridge build their own
router in `capabilities/extra_handlers.py::_router`, and a run started from the Web cockpit
or an agent host is exactly the run a researcher is least able to watch — so the property
worth pinning is that all three surfaces refuse identically, and that none of them sends a
byte first.

The load-bearing assertion is the transport. Every adapter is built on an
`httpx.MockTransport` whose handler fails the test if it is ever called, so "refused before
any HTTP call" is checked rather than asserted in a docstring. It is injected by patching
`providers.models.router.build_router`, which `_router` resolves at call time, because the
capability path has no transport seam of its own — a real deployment has no reason to want
one, and a test that reached past `build_router` would not be exercising `_router`.

The control is the last test: the same policy leaves a scripted, in-process provider alone.
A refusal here is about *egress*, never about models.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from pydantic import BaseModel, ConfigDict
from starlette.testclient import TestClient

import research_harness.providers.models.router as router_module
from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import InitProjectRequest
from research_harness.capabilities.handlers import init_project
from research_harness.capabilities.permissions import Principal
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.privacy.egress import policy_enforced_router
from research_harness.privacy.policy import EgressDeniedError, load_policy
from research_harness.protocol.mcp import HarnessMcpBridge
from research_harness.providers.models.base import (
    InputEnvelope,
    ModelRequest,
    ModelRequirements,
)
from research_harness.providers.models.scripted import ScriptedProvider, scripted_router
from research_harness.server.app import create_app, ensure_token

CAPABILITY = "work.interrogate"
WORK = "W0001"
HOSTED = "hosted"
ON_BOX = "on-box"

#: One hosted entry the policy must refuse, and one loopback entry it must not.
PROVIDERS: list[dict[str, Any]] = [
    {
        "name": HOSTED,
        "kind": "openai",
        "model": "gpt-x",
        "api_key_env": "OPENAI_API_KEY",
        "priority": 10,
    },
    {
        "name": ON_BOX,
        "kind": "local_openai_compatible",
        "model": "qwen",
        "base_url": "http://127.0.0.1:11434/v1",
        "priority": 200,
    },
]

REQUEST: dict[str, Any] = {"work": WORK, "provider": HOSTED}


class Verdict(BaseModel):
    """Schema fixture; what the scripted control answers with."""

    model_config = ConfigDict(extra="forbid")

    supported: bool


def forbidden_transport() -> httpx.MockTransport:
    """A transport that fails the test if any adapter tries to use it."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"a refused provider was contacted: {request.method} {request.url}")

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Build every router in this module on a transport that must never be used.

    `_router` resolves `build_router` from the module at call time, so patching the module
    attribute reaches the capability path without the handler knowing a test is present.
    """
    real = router_module.build_router

    def with_forbidden_transport(config: Any, env: Any = None, **kwargs: Any) -> Any:
        kwargs.setdefault("transport", forbidden_transport())
        return real(config, env, **kwargs)

    monkeypatch.setattr(router_module, "build_router", with_forbidden_transport)


@pytest.fixture
def denied(tmp_path: Path) -> Path:
    """A workspace that forbids external models and configures a hosted provider anyway."""
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="egress-gate"))
    path = result.root / "research.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["providers"] = PROVIDERS
    config["privacy"] = {"external_models": "disabled"}
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return result.root


@pytest.fixture
def project(denied: Path) -> CapabilityContext:
    return open_context(denied, HUMAN_ACTOR)


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    return build_default_registry()


@pytest.fixture
def client(denied: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    """The daemon as the local researcher; the token is what makes it one."""
    with TestClient(create_app(denied, registry=registry)) as test_client:
        test_client.headers["Authorization"] = f"Bearer {ensure_token(denied)}"
        yield test_client


@pytest.fixture
def bridge(denied: Path, registry: CapabilityRegistry) -> HarnessMcpBridge:
    """The MCP side, which is always an agent host (Product §29)."""
    return HarnessMcpBridge(denied, registry=registry)


def http(client: TestClient, request: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = client.post(f"/capabilities/{CAPABILITY}", json=request).json()
    return body


def request_for(role: str = "extractor") -> ModelRequest[Verdict]:
    return ModelRequest(
        role=role,
        requirements=ModelRequirements(context_tokens=8_000, reasoning="low"),
        instructions="Decide whether the source supports the candidate.",
        inputs=[InputEnvelope(object_id=WORK, kind="source_text", content="Table 3 reports…")],
        response_schema=Verdict,
    )


def names_the_policy(message: str) -> bool:
    """A refusal has to say which project setting refused and which host it protected."""
    return "external_models" in message and "api.openai.com" in message


# -- in process --------------------------------------------------------------


def test_the_registry_refuses_the_hosted_provider_before_a_request_exists(
    project: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """The single enforcement point: every transport reaches the handler through this."""
    with pytest.raises(EgressDeniedError) as caught:
        registry.invoke(CAPABILITY, project, REQUEST, principal=Principal.human(HUMAN_ACTOR))

    assert names_the_policy(str(caught.value))
    assert caught.value.endpoint_host == "api.openai.com"
    assert "external_models" in caught.value.policy_fields


def test_nothing_is_written_when_the_policy_refuses(
    project: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """A refused interrogation starts no run and stages no candidate (ADR-003)."""
    with pytest.raises(EgressDeniedError):
        registry.invoke(CAPABILITY, project, REQUEST, principal=Principal.human(HUMAN_ACTOR))

    research = project.repo.layout.research_dir
    assert not list((research / "runs").glob("**/*.json"))
    assert not list((research / "staging").glob("**/*.json"))


# -- over the transports -----------------------------------------------------


def test_the_daemon_refuses_the_hosted_provider(client: TestClient) -> None:
    body = http(client, REQUEST)

    assert body["ok"] is False, body
    assert body["error"]["code"] == "capability_error"
    assert names_the_policy(body["error"]["message"])
    assert body["run_id"] is None, "a refused long-running capability starts no run"


def test_the_mcp_bridge_refuses_the_hosted_provider(bridge: HarnessMcpBridge) -> None:
    body = bridge.call(CAPABILITY, REQUEST).model_dump(mode="json")

    assert body["ok"] is False, body
    assert body["error"]["code"] == "capability_error"
    assert names_the_policy(body["error"]["message"])


def test_both_transports_refuse_with_the_same_error_body(
    client: TestClient, bridge: HarnessMcpBridge
) -> None:
    """ADR-009: one answer, whichever surface asked. A refusal is an answer."""
    over_http = http(client, REQUEST)
    over_mcp = bridge.call(CAPABILITY, REQUEST).model_dump(mode="json")

    assert over_http["error"] == over_mcp["error"]


def test_the_alias_capability_is_refused_the_same_way(client: TestClient) -> None:
    """`evidence.extract` is the same handler under another name, and the same gate."""
    body: dict[str, Any] = client.post("/capabilities/evidence.extract", json=REQUEST).json()
    interrogate = http(client, REQUEST)["error"]

    assert body["ok"] is False
    assert body["error"]["capability"] == "evidence.extract", "each name reports itself"
    assert {key: body["error"][key] for key in ("code", "message")} == {
        key: interrogate[key] for key in ("code", "message")
    }


def test_verification_is_refused_at_the_same_gate(client: TestClient) -> None:
    """Every long-running capability that routes goes through `_router`, not only one."""
    body: dict[str, Any] = client.post(
        "/capabilities/evidence.verify", json={"work": WORK, "provider": HOSTED}
    ).json()

    assert body["ok"] is False
    assert names_the_policy(body["error"]["message"])


# -- what the policy does not refuse -----------------------------------------


def test_a_loopback_provider_is_not_refused_by_the_same_policy(
    project: CapabilityContext,
) -> None:
    """The refusal is about egress: an on-box endpoint is still routable (Product §34)."""
    from research_harness.capabilities.extra_handlers import _router

    router = _router(project, ON_BOX)
    entry = router.select(ModelRequirements(context_tokens=8_000, reasoning="low"), "extractor")

    assert entry.provider.name == "local"
    assert entry.model == "qwen"


def test_a_scripted_provider_still_answers_under_the_same_policy(
    project: CapabilityContext,
) -> None:
    """The offline path the whole harness is demonstrable on is untouched (Product §20.2).

    `--provider scripted --script <file>` sends nothing anywhere, so the strictest policy a
    project can write has nothing to refuse. Asserted through `policy_enforced_router`,
    which is what carries the workspace's policy onto any router a caller narrows.
    """
    policy = load_policy(project.repo)
    router = policy_enforced_router(
        scripted_router(ScriptedProvider([{"supported": True}])), policy
    )

    answer = router.complete(request_for())

    assert answer.parsed.supported is True
    assert answer.provider == "scripted"


def test_naming_a_provider_the_workspace_does_not_have_is_not_an_egress_refusal(
    project: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """A configuration mistake must not read as a privacy refusal, or neither is actionable."""
    with pytest.raises(EgressDeniedError):
        registry.invoke(CAPABILITY, project, REQUEST, principal=Principal.human(HUMAN_ACTOR))

    with pytest.raises(ResearchHarnessError) as caught:
        registry.invoke(
            CAPABILITY,
            project,
            {"work": WORK, "provider": "nowhere"},
            principal=Principal.human(HUMAN_ACTOR),
        )

    assert not isinstance(caught.value, EgressDeniedError)
    assert "no provider named 'nowhere'" in str(caught.value)

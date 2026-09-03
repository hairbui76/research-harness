"""One place the CLI decides which model backend a run talks to (Product 20.2, 34).

Providers are configuration, never code. `--provider NAME` selects an entry of the
`providers:` list in `research.yaml`; `--provider scripted --script FILE` runs the
in-process scripted adapter, so any loop is demonstrable offline with no key and no
network. Credentials come from the process environment and never from a workspace file.

Three commands used to answer this question three slightly different ways - one attached
the project's privacy policy, one silently dropped it, one refused every real provider.
They ask here instead, so a provider this project forbids is refused during *selection*
rather than called (ADR-005, ROADMAP Task 17.4).

Selection is also where the run gains its **trace sink**. Every client built here writes
each completion to `.research/traces/` through a `TraceWriter` carrying the project's
privacy policy, so `research traces list` shows a run that happened whichever command drove
it, and `redact_traces` is honoured as the trace is written rather than afterwards
(Product SS19.3, SS34). The scripted provider traces like any other: `ScriptedProvider`
implements `_execute` only, so it goes through the shared `ModelProvider.complete`.

`TracingRouter`, `traced`, and `trace_writer_for` now live in `privacy/traces.py`, because a
run driven over HTTP or MCP has no CLI to wrap its router and left no trace at all. They are
re-exported here unchanged, so `from research_harness.cli.providers import traced` keeps
working.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from research_harness.capabilities.context import CapabilityContext
from research_harness.domain.errors import ResearchHarnessError
from research_harness.privacy.egress import policy_enforced_router
from research_harness.privacy.policy import load_policy
from research_harness.privacy.traces import TraceWriter as TraceWriter
from research_harness.privacy.traces import TracingRouter as TracingRouter
from research_harness.privacy.traces import trace_writer_for as trace_writer_for
from research_harness.privacy.traces import traced as traced
from research_harness.providers.models.base import (
    ModelProvider,
    ModelRequest,
    ProviderResponseError,
)
from research_harness.providers.models.router import ModelRouter, RouterConfig, build_router
from research_harness.providers.models.scripted import ScriptedProvider, scripted_router
from research_harness.roles.registry import role_names
from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "SCRIPTED_PROVIDER",
    "ModelClient",
    "TracingRouter",
    "load_router",
    "optional_model_client",
    "resolve_model_client",
    "scripted_model_provider",
    "trace_writer_for",
    "traced",
]

SCRIPTED_PROVIDER = "scripted"
"""The provider name `--script` binds to; it sends nothing anywhere (Product 34)."""

ModelClient = ModelProvider | ModelRouter
"""Anything that can run a `ModelRequest`: one provider, or a capability router."""


def load_router(repo: WorkspaceRepository, *, env: Mapping[str, str] | None = None) -> ModelRouter:
    """Build the workspace's model router from the `providers:` list in `research.yaml`.

    `WorkspaceConfig.providers` holds the entries raw, because `workspace/` must not import
    `providers/`; `RouterConfig` validates them here, where the adapters live. API keys come
    from the environment, never from the file (Product 34), and the workspace's privacy
    policy rides along on the router, so a provider this project forbids is refused during
    selection rather than called.
    """
    config = RouterConfig.model_validate({"providers": list(repo.config.providers)})
    if not config.providers:
        raise ResearchHarnessError(
            "no model providers configured: add a `providers:` list to research.yaml, or "
            "run offline with `--provider scripted --script <file>`"
        )
    return build_router(config, env, policy=load_policy(repo))


def resolve_model_client(
    ctx: CapabilityContext | WorkspaceRepository,
    provider: str | None,
    script: Path | None,
    *,
    env: Mapping[str, str] | None = None,
) -> ModelClient:
    """The backend a run should use: the scripted adapter, or a configured entry.

    ``provider`` of ``None`` means "whatever the workspace routes to", which is the whole
    `providers:` table under the project's privacy policy. Naming one narrows the table to
    the entries carrying that tag or provider name -- and narrowing must not drop the
    policy with it, so the result is re-wrapped through `policy_enforced_router`.

    Every result is a :class:`TracingRouter`: whichever backend a command ends up on, the
    call is recorded under `.research/traces/` for the retention the privacy policy allows.
    """
    repo = ctx.repo if isinstance(ctx, CapabilityContext) else ctx
    if script is not None:
        if provider not in (None, SCRIPTED_PROVIDER):
            raise ResearchHarnessError(
                f"--script runs the {SCRIPTED_PROVIDER!r} provider; --provider {provider!r} "
                "asks for a configured one"
            )
        return traced(scripted_router(scripted_model_provider(script)), repo)
    if provider == SCRIPTED_PROVIDER:
        raise ResearchHarnessError(f"--provider {SCRIPTED_PROVIDER} needs --script <file>")
    router = load_router(repo, env=env)
    if provider is None:
        return traced(router, repo)
    entries = [
        entry
        for entry in router.entries
        if provider in entry.tags or entry.provider.name == provider
    ]
    if not entries:
        names = ", ".join(sorted({tag for entry in router.entries for tag in entry.tags})) or "none"
        raise ResearchHarnessError(
            f"no provider named {provider!r} in research.yaml (have: {names})"
        )
    return traced(policy_enforced_router(ModelRouter(entries), router.policy), repo)


def optional_model_client(
    ctx: CapabilityContext | WorkspaceRepository,
    provider: str | None,
    script: Path | None,
    *,
    env: Mapping[str, str] | None = None,
) -> ModelClient | None:
    """The same selection, but ``None`` when the caller named neither a provider nor a script.

    Used where the model pass is optional and the deterministic result *is* the result
    (`research claim audit`, ROADMAP 7.4): with nothing named, the model passes are simply
    not run rather than the command failing for want of configuration.
    """
    if provider is None and script is None:
        return None
    return resolve_model_client(ctx, provider, script, env=env)


def scripted_model_provider(path: Path) -> ScriptedProvider:
    """A scripted provider from a JSON file.

    Three shapes, all of them JSON a person can write by hand:

    * a list of replies, consumed in order;
    * an object whose every key is a role name (``extractor``, ``writer``, ...), giving
      each role its own queue, so one file scripts a multi-role run;
    * any other object: one reply, for a command that makes a single call.
    """
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchHarnessError(f"cannot read script {path}: {exc}") from exc
    if isinstance(payload, list):
        return ScriptedProvider(list(payload), name=SCRIPTED_PROVIDER)
    if not isinstance(payload, dict):
        raise ResearchHarnessError(
            f"script {path} must be a JSON list of replies or an object keyed by role"
        )
    if not _is_role_keyed(payload):
        return ScriptedProvider([payload], name=SCRIPTED_PROVIDER)
    queues: dict[str, list[Any]] = {
        role: list(replies) if isinstance(replies, list) else [replies]
        for role, replies in payload.items()
    }

    def by_role(request: ModelRequest[Any]) -> Any:
        queue = queues.get(request.role)
        if not queue:
            raise ProviderResponseError(
                f"script {path} has no reply left for role {request.role!r}; it lists "
                f"{', '.join(sorted(queues)) or 'no roles'}",
                provider=SCRIPTED_PROVIDER,
            )
        return queue.pop(0)

    return ScriptedProvider(by_role, name=SCRIPTED_PROVIDER)


def _is_role_keyed(payload: Mapping[str, Any]) -> bool:
    """True when every key names a registered role, so the object is one queue per role.

    A single reply is also an object, and its keys are the output schema's fields; asking
    the role registry is the only way to tell the two apart without guessing.
    """
    roles = set(role_names())
    return bool(payload) and all(key in roles for key in payload)

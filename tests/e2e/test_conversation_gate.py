"""Gate P18: the conversation workspace, demonstrated end to end.

The gate is five sentences from `ROADMAP.md`, and each one is a test below:

1. reopen and continue a session;
2. inspect exactly what context a response used;
3. demonstrate cross-session retrieval with privacy filtering;
4. demonstrate that conflicting accepted scientific state outranks chat;
5. promote an excerpt without bypassing review.

Everything runs through the capability registry — the surface HTTP, MCP, and the CLI all
reach — with an in-process scripted provider, so the gate is offline, deterministic, and
exercises the same code a real send does. The last test drives the CLI instead, so the
demonstration covers both transports the researcher actually types into.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.permissions import Principal
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.cli.commands import init as init_commands
from research_harness.cli.commands import session as session_commands
from research_harness.conversation.send import ScriptedProviders
from research_harness.conversation.service import ConversationService
from research_harness.domain.base import Provenance
from research_harness.domain.claim import Claim, ClaimAssessment, ClaimScopeSpec, ClaimSemantics
from research_harness.domain.conversation import (
    ContextClass,
    EgressClass,
    MessageRole,
    OmissionReason,
    Visibility,
)
from research_harness.domain.enums import ClaimScope, ClaimStatus, ClaimType
from research_harness.domain.ids import ClaimId
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.workspace.repository import WorkspaceRepository

runner = CliRunner()

CLAIM_STATEMENT = "Batching reduces tail latency across the encrypted-traffic corpus."
PILOT = "The pilot corpus showed a nine percent tail latency drop under batching."
ANSWER = "Under batching, tail latency falls; C0001 records the corpus-level result."


@pytest.fixture
def registry() -> CapabilityRegistry:
    return build_default_registry()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A project holding one accepted-looking Claim about latency."""
    repo = WorkspaceRepository.init(tmp_path / "project", "gate-p18")
    claim = Claim(
        id=ClaimId("C0001"),
        statement=CLAIM_STATEMENT,
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(subject="batching", predicate="reduces", object="tail latency"),
        scope=ClaimScopeSpec(level=ClaimScope.CORPUS_PATTERN, corpus="encrypted traffic"),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.CORPUS_PATTERN,
            allowed_strength=ClaimScope.CORPUS_PATTERN,
            status=ClaimStatus.SUPPORTED,
        ),
        provenance=Provenance.human(),
    )
    from research_harness.workspace.serialization import canonical_bytes

    path = repo.layout.claim_file(claim.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(claim))
    return repo.root


@pytest.fixture
def ctx(workspace: Path) -> CapabilityContext:
    return open_context(workspace)


def talking(ctx: CapabilityContext, *answers: str, egress: EgressClass) -> ConversationService:
    """A conversation service answering from a script, with a declared egress class."""
    provider = ScriptedProvider([{"text": answer} for answer in answers])
    return ConversationService(
        ctx, providers=ScriptedProviders(provider, chunk_words=4, egress=egress)
    )


def invoke(registry: CapabilityRegistry, ctx: CapabilityContext, name: str, request: Any) -> Any:
    return registry.invoke(name, ctx, request, principal=Principal.human())


# -- 1. reopen and continue a session ----------------------------------------


def test_a_session_reopens_with_its_transcript_and_continues(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    service = talking(
        ctx, ANSWER, "And after batching, the tail is flatter.", egress=EgressClass.LOCAL
    )
    session = service.create("Latency study")
    service.send(session.id, "What do we know about tail latency?", background=False)

    # A new process would read it exactly like this: through the capability, by id.
    reopened = invoke(registry, ctx, "session.get", {"session": str(session.id)})
    assert reopened.session.title == "Latency study"
    assert [message.role for message in reopened.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]

    continued = talking(ctx, "Batching still helps.", egress=EgressClass.LOCAL)
    continued.send(session.id, "And after batching?", background=False)

    after = invoke(registry, ctx, "session.get", {"session": str(session.id)})
    assert after.total == 4, "continuing a session appends; it never restarts one"
    assert [str(message.id) for message in after.messages] == ["M0001", "M0002", "M0003", "M0004"]


# -- 2. inspect exactly what context a response used -------------------------


def test_the_receipt_names_every_class_that_reached_the_model_and_every_one_that_did_not(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    service = talking(ctx, ANSWER, egress=EgressClass.LOCAL)
    session = service.create("Latency study")
    started = service.send(session.id, "Does @C0001 still describe tail latency?", background=False)

    read = invoke(registry, ctx, "session.get", {"session": str(session.id)})
    answer = read.messages[-1]
    assert answer.context_pack == started.context_pack, "the answer names its own receipt"

    pack = service.read_pack(session.id, started.context_pack)
    classes = set(pack.receipt.tokens_by_class())
    assert ContextClass.POLICY in classes
    assert ContextClass.ACCEPTED_STATE in classes, "the referenced Claim was sent"
    assert ContextClass.CURRENT_SESSION in classes, "so was the question"
    assert {str(item.id) for item in pack.receipt.included if item.id} >= {"C0001"}
    assert pack.model is not None and pack.egress is EgressClass.LOCAL
    assert pack.receipt.total_tokens() <= (pack.token_budget or 0)

    # And the receipt is still readable afterwards, which is the point of recording it.
    again = service.read_pack(session.id, started.context_pack)
    assert again.receipt == pack.receipt


# -- 3. cross-session retrieval with privacy filtering -----------------------


def test_a_prior_session_excerpt_is_retrieved_locally_and_withheld_from_an_external_model(
    ctx: CapabilityContext,
) -> None:
    earlier = talking(ctx, "Recorded.", egress=EgressClass.LOCAL)
    prior = earlier.create("Pilot corpus measurements")
    earlier.send(prior.id, PILOT, background=False)

    local = talking(ctx, ANSWER, egress=EgressClass.LOCAL)
    here = local.create("Writing up")
    local_send = local.send(
        here.id, "What did the pilot corpus show about tail latency?", background=False
    )
    local_pack = local.read_pack(here.id, local_send.context_pack)
    retrieved = [
        item
        for item in local_pack.receipt.included
        if item.context_class is ContextClass.PRIOR_SESSIONS
    ]
    assert retrieved, "a local model may read the researcher's own earlier session"
    assert str(prior.id) in retrieved[0].source

    # A hosted model: the conversation itself has to be shareable to reach one at all, and
    # the *retrieved* private session still does not go with it.
    external = talking(ctx, ANSWER, egress=EgressClass.EXTERNAL)
    away = external.store.create_session(
        title="Writing up, hosted model",
        provenance=ctx.provenance(),
        visibility=Visibility.PROJECT,
    )
    hosted = external.send(
        away.id, "What did the pilot corpus show about tail latency?", background=False
    )
    hosted_pack = external.read_pack(away.id, hosted.context_pack)
    assert not [
        item
        for item in hosted_pack.receipt.included
        if item.context_class is ContextClass.PRIOR_SESSIONS
    ], "a private excerpt does not leave the machine"
    blocked = [
        item
        for item in hosted_pack.receipt.omitted
        if item.context_class is ContextClass.PRIOR_SESSIONS
        and item.reason is OmissionReason.EGRESS_BLOCKED
    ]
    assert blocked, "and the receipt says so, with the reason"
    assert any(str(prior.id) in item.source for item in blocked)


def test_a_private_session_refuses_an_external_provider_instead_of_sending_nothing(
    ctx: CapabilityContext,
) -> None:
    """Refusing is the honest answer: an empty pack would look like an answer."""
    from research_harness.privacy.policy import EgressDeniedError

    external = talking(ctx, ANSWER, egress=EgressClass.EXTERNAL)
    session = external.create("Private study")

    with pytest.raises(EgressDeniedError, match="private"):
        external.send(session.id, "What did we learn?", background=False)

    assert external.transcript(session.id).total == 0, "and nothing was written"


def test_a_project_visible_session_is_shareable_and_a_private_one_is_not(
    ctx: CapabilityContext,
) -> None:
    service = talking(ctx, "Recorded.", "Recorded.", egress=EgressClass.LOCAL)
    shared = service.store.create_session(
        title="Shared measurements",
        provenance=ctx.provenance(),
        visibility=Visibility.PROJECT,
    )
    service.send(shared.id, PILOT, background=False)

    external = talking(ctx, ANSWER, egress=EgressClass.EXTERNAL)
    away = external.store.create_session(
        title="Writing up", provenance=ctx.provenance(), visibility=Visibility.PROJECT
    )
    started = external.send(
        away.id, "What did the pilot corpus show about tail latency?", background=False
    )
    pack = external.read_pack(away.id, started.context_pack)
    assert [
        item for item in pack.receipt.included if item.context_class is ContextClass.PRIOR_SESSIONS
    ], "a session the researcher marked project-visible may be sent"


# -- 4. accepted state outranks chat -----------------------------------------


def test_accepted_state_outranks_a_conflicting_memory_and_the_conflict_is_visible(
    ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    service = talking(ctx, "Noted.", ANSWER, egress=EgressClass.LOCAL)
    session = service.create("Latency study")
    service.send(
        session.id,
        "Actually C0001 is wrong: batching made tail latency worse in our run.",
        background=False,
    )

    started = service.send(session.id, "What does C0001 say about batching?", background=False)
    pack = service.read_pack(session.id, started.context_pack)

    included = {str(item.id) for item in pack.receipt.included if item.id}
    assert "C0001" in included, "the accepted Claim is what the model is shown"
    conflicted = [
        item
        for item in pack.receipt.omitted
        if item.reason is OmissionReason.CONFLICTS_WITH_ACCEPTED
    ]
    assert conflicted, "the contradicting message is not sent"
    assert "C0001" in (conflicted[0].detail or "")

    preview = invoke(
        registry,
        ctx,
        "context.preview",
        {"session": str(session.id), "text": "What does C0001 say about batching?"},
    )
    assert preview.discrepancies, "the inspector can show the disagreement, not just the gap"
    assert preview.discrepancies[0].accepted == "C0001"

    transcript = invoke(registry, ctx, "session.get", {"session": str(session.id)})
    assert any("Actually C0001 is wrong" in message.text() for message in transcript.messages), (
        "the message is left out of the pack, never out of the transcript"
    )


# -- 5. promotion without bypassing review -----------------------------------


@pytest.fixture
def cli() -> typer.Typer:
    app = typer.Typer(name="research", no_args_is_help=True, add_completion=False)
    for module in (init_commands, session_commands):
        module.register(app)
    return app


def run(app: typer.Typer, *args: str) -> Result:
    result = runner.invoke(app, list(args))
    if result.exit_code != 0:  # pragma: no cover - surfaced only when the gate breaks
        raise AssertionError(f"`research {' '.join(args)}` failed: {result.output}")
    return result


@pytest.fixture
def script(tmp_path: Path) -> Path:
    """A one-reply script, so the CLI half of the gate needs no provider and no network."""
    path = tmp_path / "reply.json"
    path.write_text(json.dumps([{"text": ANSWER}]), encoding="utf-8")
    return path


def test_an_excerpt_is_promoted_through_the_cli_without_bypassing_review(
    cli: typer.Typer, workspace: Path, script: Path, ctx: CapabilityContext
) -> None:
    created = json.loads(
        run(cli, "chat", "new", "Latency study", "-w", str(workspace), "--json").stdout
    )
    session = created["session"]["id"]
    sent = json.loads(
        run(
            cli,
            "chat",
            "send",
            session,
            "What does batching do to tail latency?",
            "-w",
            str(workspace),
            "--script",
            str(script),
            "--json",
        ).stdout
    )
    assert sent["state"] == "succeeded" and sent["text"] == ANSWER

    promoted = json.loads(
        run(
            cli,
            "chat",
            "promote",
            sent["message"],
            "claim_candidate",
            "-w",
            str(workspace),
            "--subject",
            "batching",
            "--predicate",
            "reduces",
            "--object",
            "tail latency",
            "--scope",
            "corpus_pattern",
            "--json",
        ).stdout
    )
    claim = ctx.repo.get_claim(ClaimId(promoted["object_id"]))
    assert claim.assessment.status is ClaimStatus.UNVERIFIED
    assert claim.assessment.allowed_strength is ClaimScope.INDIVIDUAL
    assert "claim.audit" in promoted["review"]
    assert promoted["accepted"] is False

    shown = json.loads(run(cli, "chat", "show", session, "-w", str(workspace), "--json").stdout)
    assert [message["id"] for message in shown["messages"]] == ["M0001", "M0002"]
    assert shown["messages"][1]["blocks"][0]["text"] == ANSWER


def test_promoting_prose_to_evidence_is_refused_and_names_the_anchor(
    cli: typer.Typer, workspace: Path, script: Path
) -> None:
    created = json.loads(
        run(cli, "chat", "new", "Latency study", "-w", str(workspace), "--json").stdout
    )
    sent = json.loads(
        run(
            cli,
            "chat",
            "send",
            created["session"]["id"],
            "What does batching do to tail latency?",
            "-w",
            str(workspace),
            "--script",
            str(script),
            "--json",
        ).stdout
    )
    refused = runner.invoke(
        cli,
        ["chat", "promote", sent["message"], "evidence", "-w", str(workspace)],
    )
    assert refused.exit_code == 1
    assert "anchor" in refused.output


def test_the_cli_and_the_capability_show_the_same_receipt(
    cli: typer.Typer, workspace: Path, script: Path, ctx: CapabilityContext
) -> None:
    created = json.loads(
        run(cli, "chat", "new", "Latency study", "-w", str(workspace), "--json").stdout
    )
    session = created["session"]["id"]
    printed = json.loads(
        run(
            cli,
            "chat",
            "context",
            session,
            "-w",
            str(workspace),
            "--text",
            "does @C0001 still hold",
            "--persist",
            "--json",
        ).stdout
    )
    service = ConversationService(ctx)
    stored = service.read_pack(service.sessions()[0].id, service.packs(service.sessions()[0].id)[0])
    assert printed["pack"] == json.loads(stored.model_dump_json())


# -- the whole loop ----------------------------------------------------------


@pytest.fixture
def gate_summary() -> Iterator[None]:
    """A marker fixture so the gate reads as one demonstration in the test output."""
    yield


def test_the_gate_holds_when_the_projection_is_deleted(
    ctx: CapabilityContext, gate_summary: None
) -> None:
    """`.research/` is disposable: a rebuild may be needed, a transcript never is."""
    import shutil

    service = talking(ctx, "Recorded.", egress=EgressClass.LOCAL)
    session = service.create("Latency study")
    service.send(session.id, PILOT, background=False)

    shutil.rmtree(ctx.repo.layout.research_dir)

    reopened = ConversationService(ctx).transcript(session.id)
    assert reopened.total == 2
    assert reopened.messages[0].text() == PILOT
    assert ConversationService(ctx).search("pilot corpus")

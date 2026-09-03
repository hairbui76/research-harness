"""Product §42 M-P: the acceptance tests the conversation-first track is measured against.

The v1.0 suite in this directory takes one sentence of §42 per module. The v1.1 sentences
are four, they share no workspace, and each of them is a *boundary* rather than a workflow,
so they are gathered here with one section per sentence and one fixture per section:

* **M. Conversation authority and context receipt** — a reopened session keeps its
  transcript, the model receives policy-allowed current and relevant prior context,
  accepted scientific state outranks conflicting chat, and `Context used` records every
  included or omitted class with a reason.
* **N. Attachment promotion boundary** — dragging a file creates only a session
  attachment, `Save to corpus` resolves Work/Version/Artifact identity explicitly, a
  half-finished promotion leaves the session copy intact, and nothing accepts Evidence.
* **O. ResearchGraph rebuild and reference resolution** — after `rm -rf .research/`, the
  same stable references and scientific relations come back from durable sources,
  candidate edges stay candidate, privacy filters stay enforced, and exact/two-hop lookups
  stay inside the measured budgets.
* **P. LaTeX rendering and source ownership** — the backend half: the manuscript compiles
  through the real toolchain path, keeps the last good PDF on failure, reports file/line
  errors distinct from scientific findings, and applies a model suggestion only as a
  reviewed diff. (Chat rendering Markdown mathematics is the Web client's half; what the
  backend owes it is that the transcript holds the TeX byte for byte, which is asserted in
  M.)

Everything is driven through the capability registry and the `research` CLI — the surfaces
a researcher and a host actually reach — with scripted providers and a fake LaTeX engine,
so the suite is offline and deterministic.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import typer
import yaml
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.permissions import Principal
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.cli.commands import attachment as attachment_commands
from research_harness.cli.commands import init as init_commands
from research_harness.cli.commands import manuscript as manuscript_commands
from research_harness.conversation.send import ScriptedProviders
from research_harness.conversation.service import ConversationService
from research_harness.domain.base import Provenance
from research_harness.domain.claim import Claim, ClaimAssessment, ClaimScopeSpec, ClaimSemantics
from research_harness.domain.conversation import (
    AttachmentState,
    ContextClass,
    EgressClass,
    MessageRole,
    OmissionReason,
    Visibility,
)
from research_harness.domain.enums import (
    ClaimScope,
    ClaimStatus,
    ClaimType,
    ManuscriptFindingKind,
)
from research_harness.domain.graph import EdgeOrigin, GraphAuthority, GraphVisibility
from research_harness.domain.ids import ClaimId, ContextPackId, ConversationSessionId
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.workspace.repository import WorkspaceRepository

runner = CliRunner()

CLAIM_STATEMENT = "Batching reduces tail latency across the encrypted-traffic corpus."
PILOT = "The pilot corpus showed a nine percent tail latency drop under batching."
MATHS = "Tail latency scales as $O(n \\log n)$; see \\[ \\sum_{i=1}^{n} t_i \\]."
ANSWER = "Under batching, tail latency falls; C0001 records the corpus-level result."
CONTRADICTION = "Actually C0001 is wrong: batching made tail latency worse in our run."


def registry_of() -> CapabilityRegistry:
    return build_default_registry()


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    return registry_of()


def invoke(registry: CapabilityRegistry, ctx: CapabilityContext, name: str, request: Any) -> Any:
    """One capability call as the researcher — the surface HTTP, MCP and the CLI share."""
    return registry.invoke(name, ctx, request, principal=Principal.human())


def run(app: typer.Typer, *args: str) -> Result:
    result = runner.invoke(app, list(args))
    if result.exit_code != 0:  # pragma: no cover - surfaced only when an invariant breaks
        raise AssertionError(f"`research {' '.join(args)}` failed: {result.output}")
    return result


def printed(result: Result) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(result.stdout)
    return body


# ===========================================================================
# M. Conversation authority and context receipt
# ===========================================================================


@pytest.fixture
def conversation_workspace(tmp_path: Path) -> Path:
    """A project holding one accepted Claim about latency, and nothing else."""
    repo = WorkspaceRepository.init(tmp_path / "conversation", "invariant-m")
    from research_harness.workspace.serialization import canonical_bytes

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
    path = repo.layout.claim_file(claim.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(claim))
    return repo.root


@pytest.fixture
def conversation_ctx(conversation_workspace: Path) -> CapabilityContext:
    return open_context(conversation_workspace, HUMAN_ACTOR)


def talking(ctx: CapabilityContext, *answers: str, egress: EgressClass) -> ConversationService:
    """A conversation service answering from a script, with a declared egress class."""
    return ConversationService(
        ctx,
        providers=ScriptedProviders(
            ScriptedProvider([{"text": answer} for answer in answers]),
            chunk_words=4,
            egress=egress,
        ),
    )


def test_m_a_reopened_session_still_holds_every_message_it_was_left_with(
    conversation_ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """§42 M, first clause: reopening is a read of durable state, never a fresh start."""
    service = talking(conversation_ctx, ANSWER, egress=EgressClass.LOCAL)
    session = service.create("Latency study")
    service.send(session.id, MATHS, background=False)

    reopened = invoke(registry, conversation_ctx, "session.get", {"session": str(session.id)})

    assert reopened.session.title == "Latency study"
    assert [message.role for message in reopened.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    # Mathematics survives byte for byte, which is what the Web client's KaTeX half renders.
    assert reopened.messages[0].text() == MATHS


def test_m_the_model_receives_current_context_and_policy_allowed_prior_context(
    conversation_ctx: CapabilityContext,
) -> None:
    """§42 M, second clause: relevant prior sessions reach a local model, and only it."""
    earlier = talking(conversation_ctx, "Recorded.", egress=EgressClass.LOCAL)
    prior = earlier.create("Pilot corpus measurements")
    earlier.send(prior.id, PILOT, background=False)

    local = talking(conversation_ctx, ANSWER, egress=EgressClass.LOCAL)
    here = local.create("Writing up")
    started = local.send(
        here.id, "What did the pilot corpus show about tail latency?", background=False
    )
    pack = local.read_pack(here.id, started.context_pack)

    packed = {item.context_class for item in pack.receipt.included}
    retrieved = [
        item for item in pack.receipt.included if item.context_class is ContextClass.PRIOR_SESSIONS
    ]
    assert {ContextClass.POLICY, ContextClass.CURRENT_SESSION} <= packed
    assert retrieved and str(prior.id) in retrieved[0].source


def test_m_a_private_prior_session_never_reaches_an_external_provider(
    conversation_ctx: CapabilityContext,
) -> None:
    """§42 M: "policy-allowed" is the operative word, and the receipt names the refusal."""
    earlier = talking(conversation_ctx, "Recorded.", egress=EgressClass.LOCAL)
    prior = earlier.create("Pilot corpus measurements")
    earlier.send(prior.id, PILOT, background=False)

    external = talking(conversation_ctx, ANSWER, egress=EgressClass.EXTERNAL)
    away = external.store.create_session(
        title="Writing up, hosted model",
        provenance=conversation_ctx.provenance(),
        visibility=Visibility.PROJECT,
    )
    started = external.send(
        away.id, "What did the pilot corpus show about tail latency?", background=False
    )
    pack = external.read_pack(away.id, started.context_pack)

    assert not [
        item for item in pack.receipt.included if item.context_class is ContextClass.PRIOR_SESSIONS
    ]
    blocked = [
        item
        for item in pack.receipt.omitted
        if item.reason is OmissionReason.EGRESS_BLOCKED and str(prior.id) in item.source
    ]
    assert blocked, "the private excerpt is withheld, and the receipt says why"
    assert pack.egress is EgressClass.EXTERNAL


def test_m_accepted_state_outranks_conflicting_chat_and_the_transcript_keeps_both(
    conversation_ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """§42 M, third clause: the Claim is sent, the contradiction is not, nothing is deleted."""
    service = talking(conversation_ctx, "Noted.", ANSWER, egress=EgressClass.LOCAL)
    session = service.create("Latency study")
    service.send(session.id, CONTRADICTION, background=False)

    started = service.send(session.id, "What does C0001 say about batching?", background=False)
    pack = service.read_pack(session.id, started.context_pack)

    assert "C0001" in {str(item.id) for item in pack.receipt.included if item.id}
    conflicted = [
        item
        for item in pack.receipt.omitted
        if item.reason is OmissionReason.CONFLICTS_WITH_ACCEPTED
    ]
    assert conflicted and "C0001" in (conflicted[0].detail or "")
    assert pack.receipt.discrepancies[0].accepted == "C0001"

    transcript = invoke(registry, conversation_ctx, "session.get", {"session": str(session.id)})
    assert any(CONTRADICTION in message.text() for message in transcript.messages), (
        "the passage is left out of the pack, never out of the transcript"
    )


def test_m_the_receipt_records_every_included_and_omitted_item_with_a_reason(
    conversation_ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """§42 M, fourth clause, read through `context.get` — the durable form of the receipt."""
    service = talking(conversation_ctx, "Noted.", ANSWER, egress=EgressClass.LOCAL)
    session = service.create("Latency study")
    service.send(session.id, CONTRADICTION, background=False)
    started = service.send(
        session.id,
        "Does @C0001 still describe tail latency, and what about @C9999?",
        background=False,
    )

    view = invoke(
        registry,
        conversation_ctx,
        "context.get",
        {"session": str(session.id), "pack": str(started.context_pack)},
    )

    assert view.pack.id == started.context_pack
    assert view.tokens == view.pack.receipt.total_tokens()
    # Every included item names the class it came from and what it cost.
    assert view.tokens_by_class and all(count > 0 for count in view.tokens_by_class.values())
    assert all(item.context_class in set(ContextClass) for item in view.pack.receipt.included)
    # Every omitted item names a class *and* a reason from the vocabulary.
    assert view.omissions
    assert all(
        item.reason in {reason.value for reason in OmissionReason} for item in view.omissions
    )
    assert all(
        item.context_class in {name.value for name in ContextClass} for item in view.omissions
    )
    assert {item.reason for item in view.omissions} >= {
        OmissionReason.CONFLICTS_WITH_ACCEPTED.value,
        OmissionReason.UNRESOLVED_REFERENCE.value,
    }
    assert view.unresolved == ("C9999",)
    assert view.discrepancies and view.discrepancies[0].accepted == "C0001"


def test_m_the_receipt_outlives_the_projection_and_reads_back_unchanged(
    conversation_ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """A receipt a researcher can only read while an index survives is not a record."""
    service = talking(conversation_ctx, ANSWER, egress=EgressClass.LOCAL)
    session = service.create("Latency study")
    started = service.send(session.id, "Does @C0001 still hold?", background=False)
    before = invoke(
        registry,
        conversation_ctx,
        "context.get",
        {"session": str(session.id), "pack": str(started.context_pack)},
    )

    shutil.rmtree(conversation_ctx.repo.layout.research_dir)

    after = invoke(
        registry,
        conversation_ctx,
        "context.get",
        {"session": str(session.id), "pack": str(started.context_pack)},
    )
    assert after == before


# ===========================================================================
# N. Attachment promotion boundary
# ===========================================================================


PAPER = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_research_paper.pdf"

BLIND_PROVIDER = {
    "name": "local-text",
    "kind": "local_openai_compatible",
    "model": "text-1",
    "base_url": "http://127.0.0.1:11434/v1",
    "priority": 10,
}


@pytest.fixture
def attachment_cli() -> typer.Typer:
    app = typer.Typer(name="research", no_args_is_help=True, add_completion=False)
    for module in (init_commands, attachment_commands):
        module.register(app)
    return app


@pytest.fixture
def attachment_workspace(attachment_cli: typer.Typer, tmp_path: Path) -> Path:
    root = tmp_path / "attachments"
    run(attachment_cli, "init", str(root), "--name", "invariant-n")
    config_path = root / "research.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["providers"] = [BLIND_PROVIDER]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return root


@pytest.fixture
def attachment_session(attachment_workspace: Path) -> str:
    from research_harness.workspace.conversations import ConversationStore

    ctx = open_context(attachment_workspace, HUMAN_ACTOR)
    store = ConversationStore.for_repository(ctx.repo)
    return str(store.create_session(title="reading", provenance=Provenance.human()).id)


def corpus_state(root: Path) -> dict[str, list[str]]:
    """What the corpus and the scientific record hold, as sorted relative paths."""
    return {
        name: sorted(str(path.relative_to(root)) for path in (root / name).rglob("*"))
        for name in ("corpus", "claims", "questions", "decisions")
    }


def test_n_attaching_an_image_and_a_pdf_creates_no_corpus_object(
    attachment_cli: typer.Typer, attachment_workspace: Path, attachment_session: str
) -> None:
    """§42 N, first clause: a drag is working material, and nothing else (Product 40)."""
    from tests.fixtures.attachments import TINY_PNG

    before = corpus_state(attachment_workspace)

    image = printed(
        run(
            attachment_cli,
            "attachment",
            "add",
            attachment_session,
            str(TINY_PNG),
            "-w",
            str(attachment_workspace),
            "--json",
        )
    )
    document = printed(
        run(
            attachment_cli,
            "attachment",
            "add",
            attachment_session,
            str(PAPER),
            "-w",
            str(attachment_workspace),
            "--json",
        )
    )

    assert (image["id"], image["state"]) == ("SA0001", "ready")
    assert (document["id"], document["state"]) == ("SA0002", "ready")
    assert image["artifact"] is None and document["artifact"] is None
    assert corpus_state(attachment_workspace) == before


def test_n_save_to_corpus_resolves_identity_explicitly_before_it_writes(
    attachment_cli: typer.Typer, attachment_workspace: Path, attachment_session: str
) -> None:
    """§42 N, second clause: Work, Version and Artifact are named, then created."""
    run(
        attachment_cli,
        "attachment",
        "add",
        attachment_session,
        str(PAPER),
        "-w",
        str(attachment_workspace),
        "--json",
    )

    resolved = printed(
        run(
            attachment_cli,
            "attachment",
            "resolve",
            attachment_session,
            "SA0001",
            "-w",
            str(attachment_workspace),
            "--json",
        )
    )
    # Resolving is a read: it decides nothing on disk.
    assert resolved["choice"] == "new_work"
    assert list((attachment_workspace / "corpus" / "works").iterdir()) == []

    saved = printed(
        run(
            attachment_cli,
            "attachment",
            "save",
            attachment_session,
            "SA0001",
            "-w",
            str(attachment_workspace),
            "--json",
        )
    )

    assert saved["created"] == "work"
    assert saved["work"] and saved["version"] and saved["artifact"]
    assert saved["attachment"]["state"] == AttachmentState.IN_CORPUS.value
    assert saved["attachment"]["artifact"] == saved["artifact"]


def test_n_promotion_accepts_no_evidence_and_no_claim(
    attachment_cli: typer.Typer, attachment_workspace: Path, attachment_session: str
) -> None:
    """§42 N, fourth clause: identity is not interpretation (attachments design SS7)."""
    run(
        attachment_cli,
        "attachment",
        "add",
        attachment_session,
        str(PAPER),
        "-w",
        str(attachment_workspace),
        "--json",
    )
    saved = printed(
        run(
            attachment_cli,
            "attachment",
            "save",
            attachment_session,
            "SA0001",
            "-w",
            str(attachment_workspace),
            "--json",
        )
    )

    assert saved["evidence_created"] is False
    assert not any(
        path.read_text(encoding="utf-8").strip()
        for path in (attachment_workspace / "corpus").rglob("evidence.jsonl")
    )
    assert list((attachment_workspace / "claims").iterdir()) == []


def test_n_a_promotion_that_fails_half_way_leaves_the_session_copy_intact(
    attachment_cli: typer.Typer,
    attachment_workspace: Path,
    attachment_session: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§42 N, third clause: a failed promotion loses neither the bytes nor the retry."""
    import research_harness.conversation.promotion_corpus as promotion_module
    from research_harness.conversation.attachments import AttachmentService
    from research_harness.domain.ids import SessionAttachmentId
    from research_harness.workspace.conversations import ConversationStore

    run(
        attachment_cli,
        "attachment",
        "add",
        attachment_session,
        str(PAPER),
        "-w",
        str(attachment_workspace),
        "--json",
    )
    ctx = open_context(attachment_workspace, HUMAN_ACTOR)
    service = AttachmentService(ConversationStore.for_repository(ctx.repo))
    session_id = ConversationSessionId(attachment_session)
    original = service.store.read_attachment_bytes(
        service.get(session_id, SessionAttachmentId("SA0001"))
    )

    class BrokenIngest(promotion_module.IngestService):
        def ingest_local_pdf(self, path: Path | str, **kwargs: object) -> Any:
            raise RuntimeError("the corpus write failed half-way")

    monkeypatch.setattr(promotion_module, "IngestService", BrokenIngest)
    failed = runner.invoke(
        attachment_cli,
        ["attachment", "save", attachment_session, "SA0001", "-w", str(attachment_workspace)],
    )
    monkeypatch.undo()

    assert failed.exit_code != 0
    record = service.get(session_id, SessionAttachmentId("SA0001"))
    assert record.state is AttachmentState.FAILED
    assert service.store.read_attachment_bytes(record) == original
    assert list((attachment_workspace / "corpus" / "works").iterdir()) == []

    recovered = printed(
        run(
            attachment_cli,
            "attachment",
            "save",
            attachment_session,
            "SA0001",
            "-w",
            str(attachment_workspace),
            "--json",
        )
    )
    assert recovered["created"] == "work"
    assert recovered["attachment"]["state"] == AttachmentState.IN_CORPUS.value


def test_n_an_unsendable_attachment_is_never_silently_dropped_from_a_request(
    attachment_cli: typer.Typer, attachment_workspace: Path, attachment_session: str
) -> None:
    """The boundary's other half: a blind model blocks the send and says which item."""
    from tests.fixtures.attachments import TINY_PNG

    run(
        attachment_cli,
        "attachment",
        "add",
        attachment_session,
        str(TINY_PNG),
        "-w",
        str(attachment_workspace),
        "--json",
    )

    check = printed(
        run(
            attachment_cli,
            "attachment",
            "check",
            attachment_session,
            "-w",
            str(attachment_workspace),
            "--json",
        )
    )

    assert check["ok"] is False
    assert check["items"][0]["omission"] == OmissionReason.UNSUPPORTED_MEDIA.value
    assert "cannot be sent" in check["refusal"]


# ===========================================================================
# O. ResearchGraph rebuild and reference resolution
# ===========================================================================


@pytest.fixture(scope="module")
def graph_workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The graph fixture plus two sessions: one project-visible, one private."""
    from tests.integration.graph.conftest import populated_workspace
    from tests.integration.graph.test_sessions_rebuild import add_sessions

    repo = populated_workspace(tmp_path_factory.mktemp("graph") / "project")
    add_sessions(repo)
    return repo.root


def stable_references() -> tuple[str, ...]:
    from tests.integration.graph.conftest import ARTIFACT, CLAIM, CONTRADICTING, SUPPORTING
    from tests.integration.graph.test_sessions_rebuild import (
        PRIVATE,
        PRIVATE_NOTE,
        SHARED,
        SHARED_ATTACHMENT,
        SHARED_QUESTION,
    )

    return tuple(
        f"@{name}"
        for name in (
            CLAIM,
            SUPPORTING,
            CONTRADICTING,
            ARTIFACT,
            SHARED,
            SHARED_QUESTION,
            SHARED_ATTACHMENT,
            PRIVATE,
            PRIVATE_NOTE,
        )
    )


def resolved_through_the_capability(root: Path) -> dict[str, tuple[Any, ...]]:
    """Every stable reference, resolved through `graph.resolve` as a client would."""
    registry = registry_of()
    ctx = open_context(root, HUMAN_ACTOR)
    answers: dict[str, tuple[Any, ...]] = {}
    for reference in stable_references():
        view = invoke(registry, ctx, "graph.resolve", {"reference": reference})
        answers[reference] = (
            view.exists,
            view.fresh,
            view.authority,
            view.visibility,
            view.link,
            None if view.node is None else (view.node.id, view.node.kind, view.node.label),
        )
    return answers


def test_o_rebuilding_after_deleting_the_projection_resolves_the_same_references(
    graph_workspace: Path, tmp_path: Path
) -> None:
    """§42 O, first clause: identity lives in the durable files, never in the index."""
    root = tmp_path / "rebuilt"
    shutil.copytree(graph_workspace, root)
    from research_harness.graph.service import ResearchGraph

    repo = WorkspaceRepository.open(root, repair=True)
    built = ResearchGraph(repo)
    try:
        built.rebuild()
    finally:
        built.close()
    before = resolved_through_the_capability(root)
    assert all(answer[0] for answer in before.values()), before

    staging = tmp_path / "staging-backup"
    research = repo.layout.research_dir
    shutil.copytree(research / "staging", staging)
    shutil.rmtree(research)
    research.mkdir(parents=True)
    shutil.copytree(staging, research / "staging")

    rebuilt = ResearchGraph(WorkspaceRepository.open(root, repair=True))
    try:
        report = rebuilt.rebuild()
    finally:
        rebuilt.close()

    assert report.nodes and report.edges
    assert resolved_through_the_capability(root) == before


def test_o_the_scientific_relations_come_back_and_a_proposal_stays_a_proposal(
    graph_workspace: Path,
) -> None:
    """§42 O, second clause: an accepted edge and a model-proposed one stay different."""
    from research_harness.graph.queries import Direction
    from research_harness.graph.service import ResearchGraph
    from tests.integration.graph.conftest import CLAIM, CONTRADICTING, SUPPORTING

    built = ResearchGraph(WorkspaceRepository.open(graph_workspace, repair=True))
    try:
        built.rebuild()
    finally:
        built.close()
    ctx = open_context(graph_workspace, HUMAN_ACTOR)
    registry = registry_of()

    view = invoke(
        registry,
        ctx,
        "graph.neighbors",
        {"id": str(CLAIM), "hops": 1, "direction": Direction.IN.value, "limit": 100},
    )

    accepted = {item.node.id for item in view.neighbours if item.edge.origin is EdgeOrigin.ACCEPTED}
    proposed = [item for item in view.neighbours if item.edge.origin is EdgeOrigin.MODEL_PROPOSED]
    assert {str(SUPPORTING), str(CONTRADICTING)} <= accepted
    assert proposed, "the proposal is visible"
    assert all(item.edge.authority is GraphAuthority.CANDIDATE for item in proposed)
    assert all(item.edge.is_candidate for item in proposed)

    # And a staged proposal never takes a scientific identity while it waits for review.
    candidates = invoke(
        registry,
        ctx,
        "graph.query",
        {"authorities": [GraphAuthority.CANDIDATE.value], "limit": 50},
    )
    assert candidates.nodes
    assert all(node.id.startswith("candidate:") for node in candidates.nodes)


def test_o_a_project_visible_traversal_cannot_reach_a_private_session(
    graph_workspace: Path,
) -> None:
    """§42 O, third clause: not even through the accepted Evidence both sessions name."""
    from research_harness.graph.service import ResearchGraph
    from tests.integration.graph.conftest import SUPPORTING
    from tests.integration.graph.test_sessions_rebuild import PRIVATE, PRIVATE_NOTE

    built = ResearchGraph(WorkspaceRepository.open(graph_workspace, repair=True))
    try:
        built.rebuild()
    finally:
        built.close()
    ctx = open_context(graph_workspace, HUMAN_ACTOR)
    registry = registry_of()

    unfiltered = invoke(
        registry, ctx, "graph.neighbors", {"id": str(SUPPORTING), "hops": 1, "limit": 100}
    )
    filtered = invoke(
        registry,
        ctx,
        "graph.neighbors",
        {
            "id": str(SUPPORTING),
            "hops": 2,
            "limit": 200,
            "visibility": [GraphVisibility.PROJECT.value],
        },
    )

    assert str(PRIVATE_NOTE) in {item.node.id for item in unfiltered.neighbours}
    reached = {item.node.id for item in filtered.neighbours}
    assert str(PRIVATE_NOTE) not in reached and str(PRIVATE) not in reached


def test_o_exact_and_two_hop_lookups_stay_inside_the_measured_budgets(
    graph_workspace: Path,
) -> None:
    """§42 O, fourth clause, on the benchmark corpus's own measuring instrument."""
    from research_harness.graph.bench import (
        EXACT_REFERENCE_BUDGET_MS,
        NEIGHBOURHOOD_BUDGET_MS,
        measure_graph_latency,
    )
    from research_harness.graph.service import ResearchGraph

    built = ResearchGraph(WorkspaceRepository.open(graph_workspace, repair=True))
    try:
        built.rebuild()
        report = measure_graph_latency(built)
    finally:
        built.close()

    over = [sample.summary() for sample in report.samples if not sample.within_budget]
    assert report.samples
    assert not over, "\n".join(over)
    assert (EXACT_REFERENCE_BUDGET_MS, NEIGHBOURHOOD_BUDGET_MS) == (100.0, 250.0)


def test_o_the_durable_sources_outlive_the_projection(
    graph_workspace: Path, tmp_path: Path
) -> None:
    """A transcript, a Claim and an attachment are files; the index is a cache."""
    from research_harness.workspace.conversations import ConversationStore
    from tests.integration.graph.conftest import CLAIM
    from tests.integration.graph.test_sessions_rebuild import PRIVATE, PRIVATE_NOTE, SHARED

    root = tmp_path / "durable"
    shutil.copytree(graph_workspace, root)
    repo = WorkspaceRepository.open(root, repair=True)
    shutil.rmtree(repo.layout.research_dir, ignore_errors=True)

    reopened = WorkspaceRepository.open(root, repair=True)
    store = ConversationStore.for_repository(reopened)

    assert [message.id for message in store.iter_messages(PRIVATE)] == [PRIVATE_NOTE]
    assert store.get_session(SHARED).message_count == 2
    assert reopened.get_claim(CLAIM).statement


# ===========================================================================
# P. LaTeX rendering and source ownership (the backend half)
# ===========================================================================


ANCHORED_FILE = "sections/intro.tex"
SPAN = (4, 5)
INTRO_TEX = """\\section{Introduction}
\\label{sec:intro}

All existing traffic classifiers degrade under sustained load, and no prior work reports
the size of the gap \\cite{kraus2019}.

We compile this manuscript from source that stays under the researcher's control.
"""
HUMANIZED = (
    "All existing traffic classifiers degrade under sustained load, and no prior work "
    "reports the size of the gap \\cite{kraus2019}.\n"
)
STRENGTHENED = (
    "Traffic classifiers always collapse under sustained load, and the size of the gap "
    "has never been measured \\cite{kraus2019}.\n"
)

pytestmark_p = pytest.mark.skipif(
    os.name == "nt", reason="the fake engine is a POSIX executable script"
)


@pytest.fixture
def manuscript_cli() -> typer.Typer:
    app = typer.Typer(name="research", no_args_is_help=True, add_completion=False)
    for module in (init_commands, manuscript_commands):
        module.register(app)
    return app


@pytest.fixture
def manuscript_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A LaTeX project, one anchored Claim, and only the fake engine on PATH."""
    from research_harness.capabilities.dto import CreateClaimRequest
    from research_harness.capabilities.handlers import create_claim
    from research_harness.manuscript.attach import ManuscriptService
    from tests.fixtures.latex import copy_project, install_fake_engine

    root = tmp_path / "manuscript-project"
    repo = WorkspaceRepository.init(root, "invariant-p")
    copy_project(repo.layout.manuscript_dir)
    (repo.layout.manuscript_dir / ANCHORED_FILE).write_text(INTRO_TEX, encoding="utf-8")

    ctx = open_context(root, HUMAN_ACTOR)
    create_claim(
        ctx,
        CreateClaimRequest(
            claim=Claim(
                id=ClaimId("C0001"),
                statement="classifiers in the reviewed corpus degrade under sustained load",
                type=ClaimType.DESCRIPTIVE,
                semantics=ClaimSemantics(
                    subject="classifiers", predicate="degrade", object="under sustained load"
                ),
                scope=ClaimScopeSpec(level=ClaimScope.CORPUS_PATTERN, corpus="traffic classifiers"),
                assessment=ClaimAssessment(
                    requested_strength=ClaimScope.CORPUS_PATTERN,
                    allowed_strength=ClaimScope.CORPUS_PATTERN,
                    status=ClaimStatus.SUPPORTED,
                    maximum_defensible_wording="the classifiers in the reviewed corpus",
                ),
                provenance=Provenance.human(HUMAN_ACTOR),
            )
        ),
    )
    ManuscriptService(ctx).attach((ANCHORED_FILE, 4), ClaimId("C0001"))

    monkeypatch.setenv("PATH", str(install_fake_engine(tmp_path / "bin", "pdflatex")))
    yield root


@pytest.fixture
def manuscript_ctx(manuscript_workspace: Path) -> CapabilityContext:
    return open_context(manuscript_workspace, HUMAN_ACTOR)


def break_the_source(root: Path) -> None:
    path = root / "manuscript" / ANCHORED_FILE
    path.write_text(f"{path.read_text(encoding='utf-8')}\n% fake-latex: fail\n", encoding="utf-8")


def writer_script(tmp_path: Path, draft: str) -> Path:
    path = tmp_path / f"writer-{abs(hash(draft))}.json"
    path.write_text(json.dumps({"writer": [{"draft": draft}]}), encoding="utf-8")
    return path


@pytestmark_p
def test_p_the_manuscript_compiles_through_the_real_toolchain_path(
    manuscript_ctx: CapabilityContext, manuscript_workspace: Path, registry: CapabilityRegistry
) -> None:
    """§42 P: a real subprocess, a real argv, a real PDF written to a real build directory."""
    view = invoke(registry, manuscript_ctx, "manuscript.compile", {})

    assert view.status.value == "succeeded"
    assert view.pdf is not None
    pdf = manuscript_workspace / view.pdf
    assert pdf.read_bytes().startswith(b"%PDF")
    assert view.build_id and view.result is not None
    # A real subprocess, with the argv the compile service built and no shell.
    assert view.result.engine.value in view.result.executable
    assert view.result.args and view.result.exit_status == 0
    # The compiler is given no execution capability: `-no-shell-escape` is passed and the
    # enabling spellings are absent (LaTeX spec SS4).
    assert "-no-shell-escape" in view.result.args
    assert not {"-shell-escape", "--shell-escape", "shell-escape"} & set(view.result.args)
    assert view.toolchain.available and view.toolchain.selected is not None
    assert view.toolchain.installed, "the engine was discovered on PATH, not assumed"
    # The output is disposable and the source is not.
    assert manuscript_ctx.repo.layout.is_regenerable(pdf)


@pytestmark_p
def test_p_a_failing_compile_reports_file_and_line_and_keeps_the_last_good_pdf(
    manuscript_ctx: CapabilityContext, manuscript_workspace: Path, registry: CapabilityRegistry
) -> None:
    """§42 P: a broken build never costs the researcher the PDF they already had."""
    good = invoke(registry, manuscript_ctx, "manuscript.compile", {})
    good_bytes = (manuscript_workspace / good.pdf).read_bytes()
    break_the_source(manuscript_workspace)

    bad = invoke(registry, manuscript_ctx, "manuscript.compile", {})

    assert bad.status.value == "failed"
    error = next(item for item in bad.diagnostics if item.severity.value == "error")
    assert error.file == ANCHORED_FILE and error.line is not None
    assert bad.pdf is None and bad.pdf_stale and bad.pdf_available
    assert bad.last_good is not None and bad.last_good.build_id == good.build_id
    assert (manuscript_workspace / bad.last_good.pdf).read_bytes() == good_bytes


@pytestmark_p
def test_p_compiler_errors_and_scientific_findings_are_different_lists(
    manuscript_ctx: CapabilityContext, manuscript_workspace: Path, registry: CapabilityRegistry
) -> None:
    """§42 P: a clean compile is not an audit pass, and a broken one is not a finding."""
    clean = invoke(registry, manuscript_ctx, "manuscript.compile", {})
    break_the_source(manuscript_workspace)
    broken = invoke(registry, manuscript_ctx, "manuscript.compile", {})

    assert clean.error_count == 0 and clean.audit_ran
    assert ManuscriptFindingKind.OVER_STRONG_WORDING in {
        finding.kind for finding in clean.audit_findings
    }
    assert broken.error_count >= 1
    assert {finding.kind for finding in broken.audit_findings} == {
        finding.kind for finding in clean.audit_findings
    }
    assert not any("fake-latex" in finding.message for finding in broken.audit_findings)


@pytestmark_p
def test_p_a_model_suggestion_reaches_the_source_only_through_a_reviewed_diff(
    manuscript_cli: typer.Typer, manuscript_workspace: Path, tmp_path: Path
) -> None:
    """§42 P, last clause: staged as a diff, applied by a person, refused when it lies."""
    from research_harness.manuscript.files import ManuscriptFiles

    files = ManuscriptFiles(open_context(manuscript_workspace, HUMAN_ACTOR).repo.layout)
    before = files.hash_of(ANCHORED_FILE)

    staged = printed(
        run(
            manuscript_cli,
            "manuscript",
            "suggest",
            f"{ANCHORED_FILE}:{SPAN[0]}-{SPAN[1]}",
            "-w",
            str(manuscript_workspace),
            "--style",
            "humanize",
            "--script",
            str(writer_script(tmp_path, HUMANIZED)),
            "--json",
        )
    )

    assert files.hash_of(ANCHORED_FILE) == before, "suggesting changes no source"
    assert staged["path"].startswith(".research/staging/manuscript/")
    assert staged["audit_status"] == "passed" and staged["applicable"] is True
    assert {"added", "removed", "context"} <= {
        line["kind"] for hunk in staged["hunks"] for line in hunk["lines"]
    }

    applied = printed(
        run(
            manuscript_cli,
            "manuscript",
            "apply",
            staged["candidate_id"],
            "-w",
            str(manuscript_workspace),
            "--json",
        )
    )

    assert files.read(ANCHORED_FILE).content == staged["proposed_content"]
    assert applied["event"]["event"] == "manuscript.source_written"


@pytestmark_p
def test_p_a_suggestion_that_moves_the_proposition_cannot_be_applied_at_all(
    manuscript_cli: typer.Typer, manuscript_workspace: Path, tmp_path: Path
) -> None:
    """§42 P and §42 L meet here: a style pass may not strengthen a claim."""
    from research_harness.manuscript.files import ManuscriptFiles

    files = ManuscriptFiles(open_context(manuscript_workspace, HUMAN_ACTOR).repo.layout)
    before = files.hash_of(ANCHORED_FILE)

    staged = printed(
        run(
            manuscript_cli,
            "manuscript",
            "suggest",
            f"{ANCHORED_FILE}:{SPAN[0]}-{SPAN[1]}",
            "-w",
            str(manuscript_workspace),
            "--style",
            "humanize",
            "--script",
            str(writer_script(tmp_path, STRENGTHENED)),
            "--json",
        )
    )
    refused = runner.invoke(
        manuscript_cli,
        ["manuscript", "apply", staged["candidate_id"], "-w", str(manuscript_workspace)],
    )

    assert staged["audit_status"] == "failed"
    assert "not meaning-preserving" in staged["blocked_reason"]
    assert refused.exit_code == 1
    assert files.hash_of(ANCHORED_FILE) == before


def test_p_chat_mathematics_is_never_compiled_and_never_normalized(
    conversation_ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """§42 P's first clause, from the backend: rendering is the client's, bytes are ours.

    The transcript stores the TeX the researcher typed, character for character, and no
    compiler is anywhere near it — which is what makes "chat renders Markdown mathematics"
    a rendering decision the Web client can make on its own.
    """
    service = talking(conversation_ctx, ANSWER, egress=EgressClass.LOCAL)
    session = service.create("Latency study")
    service.send(session.id, MATHS, background=False)

    transcript = invoke(registry, conversation_ctx, "session.get", {"session": str(session.id)})
    stored = transcript.messages[0].text()

    assert stored == MATHS
    assert "\\log" in stored and "\\sum" in stored
    assert not list((conversation_ctx.repo.layout.research_dir / "build").glob("**/*.pdf"))


def test_the_v11_receipt_identifier_is_the_one_the_message_names(
    conversation_ctx: CapabilityContext, registry: CapabilityRegistry
) -> None:
    """The thread tying M to the rest: a message names a receipt, and it can be read."""
    service = talking(conversation_ctx, ANSWER, egress=EgressClass.LOCAL)
    session = service.create("Latency study")
    started = service.send(session.id, "What do we know?", background=False)

    transcript = invoke(registry, conversation_ctx, "session.get", {"session": str(session.id)})
    answer = transcript.messages[-1]
    assert answer.context_pack is not None

    view = invoke(
        registry,
        conversation_ctx,
        "context.get",
        {"session": str(session.id), "pack": str(answer.context_pack)},
    )
    assert view.pack.id == ContextPackId(str(started.context_pack))

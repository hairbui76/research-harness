"""Serve the production bundle and real backend over disposable browser-test data."""

from __future__ import annotations

import itertools
import os
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

import uvicorn
from fastapi import FastAPI

from research_harness.domain.enums import ReviewPolicy
from research_harness.local_app.auth import BootstrapStore
from research_harness.local_app.manager import ProjectManager
from research_harness.local_app.pickers.base import ManualFolderPicker
from research_harness.server.multi_app import create_multi_project_app


def stage_review_queue(root: Path) -> None:
    """Fill a fresh workspace with a real review queue, through the daemon's own services.

    The review screens need candidates, and staging one means ingesting a paper, parsing it,
    extracting spans and verifying them — work no public capability can do here without a
    paid model provider. So this reuses the Gate P11 fixtures (`tests/e2e/test_web_gate.py`):
    the synthetic paper is ingested and parsed through the capability layer exactly as the
    cockpit would, and the extractor and verifier are the scripted providers the gate already
    uses. Everything it writes is a proposal under `.research/staging`; no accepted state is
    created, and nothing here reaches production code.
    """
    from tests.e2e.test_web_gate import FIXTURE, WORK, stage_candidates

    from research_harness.capabilities.context import open_context
    from research_harness.capabilities.permissions import Principal
    from research_harness.capabilities.registry import build_default_registry
    from research_harness.domain.transitions import HUMAN_ACTOR

    registry = build_default_registry()
    human = Principal.human()
    registry.invoke(
        "corpus.ingest", open_context(root, HUMAN_ACTOR), {"path": str(FIXTURE)}, principal=human
    )
    registry.invoke(
        "work.parse", open_context(root, HUMAN_ACTOR), {"work": str(WORK)}, principal=human
    )
    stage_candidates(root)


def stage_conversation(root: Path) -> str:
    """Give a fresh workspace one session with a real user turn and a real answer.

    A transcript row is a design surface — the reference chips, the toolbar and its
    *More actions* overflow — and the browser suite could not photograph one, because every
    route to a message runs through `session.send` and a model provider. It does not have
    to run through a *hosted* one: `ScriptedProviders` is the offline selector the CLI's own
    `--script` mode uses, a real adapter running the real contract, so the message, its
    context pack and the streamed answer are all written by the same code path a hosted send
    takes. Nothing leaves the machine and nothing here reaches production code.
    """
    from research_harness.capabilities.context import CapabilityContext
    from research_harness.conversation.send import ScriptedProviders
    from research_harness.conversation.service import ConversationService
    from research_harness.providers.models.scripted import ScriptedProvider
    from research_harness.workspace.repository import WorkspaceRepository

    repo = WorkspaceRepository.open(root)
    service = ConversationService(
        CapabilityContext(repo=repo),
        providers=ScriptedProviders(
            ScriptedProvider(
                [
                    {
                        "text": (
                            "The pretrained encoder improves F1 by 2.57 points over the "
                            "strongest baseline, and the gain is concentrated in the two "
                            "rarest attack families."
                        )
                    }
                ]
            ),
            chunk_words=4,
        ),
    )
    session = service.create("Latency study")
    started = service.send(session.id, "What did we learn about the held-out split?")
    service.wait(started.run_id, 60)
    return str(session.id)


def stage_overview_project(root: Path) -> None:
    """Fill a fresh workspace with everything the Overview groups its screen into.

    The Overview reads one composed answer, and each of its groups is a different corner of
    the workspace: a queue with candidates in it, a claim, an accepted Decision, a
    disagreement on record, a stale mark, and the event log entries all of those wrote. This
    builds every one of them through the daemon's own services, so the browser test reads a
    page composed from real state rather than from a fixture.

    Staleness is the one that cannot be asked for directly, and should not be: an object goes
    stale because something it rests on changed. So the projection is rebuilt and then the
    daemon's own invalidation hook is run over the evidence the Claim cites, which is exactly
    what a mutation touching that evidence would have done (Product 37, ADR-008).
    """
    from research_harness.capabilities.context import open_context
    from research_harness.capabilities.invalidation import DependencyInvalidation
    from research_harness.capabilities.permissions import Principal
    from research_harness.capabilities.registry import build_default_registry
    from research_harness.domain.transitions import HUMAN_ACTOR
    from research_harness.evidence.conflicts import ConflictKind, ConflictRecord, ConflictStore
    from research_harness.projection.rebuild import rebuild_workspace
    from research_harness.workspace.repository import WorkspaceRepository

    stage_review_queue(root)
    registry = build_default_registry()
    human = Principal.human()

    def call(capability: str, request: dict[str, object]) -> object:
        return registry.invoke(
            capability, open_context(root, HUMAN_ACTOR), request, principal=human
        )

    inbox = call("review.inbox", {})
    dataset = next(item for item in inbox.items if item["field"] == "dataset")  # type: ignore[attr-defined]
    accepted = call("review.accept", {"candidate_id": dataset["candidate_id"]})
    evidence = str(accepted.evidence)  # type: ignore[attr-defined]
    call(
        "claim.create",
        {
            "claim": {
                "statement": "TrafficLM reaches an F1 of 94.32 on CICIDS2017",
                "type": "descriptive",
                "semantics": {
                    "subject": "TrafficLM",
                    "predicate": "reaches",
                    "object": "F1 94.32",
                },
                "scope": {"level": "observed_subset", "corpus": "encrypted traffic classifiers"},
                "assessment": {
                    "requested_strength": "observed_subset",
                    "allowed_strength": "individual",
                },
                "provenance": {"source": "human", "actor": HUMAN_ACTOR},
            }
        },
    )
    call(
        "claim.relate",
        {"claim_id": "C0001", "relation": {"evidence": evidence, "relation": "supports"}},
    )
    call(
        "decision.accept",
        {
            "decision": {
                "type": "methodology",
                "status": "proposed",
                "title": "count only held-out splits",
                "rationale": "the pilot split leaks between train and test",
                "provenance": {"source": "human", "actor": HUMAN_ACTOR},
            }
        },
    )

    repo = WorkspaceRepository.open(root)
    ConflictStore(repo.layout.research_dir).open_or_put(
        ConflictRecord(
            kind=ConflictKind.CANDIDATE_VS_ACCEPTED,
            subject="C0001",
            summary="the staged F1 differs from the accepted reading of Table 1",
        )
    )
    rebuild_workspace(repo)
    DependencyInvalidation().invalidate(repo, [evidence])


def stage_large_corpus(root: Path, works: int) -> None:
    """Fill a fresh workspace with ``works`` works, each with one file and no stored parse.

    The corpus is the one research page whose length nothing bounds: ``work.list`` answers
    the whole corpus in a single read, and the cockpit used to mount every work — with its
    nested file table — at once. Showing that it no longer does needs a corpus well past the
    few hundred works a real project reaches, and it needs to be there in seconds, so this
    writes the smallest thing the list actually renders: a Work, its Version, one Artifact
    and a few placeholder bytes for it, in batched transactions.

    No blocks are stored, which is why every file honestly reads "no parse stored" — the
    same badge a freshly ingested PDF wears before ``work.parse`` runs. Nothing here is
    accepted scientific state: no evidence, no claim and no decision is written.
    """
    from datetime import UTC, datetime, timedelta

    from research_harness.domain import (
        Artifact,
        ArtifactId,
        ArtifactKind,
        Provenance,
        ResearchEvent,
        ResearchEventType,
        ScreeningState,
        Version,
        VersionId,
        VersionKind,
        Work,
        WorkId,
    )
    from research_harness.workspace.repository import WorkspaceRepository

    actor = "system:browser-fixture"
    provenance = Provenance.system(actor=actor)
    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    repo = WorkspaceRepository.open(root)
    batch = 250
    for start in range(0, works, batch):
        size = min(batch, works - start)
        event = ResearchEvent(
            event=ResearchEventType.WORK_INGESTED,
            subjects=(),
            actor=actor,
            occurred_at=epoch + timedelta(seconds=start),
            summary=f"seeded synthetic works {start + 1}..{start + size}",
        )
        with repo.transaction(event, actor=actor) as tx:
            for offset in range(size):
                index = start + offset
                stamp = epoch + timedelta(seconds=index)
                work_id = tx.allocate_id(WorkId)
                version_id = tx.allocate_id(VersionId, work=work_id)
                artifact_id = tx.allocate_id(ArtifactId, work=work_id)
                payload = f"%PDF-1.7 placeholder for {artifact_id}\n".encode()
                tx.put(
                    Work(
                        id=work_id,
                        title=f"Synthetic corpus study {index + 1:04d}",
                        authors=("A. Researcher", "B. Collaborator"),
                        year=2018 + index % 9,
                        venue="Journal of Synthetic Corpora",
                        screening=ScreeningState.INCLUDED,
                        versions=(version_id,),
                        artifacts=(artifact_id,),
                        created_at=stamp,
                        updated_at=stamp,
                        provenance=provenance,
                    )
                )
                tx.put(
                    Version(
                        id=version_id,
                        work=work_id,
                        kind=VersionKind.PREPRINT,
                        label="v1",
                        created_at=stamp,
                        updated_at=stamp,
                        provenance=provenance,
                    )
                )
                artifact = Artifact(
                    id=artifact_id,
                    work=work_id,
                    version=version_id,
                    kind=ArtifactKind.PDF,
                    file_hash=f"sha256:{sha256(payload).hexdigest()}",
                    original_filename=f"{artifact_id}.pdf",
                    mime_type="application/pdf",
                    size_bytes=len(payload),
                    ingested_at=stamp,
                    created_at=stamp,
                    updated_at=stamp,
                    provenance=provenance,
                )
                tx.put(artifact)
                tx.store_artifact_bytes(artifact, payload)


def stage_rollout_project(root: Path) -> None:
    """Fill a fresh workspace with the work the three rolled-out research pages lead with.

    Each of Claims, Questions and Conflicts opens with what needs a researcher, so the
    browser test needs one of each: a Claim asking for more of the scope ladder than its
    evidence allows (Product 42 G's failure state), a Question nobody has answered, and two
    open disagreements — one over a staged candidate, which is decided on the candidate's own
    review screen, and one over the Claim, which is decided on the Claim's page. Everything
    is written through the daemon's own services; nothing here reaches production code.
    """
    from research_harness.capabilities.context import open_context
    from research_harness.capabilities.permissions import Principal
    from research_harness.capabilities.registry import build_default_registry
    from research_harness.domain.transitions import HUMAN_ACTOR
    from research_harness.evidence.conflicts import ConflictKind, ConflictRecord, ConflictStore
    from research_harness.projection.rebuild import rebuild_workspace
    from research_harness.providers.models.cross_verify import ProviderPosition
    from research_harness.workspace.repository import WorkspaceRepository

    stage_review_queue(root)
    registry = build_default_registry()
    human = Principal.human()

    def call(capability: str, request: dict[str, object]) -> object:
        return registry.invoke(
            capability, open_context(root, HUMAN_ACTOR), request, principal=human
        )

    inbox = call("review.inbox", {})
    dataset = next(item for item in inbox.items if item["field"] == "dataset")  # type: ignore[attr-defined]
    metric = next(item for item in inbox.items if item["field"] == "metric_result")  # type: ignore[attr-defined]
    accepted = call("review.accept", {"candidate_id": dataset["candidate_id"]})
    evidence = str(accepted.evidence)  # type: ignore[attr-defined]
    call(
        "claim.create",
        {
            "claim": {
                "statement": "Byte-level tokenization improves recall on encrypted traffic",
                "type": "prevalence",
                "semantics": {
                    "subject": "byte-level tokenization",
                    "predicate": "improves",
                    "object": "recall",
                },
                "scope": {
                    "level": "field_generalization",
                    "corpus": "encrypted traffic classifiers",
                },
                # Asks for L3 on evidence audited at L0: the claim the Claims page leads with.
                "assessment": {
                    "requested_strength": "field_generalization",
                    "allowed_strength": "individual",
                },
                "provenance": {"source": "human", "actor": HUMAN_ACTOR},
            }
        },
    )
    call(
        "claim.relate",
        {"claim_id": "C0001", "relation": {"evidence": evidence, "relation": "supports"}},
    )
    call(
        "question.create",
        {
            "question": {
                "id": "RQ0001",
                "question": "Does byte-level tokenization survive re-encryption?",
                "claims": ["C0001"],
                "remaining_uncertainty": "no capture in the corpus re-encrypts a flow",
                "provenance": {"source": "human", "actor": HUMAN_ACTOR},
            }
        },
    )

    repo = WorkspaceRepository.open(root)
    store = ConflictStore(repo.layout.research_dir)
    store.open_or_put(
        ConflictRecord(
            kind=ConflictKind.CANDIDATE_VS_ACCEPTED,
            subject="C0001",
            summary="the staged F1 differs from the accepted reading of Table 1",
        )
    )
    store.open_or_put(
        ConflictRecord(
            kind=ConflictKind.PROVIDER_DISAGREEMENT,
            subject=str(metric["candidate_id"]),
            summary="two providers read metric_result differently",
            differing_fields=("metric_result",),
            positions=(
                ProviderPosition(
                    provider="scripted",
                    model="model-x",
                    fingerprint="a" * 64,
                    decision={"value": "94.32", "unit": "percent"},
                    rationale="the table reports it as a percentage",
                ),
                ProviderPosition(
                    provider="scripted",
                    model="model-y",
                    fingerprint="b" * 64,
                    decision={"value": "0.9432", "unit": "ratio"},
                    rationale="the caption reports it as a ratio",
                ),
            ),
        )
    )
    rebuild_workspace(repo)


def stage_research_pages(root: Path) -> None:
    """Fill a fresh workspace with what the Stale, Taxonomy and Synthesis pages report.

    Each of those three pages leads with work the daemon composed, so a browser test needs
    a project where that work exists: a classification with a term no Decision approves, a
    matrix that declares a reading nobody has recorded, and real decay under both. All of it
    is written through the daemon's own capabilities.

    Staleness is the one that cannot be asked for and should not be: an object goes stale
    because something it rests on changed. So the projection is rebuilt and the daemon's own
    invalidation hook is run over the Decision that approved the taxonomy — exactly what
    revising that Decision would have done (Product 37, ADR-008).
    """
    from tests.e2e.test_web_gate import FIXTURE

    from research_harness.capabilities.context import open_context
    from research_harness.capabilities.dto import (
        AcceptDecisionRequest,
        PutMatrixRequest,
        PutTaxonomyRequest,
    )
    from research_harness.capabilities.handlers import (
        accept_decision,
        put_matrix,
        put_taxonomy,
    )
    from research_harness.capabilities.invalidation import DependencyInvalidation
    from research_harness.capabilities.permissions import Principal
    from research_harness.capabilities.registry import build_default_registry
    from research_harness.domain.base import Provenance
    from research_harness.domain.enums import DecisionStatus, DecisionType, StaleState
    from research_harness.domain.ids import DecisionId, SynthesisId, WorkId
    from research_harness.domain.research import (
        Decision,
        MatrixCell,
        SynthesisMatrix,
        Taxonomy,
        TaxonomyTerm,
    )
    from research_harness.domain.transitions import HUMAN_ACTOR
    from research_harness.projection.rebuild import rebuild_workspace
    from research_harness.workspace.repository import WorkspaceRepository

    registry = build_default_registry()
    registry.invoke(
        "corpus.ingest",
        open_context(root, HUMAN_ACTOR),
        {"path": str(FIXTURE)},
        principal=Principal.human(),
    )
    human = Provenance.human(HUMAN_ACTOR)
    approval = Decision(
        id=DecisionId("D0001"),
        type=DecisionType.TAXONOMY_REVISION,
        rationale="separate padded flows from unpadded ones",
        taxonomy_terms=("padded",),
        provenance=human,
    )
    ctx = open_context(root, HUMAN_ACTOR)
    accept_decision(ctx, AcceptDecisionRequest(decision=approval))
    put_taxonomy(
        ctx,
        PutTaxonomyRequest(
            taxonomy=Taxonomy(
                name="traffic-shape",
                terms=(
                    TaxonomyTerm(
                        term="padded",
                        definition="a flow whose records are padded to a fixed size",
                        decision=approval.id,
                    ),
                    TaxonomyTerm(term="padded_fixed", parent="padded"),
                ),
                provenance=human,
            ),
            decision=approval.touch(status=DecisionStatus.ACCEPTED),
        ),
    )
    put_matrix(
        ctx,
        PutMatrixRequest(
            matrix=SynthesisMatrix(
                id=SynthesisId("S0001"),
                name="Traffic shape",
                taxonomy="traffic-shape",
                works=(WorkId("W0001"),),
                fields=("tokenization", "dataset"),
                cells=(MatrixCell(work=WorkId("W0001"), field="tokenization", labels=("padded",)),),
                stale=StaleState.FRESH,
                provenance=human,
            )
        ),
    )
    repo = WorkspaceRepository.open(root)
    rebuild_workspace(repo)
    DependencyInvalidation().invalidate(repo, [str(approval.id)])


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    bundle = root / "web/dist"
    if not (bundle / "index.html").is_file():
        raise SystemExit("Build the frontend first: pnpm run build")
    os.environ["RESEARCH_HARNESS_WEB_DIST"] = str(bundle)
    # The staging fixtures live in `tests/`, which is not an installed package.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    port = int(os.environ.get("TASK_BROWSER_PORT", "8877"))
    with TemporaryDirectory(prefix="research-browser-") as scratch:
        directory = Path(scratch)
        nonces = BootstrapStore()
        backend = create_multi_project_app(
            directory / "app", port=port, bootstraps=nonces, picker=ManualFolderPicker()
        )
        # Test-only outer app. No test endpoints or auth bypass enter production code.
        app = FastAPI()
        seeded = itertools.count(1)

        @app.get("/__test__/bootstrap")
        def bootstrap() -> dict[str, str]:
            return {"nonce": nonces.issue(), "parent": str(directory)}

        @app.post("/__test__/review-queue")
        def review_queue() -> dict[str, str]:
            """A registered project with candidates already waiting in its review queue.

            Its review policy is `policy_batch`, because the batch of Product 24.4 is a
            named exception a researcher declares and the browser test has to be able to
            see one. Each call builds its own project, so the two viewport runs never share
            a queue.
            """
            manager: ProjectManager = backend.state.manager
            name = f"Review queue {next(seeded)}"
            view = manager.create(directory, name, ReviewPolicy.POLICY_BATCH)
            stage_review_queue(Path(view.path))
            return {
                "project_id": view.project_id,
                "name": name,
                "review_url": f"/projects/{view.project_id}/review",
            }

        @app.post("/__test__/session-with-turn")
        def session_with_turn() -> dict[str, str]:
            """A registered project holding one session with a question and an answer.

            The transcript's own row — its reference chips, its toolbar and the overflow
            behind *More actions* — cannot be photographed without one, and no capability
            reachable from the browser can write an assistant turn without a model provider.
            Each call builds its own project, so the two viewport runs never share a session.
            """
            manager: ProjectManager = backend.state.manager
            name = f"Transcript {next(seeded)}"
            view = manager.create(directory, name, ReviewPolicy.STRICT)
            session = stage_conversation(Path(view.path))
            return {
                "project_id": view.project_id,
                "name": name,
                "session_id": session,
                "conversation_url": f"/projects/{view.project_id}/?session={session}",
            }

        @app.post("/__test__/overview-project")
        def overview_project() -> dict[str, str]:
            """A registered project the Overview has something to say about in every group.

            Each call builds its own project, so the two viewport runs never share one.
            """
            manager: ProjectManager = backend.state.manager
            name = f"Overview study {next(seeded)}"
            view = manager.create(directory, name, ReviewPolicy.STRICT)
            stage_overview_project(Path(view.path))
            return {
                "project_id": view.project_id,
                "name": name,
                "overview_url": f"/projects/{view.project_id}/overview",
            }

        large: dict[int, dict[str, str]] = {}
        large_lock = Lock()

        @app.post("/__test__/large-corpus")
        def large_corpus(works: int = 1000) -> dict[str, str]:
            """A registered project whose corpus is far longer than any screen.

            The corpus page is the list that grows without a bound the daemon imposes, so
            the browser test needs a corpus it could never have rendered a card at a time.

            Unlike the review queue this project is shared between callers of the same size:
            a thousand works is a minute of durable writes, and the corpus screen only ever
            reads it, so building one per viewport would double the cost of the run to prove
            nothing. The lock is because FastAPI runs a plain `def` handler on a threadpool
            and the two viewport runs arrive together.
            """
            with large_lock:
                existing = large.get(works)
                if existing is not None:
                    return existing
                manager: ProjectManager = backend.state.manager
                name = f"Large corpus {next(seeded)}"
                view = manager.create(directory, name, ReviewPolicy.STRICT)
                stage_large_corpus(Path(view.path), works)
                answer = {
                    "project_id": view.project_id,
                    "name": name,
                    "works": str(works),
                    "corpus_url": f"/projects/{view.project_id}/corpus",
                }
                large[works] = answer
                return answer

        @app.post("/__test__/rollout-project")
        def rollout_project() -> dict[str, str]:
            """A project the Claims, Questions and Conflicts pages all have work to show.

            Each call builds its own project, so the two viewport runs never share one.
            """
            manager: ProjectManager = backend.state.manager
            name = f"Rollout study {next(seeded)}"
            view = manager.create(directory, name, ReviewPolicy.STRICT)
            stage_rollout_project(Path(view.path))
            return {
                "project_id": view.project_id,
                "name": name,
                "workspace_url": f"/projects/{view.project_id}",
            }

        @app.post("/__test__/research-pages")
        def research_pages() -> dict[str, str]:
            """A project the Stale, Taxonomy and Synthesis pages each have work to report.

            Each call builds its own project, so the two viewport runs never share one.
            """
            manager: ProjectManager = backend.state.manager
            name = f"Research pages {next(seeded)}"
            view = manager.create(directory, name, ReviewPolicy.STRICT)
            stage_research_pages(Path(view.path))
            return {
                "project_id": view.project_id,
                "name": name,
                "workspace_url": f"/projects/{view.project_id}",
            }

        app.mount("/", backend)
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()

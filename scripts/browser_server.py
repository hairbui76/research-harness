"""Serve the production bundle and real backend over disposable browser-test data."""

from __future__ import annotations

import itertools
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

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

        app.mount("/", backend)
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()

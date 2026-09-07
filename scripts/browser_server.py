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

        app.mount("/", backend)
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()

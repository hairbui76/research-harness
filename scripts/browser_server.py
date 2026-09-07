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

        app.mount("/", backend)
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()

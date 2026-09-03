"""Gate P19: research attachments, end to end, through the CLI and the capabilities.

The five things the gate asks for, in the order ROADMAP Phase 19 states them:

1. attach and preview an image and a PDF **without corpus mutation**;
2. send them to a compatible model and inspect both in `Context used`;
3. choose an incompatible model, have the send blocked, and lose neither the attachments
   nor their states;
4. promote a PDF through identity resolution onto an existing Work as a new Version and
   Artifact;
5. save the same bytes again and resolve to the existing Artifact — and recover cleanly
   from a promotion that fails half-way.

Every write goes through `research attachment ...`, which goes through the `attachment.*`
capabilities; the send is assembled with the same `sendability` / `receipt_items` helpers
`session.send` calls, against a scripted provider that records what it was actually given.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import typer
import yaml
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.cli.commands import attachment as attachment_commands
from research_harness.cli.commands import init as init_commands
from research_harness.conversation.attachments import (
    AttachmentService,
    SendDisposition,
    attachment_link,
    receipt_items,
    sendability,
)
from research_harness.domain.base import Provenance
from research_harness.domain.conversation import (
    AttachmentState,
    ContextClass,
    ContextReceipt,
    OmissionReason,
)
from research_harness.domain.ids import SessionAttachmentId
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.providers.models import InputEnvelope, ModelRequest, ModelRequirements
from research_harness.providers.models.scripted import (
    ScriptedProvider,
    default_scripted_capabilities,
)
from research_harness.workspace.conversations import ConversationStore
from tests.fixtures.attachments import TINY_PNG, png_bytes

runner = CliRunner()

PAPER = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_research_paper.pdf"
#: Appended after `%%EOF`: the file still opens, its bytes differ, its identity does not.
REVISION_SUFFIX = b"\n%revision\n"

#: A configured model that reads text and cannot see. The gate's "incompatible model".
BLIND_PROVIDER = {
    "name": "local-text",
    "kind": "local_openai_compatible",
    "model": "text-1",
    "base_url": "http://127.0.0.1:11434/v1",
    "priority": 10,
}


@pytest.fixture
def cli() -> typer.Typer:
    """A `research` app with the families this gate drives."""
    app = typer.Typer(name="research", no_args_is_help=True, add_completion=False)
    for module in (init_commands, attachment_commands):
        module.register(app)
    return app


def run(app: typer.Typer, *args: str) -> Result:
    result = runner.invoke(app, list(args))
    if result.exit_code != 0:  # pragma: no cover - surfaced only when the gate breaks
        raise AssertionError(f"`research {' '.join(args)}` failed: {result.output}")
    return result


def payload(result: Result) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(result.stdout)
    return body


def corpus_digest(root: Path) -> str:
    """Every canonical file under `corpus/`, path and bytes, in one digest."""
    digest = hashlib.sha256()
    for path in sorted((root / "corpus").rglob("*")):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def canonical_digest(root: Path) -> str:
    """The whole canonical tree — corpus, claims, questions, evidence, events."""
    digest = hashlib.sha256()
    for name in ("corpus", "claims", "questions", "decisions", "matrices", "notes", "events"):
        for path in sorted((root / name).rglob("*")):
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            if path.is_file():
                digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture
def workspace(cli: typer.Typer, tmp_path: Path) -> Path:
    """A workspace with one blind model configured and one open session."""
    root = tmp_path / "project"
    run(cli, "init", str(root), "--name", "gate-p19")
    config_path = root / "research.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["providers"] = [BLIND_PROVIDER]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return root


@pytest.fixture
def project(workspace: Path) -> CapabilityContext:
    return open_context(workspace, HUMAN_ACTOR)


@pytest.fixture
def session(project: CapabilityContext) -> str:
    store = ConversationStore.for_repository(project.repo)
    return str(store.create_session(title="reading", provenance=Provenance.human()).id)


@pytest.fixture
def service(project: CapabilityContext) -> AttachmentService:
    return AttachmentService(ConversationStore.for_repository(project.repo))


@pytest.fixture
def revision(tmp_path: Path) -> Path:
    """The same paper with different bytes: a new Version, never a new Work."""
    path = tmp_path / "paper-v2.pdf"
    path.write_bytes(PAPER.read_bytes() + REVISION_SUFFIX)
    return path


# -- 1. attach and preview, with no corpus mutation --------------------------


def test_attaching_an_image_and_a_pdf_changes_no_canonical_state(
    cli: typer.Typer, workspace: Path, session: str, service: AttachmentService
) -> None:
    before_corpus = corpus_digest(workspace)
    before_canonical = canonical_digest(workspace)

    image = payload(
        run(cli, "attachment", "add", session, str(TINY_PNG), "-w", str(workspace), "--json")
    )
    document = payload(
        run(cli, "attachment", "add", session, str(PAPER), "-w", str(workspace), "--json")
    )
    listed = payload(run(cli, "attachment", "list", session, "-w", str(workspace), "--json"))

    assert (image["id"], image["state"], image["media_type"]) == ("SA0001", "ready", "image/png")
    assert (document["id"], document["state"]) == ("SA0002", "ready")
    assert document["page_count"] >= 1
    assert [item["id"] for item in listed["attachments"]] == ["SA0001", "SA0002"]
    assert all(item["artifact"] is None for item in listed["attachments"])

    # Both preview, and both previews are projections under `.research/`.
    records = service.list_attachments(records_session(service, session))
    for record in records:
        rendered = service.preview(record)
        assert rendered.read_bytes().startswith(b"\x89PNG")
        assert service.store.layout.is_regenerable(rendered)

    assert corpus_digest(workspace) == before_corpus
    assert canonical_digest(workspace) == before_canonical
    assert list((workspace / "corpus" / "works").iterdir()) == []


def records_session(service: AttachmentService, session: str) -> Any:
    """The session id as the store types it."""
    return next(item.id for item in service.store.list_sessions() if str(item.id) == session)


# -- 2. send with a compatible model, and read the receipt -------------------


def test_a_compatible_model_receives_both_attachments_and_the_receipt_says_so(
    cli: typer.Typer, workspace: Path, session: str, service: AttachmentService
) -> None:
    """Gate P19: send with a compatible model and inspect both in `Context used`."""
    from pydantic import BaseModel

    class Summary(BaseModel):
        summary: str

    run(cli, "attachment", "add", session, str(TINY_PNG), "-w", str(workspace), "--json")
    run(cli, "attachment", "add", session, str(PAPER), "-w", str(workspace), "--json")
    session_id = records_session(service, session)
    attachments = service.sendable(session_id)

    vision = default_scripted_capabilities(input_media={"image/png", "application/pdf"})
    check = sendability(
        attachments,
        provider="scripted",
        model="scripted-vision",
        capabilities=vision,
    )
    provider = ScriptedProvider([Summary(summary="a figure and a paper")], capabilities=vision)
    provider.complete(
        ModelRequest(
            role="conversation",
            requirements=ModelRequirements(
                context_tokens=100_000,
                reasoning="low",
                input_media=frozenset({"image/png", "application/pdf"}),
            ),
            instructions="Answer using the attachments.",
            inputs=[
                InputEnvelope(kind="message", content="what do these show?"),
                *service.inputs(session_id, check),
            ],
            response_schema=Summary,
        )
    )

    included, omitted = receipt_items(check)
    receipt = ContextReceipt(included=included, omitted=omitted)

    assert check.ok is True
    assert [item.disposition for item in check.items] == [
        SendDisposition.SENT,
        SendDisposition.SENT,
    ]
    # Each attachment reached the model exactly once, as bytes.
    assert [part.filename for part in provider.media] == [
        "tiny.png",
        "synthetic_research_paper.pdf",
    ]
    assert provider.media[0].data == png_bytes()
    # And the receipt names both of them, as attachments, with nothing omitted.
    assert [item.source for item in receipt.included] == [
        attachment_link(SessionAttachmentId("SA0001")),
        attachment_link(SessionAttachmentId("SA0002")),
    ]
    assert all(item.context_class is ContextClass.ATTACHMENTS for item in receipt.included)
    assert all("sent" in str(item.label) for item in receipt.included)
    assert receipt.omitted == ()


# -- 3. an incompatible model blocks the send and loses nothing --------------


def test_an_incompatible_model_blocks_the_send_and_leaves_every_attachment_intact(
    cli: typer.Typer, workspace: Path, session: str, service: AttachmentService
) -> None:
    """Gate P19: block an incompatible send without losing the draft."""
    run(cli, "attachment", "add", session, str(TINY_PNG), "-w", str(workspace), "--json")
    run(cli, "attachment", "add", session, str(PAPER), "-w", str(workspace), "--json")
    session_id = records_session(service, session)
    before = service.list_attachments(session_id)

    result = payload(run(cli, "attachment", "check", session, "-w", str(workspace), "--json"))

    assert result["ok"] is False
    assert result["model"] == "text-1"
    assert [item["disposition"] for item in result["items"]] == ["omitted", "omitted"]
    assert all(item["omission"] == "unsupported_media" for item in result["items"])
    assert "cannot be sent" in result["refusal"]
    # Nothing was consumed by the refusal: same ids, same states, same bytes.
    after = service.list_attachments(session_id)
    assert [(item.id, item.state) for item in after] == [(item.id, item.state) for item in before]
    assert all(item.state is AttachmentState.READY for item in after)
    assert service.store.read_attachment_bytes(after[0]) == png_bytes()


def test_a_blocked_item_names_a_model_that_would_take_it_when_one_is_configured(
    cli: typer.Typer, workspace: Path, session: str, service: AttachmentService
) -> None:
    config_path = workspace / "research.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["providers"] = [
        BLIND_PROVIDER,
        {
            **BLIND_PROVIDER,
            "name": "local-vision",
            "model": "vision-1",
            "priority": 20,
            "capabilities": {"vision": True},
        },
    ]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    run(cli, "attachment", "add", session, str(TINY_PNG), "-w", str(workspace), "--json")

    result = payload(run(cli, "attachment", "check", session, "-w", str(workspace), "--json"))

    assert result["ok"] is False
    assert result["items"][0]["suggested_model"] == "local-vision/vision-1"


# -- 4 and 5. promotion, duplication, and recovery ---------------------------


def test_a_pdf_is_promoted_through_identity_resolution_and_the_same_bytes_deduplicate(
    cli: typer.Typer,
    workspace: Path,
    session: str,
    project: CapabilityContext,
    revision: Path,
) -> None:
    """Gate P19: promote a PDF through identity resolution; save the same bytes again."""
    run(cli, "attachment", "add", session, str(PAPER), "-w", str(workspace), "--json")
    run(cli, "attachment", "add", session, str(revision), "-w", str(workspace), "--json")
    run(cli, "attachment", "add", session, str(PAPER), "-w", str(workspace), "--json")

    new_work = payload(
        run(cli, "attachment", "resolve", session, "SA0001", "-w", str(workspace), "--json")
    )
    first = payload(
        run(cli, "attachment", "save", session, "SA0001", "-w", str(workspace), "--json")
    )
    same_work = payload(
        run(cli, "attachment", "resolve", session, "SA0002", "-w", str(workspace), "--json")
    )
    second = payload(
        run(cli, "attachment", "save", session, "SA0002", "-w", str(workspace), "--json")
    )
    duplicate = payload(
        run(cli, "attachment", "resolve", session, "SA0003", "-w", str(workspace), "--json")
    )
    third = payload(
        run(cli, "attachment", "save", session, "SA0003", "-w", str(workspace), "--json")
    )

    assert new_work["choice"] == "new_work"
    assert first["created"] == "work"
    assert first["parsed"] is True

    # The revision is the same Work, a new Version and a new Artifact.
    assert same_work["choice"] == "existing_work"
    assert same_work["work"] == first["work"]
    assert second["created"] == "version"
    assert second["work"] == first["work"]
    assert (second["version"], second["artifact"]) != (first["version"], first["artifact"])

    # The same bytes resolve to the Artifact that already holds them; nothing is copied.
    assert duplicate["choice"] == "existing_artifact"
    assert third["created"] == "nothing"
    assert third["artifact"] == first["artifact"]
    assert third["linked_existing"] is True

    reopened = open_context(workspace, HUMAN_ACTOR)
    assert [str(work.id) for work in reopened.repo.list_works()] == [first["work"]]
    assert len(reopened.repo.list_artifacts(reopened.repo.list_works()[0].id)) == 2

    # And nothing scientific was accepted by any of it (attachments design SS7).
    assert third["evidence_created"] is False
    assert not any(
        path.read_text(encoding="utf-8").strip()
        for path in (workspace / "corpus").rglob("evidence.jsonl")
    )
    assert list((workspace / "claims").iterdir()) == []


def test_a_failed_promotion_keeps_the_session_copy_and_retries_cleanly(
    cli: typer.Typer,
    workspace: Path,
    session: str,
    project: CapabilityContext,
    service: AttachmentService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate P19: recover cleanly from a failed promotion."""
    import research_harness.conversation.promotion_corpus as promotion_module

    run(cli, "attachment", "add", session, str(PAPER), "-w", str(workspace), "--json")
    session_id = records_session(service, session)
    original = service.store.read_attachment_bytes(
        service.get(session_id, SessionAttachmentId("SA0001"))
    )

    class BrokenIngest(promotion_module.IngestService):
        def ingest_local_pdf(self, path: Path | str, **kwargs: object) -> Any:
            raise RuntimeError("the corpus write failed half-way")

    monkeypatch.setattr(promotion_module, "IngestService", BrokenIngest)
    failed = runner.invoke(
        cli, ["attachment", "save", session, "SA0001", "-w", str(workspace), "--json"]
    )
    monkeypatch.undo()

    assert failed.exit_code != 0
    record = service.get(session_id, SessionAttachmentId("SA0001"))
    assert record.state is AttachmentState.FAILED
    assert "save to corpus failed" in str(record.failure_reason)
    assert service.store.read_attachment_bytes(record) == original
    assert list((workspace / "corpus" / "works").iterdir()) == []

    recovered = payload(
        run(cli, "attachment", "save", session, "SA0001", "-w", str(workspace), "--json")
    )

    assert recovered["created"] == "work"
    assert recovered["attachment"]["state"] == "in_corpus"
    assert recovered["attachment"]["artifact"] == recovered["artifact"]


# -- the boundary, once more, from the outside -------------------------------


def test_an_unsupported_file_stays_visible_with_a_reason_and_never_blocks_the_others(
    cli: typer.Typer, workspace: Path, session: str, tmp_path: Path
) -> None:
    """Attachments design SS2, SS4: a failure explains itself and costs nothing else."""
    archive = tmp_path / "code.zip"
    archive.write_bytes(b"PK\x03\x04not really an archive")

    run(cli, "attachment", "add", session, str(TINY_PNG), "-w", str(workspace), "--json")
    refused = payload(
        run(cli, "attachment", "add", session, str(archive), "-w", str(workspace), "--json")
    )
    listed = payload(run(cli, "attachment", "list", session, "-w", str(workspace), "--json"))

    assert refused["state"] == "failed"
    assert "not a supported attachment type" in refused["failure_reason"]
    assert [item["state"] for item in listed["attachments"]] == ["ready", "failed"]

    check = payload(run(cli, "attachment", "check", session, "-w", str(workspace), "--json"))
    failed_item = next(item for item in check["items"] if item["attachment"] == "SA0002")
    assert failed_item["ok"] is True  # it was never ready, so it blocks nothing
    assert failed_item["omission"] == OmissionReason.UNSUPPORTED_MEDIA.value

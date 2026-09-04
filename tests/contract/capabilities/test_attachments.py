"""The `attachment.*` capabilities and the three attachment routes, as a host sees them.

Two contracts are checked here. The **capability** contract: five named capabilities with
the permissions the product assigns them — a host may ask what would happen and may not
attach or promote anything — answering with closed, typed models. And the **route**
contract: the one documented non-capability write is authorised exactly as
`attachment.add` is, and the two byte reads serve the stored bytes inertly, never as
something a browser will render or run (attachments design SS8, v1.1 plan SS0.4).
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from research_harness.capabilities.attachments import (
    AddAttachmentRequest,
    AttachmentSendCheck,
    AttachmentView,
    CheckAttachmentSendRequest,
    RemoveAttachmentRequest,
    ResolveAttachmentIdentityRequest,
    SaveAttachmentToCorpusRequest,
    add_attachment,
    check_attachment_send,
    remove_attachment,
    resolve_attachment_identity,
    save_attachment_to_corpus,
)
from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.permissions import Permission
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.conversation.service import ConversationService
from research_harness.domain.base import Provenance
from research_harness.domain.conversation import ConversationSession, Visibility
from research_harness.domain.errors import CapabilityError
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.server.app import create_app, ensure_token
from research_harness.workspace.conversations import ConversationStore
from tests.fixtures.attachments import TINY_PDF, TINY_PNG, pdf_bytes, png_bytes
from tests.fixtures.cli.fakes import FakeCli

ATTACHMENT_CAPABILITIES = (
    "attachment.add",
    "attachment.remove",
    "attachment.check_send",
    "attachment.resolve_identity",
    "attachment.save_to_corpus",
)

HUMAN = Provenance.human()

#: A provider table a fresh workspace does not have. `check_send` reads it without opening
#: a client or resolving a key, which is what lets the check answer with no credentials.
PROVIDERS = [
    {
        "name": "local-vision",
        "kind": "local_openai_compatible",
        "model": "vision-1",
        "base_url": "http://127.0.0.1:11434/v1",
        "priority": 10,
        "capabilities": {"vision": True},
    },
    {
        "name": "local-text",
        "kind": "local_openai_compatible",
        "model": "text-1",
        "base_url": "http://127.0.0.1:11434/v1",
        "priority": 20,
    },
]


@pytest.fixture
def registry() -> CapabilityRegistry:
    return build_default_registry()


@pytest.fixture
def store(project: CapabilityContext) -> ConversationStore:
    return ConversationStore.for_repository(project.repo)


@pytest.fixture
def session(store: ConversationStore) -> ConversationSession:
    return store.create_session(title="reading", provenance=HUMAN)


@pytest.fixture
def attached(
    project: CapabilityContext, session: ConversationSession
) -> tuple[AttachmentView, AttachmentView]:
    """One image and one PDF, attached through the capability."""
    image = add_attachment(
        project, AddAttachmentRequest(session=session.id, path=TINY_PNG, filename="figure.png")
    )
    document = add_attachment(
        project, AddAttachmentRequest(session=session.id, path=TINY_PDF, filename="paper.pdf")
    )
    return image, document


@pytest.fixture
def client(project: CapabilityContext, session: ConversationSession) -> Iterator[TestClient]:
    """The daemon over this workspace, as the local researcher."""
    token = ensure_token(project.root)
    with TestClient(create_app(project.root)) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {token}"})
        yield test_client


@pytest.fixture
def host_client(project: CapabilityContext, session: ConversationSession) -> Iterator[TestClient]:
    """The daemon over this workspace, as an agent host with no token."""
    ensure_token(project.root)
    with TestClient(create_app(project.root)) as test_client:
        yield test_client


def with_providers(project: CapabilityContext) -> CapabilityContext:
    """Give the workspace a provider table, written into `research.yaml` as a user would.

    Nothing is constructed and no key is read: `check_send` answers from the declared
    capabilities of each entry, which is what lets it work with no credentials present.
    """
    path = project.root / "research.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["providers"] = PROVIDERS
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return open_context(project.root, HUMAN_ACTOR)


# -- the capability contract -------------------------------------------------


def test_the_five_capabilities_are_registered_with_the_permissions_they_deserve(
    registry: CapabilityRegistry,
) -> None:
    """A host reads the checks and asks a person to attach or promote (Product 24, 29)."""
    permissions = {name: registry.get(name).permission for name in ATTACHMENT_CAPABILITIES}

    assert permissions == {
        "attachment.add": Permission.MUTATE,
        "attachment.remove": Permission.MUTATE,
        "attachment.check_send": Permission.READ,
        "attachment.resolve_identity": Permission.READ,
        "attachment.save_to_corpus": Permission.MUTATE,
    }
    assert registry.get("attachment.save_to_corpus").human_only is True
    for name in ATTACHMENT_CAPABILITIES:
        descriptor = registry.get(name).descriptor()
        assert descriptor.summary and descriptor.scientific_semantics
        assert descriptor.request_schema["type"] == "object"


def test_attaching_a_file_reports_the_session_only_record(
    project: CapabilityContext, session: ConversationSession
) -> None:
    view = add_attachment(
        project,
        AddAttachmentRequest(
            session=session.id, path=TINY_PDF, filename="paper.pdf", description="the preprint"
        ),
    )

    assert view.id == "SA0001"
    assert (view.state, view.media_type, view.page_count) == ("ready", "application/pdf", 2)
    assert view.description == "the preprint"
    assert (view.work, view.version, view.artifact) == (None, None, None)


def test_bytes_can_arrive_as_base64_for_a_host_that_has_no_local_path(
    project: CapabilityContext, session: ConversationSession
) -> None:
    view = add_attachment(
        project,
        AddAttachmentRequest(
            session=session.id,
            data_base64=base64.b64encode(png_bytes()).decode("ascii"),
            filename="figure.png",
        ),
    )

    assert view.state == "ready"
    assert view.size_bytes == len(png_bytes())


def test_a_request_must_carry_exactly_one_source_of_bytes() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        AddAttachmentRequest(session="CS0001", path=Path("a.png"), data_base64="AAA=")
    with pytest.raises(ValueError, match="exactly one"):
        AddAttachmentRequest(session="CS0001")
    with pytest.raises(ValueError, match="needs a `filename`"):
        AddAttachmentRequest(session="CS0001", data_base64="AAA=")


def test_the_send_check_answers_per_item_against_the_configured_models(
    project: CapabilityContext,
    session: ConversationSession,
    attached: tuple[AttachmentView, AttachmentView],
) -> None:
    configured = with_providers(project)

    sighted = check_attachment_send(configured, CheckAttachmentSendRequest(session=session.id))
    blind = check_attachment_send(
        configured, CheckAttachmentSendRequest(session=session.id, provider="local-text")
    )

    assert isinstance(sighted, AttachmentSendCheck)
    assert sighted.model == "vision-1"
    assert [item.disposition for item in sighted.items] == ["sent", "omitted"]
    assert sighted.ok is False  # the PDF: a vision override does not add document input
    assert blind.ok is False
    assert next(item.suggested_model for item in blind.items) == "local-vision/vision-1"


def test_the_send_check_answers_for_a_session_bound_to_a_runtime(
    project: CapabilityContext, codex: FakeCli
) -> None:
    """A bound session has a target even with an empty `providers:` table (binding spec §9).

    The check must resolve it the way the send does, or a bound composer is told there is
    no configured model for a send that would in fact go through.
    """
    store = ConversationStore.for_repository(project.repo)
    bound = store.create_session(title="reading", provenance=HUMAN, visibility=Visibility.PROJECT)
    add_attachment(
        project, AddAttachmentRequest(session=bound.id, path=TINY_PDF, filename="paper.pdf")
    )
    ConversationService(project).configure(bound.id, runtime="codex", model="gpt-5.5")

    check = check_attachment_send(project, CheckAttachmentSendRequest(session=bound.id))

    assert (check.provider, check.model) == ("session:codex", "gpt-5.5")
    assert len(check.items) == 1, "the check answers, rather than refusing for want of a table"
    assert codex.runs() == [], "a check spawns nothing"


def test_the_send_check_says_so_when_no_model_is_configured(
    project: CapabilityContext,
    session: ConversationSession,
    attached: tuple[AttachmentView, AttachmentView],
) -> None:
    """dogfood F17: "nothing is configured" is an answer, not an empty table."""
    with pytest.raises(CapabilityError, match="no model providers configured"):
        check_attachment_send(project, CheckAttachmentSendRequest(session=session.id))


def test_resolve_and_save_report_the_identity_and_the_boundary(
    project: CapabilityContext,
    session: ConversationSession,
    attached: tuple[AttachmentView, AttachmentView],
) -> None:
    _, document = attached
    request = ResolveAttachmentIdentityRequest(
        session=session.id,
        attachment=document.id,  # type: ignore[arg-type]
    )

    identity = resolve_attachment_identity(project, request)
    promotion = save_attachment_to_corpus(
        project,
        SaveAttachmentToCorpusRequest(
            session=session.id,
            attachment=document.id,  # type: ignore[arg-type]
        ),
    )

    assert identity.choice == "new_work"
    assert identity.content_hash == document.content_hash
    assert promotion.created == "work"
    assert promotion.evidence_created is False
    assert promotion.attachment.state == "in_corpus"
    assert promotion.attachment.artifact == promotion.artifact
    assert promotion.mutation is not None
    assert promotion.mutation.capability == "work.register"


def test_removing_an_attachment_reports_what_it_deleted(
    project: CapabilityContext,
    session: ConversationSession,
    attached: tuple[AttachmentView, AttachmentView],
) -> None:
    image, _ = attached

    result = remove_attachment(
        project,
        RemoveAttachmentRequest(
            session=session.id,
            attachment=image.id,  # type: ignore[arg-type]
        ),
    )

    assert (result.attachment, result.removed) == ("SA0001", True)


# -- the route contract ------------------------------------------------------


def test_the_byte_route_writes_a_session_attachment_and_returns_its_view(
    client: TestClient, session: ConversationSession
) -> None:
    response = client.post(
        f"/sessions/{session.id}/attachments?filename=figure.png",
        content=png_bytes(),
        headers={"Content-Type": "image/png"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["id"] == "SA0001"
    assert body["state"] == "ready"
    assert body["media_type"] == "image/png"
    assert body["work"] is None


def test_the_byte_route_is_authorised_exactly_as_the_capability_is(
    host_client: TestClient, session: ConversationSession
) -> None:
    """A host that may not call `attachment.add` may not POST bytes either."""
    response = host_client.post(
        f"/sessions/{session.id}/attachments?filename=figure.png",
        content=png_bytes(),
        headers={"Content-Type": "image/png"},
    )

    assert response.status_code == 403


def test_the_route_keeps_a_filename_as_metadata_and_refuses_an_empty_body(
    client: TestClient, session: ConversationSession
) -> None:
    traversal = client.post(
        f"/sessions/{session.id}/attachments?filename=../../etc/passwd.png",
        content=png_bytes(),
        headers={"Content-Type": "image/png"},
    )
    empty = client.post(
        f"/sessions/{session.id}/attachments?filename=empty.png",
        content=b"",
        headers={"Content-Type": "image/png"},
    )

    assert traversal.json()["filename"] == "passwd.png"
    assert empty.status_code == 400


def test_an_unknown_session_is_a_404_rather_than_a_new_directory(client: TestClient) -> None:
    missing = client.post(
        "/sessions/CS0404/attachments?filename=figure.png",
        content=png_bytes(),
        headers={"Content-Type": "image/png"},
    )
    malformed = client.post(
        "/sessions/not-an-id/attachments?filename=figure.png",
        content=png_bytes(),
        headers={"Content-Type": "image/png"},
    )

    assert missing.status_code == 404
    assert malformed.status_code == 404


def test_the_bytes_route_serves_the_original_inertly(
    client: TestClient, session: ConversationSession
) -> None:
    """Attachments design SS8: a preview or download never executes what a file contains."""
    client.post(
        f"/sessions/{session.id}/attachments?filename=paper.pdf",
        content=pdf_bytes(),
        headers={"Content-Type": "application/pdf"},
    )

    response = client.get(f"/sessions/{session.id}/attachments/SA0001/bytes")

    assert response.status_code == 200
    assert response.content == pdf_bytes()
    assert response.headers["content-type"] == "application/pdf"
    assert "inline" in response.headers["content-disposition"]
    assert "paper.pdf" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_the_preview_route_renders_a_png_for_each_page(
    client: TestClient, session: ConversationSession
) -> None:
    client.post(
        f"/sessions/{session.id}/attachments?filename=paper.pdf",
        content=pdf_bytes(),
        headers={"Content-Type": "application/pdf"},
    )

    page_two = client.get(f"/sessions/{session.id}/attachments/SA0001/preview?page=2")
    missing = client.get(f"/sessions/{session.id}/attachments/SA0001/preview?page=7")
    unknown = client.get(f"/sessions/{session.id}/attachments/SA0404/preview")

    assert page_two.status_code == 200
    assert page_two.headers["content-type"] == "image/png"
    assert page_two.content.startswith(b"\x89PNG")
    assert missing.status_code == 404
    assert unknown.status_code == 404


def test_a_host_may_read_attachment_bytes_it_may_not_write(
    client: TestClient, host_client: TestClient, session: ConversationSession
) -> None:
    client.post(
        f"/sessions/{session.id}/attachments?filename=figure.png",
        content=png_bytes(),
        headers={"Content-Type": "image/png"},
    )

    response = host_client.get(f"/sessions/{session.id}/attachments/SA0001/bytes")

    assert response.status_code == 200
    assert response.content == png_bytes()

"""The Phase 21 capability contract: what each name does, and who may call it.

The registry is the enforcement point (ADR-004), so this file asks it directly rather than
through a transport: the same refusals have to hold whether the caller arrived over HTTP,
over MCP, or through the CLI, and asking one transport would only prove that transport.

The property with the most weight is the last section. An agent host may list the
manuscript, open a file, read a build, and propose a candidate diff; it may not save a
file, start a compiler, or apply its own suggestion. Source ownership is the researcher's
(LaTeX spec 4), and it is enforced here rather than in a client.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.manuscript_workspace import (
    MANUSCRIPT_WORKSPACE_CAPABILITIES,
)
from research_harness.capabilities.permissions import (
    Permission,
    PermissionDenied,
    Principal,
)
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.domain.errors import CapabilityError
from research_harness.manuscript.compile import CompileStatus
from research_harness.workspace.repository import WorkspaceRepository
from tests.fixtures.latex import copy_project, install_fake_engine

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="the fake engine is a POSIX executable script"
)

HUMAN = "human:alice"

#: A request every capability can answer against a fresh manuscript workspace.
REQUESTS: dict[str, dict[str, object]] = {
    "manuscript.files": {},
    "manuscript.read_file": {"path": "main.tex"},
    "manuscript.build": {},
    "manuscript.synctex": {"file": "main.tex", "line": 1},
    "manuscript.write_file": {
        "path": "main.tex",
        "content": "x",
        "expected_hash": f"sha256:{'0' * 64}",
    },
    "manuscript.compile": {},
    "manuscript.suggest": {
        "file": "main.tex",
        "line_start": 1,
        "line_end": 1,
        "provider": "scripted",
    },
    "manuscript.apply_suggestion": {"candidate_id": "run_20260101T000000Z_deadbeef"},
}

READS = ("manuscript.files", "manuscript.read_file", "manuscript.build", "manuscript.synctex")
WRITES = ("manuscript.write_file", "manuscript.compile", "manuscript.apply_suggestion")


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    return build_default_registry()


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[CapabilityContext]:
    """A workspace with the fixture manuscript and the fake engine on its PATH."""
    root = tmp_path / "project"
    repo = WorkspaceRepository.init(root, "manuscript-capabilities")
    copy_project(repo.layout.manuscript_dir)
    binaries = install_fake_engine(tmp_path / "bin", "pdflatex")
    # Only the fake engine: a real `tectonic` on the developer's PATH would otherwise
    # win the discovery order and quietly turn this into a network-capable compile.
    monkeypatch.setenv("PATH", str(binaries))
    yield open_context(root, HUMAN)


def call(
    registry: CapabilityRegistry,
    ctx: CapabilityContext,
    name: str,
    request: dict[str, object] | None = None,
    *,
    principal: Principal | None = None,
) -> object:
    return registry.invoke(
        name,
        ctx,
        request if request is not None else REQUESTS[name],
        principal=principal or Principal.human(HUMAN),
    )


# -- the surface -------------------------------------------------------------


def test_every_phase_21_capability_is_registered(registry: CapabilityRegistry) -> None:
    """Plan 0.4 fixes these names; a host depends on them, so they are pinned here."""
    assert set(MANUSCRIPT_WORKSPACE_CAPABILITIES) <= set(registry.names())
    assert MANUSCRIPT_WORKSPACE_CAPABILITIES == (
        "manuscript.files",
        "manuscript.read_file",
        "manuscript.write_file",
        "manuscript.compile",
        "manuscript.build",
        "manuscript.synctex",
        "manuscript.suggest",
        "manuscript.apply_suggestion",
    )


@pytest.mark.parametrize("name", READS)
def test_the_reads_are_read_permission(registry: CapabilityRegistry, name: str) -> None:
    assert registry.get(name).permission is Permission.READ


@pytest.mark.parametrize("name", WRITES)
def test_the_writes_need_the_researcher(registry: CapabilityRegistry, name: str) -> None:
    spec = registry.get(name)
    assert spec.permission is Permission.MUTATE
    assert spec.descriptor().human_only is True


def test_a_suggestion_stages_and_is_therefore_a_stage_capability(
    registry: CapabilityRegistry,
) -> None:
    """A host proposes into staging and a person accepts, exactly as for `manuscript.draft`."""
    assert registry.get("manuscript.suggest").permission is Permission.STAGE


def test_compiling_returns_its_build_rather_than_a_run_id(
    registry: CapabilityRegistry,
) -> None:
    """A compile is bounded by `manuscript.timeout_seconds` and answers with the build.

    ADR-009's `long_running` means "returns a durable run id; poll `/runs/{id}`". A compile
    has no such record: its durable trace is the build under `.research/build/manuscript/`,
    which `manuscript.build` reads by id. Marking it long-running would advertise a `run_id`
    the response does not carry.
    """
    spec = registry.get("manuscript.compile")
    assert spec.long_running is False
    assert "run_id" not in spec.response_model.model_fields
    assert "build_id" in spec.response_model.model_fields


# -- reads -------------------------------------------------------------------


def test_files_lists_the_manuscript_source(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    tree = call(registry, ctx, "manuscript.files")

    assert [item.path for item in tree.files] == [  # type: ignore[attr-defined]
        "main.tex",
        "references.bib",
        "sections/intro.tex",
    ]


def test_read_file_returns_the_hash_a_save_must_present(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    snapshot = call(registry, ctx, "manuscript.read_file")

    assert snapshot.path == "main.tex"  # type: ignore[attr-defined]
    assert snapshot.content_hash.startswith("sha256:")  # type: ignore[attr-defined]


def test_a_write_with_the_wrong_hash_is_a_conflict_naming_both_hashes(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    from research_harness.manuscript.files import ManuscriptConflictError

    with pytest.raises(ManuscriptConflictError) as raised:
        call(registry, ctx, "manuscript.write_file")

    assert raised.value.expected_hash == f"sha256:{'0' * 64}"
    assert raised.value.actual_hash.startswith("sha256:")
    assert "re-read the file" in str(raised.value)


def test_a_write_with_the_current_hash_saves(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    snapshot = call(registry, ctx, "manuscript.read_file")
    body = {
        "path": "main.tex",
        "content": snapshot.content + "\n% saved through the capability\n",  # type: ignore[attr-defined]
        "expected_hash": snapshot.content_hash,  # type: ignore[attr-defined]
    }

    saved = call(registry, ctx, "manuscript.write_file", body)

    assert saved.content.endswith("% saved through the capability\n")  # type: ignore[attr-defined]


def test_compile_then_build_answer_with_the_same_build(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    compiled = call(registry, ctx, "manuscript.compile")
    view = call(registry, ctx, "manuscript.build")

    assert compiled.status is CompileStatus.SUCCEEDED  # type: ignore[attr-defined]
    assert view.build_id == compiled.build_id  # type: ignore[attr-defined]
    assert view.diagnostics == compiled.diagnostics  # type: ignore[attr-defined]


def test_synctex_answers_forward_after_a_compile(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    call(registry, ctx, "manuscript.compile")

    view = call(registry, ctx, "manuscript.synctex", {"file": "sections/intro.tex", "line": 4})

    assert view.available is True  # type: ignore[attr-defined]
    assert view.pdf_locations  # type: ignore[attr-defined]


def test_synctex_refuses_a_request_that_names_neither_direction(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    with pytest.raises(CapabilityError, match="look forward"):
        call(registry, ctx, "manuscript.synctex", {})


def test_synctex_refuses_a_request_that_names_both_directions(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    with pytest.raises(CapabilityError, match="not both"):
        call(
            registry,
            ctx,
            "manuscript.synctex",
            {"file": "main.tex", "line": 1, "page": 1, "x": 0.0, "y": 0.0},
        )


# -- refusals ----------------------------------------------------------------


@pytest.mark.parametrize("name", WRITES)
def test_an_agent_host_is_refused_every_manuscript_write(
    registry: CapabilityRegistry, ctx: CapabilityContext, name: str
) -> None:
    """Product 24, 29: a host reads and proposes; the researcher owns the source."""
    host = Principal.agent_host("claude")

    with pytest.raises(PermissionDenied) as raised:
        call(registry, ctx, name, principal=host)

    assert "does not hold the 'mutate' permission" in str(raised.value)


@pytest.mark.parametrize("name", READS)
def test_an_agent_host_may_read_the_manuscript(
    registry: CapabilityRegistry, ctx: CapabilityContext, name: str
) -> None:
    assert call(registry, ctx, name, principal=Principal.agent_host("claude")) is not None


def test_a_read_only_host_that_writes_gets_the_same_refusal_shape_as_a_state_mutation(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    """The manuscript refusal is the evidence refusal: same class, same wording."""
    host = Principal.agent_host("claude")
    with pytest.raises(PermissionDenied) as saving:
        call(registry, ctx, "manuscript.write_file", principal=host)
    with pytest.raises(PermissionDenied) as accepting:
        spec = registry.get("evidence.accept")
        host.authorize(spec.name, spec.permission, human_only=spec.human_only)

    assert type(saving.value) is type(accepting.value)
    assert str(saving.value).split(":", 1)[1] == str(accepting.value).split(":", 1)[1]


def test_a_workspace_actor_that_is_not_a_person_cannot_write_the_manuscript(
    registry: CapabilityRegistry, tmp_path: Path
) -> None:
    """The principal says who asked; the context says whose name goes on the change."""
    root = tmp_path / "model-actor"
    repo = WorkspaceRepository.init(root, "model-actor")
    copy_project(repo.layout.manuscript_dir)
    model_ctx = open_context(root, "vendor-a/model-x")

    with pytest.raises(PermissionDenied, match="not the researcher"):
        call(registry, model_ctx, "manuscript.write_file")

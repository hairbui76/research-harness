"""`research search`, `research resolve`, `research index build`: the retrieval commands.

The CLI is a transport (ADR-004). It opens the workspace, reads the deletable projection
and the deletable vector index, prints, and writes no canonical state at all — which is why
`research index build` is safe to run whenever and `rm -rf .research/index` costs nothing
but recall (ADR-006).

Output shows what a researcher needs in order to disagree with a ranking: the authority
rung a hit came from, where in its document it sits, which index produced it, and every
score component that went into its position.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any

import typer
from sqlalchemy.engine import Engine

from research_harness.capabilities.context import CapabilityContext
from research_harness.cli.context import JsonOption, WorkspaceOption, cli_errors, context_for, emit
from research_harness.domain.errors import CapabilityError, ProjectionError
from research_harness.privacy.egress import check_embedding_egress
from research_harness.privacy.policy import EgressPolicy, load_policy
from research_harness.projection.schema import create_engine_for
from research_harness.providers.models.embeddings import (
    OPENAI_DEFAULT_EMBEDDING_MODEL,
    EmbeddingProvider,
    HashingEmbeddingProvider,
    LocalOpenAICompatibleEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from research_harness.retrieval.planner import Intent, QueryHints, RetrievalMode
from research_harness.retrieval.rerank import RERANK_WEIGHTS
from research_harness.retrieval.semantic import IndexStats, SemanticIndex
from research_harness.retrieval.service import RetrievalService, build_semantic_index
from research_harness.retrieval.structured import SourceRef

__all__ = ["register"]

DEFAULT_K = 10
DEFAULT_HASHING_DIMENSION = 512
EMBEDDERS = ("hashing", "openai", "local")

index_app = typer.Typer(
    name="index", help="Build and inspect the disposable retrieval indexes.", no_args_is_help=True
)


def register(app: typer.Typer) -> None:
    """Add `research search`, `research resolve`, and `research index ...` to ``app``."""
    app.command("search")(search)
    app.command("resolve")(resolve)
    app.add_typer(index_app, name="index")


def search(
    query: Annotated[str, typer.Argument(help="What to look for.")],
    workspace: WorkspaceOption = None,
    mode: Annotated[
        list[str] | None,
        typer.Option(
            "--mode",
            help="Force a retrieval mode instead of planning one; repeatable.",
            show_default=False,
        ),
    ] = None,
    intent: Annotated[
        str | None,
        typer.Option("--intent", help="Rerank for this intent.", show_default=False),
    ] = None,
    k: Annotated[int, typer.Option("--k", help="How many hits to return.")] = DEFAULT_K,
    embedder: Annotated[
        str,
        typer.Option("--embedder", help=f"Embedding backend: {', '.join(EMBEDDERS)}."),
    ] = "hashing",
    model: Annotated[
        str | None, typer.Option("--model", help="Embedding model.", show_default=False)
    ] = None,
    dimension: Annotated[
        int | None, typer.Option("--dimension", help="Vector width.", show_default=False)
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Search the corpus, accepted state first (`retrieval.search`)."""
    with cli_errors():
        ctx = context_for(workspace)
        hints = QueryHints(modes=_modes(mode), intent=_intent(intent))
        with _engine_for(ctx) as engine:
            service = RetrievalService(
                engine,
                ctx.repo,
                embedder=_embedder(embedder, model, dimension, policy=load_policy(ctx.repo)),
            )
            response = service.search(query, k=max(k, 1), hints=hints)
        payload = response.model_dump(mode="json")
        payload["weights"] = RERANK_WEIGHTS[response.plan.intent].as_dict()
        emit(payload, _search_lines(payload), as_json=as_json)


def resolve(
    ref: Annotated[str, typer.Argument(help="Evidence id (E####) or block ref (B####@A####-n).")],
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Print the exact source location behind a reference (`retrieval.resolve_source`)."""
    with cli_errors():
        ctx = context_for(workspace)
        with _engine_for(ctx) as engine:
            source = RetrievalService(engine, ctx.repo).resolve_source(ref)
        emit(source.model_dump(mode="json"), _resolve_lines(source), as_json=as_json)


@index_app.command("build")
def index_build(
    workspace: WorkspaceOption = None,
    embedder: Annotated[
        str,
        typer.Option("--embedder", help=f"Embedding backend: {', '.join(EMBEDDERS)}."),
    ] = "hashing",
    model: Annotated[
        str | None, typer.Option("--model", help="Embedding model.", show_default=False)
    ] = None,
    dimension: Annotated[
        int | None, typer.Option("--dimension", help="Vector width.", show_default=False)
    ] = None,
    incremental: Annotated[
        bool,
        typer.Option(
            "--incremental",
            help="Re-embed only changed units; cannot notice a unit that disappeared.",
        ),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Build or refresh the semantic index under `.research/index/semantic/`."""
    with cli_errors():
        ctx = context_for(workspace)
        provider = _embedder(embedder, model, dimension, policy=load_policy(ctx.repo))
        stats = build_semantic_index(ctx.repo, provider, rebuild=not incremental)
        emit(_index_payload(stats), _index_lines(stats), as_json=as_json)


@index_app.command("status")
def index_status(
    workspace: WorkspaceOption = None,
    embedder: Annotated[
        str,
        typer.Option("--embedder", help=f"Embedding backend: {', '.join(EMBEDDERS)}."),
    ] = "hashing",
    model: Annotated[
        str | None, typer.Option("--model", help="Embedding model.", show_default=False)
    ] = None,
    dimension: Annotated[
        int | None, typer.Option("--dimension", help="Vector width.", show_default=False)
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Report the stored index for one embedding provider: size, identity, and health."""
    with cli_errors():
        ctx = context_for(workspace)
        provider = _embedder(embedder, model, dimension, policy=load_policy(ctx.repo))
        stats = SemanticIndex.open(ctx.repo.layout.index_dir, provider).stats()
        emit(_index_payload(stats), _index_lines(stats), as_json=as_json)


# -- plumbing ----------------------------------------------------------------


@contextmanager
def _engine_for(ctx: CapabilityContext) -> Iterator[Engine]:
    """The projection engine, refusing clearly rather than querying an empty database."""
    path = ctx.repo.layout.database_file
    if not path.is_file():
        raise ProjectionError(
            f"no projection at {path}; run `research rebuild` to build it from canonical state"
        )
    engine = create_engine_for(path)
    try:
        yield engine
    finally:
        engine.dispose()


def _modes(values: list[str] | None) -> tuple[RetrievalMode, ...]:
    if not values:
        return ()
    known = ", ".join(member.value for member in RetrievalMode)
    modes: list[RetrievalMode] = []
    for value in values:
        try:
            modes.append(RetrievalMode(value))
        except ValueError:
            raise CapabilityError(f"unknown mode {value!r}; known modes: {known}") from None
    return tuple(modes)


def _intent(value: str | None) -> Intent | None:
    if value is None:
        return None
    try:
        return Intent(value)
    except ValueError:
        known = ", ".join(member.value for member in Intent)
        raise CapabilityError(f"unknown intent {value!r}; known intents: {known}") from None


def _embedder(
    name: str,
    model: str | None,
    dimension: int | None,
    *,
    policy: EgressPolicy | None = None,
) -> EmbeddingProvider:
    """The embedding backend named on the command line, checked against the egress policy.

    `hashing` needs no service; anything else is refused before any text leaves the
    workstation when the workspace policy forbids it (Product 34).
    """
    provider = _build_embedder(name, model, dimension)
    if policy is not None:
        check_embedding_egress(policy, provider, name=name)
    return provider


def _build_embedder(name: str, model: str | None, dimension: int | None) -> EmbeddingProvider:
    if name == "hashing":
        return HashingEmbeddingProvider(dimension=dimension or DEFAULT_HASHING_DIMENSION)
    if name == "openai":
        return OpenAIEmbeddingProvider(
            model=model or OPENAI_DEFAULT_EMBEDDING_MODEL, dimensions=dimension
        )
    if name == "local":
        if not model:
            raise CapabilityError("--embedder local needs --model naming the served model")
        return LocalOpenAICompatibleEmbeddingProvider(model=model, dimension=dimension)
    raise CapabilityError(f"unknown embedder {name!r}; known backends: {', '.join(EMBEDDERS)}")


# -- rendering ---------------------------------------------------------------


def _search_lines(payload: dict[str, Any]) -> list[str]:
    plan = payload["plan"]
    lines = [
        f"{payload['query']}",
        f"  intent             {plan['intent']}",
        f"  plan               {' -> '.join(plan['modes']) or '-'}",
        f"  consulted          {' -> '.join(payload['rungs_consulted']) or '-'}",
    ]
    lines += [f"  why                {reason}" for reason in plan["rationale"]]
    if not payload["hits"]:
        lines.append("  no hits; nothing in accepted state or the local corpus matched")
    for hit in payload["hits"]:
        lines.append(
            f"{hit['ref']:<16} {hit['authority']:<22} {hit['score']:.3f}  "
            f"{_location_text(hit['location'])}"
        )
        lines.append(
            f"    via {hit['provenance']}"
            + (" [stale]" if hit["stale"] else "")
            + "  "
            + " ".join(f"{name}={value:.2f}" for name, value in sorted(hit["components"].items()))
        )
        if hit["snippet"]:
            lines.append(f"    {hit['snippet']}")
    lines += [f"  note               {note}" for note in payload["notes"]]
    return lines


def _location_text(location: dict[str, Any]) -> str:
    parts: list[str] = []
    if location.get("page") is not None:
        parts.append(f"p.{location['page']}")
    if location.get("section_path"):
        parts.append("/".join(location["section_path"]))
    if location.get("block"):
        parts.append(str(location["block"]))
    if location.get("char_start") is not None:
        parts.append(f"[{location['char_start']}:{location['char_end']}]")
    return " ".join(parts) or "-"


def _resolve_lines(source: SourceRef) -> list[str]:
    lines = [
        f"{source.ref}  {source.kind}",
        f"  work               {source.work}",
        f"  version            {source.version}",
        f"  artifact           {source.artifact}",
        f"  block              {source.block}",
        f"  page               {source.page if source.page is not None else '-'}",
        f"  section            {'/'.join(source.section_path) or '-'}",
    ]
    if source.char_start is not None:
        lines.append(f"  chars              [{source.char_start}:{source.char_end}]")
    if source.bbox is not None:
        lines.append("  bbox               " + ", ".join(f"{value:.1f}" for value in source.bbox))
    if source.file_hash:
        lines.append(f"  file hash          {source.file_hash}")
    if source.text:
        lines.append(f"  text               {' '.join(source.text.split())[:200]}")
    return lines


def _index_payload(stats: IndexStats) -> dict[str, Any]:
    return stats.model_dump(mode="json")


def _index_lines(stats: IndexStats) -> list[str]:
    return [
        f"{stats.provider}/{stats.model}/{stats.dimension}: {stats.unit_count} units",
        f"  directory          {stats.directory}",
        f"  index version      {stats.index_version}",
        f"  needs rebuild      {'yes' if stats.needs_rebuild else 'no'}",
        f"  built at           {stats.built_at or '-'}",
    ]

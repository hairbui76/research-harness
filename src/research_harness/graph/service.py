"""`ResearchGraph`: one object a capability, a CLI command, or a context assembler holds.

It owns the database handle and nothing else — every method here delegates to
`graph.rebuild`, `graph.queries`, or `graph.resolver`, so the façade can grow a method
without any of them learning about the others.

The graph may legitimately not exist: `.research/` is disposable and a workspace that has
never been rebuilt has no database. Reads answer emptily in that case rather than raising,
because "the index is not built" must degrade navigation, never break a workspace
(graph spec §8: direct canonical reads remain possible while the graph is unavailable).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import TracebackType
from typing import Self

from sqlalchemy.engine import Engine

from research_harness.domain.graph import (
    ContextFragment,
    DeepLink,
    EdgeKind,
    EdgeOrigin,
    GraphAuthority,
    GraphVisibility,
    NodeKind,
)
from research_harness.graph.context import DEFAULT_LIMIT as CONTEXT_LIMIT
from research_harness.graph.context import ContextAssembly, assemble
from research_harness.graph.projectors import Projector
from research_harness.graph.queries import (
    DEFAULT_LIMIT,
    Direction,
    GraphFilter,
    Neighbour,
    NodeRecord,
    ProvenancePath,
    SearchHit,
)
from research_harness.graph.queries import (
    autocomplete as _autocomplete,
)
from research_harness.graph.queries import (
    citations as _citations,
)
from research_harness.graph.queries import (
    dependents as _dependents,
)
from research_harness.graph.queries import (
    neighbors as _neighbors,
)
from research_harness.graph.queries import (
    provenance as _provenance,
)
from research_harness.graph.queries import (
    query as _query,
)
from research_harness.graph.queries import (
    resolve as _resolve,
)
from research_harness.graph.queries import (
    search as _search,
)
from research_harness.graph.rebuild import (
    GraphReport,
    GraphStatus,
    dump_graph,
    graph_status,
    rebuild_graph,
    update_graph,
)
from research_harness.graph.resolver import ResolvedTarget, resolve_deep_link
from research_harness.graph.schema import create_engine_for, graph_database_path
from research_harness.workspace.repository import WorkspaceRepository

__all__ = ["ResearchGraph"]

logger = logging.getLogger(__name__)


class ResearchGraph:
    """The ResearchGraph projection of one workspace: build it, then ask it questions."""

    def __init__(
        self,
        repo: WorkspaceRepository,
        *,
        research_dir: Path | str | None = None,
        projectors: Iterable[Projector] | None = None,
    ) -> None:
        self._repo = repo
        self._research_dir = (
            repo.layout.research_dir if research_dir is None else Path(research_dir)
        )
        self._projectors = None if projectors is None else tuple(projectors)
        self._engine: Engine | None = None

    def __repr__(self) -> str:
        return f"ResearchGraph({str(self.database)!r})"

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # -- lifecycle -----------------------------------------------------------

    @property
    def repo(self) -> WorkspaceRepository:
        """The workspace this graph projects; canonical reads still go through it."""
        return self._repo

    @property
    def database(self) -> Path:
        """`<research_dir>/graph/research-graph.db`."""
        return graph_database_path(self._research_dir)

    @property
    def engine(self) -> Engine | None:
        """The open engine, or ``None`` while the graph has never been built."""
        if self._engine is None and self.database.is_file():
            self._engine = create_engine_for(self.database)
        return self._engine

    def close(self) -> None:
        """Release the database handle; the graph stays on disk."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def rebuild(self) -> GraphReport:
        """Rebuild the whole graph from durable sources (graph spec §4)."""
        self.close()
        return rebuild_graph(
            self._repo, research_dir=self._research_dir, projectors=self._projectors
        )

    def update(self) -> GraphReport:
        """Re-project only the sources whose fingerprint changed, in one transaction."""
        self.close()
        return update_graph(
            self._repo, research_dir=self._research_dir, projectors=self._projectors
        )

    def status(self) -> GraphStatus:
        """Schema version, build time, canonical digest, event cursor, and row counts."""
        engine = self.engine
        if engine is None:
            return GraphStatus(
                database=self.database,
                exists=False,
                schema_version=None,
                built_at=None,
                canonical_digest=None,
                event_cursor=None,
                nodes=0,
                edges=0,
                sources=0,
            )
        return graph_status(engine, database=self.database)

    def dump(self, *, include_sources: bool = False) -> str:
        """Deterministic text of every node and edge; how a test compares two builds."""
        engine = self.engine
        return "" if engine is None else dump_graph(engine, include_sources=include_sources)

    # -- queries -------------------------------------------------------------

    def resolve(self, reference: str) -> NodeRecord | None:
        """Resolve `@E0482`, `E0482`, or a node identity to its projected node."""
        engine = self.engine
        return None if engine is None else _resolve(engine, reference)

    def autocomplete(
        self,
        prefix: str,
        *,
        kinds: Sequence[NodeKind] | None = None,
        visibility: Sequence[GraphVisibility] | None = None,
        limit: int = 10,
    ) -> list[NodeRecord]:
        """Composer completion for a partially typed `@` reference or name."""
        engine = self.engine
        if engine is None:
            return []
        return _autocomplete(engine, prefix, kinds=kinds, visibility=visibility, limit=limit)

    def neighbors(
        self,
        identity: str,
        *,
        hops: int = 1,
        direction: Direction = Direction.BOTH,
        edge_kinds: Sequence[EdgeKind] | None = None,
        origins: Sequence[EdgeOrigin] | None = None,
        authority: Sequence[GraphAuthority] | None = None,
        visibility: Sequence[GraphVisibility] | None = None,
        kinds: Sequence[NodeKind] | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[Neighbour]:
        """One- or two-hop neighbourhood, in either direction, filtered as asked."""
        engine = self.engine
        if engine is None:
            return []
        return _neighbors(
            engine,
            identity,
            hops=hops,
            direction=direction,
            edge_kinds=edge_kinds,
            origins=origins,
            authority=authority,
            visibility=visibility,
            kinds=kinds,
            limit=limit,
        )

    def query(self, filters: GraphFilter) -> list[NodeRecord]:
        """Structured node query: kind, authority, visibility, link, and text filters."""
        engine = self.engine
        return [] if engine is None else _query(engine, filters)

    def search(
        self,
        terms: str,
        *,
        kinds: Sequence[NodeKind] | None = None,
        neighbourhood: str | None = None,
        hops: int = 1,
        limit: int = DEFAULT_LIMIT,
        filters: GraphFilter | None = None,
    ) -> list[SearchHit]:
        """Lexical search, optionally constrained to one node's neighbourhood."""
        engine = self.engine
        if engine is None:
            return []
        return _search(
            engine,
            terms,
            kinds=kinds,
            neighbourhood=neighbourhood,
            hops=hops,
            limit=limit,
            filters=filters,
        )

    def provenance(
        self,
        from_id: str,
        *,
        to_kind: NodeKind = NodeKind.ARTIFACT,
        visibility: Sequence[GraphVisibility] | None = None,
    ) -> ProvenancePath | None:
        """Shortest provenance path, e.g. Claim → Evidence → the exact Artifact anchor."""
        engine = self.engine
        if engine is None:
            return None
        return _provenance(engine, from_id, to_kind=to_kind, visibility=visibility)

    def dependents(self, identity: str, *, limit: int = DEFAULT_LIMIT) -> list[NodeRecord]:
        """What a change to ``identity`` reaches, as far as the graph's namespaces go."""
        engine = self.engine
        return [] if engine is None else _dependents(engine, identity, limit=limit)

    def citations(self, identity: str, *, limit: int = DEFAULT_LIMIT) -> list[NodeRecord]:
        """What ``identity`` cites."""
        engine = self.engine
        return [] if engine is None else _citations(engine, identity, limit=limit)

    def resolve_deep_link(self, link: DeepLink | str) -> ResolvedTarget:
        """Validate an `rh://` link against canonical state before anything opens it."""
        return resolve_deep_link(self._repo, link, engine=self.engine)

    # -- context assembly ----------------------------------------------------

    def context_fragments(
        self,
        *,
        session: str | None = None,
        query: str = "",
        references: Sequence[str] = (),
        visibility: str = GraphVisibility.PRIVATE.value,
        limit: int = CONTEXT_LIMIT,
    ) -> tuple[ContextFragment, ...]:
        """The provenance-bearing subgraph for one context request (graph spec §7).

        ``visibility`` is the egress class of the request — ``"project"`` assembles only
        what may reach the selected provider, ``"private"`` assembles everything on this
        machine — and it is applied at every hop, so a private prior-session node cannot
        enter a project-visible pack through an allowed public neighbour (graph spec §8).

        An absent graph returns no fragments rather than raising: the caller falls back to
        direct canonical and transcript reads, which is what keeps a workspace usable while
        `.research/` is missing or rebuilding.
        """
        return self.context_assembly(
            session=session,
            query=query,
            references=references,
            visibility=visibility,
            limit=limit,
        ).fragments

    def context_assembly(
        self,
        *,
        session: str | None = None,
        query: str = "",
        references: Sequence[str] = (),
        visibility: str = GraphVisibility.PRIVATE.value,
        limit: int = CONTEXT_LIMIT,
    ) -> ContextAssembly:
        """:meth:`context_fragments` plus the omissions a `Context used` receipt needs."""
        return assemble(
            self.engine,
            session=session,
            query=query,
            references=references,
            visibility=GraphVisibility(str(visibility)),
            limit=limit,
        )

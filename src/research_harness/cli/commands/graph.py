"""`research graph ...`: resolve, complete, traverse, filter, trace, and inspect the index.

A transport and nothing else (ADR-004): every command validates its arguments into the
matching `graph.*` capability request and prints what the capability returned, so the
terminal, the daemon, and an MCP host answer identically. Nothing here writes — rebuilding
the index is `research rebuild`.

Text output names the authority and visibility of every row, because those are the two
labels that decide whether a researcher may act on what they are looking at, and a terminal
has no colour budget to spend on them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

import typer

from research_harness.capabilities.graph import (
    AutocompleteRequest,
    AutocompleteResult,
    GraphNodeView,
    GraphQueryRequest,
    GraphQueryResult,
    GraphStatusRequest,
    GraphStatusView,
    NeighborsRequest,
    NeighbourhoodView,
    ProvenanceRequest,
    ProvenanceView,
    ResolvedView,
    ResolveRequest,
    graph_autocomplete,
    graph_neighbors,
    graph_provenance,
    graph_query,
    graph_resolve,
    graph_status,
)
from research_harness.cli.context import (
    JsonOption,
    WorkspaceOption,
    cli_errors,
    context_for,
    emit,
)
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.graph import (
    EdgeKind,
    GraphAuthority,
    GraphVisibility,
    NodeKind,
)
from research_harness.graph.queries import Direction

__all__ = ["register"]

graph_app = typer.Typer(
    name="graph",
    help="Resolve references and traverse the ResearchGraph index.",
    no_args_is_help=True,
)

ReferenceArgument = Annotated[
    str,
    typer.Argument(metavar="REFERENCE", help="An @ reference, a node identity, or an rh:// link."),
]
IdentityArgument = Annotated[
    str, typer.Argument(metavar="ID", help="Node identity, e.g. C0041 or block:A0017-3#B0081.")
]
KindOption = Annotated[
    list[str] | None,
    typer.Option("--kind", help="Restrict to a node kind; repeatable.", show_default=False),
]
EdgeKindOption = Annotated[
    list[str] | None,
    typer.Option("--edge", help="Restrict to an edge kind; repeatable.", show_default=False),
]
AuthorityOption = Annotated[
    list[str] | None,
    typer.Option(
        "--authority", help="Restrict to an authority label; repeatable.", show_default=False
    ),
]
VisibilityOption = Annotated[
    list[str] | None,
    typer.Option(
        "--visibility",
        help="Restrict to an egress class (private, project); repeatable. Excluded nodes "
        "are never traversed through.",
        show_default=False,
    ),
]
LimitOption = Annotated[int, typer.Option("--limit", min=1, help="Maximum rows to return.")]


def register(app: typer.Typer) -> None:
    """Add `research graph ...` to ``app``."""
    app.add_typer(graph_app, name="graph")


# -- commands ----------------------------------------------------------------


@graph_app.command("resolve")
def resolve(
    reference: ReferenceArgument,
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Resolve a reference against canonical state (`graph.resolve`)."""
    with cli_errors():
        ctx = context_for(workspace)
        view = graph_resolve(ctx, ResolveRequest(reference=reference))
    emit(_payload(view), _resolve_lines(view), as_json=as_json)
    if not view.ok:
        raise typer.Exit(code=1)


@graph_app.command("complete")
def complete(
    prefix: Annotated[str, typer.Argument(help="Partially typed reference or name.")],
    workspace: WorkspaceOption = None,
    kind: KindOption = None,
    visibility: VisibilityOption = None,
    limit: LimitOption = 10,
    as_json: JsonOption = False,
) -> None:
    """Complete a partially typed `@` reference (`graph.autocomplete`)."""
    with cli_errors():
        ctx = context_for(workspace)
        view = graph_autocomplete(
            ctx,
            AutocompleteRequest(
                prefix=prefix,
                kinds=_values(NodeKind, kind, "node kind"),
                visibility=_values(GraphVisibility, visibility, "visibility"),
                limit=limit,
            ),
        )
    emit(_payload(view), _complete_lines(view), as_json=as_json)


@graph_app.command("neighbors")
def neighbors(
    identity: IdentityArgument,
    workspace: WorkspaceOption = None,
    hops: Annotated[int, typer.Option("--hops", min=1, max=2, help="One or two hops.")] = 1,
    direction: Annotated[
        Direction, typer.Option("--direction", help="Follow edges out, in, or both ways.")
    ] = Direction.BOTH,
    kind: KindOption = None,
    edge: EdgeKindOption = None,
    authority: AuthorityOption = None,
    visibility: VisibilityOption = None,
    limit: LimitOption = 50,
    as_json: JsonOption = False,
) -> None:
    """Traverse a one- or two-hop neighbourhood (`graph.neighbors`)."""
    with cli_errors():
        ctx = context_for(workspace)
        view = graph_neighbors(
            ctx,
            NeighborsRequest(
                id=identity,
                hops=hops,
                direction=direction,
                kinds=_values(NodeKind, kind, "node kind"),
                edge_kinds=_values(EdgeKind, edge, "edge kind"),
                authority=_values(GraphAuthority, authority, "authority"),
                visibility=_values(GraphVisibility, visibility, "visibility"),
                limit=limit,
            ),
        )
    emit(_payload(view), _neighbour_lines(view), as_json=as_json)


@graph_app.command("query")
def query(
    workspace: WorkspaceOption = None,
    kind: KindOption = None,
    authority: AuthorityOption = None,
    visibility: VisibilityOption = None,
    edge: EdgeKindOption = None,
    linked_to: Annotated[
        str | None,
        typer.Option("--linked-to", help="Only nodes joined to this identity.", show_default=False),
    ] = None,
    text: Annotated[
        str | None,
        typer.Option("--text", help="Lexical constraint over label and text.", show_default=False),
    ] = None,
    limit: LimitOption = 50,
    as_json: JsonOption = False,
) -> None:
    """Filter nodes by kind, authority, visibility, link, and text (`graph.query`)."""
    with cli_errors():
        ctx = context_for(workspace)
        view = graph_query(
            ctx,
            GraphQueryRequest(
                kinds=_values(NodeKind, kind, "node kind"),
                authorities=_values(GraphAuthority, authority, "authority"),
                visibility=_values(GraphVisibility, visibility, "visibility"),
                edge_kinds=_values(EdgeKind, edge, "edge kind"),
                linked_to=linked_to,
                text=text,
                limit=limit,
            ),
        )
    emit(_payload(view), _query_lines(view), as_json=as_json)


@graph_app.command("provenance")
def provenance(
    identity: IdentityArgument,
    workspace: WorkspaceOption = None,
    to_kind: Annotated[
        NodeKind, typer.Option("--to", help="Kind of source the path should end at.")
    ] = NodeKind.ARTIFACT,
    visibility: VisibilityOption = None,
    as_json: JsonOption = False,
) -> None:
    """Trace a node back to its source, e.g. Claim to Artifact anchor (`graph.provenance`)."""
    with cli_errors():
        ctx = context_for(workspace)
        view = graph_provenance(
            ctx,
            ProvenanceRequest(
                id=identity,
                to_kind=to_kind,
                visibility=_values(GraphVisibility, visibility, "visibility"),
            ),
        )
    emit(_payload(view), _provenance_lines(view), as_json=as_json)
    if not view.found:
        raise typer.Exit(code=1)


@graph_app.command("status")
def status(workspace: WorkspaceOption = None, as_json: JsonOption = False) -> None:
    """Whether the index exists, how big it is, and when it was built (`graph.status`)."""
    with cli_errors():
        ctx = context_for(workspace)
        view = graph_status(ctx, GraphStatusRequest())
    emit(_payload(view), _status_lines(view), as_json=as_json)


# -- rendering ---------------------------------------------------------------


def _payload(view: Any) -> dict[str, Any]:
    payload: dict[str, Any] = view.model_dump(mode="json")
    return payload


def _values[T: StrEnum](vocabulary: type[T], given: list[str] | None, what: str) -> tuple[T, ...]:
    """Parse repeated option strings into their vocabulary, or say what was expected."""
    parsed: list[T] = []
    for value in given or ():
        try:
            parsed.append(vocabulary(value))
        except ValueError:
            known = ", ".join(sorted(member.value for member in vocabulary))
            raise ResearchHarnessError(
                f"unknown {what} {value!r}; expected one of {known}"
            ) from None
    return tuple(parsed)


def _node_line(node: GraphNodeView, indent: str = "") -> str:
    label = node.label or node.text
    labels = f"{node.kind.value}/{node.authority.value}/{node.visibility.value}"
    return f"{indent}{node.id}  [{labels}]  {label}"


def _resolve_lines(view: ResolvedView) -> list[str]:
    head = "resolved" if view.ok else "unavailable"
    lines = [
        f"{view.reference} {head} in {view.project}: "
        f"{view.authority.value}/{view.visibility.value}" + ("" if view.fresh else ", not fresh")
    ]
    if view.link is not None:
        lines.append(f"  link   {view.link}")
    if view.node is not None:
        lines.append(_node_line(view.node, "  node   "))
        if view.node.source is not None:
            lines.append(f"  source {view.node.source}")
    lines += [f"  problem {problem}" for problem in view.problems]
    return lines


def _complete_lines(view: AutocompleteResult) -> list[str]:
    if not view.matches:
        return [f"no completion for {view.prefix!r}"]
    return [f"{len(view.matches)} completion(s) for {view.prefix!r}"] + [
        _node_line(node, "  ") for node in view.matches
    ]


def _neighbour_lines(view: NeighbourhoodView) -> list[str]:
    if view.origin is None:
        return ["no such node in the index"]
    lines = [_node_line(view.origin)]
    if not view.neighbours:
        lines.append("  (no neighbours under these filters)")
    for item in view.neighbours:
        arrow = "->" if item.direction is Direction.OUT else "<-"
        lines.append(
            f"  {item.hops} {arrow} {item.edge.kind.value}"
            f"{' (candidate)' if item.edge.is_candidate else ''}"
        )
        lines.append(_node_line(item.node, "      "))
    return lines


def _query_lines(view: GraphQueryResult) -> list[str]:
    if not view.nodes:
        return ["no node matches this filter"]
    return [f"{len(view.nodes)} node(s)"] + [_node_line(node, "  ") for node in view.nodes]


def _provenance_lines(view: ProvenanceView) -> list[str]:
    if not view.found or view.origin is None:
        return ["no provenance path under these filters"]
    lines = [" -> ".join(view.identities), _node_line(view.origin, "  from ")]
    for step in view.steps:
        lines.append(f"  {step.edge.kind.value} ({step.direction.value})")
        lines.append(_node_line(step.node, "      "))
    if view.anchor:
        detail = ", ".join(f"{key}={value}" for key, value in sorted(view.anchor.items()))
        lines.append(f"  anchor {detail}")
    return lines


def _status_lines(view: GraphStatusView) -> list[str]:
    if not view.exists:
        return [f"no graph index at {view.database}; run `research rebuild`"]
    state = "current" if view.available else "stale schema; rebuild"
    lines = [
        f"graph index {state}: {view.nodes} nodes, {view.edges} edges "
        f"from {view.sources} source(s)",
        f"  database {view.database}",
        f"  built    {view.built_at}",
        f"  schema   {view.schema_version}",
    ]
    if view.canonical_digest:
        lines.append(f"  canonical {view.canonical_digest}")
    if view.rebuilding:
        lines.append("  a rebuild is writing a replacement database right now")
    return lines

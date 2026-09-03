"""`research providers list`: the model catalog the terminal reads (`provider.list`).

A transport and nothing else (ADR-004): the command calls the same `provider.list`
capability the Web client and an MCP host call, and prints what came back. Nothing here
knows a provider rule, and nothing here reads a credential — the catalog says whether a key
is present, and the name of the variable it would come from, exactly as `research egress`
does (Product 34).

The family is `providers` because that is what `research.yaml` calls the table these rows
come from; `research egress` remains the privacy view of the same configuration, and this
is the selector view.
"""

from __future__ import annotations

import typer

from research_harness.capabilities.providers import (
    ListProvidersRequest,
    ProviderCatalog,
    list_providers,
)
from research_harness.cli.context import (
    JsonOption,
    WorkspaceOption,
    cli_errors,
    context_for,
    emit,
)

__all__ = ["register"]

providers_app = typer.Typer(
    name="providers",
    help="The models this project can route to, and whether they are available.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Add the `research providers ...` family to ``app``."""
    app.add_typer(providers_app, name="providers")


@providers_app.command("list")
def providers_list(workspace: WorkspaceOption = None, as_json: JsonOption = False) -> None:
    """Every configured model, with what it accepts and whether it can be called."""
    with cli_errors():
        catalog = list_providers(context_for(workspace), ListProvidersRequest())
        emit(catalog.model_dump(mode="json"), _lines(catalog), as_json=as_json)


def _lines(catalog: ProviderCatalog) -> list[str]:
    """One row per model: what to pass, where it sends, and what stops it."""
    if not catalog.models:
        lines = ["no model providers configured"]
        lines.append("add a `providers:` list to research.yaml to route a conversation")
        return lines
    lines = []
    for item in catalog.models:
        marker = "*" if item.default else " "
        media = ", ".join(item.input_media) or "text only"
        state = "available" if item.available else f"unavailable — {item.unavailable_reason}"
        lines.append(
            f"{marker} {item.id:<16} {item.label:<28} {item.egress_class.value:<8} "
            f"{item.context_tokens:>8} tok  {state}"
        )
        lines.append(f"    accepts: {media}")
    lines.append("")
    lines.append("* the model an unconstrained call routes to")
    return lines

"""`research providers list`: the model catalog the terminal reads (`provider.list`).

A transport and nothing else (ADR-004): the command calls the same `provider.list`
capability the Web client and an MCP host call, and prints what came back. Nothing here
knows a provider rule, and nothing here reads a credential — the catalog says whether a key
is present, and the name of the variable it would come from, exactly as `research egress`
does (Product 34).

The family is `providers` because that is what `research.yaml` calls the table these rows
come from; `research egress` remains the privacy view of the same configuration, and this
is the selector view.

`scan`, `add`, `test` and `remove` are the terminal's view of `provider.cli.*` (CLI
providers spec §17): the subscription-backed local CLIs a researcher already pays for.
The gates that decide whether a runtime may be routed -- installed, logged in, provably
bounded, not a blocked version -- live in the capability, not here; these commands print
the sentence the server returned and exit 1 when it says no. `test` names the destination
before it calls, because that call leaves the workstation, and never prints what the model
answered.
"""

from __future__ import annotations

from typing import Annotated

import typer

from research_harness.capabilities.cli_providers import (
    CliProviderTestReport,
    CliScanReport,
    ConfigureCliProviderRequest,
    RemoveCliProviderRequest,
    ScanCliRuntimesRequest,
    TestCliProviderRequest,
    configure_cli_provider,
    remove_cli_provider,
    scan_cli_runtimes,
    test_cli_provider,
)
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
from research_harness.providers.cli.registry import RUNTIME_IDS, RUNTIMES
from research_harness.providers.cli.types import CliRuntimeStatus, unavailable_reason

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


@providers_app.command("scan")
def providers_scan(
    workspace: WorkspaceOption = None,
    rescan: Annotated[
        bool, typer.Option("--rescan", help="Bypass the short in-memory cache.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Detect the supported local CLIs: installed, version, login, bounded mode, models."""
    with cli_errors():
        report = scan_cli_runtimes(context_for(workspace), ScanCliRuntimesRequest(rescan=rescan))
        emit(report.model_dump(mode="json"), _scan_lines(report), as_json=as_json)


@providers_app.command("add")
def providers_add(
    runtime: Annotated[
        str,
        typer.Argument(help=f"Runtime id: {', '.join(RUNTIME_IDS)}."),
    ],
    name: Annotated[str, typer.Option("--name", help="The entry name `--provider` selects.")],
    workspace: WorkspaceOption = None,
    model: Annotated[
        str, typer.Option("--model", help="Model id from `providers scan`, or `default`.")
    ] = "default",
    priority: Annotated[int, typer.Option("--priority", help="Lower is preferred.")] = 100,
    reasoning: Annotated[
        str | None,
        typer.Option("--reasoning", help="The runtime's own effort name.", show_default=False),
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="Request timeout in seconds.", show_default=False),
    ] = None,
    role: Annotated[
        list[str] | None,
        typer.Option("--role", help="Restrict to a role; repeatable.", show_default=False),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Add (or update) a subscription-backed CLI provider entry in research.yaml."""
    with cli_errors():
        request = ConfigureCliProviderRequest(
            name=name,
            runtime=runtime,
            model=model,
            priority=priority,
            reasoning=reasoning,
            timeout_seconds=timeout,
            roles=role,
        )
        result = configure_cli_provider(context_for(workspace), request)
        verb = "added" if result.created else "updated"
        lines = [
            f"{verb} {result.entry.name} ({result.entry.runtime}/{result.entry.model}, "
            f"priority {result.entry.priority}) in {result.file}",
            f"select it with --provider {result.entry.name}",
        ]
        emit(result.model_dump(mode="json"), lines, as_json=as_json)


@providers_app.command("test")
def providers_test(
    name: Annotated[str, typer.Argument(help="A local_cli entry name from research.yaml.")],
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Run one minimal schema-validated request through a configured CLI provider."""
    with cli_errors():
        ctx = context_for(workspace)
        entry = next((item for item in ctx.repo.config.providers if item.get("name") == name), None)
        if entry is not None and not as_json:
            definition = RUNTIMES.get(str(entry.get("runtime")))
            if definition is not None:
                typer.echo(
                    f"egress: {name} sends research content to {definition.egress_host} "
                    f"through {definition.name}"
                )
        report = test_cli_provider(ctx, TestCliProviderRequest(name=name))
        emit(report.model_dump(mode="json"), _test_lines(report), as_json=as_json)
        if not report.ok:
            raise typer.Exit(code=1)


@providers_app.command("remove")
def providers_remove(
    name: Annotated[str, typer.Argument(help="A local_cli entry name from research.yaml.")],
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Remove a subscription-backed CLI provider entry from research.yaml."""
    with cli_errors():
        result = remove_cli_provider(context_for(workspace), RemoveCliProviderRequest(name=name))
        emit(
            result.model_dump(mode="json"),
            [f"removed {result.name} from {result.file}"],
            as_json=as_json,
        )


def _scan_lines(report: CliScanReport) -> list[str]:
    """One block per runtime, then whatever this project has already configured."""
    lines = [report.notice, ""]
    for item in report.runtimes:
        lines.append(f"{item.runtime:<18} {_state(item)}")
        for diagnostic in item.diagnostics:
            lines.append(f"    {diagnostic}")
        if item.available:
            models = ", ".join(model.id for model in item.models[:6]) + (
                " …" if len(item.models) > 6 else ""
            )
            lines.append(f"    models ({item.model_source}): {models}")
    if report.configured:
        lines.append("")
        lines.append("configured in research.yaml")
        for entry in report.configured:
            state = "available" if entry.available else f"unavailable — {entry.unavailable_reason}"
            lines.append(
                f"  {entry.name:<16} {entry.runtime}/{entry.model:<20} "
                f"priority {entry.priority:<4} {state}"
            )
    return lines


def _state(item: CliRuntimeStatus) -> str:
    """One runtime's row: version, login, bounded mode, and the first gate that refuses it."""
    if not item.available:
        return "not installed"
    version = item.version or "version unknown"
    auth = {"ok": "logged in", "missing": "not logged in", "unknown": "login unverified"}[
        item.auth_status
    ]
    bounded = {
        "safe": "bounded mode ok",
        "unsupported": "no bounded mode",
        "unknown": "bounded mode unproven",
    }[item.bounded_mode]
    reason = unavailable_reason(item)
    tail = "" if reason is None else f" — {reason}"
    return f"{version:<14} {auth:<18} {bounded:<22} {item.compatibility}{tail}"


def _test_lines(report: CliProviderTestReport) -> list[str]:
    """The verdict and the reason for it — never the object the model returned."""
    verdict = "ok" if report.ok else "failed"
    lines = [
        f"{report.name} ({report.runtime}/{report.model}, "
        f"{report.version or 'version unknown'}): {verdict}",
        f"  {report.message}",
    ]
    if report.diagnostic:
        lines.append(f"  diagnostic: {report.diagnostic}")
    return lines

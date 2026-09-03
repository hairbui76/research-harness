"""`research egress`, `research privacy`, and `research traces`: the privacy family.

Product §34 asks for privacy to be a visible, default property of the workstation. These
commands are that surface:

* `research egress` prints every provider this workspace could reach, what would leave the
  workstation if it were used, whether the project's policy allows it, and whether a
  credential is present. It never prints a key — only the name of the environment variable
  a key would come from. The model section is always printed, empty or not: it is the
  largest egress channel a workstation has, and a missing section reads as an answer
  (dogfood F17).
* `research privacy show|set` reads and writes the `privacy:` section of `research.yaml`.
* `research traces list|purge` manages `.research/traces/`, which is disposable by design
  and may contain source text (Product §19.3).

Like every command module this one is a transport: it reads through the repository and
writes configuration through `WorkspaceRepository.update_config`, which journals the write
the same way a canonical mutation is journaled.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

import typer

from research_harness.cli.context import JsonOption, WorkspaceOption, cli_errors, context_for, emit
from research_harness.domain.errors import ResearchHarnessError
from research_harness.privacy.egress import EgressReport, egress_report
from research_harness.privacy.policy import EgressPolicy
from research_harness.privacy.traces import PurgeResult, TraceRecord, TraceWriter

__all__ = ["register"]

privacy_app = typer.Typer(
    name="privacy",
    help="Show and set this project's privacy and egress policy.",
    no_args_is_help=True,
)

traces_app = typer.Typer(
    name="traces",
    help="List and purge the disposable provider traces under `.research/traces/`.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Add `research egress`, `research privacy ...`, and `research traces ...` to ``app``."""
    app.command("egress")(egress)
    app.add_typer(privacy_app, name="privacy")
    app.add_typer(traces_app, name="traces")


# -- options -----------------------------------------------------------------

_SWITCH = "allowed|disabled"

ExternalModelsOption = Annotated[
    str | None,
    typer.Option(
        "--external-models",
        help=f"{_SWITCH}: allow or refuse every non-local model and embedding provider.",
        show_default=False,
    ),
]

SearchProvidersOption = Annotated[
    str | None,
    typer.Option(
        "--search-providers",
        help=f"{_SWITCH}: allow or refuse external discovery sources.",
        show_default=False,
    ),
]

AllowedHostOption = Annotated[
    list[str] | None,
    typer.Option(
        "--allowed-host",
        help="Endpoint host this project may talk to; repeatable, replaces the current list.",
        show_default=False,
    ),
]

AllowSourceTextOption = Annotated[
    bool | None,
    typer.Option(
        "--allow-source-text/--no-allow-source-text",
        help="Whether providers that send source text off the workstation may be used.",
        show_default=False,
    ),
]

AllowIdentifiersOption = Annotated[
    bool | None,
    typer.Option(
        "--allow-identifiers/--no-allow-identifiers",
        help="Whether providers that send object identifiers may be used.",
        show_default=False,
    ),
]

RedactTracesOption = Annotated[
    bool | None,
    typer.Option(
        "--redact-traces/--no-redact-traces",
        help="Hash source text out of traces as they are written.",
        show_default=False,
    ),
]

TraceRetentionOption = Annotated[
    int | None,
    typer.Option(
        "--trace-retention-days",
        min=0,
        help="How many days of traces `research traces purge` keeps.",
        show_default=False,
    ),
]


# -- research egress ---------------------------------------------------------


def egress(
    workspace: WorkspaceOption = None,
    denied_only: Annotated[
        bool,
        typer.Option("--denied", help="Show only the providers the policy currently refuses."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Show what would leave this workstation, per provider, and whether policy allows it."""
    with cli_errors():
        ctx = context_for(workspace)
        report = egress_report(ctx.repo, os.environ)
        # Asked before `--denied` narrows the table: "no model row survived the filter" and
        # "no model provider is configured" are different facts (dogfood F17).
        configured = bool(report.of_kind("model"))
        if denied_only:
            report = report.model_copy(update={"entries": report.denied})
        payload = {**report.model_dump(mode="json"), "model_providers_configured": configured}
        emit(payload, _egress_lines(report, models_configured=configured), as_json=as_json)


# -- research privacy --------------------------------------------------------


@privacy_app.command("show")
def privacy_show(workspace: WorkspaceOption = None, as_json: JsonOption = False) -> None:
    """Print the `privacy:` section of `research.yaml` as it is now."""
    with cli_errors():
        ctx = context_for(workspace)
        policy = ctx.repo.config.privacy
        emit(policy.model_dump(mode="json"), _policy_lines(policy), as_json=as_json)


@privacy_app.command("set")
def privacy_set(
    workspace: WorkspaceOption = None,
    external_models: ExternalModelsOption = None,
    allow_source_text: AllowSourceTextOption = None,
    allow_identifiers: AllowIdentifiersOption = None,
    allowed_host: AllowedHostOption = None,
    search_providers: SearchProvidersOption = None,
    redact_traces: RedactTracesOption = None,
    trace_retention_days: TraceRetentionOption = None,
    as_json: JsonOption = False,
) -> None:
    """Change the project's privacy policy; only the options given are changed."""
    with cli_errors():
        ctx = context_for(workspace)
        updates = _updates(
            external_models=external_models,
            allow_source_text=allow_source_text,
            allow_identifiers=allow_identifiers,
            allowed_host=allowed_host,
            search_providers=search_providers,
            redact_traces=redact_traces,
            trace_retention_days=trace_retention_days,
        )
        if not updates:
            raise ResearchHarnessError(
                "nothing to set: pass at least one option, or run `research privacy show`"
            )
        policy = EgressPolicy.model_validate({**ctx.repo.config.privacy.model_dump(), **updates})
        config = ctx.repo.update_config(policy)
        payload = {"privacy": config.privacy.model_dump(mode="json"), "changed": sorted(updates)}
        emit(payload, _set_lines(config.privacy, sorted(updates)), as_json=as_json)


def _updates(
    *,
    external_models: str | None,
    allow_source_text: bool | None,
    allow_identifiers: bool | None,
    allowed_host: list[str] | None,
    search_providers: str | None,
    redact_traces: bool | None,
    trace_retention_days: int | None,
) -> dict[str, Any]:
    """The fields the researcher actually asked to change, validated as switches."""
    updates: dict[str, Any] = {}
    if external_models is not None:
        updates["external_models"] = _switch(external_models, "--external-models")
    if search_providers is not None:
        updates["search_providers"] = _switch(search_providers, "--search-providers")
    if allowed_host is not None:
        updates["allowed_hosts"] = tuple(allowed_host)
    if allow_source_text is not None:
        updates["allow_source_text"] = allow_source_text
    if allow_identifiers is not None:
        updates["allow_identifiers"] = allow_identifiers
    if redact_traces is not None:
        updates["redact_traces"] = redact_traces
    if trace_retention_days is not None:
        updates["trace_retention_days"] = trace_retention_days
    return updates


def _switch(value: str, option: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"allowed", "disabled"}:
        raise ResearchHarnessError(f"{option} takes {_SWITCH}, not {value!r}")
    return normalized


# -- research traces ---------------------------------------------------------


@traces_app.command("list")
def traces_list(workspace: WorkspaceOption = None, as_json: JsonOption = False) -> None:
    """List the disposable traces on disk. Traces carry no scientific authority."""
    with cli_errors():
        ctx = context_for(workspace)
        writer = _writer(ctx.repo.layout.research_dir, ctx.repo.config.privacy)
        records = writer.list_traces()
        payload = {
            "traces": [_trace_payload(record, writer.traces_dir) for record in records],
            "count": len(records),
            "bytes": sum(record.size_bytes for record in records),
            "redact_traces": writer.policy.redact_traces,
            "trace_retention_days": writer.policy.trace_retention_days,
        }
        emit(payload, _trace_lines(records), as_json=as_json)


@traces_app.command("purge")
def traces_purge(
    workspace: WorkspaceOption = None,
    everything: Annotated[
        bool, typer.Option("--all", help="Delete every trace, whatever its age.")
    ] = False,
    older_than: Annotated[
        int | None,
        typer.Option(
            "--older-than",
            min=0,
            help="Delete traces older than this many days; defaults to the policy retention.",
            show_default=False,
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Delete traces: all of them, or every day older than a cutoff."""
    with cli_errors():
        if everything and older_than is not None:
            raise ResearchHarnessError("--all and --older-than ask for different things")
        ctx = context_for(workspace)
        writer = _writer(ctx.repo.layout.research_dir, ctx.repo.config.privacy)
        result = writer.purge(older_than_days=older_than, all_traces=everything)
        payload = {
            "removed_files": result.files,
            "removed_days": result.days,
            "freed_bytes": result.freed_bytes,
        }
        emit(payload, _purge_lines(result, everything, older_than, writer.policy), as_json=as_json)


def _writer(research_dir: Path, policy: EgressPolicy) -> TraceWriter:
    return TraceWriter(research_dir, policy)


# -- rendering ---------------------------------------------------------------


#: The `kind` of the model row, and what its absence means. Model egress is the largest
#: channel a workstation has, and an empty `providers:` list used to remove the whole
#: section from the report rather than say so — leaving a complete-looking table that
#: disclosed nothing about the one channel the researcher was checking (dogfood F17).
NO_MODEL_PROVIDERS = "(none configured — model stages will refuse)"


def _egress_lines(report: EgressReport, *, models_configured: bool = True) -> list[str]:
    rows = [("provider", "kind", "endpoint", "sends", "policy", "key")]
    rows += [
        (
            entry.label,
            entry.kind,
            entry.endpoint_host,
            _sends(entry.sends_source_text, entry.sends_identifiers),
            "allowed" if entry.allowed_by_policy else "DENIED",
            _key(entry.key_env, entry.key_present),
        )
        for entry in report.entries
    ]
    if not models_configured:
        # Always a model row, even when there is nothing to put in it. A section that
        # disappears reads as "nothing goes out this way"; the truth is "nothing can run".
        rows.append((NO_MODEL_PROVIDERS, "model", "-", "-", "-", "-"))
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    ]
    if not models_configured:
        lines.append("")
        lines.append(
            "no model providers in research.yaml: `research interrogate`, `verify`, "
            "`claim audit`, and `manuscript draft` refuse until one is added, or run offline "
            "with `--provider scripted --script <file>`"
        )
    denied = report.denied
    if denied:
        lines.append("")
        lines.extend(f"denied  {entry.label}: {entry.reason}" for entry in denied)
    lines.append("")
    lines.extend(_policy_lines(report.policy))
    return lines


def _sends(source_text: bool, identifiers: bool) -> str:
    parts = [name for name, on in (("source text", source_text), ("ids", identifiers)) if on]
    return " + ".join(parts) if parts else "nothing"


def _key(env_var: str | None, present: bool) -> str:
    if env_var is None:
        return "-"
    return f"{env_var} ({'set' if present else 'unset'})"


def _policy_lines(policy: EgressPolicy) -> list[str]:
    hosts = ", ".join(policy.allowed_hosts) if policy.allowed_hosts else "any declared host"
    retention = (
        "kept until purged"
        if policy.trace_retention_days is None
        else f"{policy.trace_retention_days} days"
    )
    return [
        "privacy policy",
        f"  external models    {policy.external_models}",
        f"  search providers   {policy.search_providers}",
        f"  allowed hosts      {hosts}",
        f"  source text        {'may leave' if policy.allow_source_text else 'must not leave'}",
        f"  identifiers        {'may leave' if policy.allow_identifiers else 'must not leave'}",
        f"  traces             {'redacted' if policy.redact_traces else 'verbatim'}, {retention}",
    ]


def _set_lines(policy: EgressPolicy, changed: list[str]) -> list[str]:
    return [f"updated {', '.join(changed)} in research.yaml", "", *_policy_lines(policy)]


def _trace_payload(record: TraceRecord, root: Path) -> dict[str, Any]:
    return {
        "path": str(record.path),
        "name": record.name,
        "day": record.day,
        "kind": record.kind,
        "fingerprint": record.fingerprint,
        "size_bytes": record.size_bytes,
        "root": str(root),
    }


def _trace_lines(records: list[TraceRecord]) -> list[str]:
    if not records:
        return ["no traces on disk"]
    lines = [
        f"{record.day}  {record.kind:<16}  {record.fingerprint:<8}  {record.size_bytes:>8} B"
        for record in records
    ]
    total = sum(record.size_bytes for record in records)
    lines.append(f"{len(records)} trace(s), {total} bytes")
    lines.append("traces are disposable diagnostics and carry no scientific authority")
    return lines


def _purge_lines(
    result: PurgeResult, everything: bool, older_than: int | None, policy: EgressPolicy
) -> list[str]:
    if everything:
        scope = "every trace"
    elif older_than is not None:
        scope = f"traces older than {older_than} days"
    elif policy.trace_retention_days is not None:
        scope = f"traces older than {policy.trace_retention_days} days (policy retention)"
    else:
        scope = "nothing: this project keeps traces until they are purged explicitly"
    return [
        f"purged {scope}",
        f"  files              {result.files}",
        f"  days               {result.days}",
        f"  freed              {result.freed_bytes} bytes",
    ]

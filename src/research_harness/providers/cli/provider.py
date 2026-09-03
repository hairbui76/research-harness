"""`CliModelProvider`: one `ModelRequest`, one bounded subprocess, one `RawCompletion`.

CLI providers spec §12, §13, §14, §15. The prompt is rendered deterministically and delivered over
stdin or RPC; the process runs in an empty temp cwd with a filtered environment; the
stream parser feeds the engine's small vocabulary; a tool event is a bounded-authority
violation; and the final text goes back through `ModelProvider.complete()` so validation
stays the shared path. `stream()` answers a `ChatReply` turn in prose, delta by delta.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from collections.abc import Callable, Generator, Iterator, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from research_harness.providers.cli.detection import resolve_executable
from research_harness.providers.cli.environment import bounded_environment
from research_harness.providers.cli.errors import (
    CliResponseError,
    CliTransportError,
    classify_failure,
    describe_runtime,
    provider_name,
    redact,
)
from research_harness.providers.cli.parsers import CliEvent, parser_for
from research_harness.providers.cli.process import (
    BoundedProcess,
    OutputLimitExceeded,
    ProcessTimeout,
)
from research_harness.providers.cli.prompt import render_chat_prompt, render_prompt
from research_harness.providers.cli.registry import get_runtime
from research_harness.providers.cli.transport import transport_for
from research_harness.providers.cli.types import DEFAULT_MODEL, CliInvocation, CliRuntimeDef
from research_harness.providers.models.base import (
    EgressDeclaration,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderCapabilities,
    RawCompletion,
    TraceSink,
    Usage,
    canonical_json,
    trace_payload,
)
from research_harness.providers.models.media import media_parts
from research_harness.providers.models.streaming import StreamDelta

__all__ = ["CliModelProvider", "SpawnFactory", "default_cli_capabilities"]

logger = logging.getLogger(__name__)

SpawnFactory = Callable[..., BoundedProcess]
HARNESS_LEVELS = frozenset({"low", "medium", "high"})


def default_cli_capabilities(
    definition: CliRuntimeDef, model: str | None = None
) -> ProviderCapabilities:
    """Declared without spawning anything: text-only, structured, always external egress."""
    window = definition.default_context_tokens
    for option in definition.fallback_models:
        if model and option.id == model and option.context_tokens:
            window = option.context_tokens
    where = (
        definition.egress_host
        if definition.egress == "external"
        else "a destination the CLI does not disclose"
    )
    return ProviderCapabilities(
        structured_output=definition.structured_output,
        max_context_tokens=window,
        reasoning_levels=set(HARNESS_LEVELS),
        vision=False,
        input_media=frozenset(),
        egress=EgressDeclaration(
            endpoint_host=definition.egress_host,
            sends_source_text=True,
            sends_identifiers=True,
            description=(
                f"The {definition.name} process starts locally, but research content and "
                f"object IDs go to {where}: the request leaves this workstation."
            ),
        ),
    )


class _Collector:
    """What the stream said so far, and whether it is finished."""

    def __init__(self) -> None:
        self.deltas: list[str] = []
        self.final: str | None = None
        self.usage = Usage()
        self.model: str | None = None
        self.stop_reason: str | None = None
        self.error: CliEvent | None = None
        self.tool: str | None = None
        self.done = False

    def take(self, event: CliEvent) -> str | None:
        """Absorb one event; return the new text a streaming consumer should see."""
        if event.kind == "text_delta":
            self.deltas.append(event.text)
            return event.text
        if event.kind == "final_text":
            self.final = event.text
            streamed = "".join(self.deltas)
            if event.text.startswith(streamed) and len(event.text) > len(streamed):
                rest = event.text[len(streamed) :]
                self.deltas.append(rest)
                return rest
            return None
        if event.kind == "usage" and event.usage is not None:
            self.usage = event.usage
        elif event.kind == "model" and event.model:
            self.model = event.model
        elif event.kind == "stop":
            self.stop_reason = event.stop_reason
        elif event.kind == "error":
            self.error = event
        elif event.kind == "tool":
            self.tool = event.tool or "tool"
        elif event.kind == "done":
            self.done = True
        return None

    @property
    def finished(self) -> bool:
        return self.done or self.error is not None or self.tool is not None

    def text(self) -> str:
        return self.final if self.final is not None else "".join(self.deltas)


class CliModelProvider(ModelProvider):
    """A subscription-backed CLI behind the neutral provider contract (spec §12)."""

    def __init__(
        self,
        runtime: CliRuntimeDef | str,
        model: str = DEFAULT_MODEL,
        *,
        reasoning: str | None = None,
        timeout: float = 300.0,
        capabilities: ProviderCapabilities | None = None,
        env: Mapping[str, str] | None = None,
        executable: Path | None = None,
        version: str | None = None,
        spawn: SpawnFactory = BoundedProcess.spawn,
    ) -> None:
        self.runtime = get_runtime(runtime) if isinstance(runtime, str) else runtime
        self.name = provider_name(self.runtime.id)
        self.model = model
        self.reasoning = reasoning
        self._timeout = timeout
        self._capabilities = capabilities or default_cli_capabilities(self.runtime, model)
        self._env: Mapping[str, str] | None = env
        self._executable = executable
        self._spawn = spawn
        self.version = version
        """The installed version when the caller learned it from a scan; never probed here."""
        self._resolved: Path | None = None
        self.last_process: BoundedProcess | None = None

    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def trace_metadata(self) -> dict[str, Any]:
        """Runtime identity for a trace (spec §19); never a token or a raw path."""
        return {
            "runtime": self.runtime.id,
            "version": self.version,
            "protocol": self.runtime.protocol,
            "transport": self.runtime.transport,
            "model": self.model,
            "executable": self._display_executable(),
        }

    # -- the neutral contract -------------------------------------------------

    def _execute[T: BaseModel](
        self, request: ModelRequest[T], schema_json: dict[str, Any]
    ) -> RawCompletion:
        """One bounded run; the final text goes back through `ModelProvider.complete()`."""
        collected = _Collector()
        completion: RawCompletion | None = None
        for _text, done in self._run(request, schema_json=schema_json, collected=collected):
            if done is not None:
                completion = done
        if completion is None:  # pragma: no cover - `_run` always ends with the completion
            raise CliTransportError(
                f"{self._who()}: the run produced no completion",
                runtime=self.runtime.id,
                diagnostic="missing_terminal_event",
            )
        return completion

    def stream(self, request: ModelRequest[Any]) -> Iterator[StreamDelta]:
        """Prose deltas for a `ChatReply` turn; the final delta carries model, stop, usage.

        A generator on purpose: a consumer that abandons it triggers `GeneratorExit` inside
        `_drive`, which cancels the process (spec §14).
        """
        collected = _Collector()
        index = 0
        run = self._run(request, schema_json=None, collected=collected)
        # Closed explicitly rather than left to the garbage collector: abandoning this
        # generator must stop the subprocess *now*, and the dropped reference only reaches
        # `_drive` when the cycle detector next runs -- minutes of a live CLI turn later.
        try:
            for text, completion in run:
                if completion is None:
                    yield StreamDelta(text=text, index=index)
                    index += 1
                else:
                    yield StreamDelta(
                        text=text,
                        index=index,
                        final=True,
                        model=completion.model,
                        stop_reason=completion.stop_reason,
                        usage=completion.usage,
                    )
        finally:
            run.close()

    def _trace[T: BaseModel](
        self, sink: TraceSink, request: ModelRequest[T], response: ModelResponse[T]
    ) -> None:
        try:
            sink.record(
                "completion",
                provider=self.name,
                model=response.model,
                request_fingerprint=response.request_fingerprint,
                payload={**trace_payload(request, response), "cli": self.trace_metadata()},
            )
        except Exception:
            logger.warning("could not write a %s completion trace", self.name, exc_info=True)

    # -- the run ----------------------------------------------------------------

    def _run(
        self,
        request: ModelRequest[Any],
        *,
        schema_json: dict[str, Any] | None,
        collected: _Collector,
    ) -> Generator[tuple[str, RawCompletion | None]]:
        """A `Generator`, not an `Iterator`: `stream()` closes it to stop the subprocess."""
        if media_parts(request.inputs):
            raise CliResponseError(
                f"{self._who()}: CLI providers accept text-only inputs in this release",
                runtime=self.runtime.id,
                diagnostic="invalid_invocation",
            )
        env_base: Mapping[str, str] = self._env if self._env is not None else os.environ
        executable = self._executable or resolve_executable(self.runtime, env_base)
        self._resolved = executable
        if executable is None:
            raise classify_failure(
                runtime=self.runtime.id,
                model=self.model,
                version=self.version,
                os_error="ENOENT: no executable on PATH",
                login_guidance=self.runtime.login_guidance,
            )
        prompt = (
            render_prompt(request, schema_json)
            if schema_json is not None
            else render_chat_prompt(request)
        )
        cwd = Path(tempfile.mkdtemp(prefix="rh-cli-"))
        try:
            schema_path: Path | None = None
            if schema_json is not None:
                schema_path = cwd / "response.schema.json"
                schema_path.write_text(canonical_json(schema_json), encoding="utf-8")
            invocation = CliInvocation(
                model=None if self.model == DEFAULT_MODEL else self.model,
                reasoning=self._effort(request),
                cwd=cwd,
                request_id=uuid4().hex,
                schema_path=schema_path,
            )
            argv = (str(executable), *self.runtime.build_args(invocation))
            env = bounded_environment(self.runtime, env_base, executable=executable)
            yield from self._drive(argv, env, cwd, prompt, invocation, collected)
        finally:
            shutil.rmtree(cwd, ignore_errors=True)

    def _drive(
        self,
        argv: tuple[str, ...],
        env: Mapping[str, str],
        cwd: Path,
        prompt: str,
        invocation: CliInvocation,
        collected: _Collector,
    ) -> Iterator[tuple[str, RawCompletion | None]]:
        parser = parser_for(self.runtime)
        transport = transport_for(self.runtime)
        process = self._spawn(argv, env=env, cwd=cwd, timeout=self._timeout)
        self.last_process = process
        with process:
            transport.start(process, prompt, invocation)
            try:
                for line in process.lines():
                    if transport.intercept(process, line):
                        continue
                    for event in parser.feed(line):
                        transport.observe(process, event)
                        delta = collected.take(event)
                        if delta:
                            yield delta, None
                        if collected.finished:
                            break
                    if collected.finished:
                        break
                else:
                    for event in parser.finish():
                        delta = collected.take(event)
                        if delta:
                            yield delta, None
            except ProcessTimeout:
                transport.cancel(process)
                process.cancel()
                raise self._failure(process, timed_out=True) from None
            except OutputLimitExceeded:
                raise self._failure(process, output_limited=True) from None
            except GeneratorExit:
                transport.cancel(process)
                process.cancel()
                raise
            if collected.tool is not None:
                transport.cancel(process)
                process.cancel()
                raise CliResponseError(
                    f"{self._who()}: the runtime tried to use a tool ({collected.tool}) in "
                    f"bounded mode; the request was cancelled",
                    runtime=self.runtime.id,
                    diagnostic="bounded_authority_violation",
                )
            if collected.error is not None:
                process.cancel()
                raise self._failure(
                    process,
                    stream_error=collected.error.message,
                    stream_code=collected.error.code,
                )
            exit_code = process.wait(self._grace())
            if exit_code is None:
                process.cancel()
                exit_code = process.exit_code
            if not collected.done:
                raise self._failure(process, exit_code=exit_code)
        text = collected.text()
        if not text.strip():
            raise CliResponseError(
                f"{self._who()}: the runtime completed without an answer",
                runtime=self.runtime.id,
                diagnostic="empty_response",
            )
        yield (
            "",
            RawCompletion(
                text=text,
                usage=collected.usage,
                model=collected.model or self.model,
                stop_reason=collected.stop_reason or "end_turn",
            ),
        )

    # -- helpers ----------------------------------------------------------------

    def _effort(self, request: ModelRequest[Any]) -> str | None:
        if self.reasoning:
            return self.reasoning
        level = request.requirements.reasoning
        return level if level in self.runtime.reasoning_choices else None

    def _grace(self) -> float:
        return min(5.0, self._timeout)

    def _who(self) -> str:
        return describe_runtime(self.runtime.id, self.model, self.version)

    def _display_executable(self) -> str | None:
        path = self._executable or self._resolved
        if path is None:
            return None
        home = (
            None if self._env is None else (self._env.get("HOME") or self._env.get("USERPROFILE"))
        )
        return _redact_path(path, home=home)

    def _failure(self, process: BoundedProcess, **fields: Any) -> Exception:
        return classify_failure(
            runtime=self.runtime.id,
            model=self.model,
            version=self.version,
            stderr_tail=process.stderr_tail(),
            login_guidance=self.runtime.login_guidance,
            exit_code=fields.pop("exit_code", process.exit_code),
            **fields,
        )


def _redact_path(path: Path, *, home: str | None = None) -> str:
    """A filesystem path a trace may carry: home as `~`, then each name redacted alone.

    `redact` on the whole path would erase it: a directory chain is one long run of
    path-safe characters, which the long-token pattern cannot tell from a base64
    credential. Component by component keeps `~/.local/bin/codex` readable and still
    strips a secret that was written into one of the names.
    """
    text = str(path)
    for candidate in (home, str(Path.home())):
        if candidate and candidate not in ("/", ""):
            text = text.replace(candidate, "~")
    return os.sep.join(redact(part) for part in text.split(os.sep))

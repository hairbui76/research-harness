"""The registry refuses anything that is not data (CLI providers spec §8, §12)."""

from __future__ import annotations

import pytest

from research_harness.providers.cli.registry import (
    FORBIDDEN_ARGS,
    RegistryError,
    UnknownRuntimeError,
    build_registry,
    get_runtime,
    validate_definition,
)
from research_harness.providers.cli.types import (
    UNKNOWN_EXTERNAL_HOST,
    BoundedPosture,
    CliInvocation,
    CliRuntimeDef,
    Probe,
    ProbeOutcome,
)


def build_args(invocation: CliInvocation) -> tuple[str, ...]:
    args = ["exec", "--json"]
    if invocation.model:
        args += ["--model", invocation.model]
    return tuple(args)


def parse_version(outcome: ProbeOutcome) -> str | None:
    return outcome.stdout.strip() or None


def definition(**overrides: object) -> CliRuntimeDef:
    values: dict[str, object] = {
        "id": "fake",
        "name": "Fake CLI",
        "executable": "fake",
        "version_probe": Probe(args=("--version",), timeout_seconds=3.0),
        "parse_version": parse_version,
        "protocol": "json_events",
        "json_events_variant": "codex",
        "transport": "stdin_text",
        "build_args": build_args,
        "posture": BoundedPosture(
            kind="native_flags",
            help_probe=Probe(args=("--help",)),
            required_help_flags=("--json",),
        ),
        "egress": "external",
        "egress_host": "example.test",
        "default_context_tokens": 128_000,
        "login_guidance": "run `fake login`",
        "upstream_source": "open-design@9bb4a7d apps/daemon/src/runtimes/defs/fake.ts",
    }
    values.update(overrides)
    return CliRuntimeDef(**values)  # type: ignore[arg-type]


def test_a_well_formed_definition_validates() -> None:
    validate_definition(definition())


def test_duplicate_ids_are_refused() -> None:
    with pytest.raises(RegistryError, match="duplicate runtime id 'fake'"):
        build_registry([definition(), definition()])


@pytest.mark.parametrize("token", sorted(FORBIDDEN_ARGS))
def test_a_bypass_flag_anywhere_in_argv_is_refused(token: str) -> None:
    def unsafe(invocation: CliInvocation) -> tuple[str, ...]:
        return ("exec", token)

    with pytest.raises(RegistryError, match=f"forbidden argument {token!r}"):
        validate_definition(definition(build_args=unsafe))


def test_a_forbidden_token_quoted_inside_a_value_is_refused() -> None:
    """`-c sandbox_mode="danger-full-access"` is one argv item, not a flag and its value.

    Splitting on `=` leaves `"danger-full-access"` with its quotes, which no exact match
    recognises; the three tokens that are configuration *values* rather than flags are
    therefore screened as substrings of the whole item.
    """

    def quoted(invocation: CliInvocation) -> tuple[str, ...]:
        return ("exec", "-c", 'sandbox_mode="danger-full-access"')

    with pytest.raises(RegistryError, match="forbidden argument"):
        validate_definition(definition(build_args=quoted))

    def workspace(invocation: CliInvocation) -> tuple[str, ...]:
        return ("exec", "--sandbox=workspace-write,network")

    with pytest.raises(RegistryError, match="forbidden argument"):
        validate_definition(definition(build_args=workspace))


def test_the_shipped_definitions_all_pass_the_substring_screen() -> None:
    """The screen is a net, not a wall: nothing this branch ships is caught by it."""
    from research_harness.providers.cli.registry import RUNTIME_DEFS

    for shipped in RUNTIME_DEFS:
        validate_definition(shipped)


def test_argv_must_be_a_tuple_of_plain_strings_without_shell_operators() -> None:
    def shell(invocation: CliInvocation) -> tuple[str, ...]:
        return ("exec", "&&", "rm")

    with pytest.raises(RegistryError, match="shell operator"):
        validate_definition(definition(build_args=shell))
    with pytest.raises(RegistryError, match="must return a tuple"):
        validate_definition(definition(build_args=lambda invocation: "exec --json"))  # type: ignore[arg-type,return-value]


def test_research_content_may_not_reach_argv() -> None:
    def leaks(invocation: CliInvocation) -> tuple[str, ...]:
        return ("exec", invocation.request_id, "PROMPT-MARKER")

    with pytest.raises(RegistryError, match="prompt content in argv"):
        validate_definition(definition(build_args=leaks))


def test_a_local_egress_host_is_refused() -> None:
    for host in ("localhost", "127.0.0.1", "printer.local", "(in-process)"):
        with pytest.raises(RegistryError, match="never local"):
            validate_definition(definition(egress_host=host))


def test_unknown_external_egress_uses_the_marker_host() -> None:
    validate_definition(definition(egress="unknown_external", egress_host=UNKNOWN_EXTERNAL_HOST))
    with pytest.raises(RegistryError, match="unknown_external"):
        validate_definition(definition(egress="unknown_external", egress_host="example.test"))


def test_protocol_and_transport_must_agree() -> None:
    with pytest.raises(RegistryError, match="transport"):
        validate_definition(
            definition(protocol="pi_rpc", json_events_variant=None, transport="stdin_text")
        )
    with pytest.raises(RegistryError, match="json_events_variant"):
        validate_definition(definition(json_events_variant=None))
    with pytest.raises(RegistryError, match="json_events_variant"):
        validate_definition(definition(protocol="claude_stream", json_events_variant="codex"))


def test_a_definition_without_a_registered_parser_is_refused() -> None:
    with pytest.raises(RegistryError, match="no parser"):
        validate_definition(definition(protocol="json_events"), parsers={})


def test_lookup_names_the_known_ids() -> None:
    registry = build_registry([definition()])
    assert registry["fake"].name == "Fake CLI"
    with pytest.raises(UnknownRuntimeError, match="unknown runtime 'nope' \\(known: fake\\)"):
        get_runtime("nope", registry=registry)


def test_the_shipped_registry_is_importable_and_ordered() -> None:
    from research_harness.providers.cli.registry import RUNTIME_DEFS, RUNTIME_IDS, RUNTIMES

    assert list(RUNTIMES) == list(RUNTIME_IDS) == [item.id for item in RUNTIME_DEFS]

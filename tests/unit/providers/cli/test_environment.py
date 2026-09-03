"""The child environment: enough to log in, nothing that pays by the token (spec §12)."""

from __future__ import annotations

from pathlib import Path

from research_harness.providers.cli.environment import ALWAYS_DROP, FIXED_ENV, bounded_environment
from tests.unit.providers.cli.test_registry import definition

BASE = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/home/alice",
    "USER": "alice",
    "LANG": "en_US.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TMPDIR": "/tmp",
    "HTTPS_PROXY": "http://proxy.test:3128",
    "OPENAI_API_KEY": "sk-metered",
    "ANTHROPIC_API_KEY": "sk-ant-metered",
    "ANTHROPIC_AUTH_TOKEN": "tok",
    "CODEX_API_KEY": "k",
    "CURSOR_API_KEY": "k",
    "AWS_SECRET_ACCESS_KEY": "k",
    "AZURE_OPENAI_API_KEY": "k",
    "GOOGLE_APPLICATION_CREDENTIALS": "/home/alice/creds.json",
    "GITHUB_TOKEN": "ghp_x",
    "MY_SERVICE_SECRET_VALUE": "s",
    "DATABASE_URL": "postgres://u:p@h/db",
    "CODEX_HOME": "/home/alice/.codex",
    "RANDOM_THING": "1",
}


def test_only_the_allowlist_survives_and_every_credential_is_removed() -> None:
    env = bounded_environment(definition(), BASE)
    assert set(env) == {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "HTTPS_PROXY",
        *FIXED_ENV,
    }
    for key in BASE:
        if any(pattern.match(key) for pattern in ALWAYS_DROP):
            assert key not in env


def test_a_definition_may_keep_its_own_config_variables_but_never_a_key() -> None:
    env = bounded_environment(definition(env_keep=("CODEX_HOME", "OPENAI_API_KEY")), BASE)
    assert env["CODEX_HOME"] == "/home/alice/.codex"
    assert "OPENAI_API_KEY" not in env, "the deny list wins over a definition's keep list"


def test_a_definition_may_drop_and_set_variables() -> None:
    env = bounded_environment(
        definition(env_drop=("HTTPS_PROXY",), env_set={"OPENCODE_DISABLE_PROJECT_CONFIG": "true"}),
        BASE,
    )
    assert "HTTPS_PROXY" not in env
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "true"


def test_the_executable_directory_leads_path() -> None:
    env = bounded_environment(definition(), BASE, executable=Path("/opt/tools/bin/fake"))
    assert env["PATH"].split(":")[0] == "/opt/tools/bin"


def test_fixed_values_make_output_machine_readable() -> None:
    env = bounded_environment(definition(), BASE)
    assert (
        env["NO_COLOR"] == "1" and env["TERM"] == "dumb" and env["RESEARCH_HARNESS_BOUNDED"] == "1"
    )

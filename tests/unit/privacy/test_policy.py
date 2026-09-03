"""The egress policy: what it permits, what it refuses, and how it says so.

ROADMAP Task 17.4 / Product SS34. Every assertion here is about the rule itself; nothing in
this module opens a socket or a workspace.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from research_harness.privacy.policy import (
    EgressDeniedError,
    EgressPolicy,
    check_egress,
    enforce_egress,
    is_local_endpoint,
    refuse_inline_secrets,
    secret_keys_in,
)
from research_harness.providers.models.base import EgressDeclaration
from research_harness.workspace.serialization import dump_yaml, load_yaml

OPENAI_HOST = "api.openai.com"


def declaration(
    host: str = OPENAI_HOST, *, source_text: bool = True, identifiers: bool = True
) -> EgressDeclaration:
    return EgressDeclaration(
        endpoint_host=host,
        sends_source_text=source_text,
        sends_identifiers=identifiers,
        description="test declaration",
    )


# -- defaults ----------------------------------------------------------------


def test_the_default_policy_permits_what_the_harness_did_before_it_existed() -> None:
    policy = EgressPolicy()
    assert policy.external_models == "allowed"
    assert policy.search_providers == "allowed"
    assert policy.allowed_hosts == ()
    assert policy.allow_source_text is True
    assert policy.allow_identifiers is True
    assert policy.trace_retention_days == 30
    assert policy.redact_traces is False
    assert check_egress(policy, declaration(), kind="model").allowed


def test_a_policy_round_trips_through_canonical_yaml() -> None:
    policy = EgressPolicy(
        external_models="disabled",
        allowed_hosts=("api.anthropic.com",),
        allow_source_text=False,
        search_providers="disabled",
        trace_retention_days=None,
        redact_traces=True,
    )
    assert load_yaml(dump_yaml(policy), EgressPolicy) == policy


def test_allowed_hosts_are_normalized_so_case_never_decides_egress() -> None:
    policy = EgressPolicy(allowed_hosts=("API.OpenAI.com ", "", "  "))
    assert policy.allowed_hosts == (OPENAI_HOST,)


def test_a_negative_trace_retention_is_refused() -> None:
    with pytest.raises(ValidationError):
        EgressPolicy(trace_retention_days=-1)


def test_an_unknown_privacy_field_is_refused_rather_than_silently_ignored() -> None:
    with pytest.raises(ValidationError):
        EgressPolicy.model_validate({"external_modles": "disabled"})


# -- local endpoints ---------------------------------------------------------


@pytest.mark.parametrize(
    "host", ["localhost", "127.0.0.1", "127.0.1.1", "::1", "workstation.local", "(in-process)", ""]
)
def test_a_local_endpoint_is_always_allowed_whatever_the_policy_says(host: str) -> None:
    policy = EgressPolicy(
        external_models="disabled",
        search_providers="disabled",
        allowed_hosts=("nowhere.example",),
        allow_source_text=False,
        allow_identifiers=False,
    )
    assert is_local_endpoint(host)
    for kind in ("model", "embedding", "search"):
        check = check_egress(policy, declaration(host), kind=kind)  # type: ignore[arg-type]
        assert check.allowed, f"{host} refused for {kind}: {check.reason}"


def test_a_remote_host_is_not_mistaken_for_a_local_one() -> None:
    assert not is_local_endpoint(OPENAI_HOST)
    assert not is_local_endpoint("localhost.evil.example")


# -- the external-model switch -----------------------------------------------


def test_disabling_external_models_refuses_every_non_local_model_and_embedding() -> None:
    policy = EgressPolicy(external_models="disabled")
    for kind in ("model", "embedding"):
        check = check_egress(policy, declaration(), kind=kind)  # type: ignore[arg-type]
        assert not check.allowed
        assert check.policy_fields == ("external_models",)
    assert check_egress(policy, declaration(), kind="search").allowed


def test_disabling_search_providers_refuses_discovery_but_not_models() -> None:
    policy = EgressPolicy(search_providers="disabled")
    denied = check_egress(policy, declaration("api.crossref.org"), kind="search")
    assert not denied.allowed
    assert denied.policy_fields == ("search_providers",)
    assert check_egress(policy, declaration(), kind="model").allowed


# -- host and content restrictions -------------------------------------------


def test_allowed_hosts_refuse_every_host_outside_the_list() -> None:
    policy = EgressPolicy(allowed_hosts=("api.anthropic.com",))
    assert check_egress(policy, declaration("api.anthropic.com"), kind="model").allowed
    denied = check_egress(policy, declaration(OPENAI_HOST), kind="model")
    assert not denied.allowed
    assert denied.policy_fields == ("allowed_hosts",)
    assert "api.anthropic.com" in denied.reason


def test_refusing_source_text_blocks_only_providers_that_send_it() -> None:
    policy = EgressPolicy(allow_source_text=False)
    denied = check_egress(policy, declaration(source_text=True), kind="model")
    assert not denied.allowed
    assert denied.policy_fields == ("allow_source_text",)
    metadata_only = declaration("api.crossref.org", source_text=False, identifiers=True)
    assert check_egress(policy, metadata_only, kind="search").allowed


def test_refusing_identifiers_blocks_only_providers_that_send_them() -> None:
    policy = EgressPolicy(allow_identifiers=False)
    denied = check_egress(policy, declaration("api.crossref.org", source_text=False), kind="search")
    assert not denied.allowed
    assert denied.policy_fields == ("allow_identifiers",)
    anonymous = declaration("api.openai.com", source_text=True, identifiers=False)
    assert check_egress(policy, anonymous, kind="model").allowed


def test_every_failing_rule_is_reported_not_just_the_first() -> None:
    policy = EgressPolicy(
        external_models="disabled", allowed_hosts=("elsewhere.example",), allow_source_text=False
    )
    check = check_egress(policy, declaration(), kind="model")
    assert not check.allowed
    assert check.policy_fields == ("external_models", "allowed_hosts", "allow_source_text")
    assert len(check.reasons) == 3


# -- refusal -----------------------------------------------------------------


def test_the_refusal_names_the_provider_the_host_and_the_policy_field() -> None:
    policy = EgressPolicy(external_models="disabled")
    with pytest.raises(EgressDeniedError) as caught:
        enforce_egress(policy, declaration(), provider="openai/gpt-x", kind="model")
    error = caught.value
    assert error.provider == "openai/gpt-x"
    assert error.endpoint_host == OPENAI_HOST
    assert error.policy_fields == ("external_models",)
    message = str(error)
    assert "openai/gpt-x" in message
    assert OPENAI_HOST in message
    assert "privacy.external_models" in message


def test_enforcing_an_allowed_provider_does_nothing() -> None:
    enforce_egress(EgressPolicy(), declaration(), provider="openai/gpt-x", kind="model")


# -- secrets in configuration ------------------------------------------------


@pytest.mark.parametrize("key", ["api_key", "API_KEY", "token", "secret", "authorization"])
def test_a_credential_written_into_configuration_is_refused_with_the_fix(key: str) -> None:
    entry = {"name": "fast", "kind": "openai", key: "sk-live-do-not-store"}
    assert secret_keys_in(entry) == (key,)  # reported as written, so the fix is obvious
    with pytest.raises(ValueError) as caught:
        refuse_inline_secrets(entry, where="providers[0] in research.yaml")
    message = str(caught.value)
    assert "api_key_env" in message
    assert "environment variables" in message
    assert "sk-live-do-not-store" not in message


def test_an_entry_that_only_names_an_environment_variable_is_accepted() -> None:
    entry = {"name": "fast", "kind": "openai", "api_key_env": "OPENAI_API_KEY"}
    assert secret_keys_in(entry) == ()
    refuse_inline_secrets(entry, where="providers[0] in research.yaml")

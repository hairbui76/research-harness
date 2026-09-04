"""`SessionDefaults` carries a binding in one of three shapes (binding spec §7)."""

import pytest
from pydantic import ValidationError

from research_harness.domain.conversation import ModelIdentity, SessionDefaults


def test_a_runtime_binding_carries_a_reasoning_level() -> None:
    defaults = SessionDefaults(
        model=ModelIdentity(provider="local_cli:codex", model="gpt-5.5"), reasoning="high"
    )
    assert defaults.reasoning == "high"


def test_an_entry_binding_carries_no_reasoning() -> None:
    defaults = SessionDefaults(model=ModelIdentity(provider="entry", model="codex-sub"))
    assert defaults.reasoning is None


def test_reasoning_without_a_runtime_binding_is_refused() -> None:
    with pytest.raises(ValidationError, match="runtime binding"):
        SessionDefaults(model=ModelIdentity(provider="entry", model="codex-sub"), reasoning="high")
    with pytest.raises(ValidationError, match="runtime binding"):
        SessionDefaults(reasoning="high")


def test_an_old_record_without_the_field_still_loads() -> None:
    defaults = SessionDefaults.model_validate(
        {"model": {"provider": "local", "model": "local-small"}, "mode": None, "token_budget": 8000}
    )
    assert defaults.reasoning is None and defaults.token_budget == 8000

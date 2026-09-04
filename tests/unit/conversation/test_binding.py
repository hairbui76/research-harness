"""What a session's `defaults.model` means (binding spec §7, §9, §15)."""

from research_harness.conversation.binding import (
    EntryBinding,
    RuntimeBinding,
    binding_of,
    binding_words,
    entry_identity,
    runtime_identity,
)
from research_harness.domain.conversation import ModelIdentity, SessionDefaults


def test_a_runtime_binding_names_the_runtime_model_and_reasoning() -> None:
    defaults = SessionDefaults(model=runtime_identity("codex", "gpt-5.5"), reasoning="high")
    binding = binding_of(defaults)
    assert binding == RuntimeBinding(runtime="codex", model="gpt-5.5", reasoning="high")
    assert binding.label == "session:codex"
    assert binding.words == "session:codex/gpt-5.5 (reasoning high)"
    assert binding_words(SessionDefaults(model=runtime_identity("claude", "default"))) == (
        "session:claude/default"
    )


def test_an_entry_binding_names_the_entry() -> None:
    binding = binding_of(SessionDefaults(model=entry_identity("codex-sub")))
    assert binding == EntryBinding(name="codex-sub")
    assert binding.words == "entry codex-sub"


def test_no_binding_means_the_project_default() -> None:
    assert binding_of(SessionDefaults()) is None
    assert binding_words(SessionDefaults()) == "project default"


def test_a_record_written_before_bindings_is_no_binding() -> None:
    """Only `entry` and `local_cli:<runtime>` bind; every other provider is a stale label.

    `defaults.model` was never read on the send path before bindings existed, and `create
    --model X` stored whatever it was given -- `provider == model == X`, or the two halves
    of an `openai/gpt-4`. Reading either as a binding would fail every send of an old
    session on a name that never named a `research.yaml` entry (spec §15).
    """
    old = SessionDefaults(model=ModelIdentity(provider="fast", model="fast"))
    assert binding_of(old) is None
    assert binding_words(old) == "project default"
    split = SessionDefaults(model=ModelIdentity(provider="openai", model="gpt-4"))
    assert binding_of(split) is None
    assert binding_words(split) == "project default"

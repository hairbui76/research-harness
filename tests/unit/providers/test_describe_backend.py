"""One answer to "which provider and model would answer this role", for the whole harness.

`evidence/extraction.py` and `claims/audit.py` each carried their own copy of this, and the
copies were free to drift while both fed stage fingerprints (Product 19.1) - two answers to
one question is one answer too many. `providers.models.describe_backend` is the
implementation; the two old names delegate and stay importable.
"""

from __future__ import annotations

import pytest

from research_harness.claims.audit import backend_label as audit_backend_label
from research_harness.evidence.extraction import (
    BackendInfo,
    backend_label,
    resolve_backend,
)
from research_harness.providers.models import BackendInfo as CanonicalBackendInfo
from research_harness.providers.models import describe_backend
from research_harness.providers.models.base import ModelProvider, ProviderCapabilities
from research_harness.providers.models.router import ModelRouter, ProviderEntry
from research_harness.roles.auditor import CLAIM_AUDITOR
from research_harness.roles.extractor import EXTRACTOR

from .conftest import FakeProvider, capabilities


class ModellessProvider(ModelProvider):
    """An adapter that names no model at all; nothing may invent one for it."""

    name = "modelless"

    def capabilities(self) -> ProviderCapabilities:
        return capabilities()

    def _execute(self, request: object, schema_json: object) -> object:  # pragma: no cover
        raise AssertionError("describe_backend must never call a provider")


def router(*entries: ProviderEntry) -> ModelRouter:
    return ModelRouter(entries)


def test_a_bare_adapter_answers_with_the_model_it_was_configured_with() -> None:
    backend = describe_backend(FakeProvider("vendor-a", model="model-x"), EXTRACTOR)
    assert backend == CanonicalBackendInfo(provider="vendor-a", model="model-x")
    assert backend.label == "vendor-a/model-x"


def test_an_adapter_that_names_no_model_is_unknown_rather_than_invented() -> None:
    assert describe_backend(ModellessProvider(), EXTRACTOR).model == "unknown"


def test_a_router_answers_by_selecting_without_calling_anything() -> None:
    fast = FakeProvider("vendor-a", model="fast")
    slow = FakeProvider("vendor-b", model="slow")
    selected = describe_backend(
        router(
            ProviderEntry(provider=slow, model="slow", priority=50),
            ProviderEntry(provider=fast, model="fast", priority=10),
        ),
        EXTRACTOR,
    )
    assert selected == CanonicalBackendInfo(provider="vendor-a", model="fast")
    assert fast.calls == [] and slow.calls == []


def test_the_router_answer_follows_the_role_it_is_asked_about() -> None:
    """Two roles routed to two providers must not report the same backend."""
    extractor = FakeProvider("vendor-a", model="extract-1")
    auditor = FakeProvider("vendor-b", model="audit-1")
    table = router(
        ProviderEntry(provider=extractor, model="extract-1", roles={EXTRACTOR.name}),
        ProviderEntry(provider=auditor, model="audit-1", roles={CLAIM_AUDITOR.name}),
    )
    assert describe_backend(table, EXTRACTOR).label == "vendor-a/extract-1"
    assert describe_backend(table, CLAIM_AUDITOR).label == "vendor-b/audit-1"


# -- the names that used to hold their own copies ----------------------------


def test_resolve_backend_is_the_same_answer_under_its_old_name() -> None:
    provider = FakeProvider("vendor-a", model="model-x")
    assert resolve_backend(provider, EXTRACTOR) == describe_backend(provider, EXTRACTOR)
    assert backend_label(provider, EXTRACTOR) == "vendor-a/model-x"
    assert BackendInfo is CanonicalBackendInfo


def test_the_claim_audit_label_is_the_same_answer() -> None:
    provider = FakeProvider("vendor-a", model="model-x")
    assert audit_backend_label(provider, CLAIM_AUDITOR) == backend_label(provider, CLAIM_AUDITOR)


def test_the_claim_audit_label_is_none_when_no_model_pass_runs() -> None:
    """The deterministic audit names no backend rather than naming a fictional one."""
    assert audit_backend_label(None, CLAIM_AUDITOR) is None


@pytest.mark.parametrize("role", [EXTRACTOR, CLAIM_AUDITOR])
def test_a_backend_label_is_always_provider_slash_model(role: object) -> None:
    info = describe_backend(FakeProvider("vendor-a", model="m"), role)  # type: ignore[arg-type]
    assert info.label == f"{info.provider}/{info.model}"

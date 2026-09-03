"""`corpus.search`: external discovery is a capability, not a CLI-only command.

Product 22 names `corpus.search`, and it was the one name in the list this build recorded
as *planned* rather than registered, because the search provider registry needs the
process environment. It is registered now: the handler builds the registry from
`os.environ` under the project's privacy policy, and the `SearchRun` is persisted through
`search_run.record` inside `DiscoveryService`, exactly as `research discover` does.

The registry builder is monkeypatched so the test runs offline against in-memory sources.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

import research_harness.providers.search as search_package
from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.extra_handlers import DiscoverCorpusRequest, discover_corpus
from research_harness.capabilities.permissions import Permission, PermissionDenied, Principal
from research_harness.capabilities.registry import MutationResponse, build_default_registry
from research_harness.domain.enums import ResearchEventType, ScreeningState
from research_harness.privacy.policy import EgressPolicy
from research_harness.providers.search import SearchProviderRegistry
from tests.integration.discovery.fakes import FakeSearchSource, record

CAPABILITY = "corpus.search"


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Replace the configured registry with two in-memory sources; record how it was built."""
    calls: list[dict[str, Any]] = []
    provider = FakeSearchSource(
        "openalex",
        pages=[
            [
                record("openalex", doi="10.1/aaa", title="Encrypted traffic survey", year=2023),
                record("openalex", doi="10.1/bbb", title="Flow representations", year=2024),
            ]
        ],
    )

    def build(env: Any = None, **kwargs: Any) -> SearchProviderRegistry:
        calls.append({"env": env, **kwargs})
        return SearchProviderRegistry([provider])

    monkeypatch.setattr(search_package, "build_search_registry", build)
    yield calls


def test_corpus_search_is_registered_rather_than_planned() -> None:
    registry = build_default_registry()
    assert CAPABILITY in registry
    assert CAPABILITY not in {item.name for item in registry.planned()}


def test_the_shrunken_planned_list_still_says_why_for_what_is_left() -> None:
    """`describe().planned` shrinks; what remains keeps its reason (Product 22)."""
    planned = build_default_registry().planned()
    assert {item.name for item in planned} == {"project.init", "synthesis.find_pattern"}
    assert all(item.reason.strip() for item in planned)


def test_the_registry_is_built_from_the_environment_under_the_project_policy(
    project: CapabilityContext, sources: list[dict[str, Any]]
) -> None:
    """Credentials come from the process environment; the policy comes from the workspace."""
    import os

    discover_corpus(
        project,
        DiscoverCorpusRequest(question="what represents traffic?", query="encrypted traffic"),
    )

    assert len(sources) == 1
    assert sources[0]["env"] is os.environ
    assert sources[0]["policy"] == EgressPolicy()


def test_the_run_is_persisted_through_search_run_record(
    project: CapabilityContext, sources: list[dict[str, Any]]
) -> None:
    """Nothing joins the corpus; what is written is the record of the operation."""
    response = discover_corpus(
        project,
        DiscoverCorpusRequest(question="what represents traffic?", query="encrypted traffic"),
    )

    assert response.capability == "search_run.record"
    assert response.event.event is ResearchEventType.SEARCH_RUN_RECORDED
    runs = project.repo.list_search_runs()
    assert len(runs) == 1
    assert runs[0].question == "what represents traffic?"
    assert [candidate.screening for candidate in runs[0].candidates] == [
        ScreeningState.DISCOVERED,
        ScreeningState.DISCOVERED,
    ]
    assert project.repo.list_works() == []


def test_the_capability_runs_through_the_registry_as_the_researcher(
    project: CapabilityContext, sources: list[dict[str, Any]]
) -> None:
    registry = build_default_registry()
    response = registry.invoke(
        CAPABILITY,
        project,
        DiscoverCorpusRequest(question="what represents traffic?", query="encrypted traffic"),
        principal=Principal.human(),
    )
    assert isinstance(response, MutationResponse)
    assert response.capability == "search_run.record"


def test_an_agent_host_may_not_run_it(
    project: CapabilityContext, sources: list[dict[str, Any]]
) -> None:
    """It records canonical state, so it carries the same refusal every mutation does."""
    registry = build_default_registry()
    assert registry.get(CAPABILITY).permission is Permission.MUTATE
    with pytest.raises(PermissionDenied):
        registry.invoke(
            CAPABILITY,
            project,
            DiscoverCorpusRequest(question="q", query="encrypted traffic"),
            principal=Principal.agent_host("claude"),
        )
    assert sources == []

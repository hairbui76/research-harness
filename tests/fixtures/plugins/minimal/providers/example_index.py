"""A discovery connector that declares its egress and returns an honest empty page.

`PROVIDER` is the descriptor the loader validates against the manifest's `egress:` block;
`build(env)` is the factory. The provider is built lazily, so loading this plugin opens no
connection, and its own `EgressDeclaration` is checked against the manifest at build time.
"""

from __future__ import annotations

from collections.abc import Mapping

from research_harness.providers.models.base import EgressDeclaration
from research_harness.providers.search.base import (
    SearchPage,
    SearchProvider,
    SearchProviderCapabilities,
    SearchQuery,
)

PROVIDER = {"name": "minimal-example-index", "endpoint_host": "index.example.org"}


class ExampleIndex(SearchProvider):
    """A source that is reachable and simply has nothing to say about any query."""

    name = "minimal-example-index"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    def capabilities(self) -> SearchProviderCapabilities:
        """What this source supports, and exactly what leaves the workstation."""
        return SearchProviderCapabilities(
            supports_cursor=False,
            supports_year_filter=False,
            supports_references=False,
            supports_citations=False,
            requires_api_key=False,
            egress=EgressDeclaration(
                endpoint_host="index.example.org",
                sends_source_text=False,
                sends_identifiers=True,
                description="Sends the query string and DOIs; never sends source text.",
            ),
        )

    def search(self, query: SearchQuery) -> SearchPage:
        """A successful search that matched nothing: an empty page, never an error."""
        return SearchPage(source=self.name, query=query, hits=(), incomplete=False)


def build(env: Mapping[str, str]) -> ExampleIndex:
    """Construct the provider from the environment the host chose to expose."""
    return ExampleIndex(api_key=env.get("MINIMAL_EXAMPLE_API_KEY"))

"""`search_run.list` and `search_run.get` answer identically on HTTP and on MCP (ADR-009).

The gap these close is the one dogfood F5 named twice. Discovery *does* find better
metadata for a Work the corpus already holds — the right authors, the venue, a year the
parse got wrong — and `DiscoveryService.enrichments` reads it back off the recorded run.
But the only caller was `research discover`: no capability published a `SearchRun`, so the
Web cockpit, the VS Code extension, and an MCP host could not show a researcher the
`work.update_metadata` proposal they are supposed to approve, and the CLI stayed the only
place the fix existed.

So the property pinned here is the ADR-009 one: two transports, one answer. The workspace
is built through the capability layer and the discovery service, never by writing files, so
the object under test is the object a host would really read.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from research_harness.capabilities.context import open_context
from research_harness.capabilities.dto import InitProjectRequest, RegisterWorkRequest
from research_harness.capabilities.handlers import init_project, register_work
from research_harness.capabilities.permissions import Permission
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.discovery.search_runs import DiscoveryService
from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    ArtifactKind,
    IdentityResolutionOutcome,
    ProvenanceSource,
    VersionKind,
)
from research_harness.domain.research import SearchRun
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.protocol.mcp import (
    HarnessMcpBridge,
    capability_for_tool,
    create_mcp_server,
    mcp_tool_name,
)
from research_harness.providers.search.base import SearchProviderRegistry, SearchQuery
from research_harness.server.app import create_app, ensure_token
from tests.integration.discovery.fakes import FakeSearchSource, field, record

TITLE = "ET-BERT: A Contextualized Datagram Representation for Encrypted Traffic"
DOI = "10.1145/3485447.3512217"
VENUE = "Proceedings of the ACM Web Conference 2022"
QUESTION = "pre-trained transformer encrypted traffic classification"

#: What the corpus holds after a broken ToUnicode CMap: the third entry is undecodable.
MOJIBAKE_AUTHORS = ("anced traffic data", "which is challenging", "ORVH\x10GRPDLQ")
REAL_AUTHORS = ("Xinjie Lin", "Gang Xiong", "Gaopeng Gou")

CAPABILITIES = ("search_run.list", "search_run.get")


@pytest.fixture
def artifact(tmp_path: Path) -> Path:
    path = tmp_path / "source" / "etbert.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n% a stand-in for the acquired source file\n")
    return path


@pytest.fixture
def discovered(tmp_path: Path, artifact: Path) -> Path:
    """A workspace with one Work and one run whose candidate resolves to it."""
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="search-run-reads"))
    ctx = open_context(result.root, HUMAN_ACTOR)
    register_work(
        ctx,
        RegisterWorkRequest(
            candidate=WorkCandidate(
                provenance=Provenance.system(actor="ingest"),
                metadata=CandidateMetadata(
                    title=IdentifierField(value=TITLE, source=ProvenanceSource.SYSTEM),
                    authors=tuple(
                        IdentifierField(value=name, source=ProvenanceSource.SYSTEM)
                        for name in MOJIBAKE_AUTHORS
                    ),
                    year=IdentifierField(value="2022", source=ProvenanceSource.SYSTEM),
                    identifiers=WorkIdentifiers(doi=field(DOI, "ingest")),
                ),
            ),
            artifact_path=artifact,
            version_kind=VersionKind.PREPRINT,
            mime_type="application/pdf",
            artifact_kind=ArtifactKind.PDF,
        ),
    )
    reported = record("openalex", doi=DOI, title=TITLE, year=2022, authors=REAL_AUTHORS)
    reported = reported.touch(metadata=reported.metadata.touch(venue=field(VENUE, "openalex")))
    source = FakeSearchSource("openalex", pages=[[reported]])
    DiscoveryService(ctx, SearchProviderRegistry((source,))).run_search(
        QUESTION, SearchQuery(text=QUESTION)
    )
    return result.root


@pytest.fixture
def run(discovered: Path) -> SearchRun:
    return open_context(discovered, HUMAN_ACTOR).repo.list_search_runs()[0]


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    return build_default_registry()


@pytest.fixture
def client(discovered: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    with TestClient(create_app(discovered, registry=registry)) as test_client:
        test_client.headers["Authorization"] = f"Bearer {ensure_token(discovered)}"
        yield test_client


@pytest.fixture
def host_client(discovered: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    """No token, so the caller is an agent host: reads and staging only."""
    with TestClient(create_app(discovered, registry=registry)) as test_client:
        yield test_client


@pytest.fixture
def bridge(discovered: Path, registry: CapabilityRegistry) -> HarnessMcpBridge:
    return HarnessMcpBridge(discovered, registry=registry)


def http(client: TestClient, name: str, request: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = client.post(f"/capabilities/{name}", json=request).json()
    return body


# -- the run is a real one ---------------------------------------------------


def test_the_fixture_records_a_candidate_that_resolved_to_the_corpus_work(run: SearchRun) -> None:
    """Without this the read below would be asserting an empty enrichment list."""
    assert run.candidates
    assert run.candidates[0].identity is IdentityResolutionOutcome.SAME_WORK
    assert str(run.candidates[0].matched_work) == "W0001"


# -- discovery ---------------------------------------------------------------


@pytest.mark.parametrize("name", CAPABILITIES)
def test_the_read_is_in_both_catalogs_with_the_same_schema(
    client: TestClient, discovered: Path, registry: CapabilityRegistry, name: str
) -> None:
    """Identity, not a copy: the tool and the descriptor read the same registry entry."""
    catalog = client.get("/capabilities").json()["capabilities"]
    descriptor = next(item for item in catalog if item["name"] == name)
    server = create_mcp_server(discovered, registry=registry)
    tool = next(
        item for item in asyncio.run(server.list_tools()) if item.name == mcp_tool_name(name)
    )

    assert capability_for_tool(mcp_tool_name(name), registry) == name
    assert registry.get(name).permission is Permission.READ
    assert descriptor["human_only"] is False, "a read is not a human-only mutation"
    assert tool.input_schema == descriptor["request_schema"]


# -- the same answers --------------------------------------------------------


def test_search_run_list_answers_identically_over_http_and_mcp(
    client: TestClient, bridge: HarnessMcpBridge, run: SearchRun
) -> None:
    over_http = http(client, "search_run.list", {})
    over_mcp = bridge.call("search_run.list", {}).model_dump(mode="json")

    assert over_http["ok"] is True, over_http
    assert over_http["result"] == over_mcp["result"]
    listed = over_http["result"]
    assert listed["count"] == 1
    assert listed["search_runs"][0]["id"] == str(run.id)
    assert listed["search_runs"][0]["discovered"] == run.results.discovered
    assert listed["search_runs"][0]["question"] == QUESTION


def test_search_run_get_answers_identically_over_http_and_mcp(
    client: TestClient, bridge: HarnessMcpBridge, run: SearchRun
) -> None:
    request = {"search_run": str(run.id)}
    over_http = http(client, "search_run.get", request)
    over_mcp = bridge.call("search_run.get", request).model_dump(mode="json")

    assert over_http["ok"] is True, over_http
    assert json.dumps(over_http["result"], sort_keys=True) == json.dumps(
        over_mcp["result"], sort_keys=True
    )


def test_the_run_comes_back_with_its_candidates(client: TestClient, run: SearchRun) -> None:
    """A host that screens has to see the `WorkCandidate` each source reported."""
    result = http(client, "search_run.get", {"search_run": str(run.id)})["result"]

    assert result["summary"]["id"] == str(run.id)
    assert result["run"]["id"] == str(run.id)
    assert [entry["key"] for entry in result["run"]["candidates"]] == [
        entry.key for entry in run.candidates
    ]


def test_the_metadata_proposal_reaches_a_host(client: TestClient, run: SearchRun) -> None:
    """Dogfood F5: the authors and venue discovery found are offered, not discarded."""
    result = http(client, "search_run.get", {"search_run": str(run.id)})["result"]

    assert result["enrichments_derived"] is True
    assert result["apply_capability"] == "work.update_metadata"
    enrichment = result["enrichments"][0]
    assert enrichment["work"] == "W0001"
    assert [item["value"] for item in enrichment["fields"]["authors"]] == list(REAL_AUTHORS)
    assert [item["value"] for item in enrichment["fields"]["venue"]] == [VENUE]
    conflict = next(item for item in enrichment["conflicts"] if item["field"] == "authors")
    assert conflict["existing_is_undecodable"] is True


def test_the_proposals_can_be_left_out_when_a_host_only_wants_the_run(
    client: TestClient, run: SearchRun
) -> None:
    result = http(client, "search_run.get", {"search_run": str(run.id), "enrichments": False})[
        "result"
    ]

    assert result["enrichments"] == []
    assert result["enrichments_derived"] is False
    assert result["run"]["id"] == str(run.id)


# -- refusals and absences ---------------------------------------------------


def test_an_agent_host_may_read_a_run_without_a_token(
    host_client: TestClient, bridge: HarnessMcpBridge, run: SearchRun
) -> None:
    """A read is a read on every transport: showing a proposal is not making one."""
    request = {"search_run": str(run.id)}
    over_http = http(host_client, "search_run.get", request)
    over_mcp = bridge.call("search_run.get", request).model_dump(mode="json")

    assert over_http["ok"] is True, over_http
    assert over_http["result"] == over_mcp["result"]


def test_a_run_that_does_not_exist_is_refused_the_same_way_on_both_transports(
    client: TestClient, bridge: HarnessMcpBridge
) -> None:
    request = {"search_run": "SR9999"}
    over_http = http(client, "search_run.get", request)
    over_mcp = bridge.call("search_run.get", request).model_dump(mode="json")

    assert over_http["ok"] is False
    assert over_http["error"]["code"] == "object_not_found"
    assert over_mcp["error"] == over_http["error"]


def test_the_list_filters_by_source_on_both_transports(
    client: TestClient, bridge: HarnessMcpBridge
) -> None:
    matching = http(client, "search_run.list", {"source": "openalex"})["result"]
    missing = bridge.call("search_run.list", {"source": "crossref"}).model_dump(mode="json")

    assert matching["count"] == 1
    assert missing["result"]["count"] == 0

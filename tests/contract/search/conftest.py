"""Recorded discovery traffic and fake transports shared by the search contract tests.

Nothing here touches a network or a real key: every adapter is driven through
`httpx.MockTransport`, so the tests can also assert on what *would* have been sent --
the polite User-Agent, the absence of credentials, and the cursor echoed into the next
request (ROADMAP 5, "provider tests use fake/recorded transports by default").

The bodies are trimmed recordings of each API's real shape: Crossref's list-valued
titles and cursor, OpenAlex's inverted abstract index and id URLs, Semantic Scholar's
`externalIds`/`next` offset, DBLP's string counters and collapsed single-element lists,
and arXiv's Atom feed with its three namespaces.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from research_harness.providers.search import (
    ARXIV,
    CROSSREF,
    DBLP,
    OPENALEX,
    SEMANTIC_SCHOLAR,
    ArxivSearchProvider,
    CrossrefSearchProvider,
    DblpSearchProvider,
    OpenAlexSearchProvider,
    SearchProvider,
    SearchQuery,
    SemanticScholarSearchProvider,
)

CONTACT_EMAIL = "researcher@example.org"
API_KEY = "test-key-do-not-log"

QUERY_TEXT = "protocol-compliant adversarial traffic"


@pytest.fixture
def query() -> SearchQuery:
    """One neutral query, reused across every source."""
    return SearchQuery(text=QUERY_TEXT, max_results=5)


# ------------------------------------------------------------------ fake transports


@dataclass
class CallRecorder:
    """Captures what an adapter put on the wire."""

    requests: list[httpx.Request] = field(default_factory=list)

    def record(self, request: httpx.Request) -> None:
        self.requests.append(request)

    @property
    def last(self) -> httpx.Request:
        assert self.requests, "no request was sent"
        return self.requests[-1]

    def params(self, index: int = -1) -> Mapping[str, str]:
        return dict(self.requests[index].url.params)

    @property
    def last_params(self) -> Mapping[str, str]:
        return self.params()


@pytest.fixture
def recorder() -> CallRecorder:
    return CallRecorder()


def make_transport(
    recorder: CallRecorder, *responses: httpx.Response | Exception
) -> httpx.MockTransport:
    """Fake transport replying with `responses` in order; the last one repeats."""
    assert responses, "at least one canned response is required"

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.record(request)
        reply = responses[min(len(recorder.requests) - 1, len(responses) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply

    return httpx.MockTransport(handler)


def json_response(body: Mapping[str, Any], status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=dict(body))


def atom_response(body: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=body.encode("utf-8"),
        headers={"content-type": "application/atom+xml; charset=utf-8"},
    )


def html_response(status_code: int = 403) -> httpx.Response:
    """A challenge/captcha interstitial of the kind a CDN serves instead of data."""
    return httpx.Response(
        status_code,
        content=(
            b"<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
            b"<body><h1>Please complete the captcha challenge to continue.</h1></body></html>"
        ),
        headers={"content-type": "text/html; charset=utf-8"},
    )


def rate_limited_response(retry_after: str = "2") -> httpx.Response:
    return httpx.Response(
        429,
        json={"error": "too many requests"},
        headers={"retry-after": retry_after},
    )


def malformed_json_response() -> httpx.Response:
    return httpx.Response(
        200, content=b'{"results": [', headers={"content-type": "application/json"}
    )


def malformed_atom_response() -> httpx.Response:
    return httpx.Response(
        200,
        content=b"totally not xml <<<",
        headers={"content-type": "application/atom+xml"},
    )


# ------------------------------------------------------------------- recorded bodies

CROSSREF_ITEM: dict[str, Any] = {
    "DOI": "10.1145/3292500.3330701",
    "URL": "https://doi.org/10.1145/3292500.3330701",
    "type": "proceedings-article",
    "title": ["Detecting Protocol-Compliant Adversarial Traffic"],
    "container-title": ["Proceedings of KDD '19"],
    "short-container-title": ["KDD"],
    "author": [
        {"given": "Ada", "family": "Lovelace", "sequence": "first"},
        {"family": "Hopper", "sequence": "additional"},
        {"name": "The Standards Consortium", "sequence": "additional"},
    ],
    "issued": {"date-parts": [[2019, 8, 4]]},
    "created": {"date-parts": [[2019, 7, 25]]},
    "abstract": (
        "<jats:p>We study <jats:italic>protocol-compliant</jats:italic> adversarial "
        "traffic and its detection.</jats:p>"
    ),
    "is-referenced-by-count": 42,
    "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
    "link": [
        {"URL": "https://example.org/paper.xml", "content-type": "application/xml"},
        {"URL": "https://example.org/paper.pdf", "content-type": "application/pdf"},
    ],
}

CROSSREF_NEXT_CURSOR = "DnF1ZXJ5VGhlbkZldGNoBQAAAAAA"


def crossref_body(
    items: list[dict[str, Any]] | None = None,
    *,
    total: int = 137,
    next_cursor: str | None = CROSSREF_NEXT_CURSOR,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "facets": {},
        "total-results": total,
        "items": [CROSSREF_ITEM] if items is None else items,
        "items-per-page": 5,
    }
    if next_cursor is not None:
        message["next-cursor"] = next_cursor
    return {"status": "ok", "message-type": "work-list", "message": message}


def crossref_empty_body() -> dict[str, Any]:
    return crossref_body(items=[], total=0)


def crossref_work_body(reference: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`GET /works/{doi}` -- one work with its deposited reference list."""
    message = dict(CROSSREF_ITEM)
    message["reference"] = (
        reference
        if reference is not None
        else [
            {
                "key": "e_1_3_2_1_1",
                "DOI": "10.1109/SP.2016.42",
                "article-title": "Adversarial Examples in the Physical World",
                "journal-title": "IEEE S&P",
                "year": "2016",
                "author": "Kurakin",
                "doi-asserted-by": "publisher",
            },
            {"key": "e_1_3_2_1_2", "unstructured": "Anonymous. A note without a DOI. 2018."},
            {"key": "e_1_3_2_1_3", "volume-title": "A Book Without a DOI"},
            {"key": "e_1_3_2_1_4"},
        ]
    )
    return {"status": "ok", "message-type": "work", "message": message}


OPENALEX_ITEM: dict[str, Any] = {
    "id": "https://openalex.org/W2741809807",
    "doi": "https://doi.org/10.7717/PEERJ.4375",
    "title": "The state of OA: a large-scale analysis",
    "display_name": "The state of OA: a large-scale analysis",
    "publication_year": 2018,
    "publication_date": "2018-02-13",
    "cited_by_count": 311,
    "authorships": [
        {"author": {"id": "https://openalex.org/A123", "display_name": "Heather Piwowar"}},
        {"author": {"id": None, "display_name": None}, "raw_author_name": "Jason Priem"},
    ],
    "primary_location": {
        "source": {"id": "https://openalex.org/S1983995261", "display_name": "PeerJ"},
        "landing_page_url": "https://arxiv.org/abs/1802.00001v3",
        "pdf_url": None,
    },
    "best_oa_location": {"pdf_url": "https://peerj.com/articles/4375.pdf"},
    "open_access": {"is_oa": True, "oa_url": "https://peerj.com/articles/4375"},
    "abstract_inverted_index": {
        "Despite": [0],
        "growing": [1],
        "interest": [2],
        "in": [3, 6],
        "open": [4],
        "access": [5],
        "scholarly": [7],
        "publishing": [8],
    },
    "referenced_works": [
        "https://openalex.org/W1",
        "https://openalex.org/W2",
    ],
}

OPENALEX_NEXT_CURSOR = "IlsxNjA5MzYwMDAwMDAwLCAn"


def openalex_body(
    results: list[dict[str, Any]] | None = None,
    *,
    count: int = 249,
    next_cursor: str | None = OPENALEX_NEXT_CURSOR,
) -> dict[str, Any]:
    return {
        "meta": {
            "count": count,
            "db_response_time_ms": 12,
            "page": None,
            "per_page": 5,
            "next_cursor": next_cursor,
        },
        "results": [OPENALEX_ITEM] if results is None else results,
        "group_by": [],
    }


def openalex_empty_body() -> dict[str, Any]:
    return openalex_body(results=[], count=0, next_cursor=None)


def openalex_work_body() -> dict[str, Any]:
    """`GET /works/{id}` -- a single work record, not a list."""
    return dict(OPENALEX_ITEM)


SEMANTIC_SCHOLAR_ITEM: dict[str, Any] = {
    "paperId": "649def34f8be52c8b66281af98ae884c09aef38b",
    "externalIds": {
        "DOI": "10.18653/v1/N18-3011",
        "ArXiv": "1805.06556",
        "DBLP": "conf/naacl/AmmarGBBCDDEFGH18",
        "CorpusId": 21736986,
    },
    "title": "Construction of the Literature Graph in Semantic Scholar",
    "abstract": "We describe a deployed scalable system for organizing published papers.",
    "venue": "NAACL",
    "year": 2018,
    "authors": [
        {"authorId": "1741101", "name": "Waleed Ammar"},
        {"authorId": None, "name": "Dirk Groeneveld"},
    ],
    "citationCount": 321,
    "openAccessPdf": {"url": "https://aclanthology.org/N18-3011.pdf", "status": "GOLD"},
    "url": "https://www.semanticscholar.org/paper/649def34",
}

SEMANTIC_SCHOLAR_NEXT_OFFSET = 5


def semantic_scholar_body(
    data: list[dict[str, Any]] | None = None,
    *,
    total: int = 1200,
    offset: int = 0,
    next_offset: int | None = SEMANTIC_SCHOLAR_NEXT_OFFSET,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "total": total,
        "offset": offset,
        "data": [SEMANTIC_SCHOLAR_ITEM] if data is None else data,
    }
    if next_offset is not None:
        body["next"] = next_offset
    return body


def semantic_scholar_empty_body() -> dict[str, Any]:
    return semantic_scholar_body(data=[], total=0, next_offset=None)


def semantic_scholar_graph_body(key: str) -> dict[str, Any]:
    """`/paper/{id}/references|citations` wraps each neighbour under `key`."""
    return {"offset": 0, "data": [{key: SEMANTIC_SCHOLAR_ITEM}]}


DBLP_HIT: dict[str, Any] = {
    "@score": "8",
    "@id": "3025619",
    "info": {
        "authors": {
            "author": [
                {"@pid": "1/1", "text": "Ada Lovelace"},
                {"@pid": "2/2", "text": "Grace Hopper"},
            ]
        },
        "title": "Analytical Engines and Adversarial Traffic.",
        "venue": "NeurIPS",
        "year": "2020",
        "type": "Conference and Workshop Papers",
        "access": "open",
        "key": "conf/nips/LovelaceH20",
        "doi": "10.5555/NIPS.2020.1",
        "ee": "https://proceedings.example.org/paper.pdf",
        "url": "https://dblp.org/rec/conf/nips/LovelaceH20",
    },
}

DBLP_SINGLE_AUTHOR_HIT: dict[str, Any] = {
    "@score": "6",
    "@id": "3025620",
    "info": {
        "authors": {"author": {"@pid": "3/3", "text": "Solo Author"}},
        "title": "A single-author record.",
        "venue": ["CoRR", "NeurIPS"],
        "year": "2021",
        "type": "Informal Publications",
        "access": "closed",
        "key": "journals/corr/Solo21",
        "ee": "https://arxiv.org/abs/2101.00001",
    },
}


def dblp_body(
    hits: list[dict[str, Any]] | None = None,
    *,
    total: str = "77",
    first: str = "0",
) -> dict[str, Any]:
    rows = [DBLP_HIT, DBLP_SINGLE_AUTHOR_HIT] if hits is None else hits
    block: dict[str, Any] = {
        "@total": total,
        "@computed": total,
        "@sent": str(len(rows)),
        "@first": first,
    }
    if rows:
        block["hit"] = rows
    return {
        "result": {
            "query": QUERY_TEXT,
            "status": {"@code": "200", "text": "OK"},
            "time": {"@unit": "msecs", "text": "3.21"},
            "hits": block,
        }
    }


def dblp_empty_body() -> dict[str, Any]:
    return dblp_body(hits=[], total="0")


ARXIV_ENTRY = """  <entry>
    <id>http://arxiv.org/abs/2101.00001v2</id>
    <updated>2021-02-01T09:00:00Z</updated>
    <published>2021-01-04T18:00:00Z</published>
    <title>Protocol-Compliant Adversarial
  Traffic</title>
    <summary>  We study protocol-compliant adversarial traffic and how detectors fail.
    </summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Grace Hopper</name></author>
    <arxiv:doi>10.1109/TIFS.2021.000001</arxiv:doi>
    <arxiv:journal_ref>IEEE TIFS 16 (2021) 1-14</arxiv:journal_ref>
    <link href="http://arxiv.org/abs/2101.00001v2" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2101.00001v2" rel="related"
          type="application/pdf"/>
    <arxiv:primary_category term="cs.CR" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.CR" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
"""

#: A recording of what arXiv returns for the AND-ed conjunction of a five-term research
#: question (dogfood F1). The same question sent as one `all:"..."` phrase returns the
#: `arxiv_empty_feed()` below -- both shapes are recorded so the difference is testable.
ARXIV_MULTI_TERM_QUERY = "pre-trained transformer encrypted traffic classification"
ARXIV_MULTI_TERM_WIRE_QUERY = (
    'all:"pre-trained" AND all:"transformer" AND all:"encrypted" AND all:"traffic" '
    'AND all:"classification"'
)

ARXIV_MULTI_TERM_ENTRY = """  <entry>
    <id>http://arxiv.org/abs/2202.06335v1</id>
    <updated>2022-02-13T15:31:20Z</updated>
    <published>2022-02-13T15:31:20Z</published>
    <title>ET-BERT: A Contextualized Datagram Representation with Pre-training
  Transformers for Encrypted Traffic Classification</title>
    <summary>  Encrypted traffic classification requires discriminative and robust traffic
    representation captured from content-invisible and imbalanced traffic data.
    </summary>
    <author><name>Xinjie Lin</name></author>
    <author><name>Gang Xiong</name></author>
    <author><name>Gaopeng Gou</name></author>
    <arxiv:doi>10.1145/3485447.3512217</arxiv:doi>
    <link href="http://arxiv.org/abs/2202.06335v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2202.06335v1" rel="related"
          type="application/pdf"/>
    <arxiv:primary_category term="cs.CR" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
"""

ARXIV_ERROR_ENTRY = """  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format</id>
    <title>Error</title>
    <summary>incorrect id format for 2101.abcde</summary>
  </entry>
"""


def arxiv_feed(entries: str = ARXIV_ENTRY, *, total: int = 42, start: int = 0) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <link href="http://arxiv.org/api/query" rel="self" type="application/atom+xml"/>
  <title type="html">ArXiv Query: {QUERY_TEXT}</title>
  <id>http://arxiv.org/api/query-id</id>
  <updated>2024-01-01T00:00:00-05:00</updated>
  <opensearch:totalResults>{total}</opensearch:totalResults>
  <opensearch:startIndex>{start}</opensearch:startIndex>
  <opensearch:itemsPerPage>5</opensearch:itemsPerPage>
{entries}</feed>
"""


def arxiv_empty_feed() -> str:
    return arxiv_feed(entries="", total=0)


# ---------------------------------------------------------------- the provider matrix


@dataclass(frozen=True)
class SearchCase:
    """One adapter plus the recorded traffic it understands."""

    id: str
    build: Callable[[httpx.BaseTransport, Mapping[str, str]], SearchProvider]
    success: Callable[[], httpx.Response]
    empty: Callable[[], httpx.Response]
    malformed: Callable[[], httpx.Response]
    path: str
    cursor_param: str
    next_cursor: str
    total_estimate: int
    mailto_param: bool


def _crossref(transport: httpx.BaseTransport, env: Mapping[str, str]) -> SearchProvider:
    return CrossrefSearchProvider(transport=transport, env=env)


def _openalex(transport: httpx.BaseTransport, env: Mapping[str, str]) -> SearchProvider:
    return OpenAlexSearchProvider(transport=transport, env=env)


def _semantic_scholar(transport: httpx.BaseTransport, env: Mapping[str, str]) -> SearchProvider:
    return SemanticScholarSearchProvider(transport=transport, env=env)


def _dblp(transport: httpx.BaseTransport, env: Mapping[str, str]) -> SearchProvider:
    return DblpSearchProvider(transport=transport, env=env)


def _arxiv(transport: httpx.BaseTransport, env: Mapping[str, str]) -> SearchProvider:
    return ArxivSearchProvider(transport=transport, env=env)


SEARCH_CASES: tuple[SearchCase, ...] = (
    SearchCase(
        id=CROSSREF,
        build=_crossref,
        success=lambda: json_response(crossref_body()),
        empty=lambda: json_response(crossref_empty_body()),
        malformed=malformed_json_response,
        path="/works",
        cursor_param="cursor",
        next_cursor=CROSSREF_NEXT_CURSOR,
        total_estimate=137,
        mailto_param=True,
    ),
    SearchCase(
        id=OPENALEX,
        build=_openalex,
        success=lambda: json_response(openalex_body()),
        empty=lambda: json_response(openalex_empty_body()),
        malformed=malformed_json_response,
        path="/works",
        cursor_param="cursor",
        next_cursor=OPENALEX_NEXT_CURSOR,
        total_estimate=249,
        mailto_param=True,
    ),
    SearchCase(
        id=SEMANTIC_SCHOLAR,
        build=_semantic_scholar,
        success=lambda: json_response(semantic_scholar_body()),
        empty=lambda: json_response(semantic_scholar_empty_body()),
        malformed=malformed_json_response,
        path="/graph/v1/paper/search",
        cursor_param="offset",
        next_cursor=str(SEMANTIC_SCHOLAR_NEXT_OFFSET),
        total_estimate=1200,
        mailto_param=False,
    ),
    SearchCase(
        id=DBLP,
        build=_dblp,
        success=lambda: json_response(dblp_body()),
        empty=lambda: json_response(dblp_empty_body()),
        malformed=malformed_json_response,
        path="/search/publ/api",
        cursor_param="f",
        next_cursor="2",
        total_estimate=77,
        mailto_param=False,
    ),
    SearchCase(
        id=ARXIV,
        build=_arxiv,
        success=lambda: atom_response(arxiv_feed()),
        empty=lambda: atom_response(arxiv_empty_feed()),
        malformed=malformed_atom_response,
        path="/api/query",
        cursor_param="start",
        next_cursor="1",
        total_estimate=42,
        mailto_param=False,
    ),
)


@pytest.fixture(params=SEARCH_CASES, ids=[case.id for case in SEARCH_CASES])
def search_case(request: pytest.FixtureRequest) -> SearchCase:
    case = request.param
    assert isinstance(case, SearchCase)
    return case

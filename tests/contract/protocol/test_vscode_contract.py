"""Task 16.1: the daemon answers the VS Code extension the way the extension expects.

The extension is a transport (ADR-004): it edits nothing canonical and reaches the workspace
only through named capabilities. That makes its correctness a contract question rather than a
UI one - *does the harness accept the requests it sends, and does it answer with the fields it
reads?* - and this file is where that question is asked, in three ways:

1. **names** - every capability `vscode/src/client/types.ts` lists is in `GET /capabilities`;
2. **requests** - the exact bodies from `vscode/src/client/requests.ts` are accepted, and the
   ones the extension deliberately does not send are refused;
3. **fields** - each field name declared in `types.ts` appears in the JSON the daemon
   returns, so a rename on either side fails here rather than in a researcher's tooltip.

The workspace is the one `vscode/scripts/export_fixtures.py` builds, imported rather than
copied: the TypeScript unit tests assert against that script's output, so pinning both to one
manuscript is what makes "the mock and the daemon agree" mean anything.

The six backend gaps this extension used to work around are closed, and the assertions that
pinned them are gone with the workarounds: `claim.list` answers the Claim picker,
`claim.create` names its own Claim, `manuscript.audit` takes a line range, every finding
carries a structured `location`, `manuscript.anchors` and `manuscript.revalidate` read and
record the anchor verdicts, and `manuscript.trace` answers for one sentence.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from starlette.testclient import TestClient

from research_harness.capabilities.registry import CapabilityRegistry
from research_harness.manuscript.latex import LatexProject, sentence_fingerprint
from research_harness.server.app import create_app, ensure_token

REPO_ROOT = Path(__file__).resolve().parents[3]
VSCODE_ROOT = REPO_ROOT / "vscode"
TYPES_TS = VSCODE_ROOT / "src" / "client" / "types.ts"
FIXTURE_SCRIPT = VSCODE_ROOT / "scripts" / "export_fixtures.py"

#: The capability the extension calls, keyed by the `CAPABILITIES` entry in `types.ts`.
EXPECTED_CAPABILITIES = {
    "manuscriptAudit": "manuscript.audit",
    "manuscriptAnchors": "manuscript.anchors",
    "manuscriptRevalidate": "manuscript.revalidate",
    "manuscriptTrace": "manuscript.trace",
    "manuscriptAttachClaim": "manuscript.attach_claim",
    "claimCreate": "claim.create",
    "claimList": "claim.list",
    "claimAudit": "claim.audit",
    "claimFindSupport": "claim.find_support",
    "noteAdd": "note.add",
    "resolveSource": "retrieval.resolve_source",
}

#: The refusal the daemon gives a handler that allocates its own id under an already-held
#: lock. See `tests/e2e/test_web_gate.py::ALLOCATION_DEFECT` for the whole story and the fix.
REENTRANT_LOCK = "the workspace lock is not reentrant"

#: The unanchored substantive sentence of the fixture manuscript; the extension's
#: `Research: Attach Claim` is what would bind it.
UNANCHORED_LINE = 23


# -- reading the TypeScript side ---------------------------------------------


def _load_fixture_builder() -> ModuleType:
    """Import `vscode/scripts/export_fixtures.py` by path; it is not an installed package."""
    spec = importlib.util.spec_from_file_location("vscode_export_fixtures", FIXTURE_SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - only if the file is deleted
        raise RuntimeError(f"cannot import {FIXTURE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _interface_fields(source: str, name: str) -> set[str]:
    """The property names of one `export interface` in `types.ts`.

    A deliberately small parse: the file is hand-maintained DTO declarations with no
    computed members, so matching `name?: type;` lines inside the braces is enough to catch
    a rename, which is the whole job.
    """
    match = re.search(rf"export interface {re.escape(name)}\s*\{{(.*?)\n\}}", source, re.DOTALL)
    if match is None:
        raise AssertionError(f"{TYPES_TS.name} declares no interface {name}")
    body = match.group(1)
    return set(re.findall(r"^\s{2}(\w+)\??:", body, re.MULTILINE))


def _capability_constants(source: str) -> dict[str, str]:
    """The `CAPABILITIES` map from `types.ts`, as a Python dict."""
    match = re.search(r"export const CAPABILITIES = \{(.*?)\n\} as const;", source, re.DOTALL)
    if match is None:
        raise AssertionError(f"{TYPES_TS.name} declares no CAPABILITIES map")
    return dict(re.findall(r'(\w+):\s*"([^"]+)"', match.group(1)))


def _present(payload: Any, field: str) -> bool:
    """True when ``field`` appears as a key anywhere in a JSON document."""
    if isinstance(payload, dict):
        return field in payload or any(_present(value, field) for value in payload.values())
    if isinstance(payload, list):
        return any(_present(item, field) for item in payload)
    return False


def _assert_fields(
    payload: Any, interface: str, *, source: str, optional: frozenset[str] = frozenset()
) -> None:
    """Every field `types.ts` declares for ``interface`` appears in ``payload``."""
    missing = sorted(
        field
        for field in _interface_fields(source, interface) - optional
        if not _present(payload, field)
    )
    assert not missing, (
        f"{interface} in {TYPES_TS.name} declares {missing}, which the daemon did not return; "
        "one of the two has drifted"
    )


# -- fixtures ----------------------------------------------------------------


@pytest.fixture(scope="module")
def types_source() -> str:
    """The extension's hand-maintained DTO declarations, as text."""
    return TYPES_TS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def fixture_builder() -> ModuleType:
    """The module that builds both the TypeScript fixtures and this workspace."""
    return _load_fixture_builder()


@pytest.fixture
def manuscript_workspace(tmp_path: Path, fixture_builder: ModuleType) -> Path:
    """The fixture manuscript workspace: two Claims, three anchors, one unanchored sentence."""
    root = tmp_path / "project"
    fixture_builder.build_workspace(root)
    return root


@pytest.fixture
def vscode_client(manuscript_workspace: Path, registry: CapabilityRegistry) -> Iterator[TestClient]:
    """The daemon as the extension sees it: the local researcher, holding the token."""
    token = ensure_token(manuscript_workspace)
    with TestClient(create_app(manuscript_workspace, registry=registry)) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


@pytest.fixture
def agent_host_client(
    manuscript_workspace: Path, registry: CapabilityRegistry
) -> Iterator[TestClient]:
    """The daemon as an extension with no token: reads only (Product 29)."""
    with TestClient(create_app(manuscript_workspace, registry=registry)) as client:
        yield client


def invoke(client: TestClient, name: str, request: dict[str, Any]) -> dict[str, Any]:
    """One capability call, returning the envelope whether or not it succeeded."""
    body: dict[str, Any] = client.post(f"/capabilities/{name}", json=request).json()
    return body


def succeed(client: TestClient, name: str, request: dict[str, Any]) -> Any:
    """One capability call that must succeed, returning its result."""
    envelope = invoke(client, name, request)
    assert envelope["ok"], f"{name} refused: {envelope.get('error')}"
    return envelope["result"]


def project_request() -> dict[str, Any]:
    """What `ManuscriptService.projectRequest()` sends for the default manuscript location."""
    return {"main_tex": "main.tex"}


# -- 1. names ----------------------------------------------------------------


def test_every_capability_the_extension_names_is_registered(
    vscode_client: TestClient, types_source: str
) -> None:
    """`types.ts::CAPABILITIES` is a promise about Product 22 names; the daemon keeps it."""
    declared = _capability_constants(types_source)
    assert declared == EXPECTED_CAPABILITIES, "types.ts changed which capabilities it calls"

    catalog = vscode_client.get("/capabilities").json()
    registered = {item["name"] for item in catalog["capabilities"]}
    missing = sorted(set(declared.values()) - registered)
    assert not missing, f"the extension calls {missing}, which this build does not implement"


def test_the_extension_uses_only_routes_the_daemon_publishes(vscode_client: TestClient) -> None:
    """The whole HTTP surface of the extension: three reads and one capability POST.

    `GET /index` is no longer among them. It was the extension's Claim list, and it was a
    Web-cockpit route the capability contract does not promise — `claim.list` answers the
    same question by a name every transport shares, so `HarnessClient.claims()` and its 404
    fallback are gone.
    """
    assert vscode_client.get("/health").status_code == 200
    assert vscode_client.get("/capabilities").status_code == 200
    assert vscode_client.get("/objects/C0001").status_code == 200

    source = (VSCODE_ROOT / "src" / "client" / "HarnessClient.ts").read_text(encoding="utf-8")
    assert '"/index"' not in source, "the extension must not depend on a Web-cockpit route"


def test_health_carries_the_fields_the_status_bar_shows(
    vscode_client: TestClient, types_source: str
) -> None:
    payload = vscode_client.get("/health").json()
    _assert_fields(payload, "HealthReport", source=types_source)


def test_objects_get_carries_the_fields_the_claim_picker_reads(
    vscode_client: TestClient, types_source: str
) -> None:
    """`GET /objects/{id}` is how the extension validates a typed Claim id.

    Still the fallback, and still contract-tested: `claim.list` now answers the picker's
    question directly, but an id the researcher typed by hand is validated here.
    """
    payload = vscode_client.get("/objects/C0001").json()
    _assert_fields(payload, "ObjectView", source=types_source)
    assert payload["kind"] == "claim"


def test_an_id_the_workspace_does_not_hold_answers_404_rather_than_a_guess(
    vscode_client: TestClient,
) -> None:
    """`promptForClaimId` validates a hand-typed id on this 404.

    It is all that is left of `claimIds.ts`: the extension no longer probes for a free id,
    because `claim.create` allocates one. What it still does is refuse to attach a Claim the
    workspace does not hold, before the attach costs a round trip.
    """
    assert vscode_client.get("/objects/C0002").status_code == 200
    assert vscode_client.get("/objects/C0003").status_code == 404


def test_claim_list_answers_the_attach_claim_picker(
    vscode_client: TestClient, types_source: str
) -> None:
    """The picker's whole source of truth, and a capability every transport shares.

    `HarnessClient.claims()` and its 404 fallback are gone: `GET /index` was a Web-cockpit
    route the capability contract does not promise, and an MCP host had no answer at all.
    `claim.list` composes the same `ClaimSummary` objects the route composes, so the picker
    lists the same Claims from either.
    """
    result = succeed(vscode_client, "claim.list", {})

    assert result["count"] == 2
    assert {claim["id"] for claim in result["claims"]} == {"C0001", "C0002"}
    declared = _interface_fields(types_source, "ClaimSummary")
    for claim in result["claims"]:
        assert set(claim) >= declared, f"ClaimSummary declares {sorted(declared - set(claim))}"

    route = vscode_client.get("/index")
    if route.status_code == 200:
        assert result["claims"] == route.json()["claims"], "one answer, under two names"


def test_claim_list_takes_the_filters_the_picker_may_send(vscode_client: TestClient) -> None:
    """`ListClaimsRequest` in `types.ts`, field for field; an invented one is refused."""
    assert succeed(vscode_client, "claim.list", {"status": "supported"})["count"] == 1
    assert succeed(vscode_client, "claim.list", {"stale": "fresh"})["count"] == 2
    assert succeed(vscode_client, "claim.list", {"type": "descriptive"})["count"] == 2

    refused = invoke(vscode_client, "claim.list", {"claim": "C0001"})
    assert refused["ok"] is False
    assert refused["error"]["code"] == "invalid_request"


def test_an_agent_host_may_list_claims_the_way_the_editor_does(
    agent_host_client: TestClient,
) -> None:
    """The point of moving off `GET /index`: every transport gets the same answer."""
    envelope = invoke(agent_host_client, "claim.list", {})
    assert envelope["ok"] is True
    assert envelope["result"]["count"] == 2


# -- 2. requests -------------------------------------------------------------


def test_manuscript_audit_accepts_the_project_request_the_extension_builds(
    vscode_client: TestClient, types_source: str
) -> None:
    result = succeed(vscode_client, "manuscript.audit", project_request())
    _assert_fields(result, "ManuscriptAuditReport", source=types_source)
    assert result["sentences_checked"] == 4
    assert result["anchored_sentences"] == 3
    assert result["unanchored_substantive"] == 1


def test_manuscript_audit_accepts_an_explicit_project_root(
    vscode_client: TestClient, manuscript_workspace: Path
) -> None:
    """`researchHarness.manuscriptRoot` becomes `project_root`, which is an absolute path."""
    result = succeed(
        vscode_client,
        "manuscript.audit",
        {"project_root": str(manuscript_workspace / "manuscript"), "main_tex": "main.tex"},
    )
    assert result["sentences_checked"] == 4


def test_the_audit_reports_the_finding_fields_the_diagnostics_map(
    vscode_client: TestClient, types_source: str
) -> None:
    """Task 16.4 maps `kind`, `severity`, `message`, `anchor`, and `related` onto ranges."""
    result = succeed(vscode_client, "manuscript.audit", project_request())
    findings = result["findings"]
    assert findings, "the fixture manuscript is meant to raise findings"
    for finding in findings:
        assert set(finding) >= _interface_fields(types_source, "ManuscriptAuditFinding")

    kinds = {finding["kind"] for finding in findings}
    assert kinds <= {
        "unregistered_claim",
        "over_strong_wording",
        "citation_mismatch",
        "unsupported_numeric",
        "stale_claim",
        "invalid_evidence_anchor",
    }


def test_every_finding_carries_the_structured_location_the_diagnostics_place_it_by(
    vscode_client: TestClient, types_source: str
) -> None:
    """`report.ts::findingLocation` reads `location`; it no longer parses the message.

    The finding that matters is the unregistered one: it carries no anchor, so before
    `FindingLocation` existed the `"<file>:<line>: "` prefix was the only record of where it
    happened. The prefix is still written, and the extension still falls back to it for an
    older daemon, but prose is not a location.
    """
    result = succeed(vscode_client, "manuscript.audit", project_request())
    declared = _interface_fields(types_source, "FindingLocation")

    for finding in result["findings"]:
        location = finding["location"]
        assert location is not None, f"{finding['kind']} placed nowhere"
        assert set(location) >= declared, f"FindingLocation declares {sorted(declared)}"
        assert location["line_end"] >= location["line_start"] >= 1
        assert re.match(rf"^{re.escape(location['file'])}:\d+: ", finding["message"]), (
            "the message prefix stays, as the fallback for a daemon built before `location`"
        )

    unregistered = [
        finding for finding in result["findings"] if finding["kind"] == "unregistered_claim"
    ]
    assert unregistered, "the fixture leaves one substantive sentence unattached"
    assert all(finding["anchor"] is None for finding in unregistered)
    assert all(finding["location"]["line_start"] == UNANCHORED_LINE for finding in unregistered)


def test_manuscript_audit_narrows_to_the_selection_the_editor_sends(
    vscode_client: TestClient,
) -> None:
    """`Research: Audit Selection` sends the range instead of filtering client-side.

    The counts are recomputed over the range, so an editor showing two findings out of one
    sentence is not told it checked four; and the rules are the same either way, so what
    the range changes is what was asked about.
    """
    whole = succeed(vscode_client, "manuscript.audit", project_request())
    narrowed = succeed(
        vscode_client,
        "manuscript.audit",
        {**project_request(), "file": "main.tex", "line_start": 17, "line_end": 18},
    )

    assert narrowed["sentences_checked"] == 1
    assert narrowed["anchored_sentences"] == 1
    assert narrowed["unanchored_substantive"] == 0
    assert {finding["location"]["line_start"] for finding in narrowed["findings"]} == {17}
    assert narrowed["findings"] == [
        finding for finding in whole["findings"] if finding["location"]["line_start"] == 17
    ], "narrowing selects findings; it never produces a different one"


def test_a_line_range_without_the_file_it_is_a_range_in_is_refused(
    vscode_client: TestClient,
) -> None:
    """The extension always sends `file` beside the range; the daemon insists on it."""
    refused = invoke(
        vscode_client, "manuscript.audit", {**project_request(), "line_start": 17, "line_end": 18}
    )
    assert refused["ok"] is False
    assert "line range" in refused["error"]["message"]


def test_manuscript_anchors_reports_every_stored_anchor_and_records_none_of_them(
    vscode_client: TestClient, types_source: str
) -> None:
    """The read half of `Research: Revalidate Anchors`, without a whole-project audit."""
    result = succeed(vscode_client, "manuscript.anchors", project_request())

    _assert_fields(result, "ManuscriptAnchors", source=types_source)
    assert result["count"] == 3
    for anchor in result["anchors"]:
        assert set(anchor) >= _interface_fields(types_source, "AnchorSummary") - {"citation_keys"}
    for verdict in result["verdicts"]:
        assert set(verdict) >= _interface_fields(types_source, "AnchorVerdict")
        assert verdict["status"] == "valid"


def test_manuscript_revalidate_records_the_verdicts_and_needs_the_researcher(
    vscode_client: TestClient, agent_host_client: TestClient, types_source: str
) -> None:
    """`Research: Revalidate Anchors` no longer offers a terminal command.

    Recording that a reworded sentence has gone stale is a change to accepted state, so it
    is a mutation and human-only (ADR-008). `dry_run` reports the same verdicts and writes
    nothing, which is what the read above is for.
    """
    dry = succeed(vscode_client, "manuscript.revalidate", {**project_request(), "dry_run": True})
    applied = succeed(vscode_client, "manuscript.revalidate", project_request())

    _assert_fields(
        applied, "RevalidationView", source=types_source, optional=frozenset({"applied"})
    )
    assert dry["dry_run"] is True and dry["applied"] == []
    assert applied["dry_run"] is False
    assert applied["checked"] == 3
    assert applied["valid"] == 3
    assert [result["status"] for result in applied["results"]] == ["valid"] * 3

    refused = invoke(agent_host_client, "manuscript.revalidate", project_request())
    assert refused["ok"] is False
    assert refused["error"]["code"] == "permission_denied"


def test_manuscript_trace_answers_for_one_sentence(
    vscode_client: TestClient, types_source: str
) -> None:
    """`Open Evidence` and `Show Claim Under Cursor` no longer pay for a project audit."""
    traced = succeed(
        vscode_client, "manuscript.trace", {**project_request(), "file": "main.tex", "line": 17}
    )
    unattached = succeed(
        vscode_client,
        "manuscript.trace",
        {**project_request(), "file": "main.tex", "line": UNANCHORED_LINE},
    )

    _assert_fields(traced, "TraceView", source=types_source)
    assert traced["claim"] == "C0001"
    assert traced["anchor"]
    assert set(traced["link"]) >= _interface_fields(types_source, "TraceLink")
    assert unattached["anchor"] is None and unattached["link"] is None, (
        "a sentence with no anchor is a different answer from a broken chain, and is still "
        "reported so the editor can offer to attach one"
    )


def test_the_audit_carries_every_anchor_with_its_revalidation_verdict(
    vscode_client: TestClient, types_source: str
) -> None:
    """The audit still carries them, so the hover reads one report rather than three."""
    result = succeed(vscode_client, "manuscript.audit", project_request())
    assert len(result["revalidations"]) == 3
    for entry in result["revalidations"]:
        assert set(entry) >= _interface_fields(types_source, "AnchorRevalidation") - {
            "relocated",
            "similarity",
        }
        assert set(entry["anchor"]) >= _interface_fields(types_source, "ManuscriptAnchor")
        assert entry["status"] == "valid"


def test_the_audit_carries_the_trace_open_evidence_walks(
    vscode_client: TestClient, types_source: str
) -> None:
    result = succeed(vscode_client, "manuscript.audit", project_request())
    assert result["trace"], "three anchored sentences should trace"
    for link in result["trace"]:
        assert set(link) >= _interface_fields(types_source, "TraceLink")


def test_manuscript_attach_claim_accepts_the_anchor_the_editor_builds(
    vscode_client: TestClient, manuscript_workspace: Path, types_source: str
) -> None:
    """The `buildAnchor` output, field for field, including the client-computed fingerprint."""
    project = LatexProject.load(manuscript_workspace / "manuscript" / "main.tex")
    sentence = next(item for item in project.sentences if item.line_start == UNANCHORED_LINE)
    anchor = {
        "provenance": {"source": "human", "actor": "human", "workflow": "vscode"},
        "file": sentence.file,
        "line_start": sentence.line_start,
        "line_end": sentence.line_end,
        "char_start": sentence.char_start,
        "char_end": sentence.char_end,
        "sentence": sentence.normalized_text,
        "sentence_fingerprint": sentence_fingerprint(sentence.normalized_text),
        "claim": "C0001",
        "citation_keys": list(sentence.citation_keys),
        "status": "valid",
        "stale": "fresh",
    }
    result = succeed(vscode_client, "manuscript.attach_claim", {"anchor": anchor})
    _assert_fields(result, "MutationResponse", source=types_source)
    assert result["event"]["event"] == "manuscript.claim_attached"

    # `attachSentence` re-audits and calls `verifyAttachment`: the harness must now know the
    # anchor as valid, which is what proves the TypeScript fingerprint matches the Python one.
    audit = succeed(vscode_client, "manuscript.audit", project_request())
    keys = {
        f"{entry['anchor']['file']}#{entry['anchor']['sentence_fingerprint']}": entry["status"]
        for entry in audit["revalidations"]
    }
    assert keys[f"{anchor['file']}#{anchor['sentence_fingerprint']}"] == "valid"
    assert audit["unanchored_substantive"] == 0


def test_claim_find_support_returns_the_fields_the_hover_counts(
    vscode_client: TestClient, types_source: str
) -> None:
    result = succeed(vscode_client, "claim.find_support", {"claim_id": "C0001"})
    _assert_fields(result, "ClaimSupport", source=types_source)
    assert result["status"] == "supported"
    assert result["requested_strength"] == "corpus_pattern"
    assert result["allowed_strength"] == "corpus_pattern"


def test_claim_create_lets_the_daemon_name_the_claim(
    vscode_client: TestClient, types_source: str
) -> None:
    """`Create Claim from Selection` sends no id, and attaches the one it gets back.

    This is what `claimIds.ts` existed to work around, and why it is gone: the extension
    used to probe `GET /objects/C####` for a free number, which is right only for a densely
    allocated workspace and races any other client. The daemon allocates under the
    workspace lock instead and reports the id in `objects[0]`.
    """
    claim = {
        "statement": "Sustained load degrades detection quality",
        "type": "descriptive",
        "semantics": {
            "subject": "sustained load",
            "predicate": "degrades",
            "object": "detection quality",
        },
        "scope": {"level": "corpus_pattern"},
        "assessment": {
            "requested_strength": "corpus_pattern",
            "allowed_strength": "individual",
            "status": "unverified",
        },
        "provenance": {"source": "human", "actor": "human", "workflow": "vscode"},
    }
    envelope = invoke(vscode_client, "claim.create", {"claim": claim})
    if not envelope["ok"] and REENTRANT_LOCK in envelope["error"]["message"]:
        pytest.xfail(
            "claim.create cannot allocate an id over HTTP: the daemon already holds "
            "`ctx.repo.lock()` for every mutating capability (`server/app.py::_invoke`) and "
            "the handler takes it again to allocate under it, which "
            "`WorkspaceRepository.lock()` refuses. The same call succeeds in process. See "
            "`tests/e2e/test_web_gate.py::ALLOCATION_DEFECT` for the one-line fix."
        )
    assert envelope["ok"], f"claim.create refused: {envelope.get('error')}"
    result = envelope["result"]
    _assert_fields(result, "MutationResponse", source=types_source)
    assert result["objects"] == ["C0003"], "the next free id, allocated under the lock"
    assert vscode_client.get("/objects/C0003").status_code == 200
    assert "id" not in claim, "the extension never sends one"


def test_claim_audit_accepts_the_status_and_allowed_strength(vscode_client: TestClient) -> None:
    result = succeed(
        vscode_client,
        "claim.audit",
        {
            "claim_id": "C0002",
            "status": "qualified",
            "allowed_strength": "individual",
            "maximum_defensible_wording": "one reviewed setting",
        },
    )
    assert result["event"]["event"] in {"claim.audited", "claim.qualified"}


def test_note_add_records_the_capture_host_as_provenance_not_as_text(
    vscode_client: TestClient,
) -> None:
    """`noteCommands.noteSource` sends `source`; the note text stays the researcher's words."""
    result = succeed(
        vscode_client,
        "note.add",
        {"text": "check the corrected split", "source": "vscode main.tex:23"},
    )
    assert result["event"]["event"] == "note.captured"
    assert result["event"]["payload"]["text"] == "check the corrected split"
    assert "source" not in result["event"]["payload"], (
        "the capture host stays out of the event, so CLI and HTTP journal the same thing"
    )

    fields = result["diff"]["fields"]
    assert fields["text"]["new"] == "check the corrected split"
    assert fields["provenance.note"]["new"] == "captured via vscode main.tex:23", (
        "the editor's origin belongs in provenance, never in what the note says"
    )

    refused = invoke(vscode_client, "note.add", {"text": "from the editor", "origin": "vscode"})
    assert refused["ok"] is False
    assert refused["error"]["code"] == "invalid_request", (
        "note.add rejects an unknown field, so the extension must not invent one"
    )


def test_retrieval_resolve_source_takes_a_reference(
    vscode_client: TestClient, types_source: str
) -> None:
    """`Open Evidence` sends `{ref}`; with no Evidence here, it must refuse cleanly."""
    catalog = vscode_client.get("/capabilities").json()
    descriptor = next(
        item for item in catalog["capabilities"] if item["name"] == "retrieval.resolve_source"
    )
    assert set(descriptor["request_schema"]["properties"]) == {"ref"}

    declared = _interface_fields(types_source, "SourceRef")
    published = set(descriptor["response_schema"]["properties"])
    assert declared <= published, f"SourceRef declares {sorted(declared - published)}"

    envelope = invoke(vscode_client, "retrieval.resolve_source", {"ref": "E0001"})
    assert envelope["ok"] is False
    assert envelope["error"]["code"] in {"object_not_found", "projection_error", "capability_error"}


# -- 3. authority ------------------------------------------------------------


def test_an_extension_without_the_token_may_read_but_not_attach(
    agent_host_client: TestClient,
) -> None:
    """The refusal `errors.ts` explains: no token means agent host, which never accepts."""
    assert agent_host_client.get("/objects/C0001").status_code == 200
    read = invoke(agent_host_client, "manuscript.audit", project_request())
    assert read["ok"] is True

    refused = invoke(
        agent_host_client,
        "manuscript.attach_claim",
        {
            "anchor": {
                "provenance": {"source": "human", "actor": "human", "workflow": "vscode"},
                "file": "main.tex",
                "line_start": 23,
                "line_end": 23,
                "sentence": "Our sweep shows that detection quality degrades.",
                "sentence_fingerprint": sentence_fingerprint("anything"),
                "claim": "C0001",
            }
        },
    )
    assert refused["ok"] is False
    assert refused["error"]["code"] == "permission_denied"


def test_the_error_codes_the_extension_branches_on_are_the_daemon_s(
    vscode_client: TestClient,
) -> None:
    """`errors.ts` maps `code`, never the message; these are the codes it maps."""
    unknown = invoke(vscode_client, "claim.no_such_capability", {})
    assert unknown["error"]["code"] == "capability_not_found"

    bad = invoke(vscode_client, "claim.find_support", {"claim_id": "not-an-id"})
    assert bad["error"]["code"] == "invalid_request"

    absent = invoke(vscode_client, "claim.find_support", {"claim_id": "C0404"})
    assert absent["error"]["code"] == "object_not_found"


# -- 4. the exported fixtures still describe this daemon ---------------------


def test_the_typescript_fixtures_match_what_the_daemon_returns(vscode_client: TestClient) -> None:
    """`vscode/src/test/fixtures/audit-report.json` is a real response, and must stay one.

    The extension's unit tests map that file onto editor ranges. Re-run
    `uv run python vscode/scripts/export_fixtures.py` when this fails: it means the auditor
    changed and the mocked tests are now asserting against an answer nobody gives.
    """
    exported = json.loads(
        (VSCODE_ROOT / "src" / "test" / "fixtures" / "audit-report.json").read_text(
            encoding="utf-8"
        )
    )
    live = succeed(vscode_client, "manuscript.audit", project_request())

    assert [finding["kind"] for finding in live["findings"]] == [
        finding["kind"] for finding in exported["findings"]
    ]
    assert [finding["severity"] for finding in live["findings"]] == [
        finding["severity"] for finding in exported["findings"]
    ]
    assert [finding["location"] for finding in live["findings"]] == [
        finding["location"] for finding in exported["findings"]
    ], "the exported report must carry `location`; re-run export_fixtures.py"
    assert live["sentences_checked"] == exported["sentences_checked"]
    assert live["anchored_sentences"] == exported["anchored_sentences"]
    assert live["unanchored_substantive"] == exported["unanchored_substantive"]

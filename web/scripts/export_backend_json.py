"""Refresh the checked-in snapshots the cockpit is typed and tested against.

Run from the repository root:

    uv run python web/scripts/export_backend_json.py

It writes four kinds of file, all of them derived from the running daemon rather than
hand-written, so a drift between the Web and the API shows up as a diff:

* `web/openapi.json`        - the daemon's OpenAPI document (`pnpm gen:types` reads it).
* `web/capabilities.json`   - `GET /capabilities`: every name, permission, and JSON schema.
* `web/src/test/fixtures/*` - real responses from a real workspace, for the vitest suite.

Two workspaces are built. The first is the Gate P11 one (`tests/e2e/test_web_gate.py`): the
synthetic paper, ingested and parsed through capabilities, with three verified candidates
staged by a scripted extractor and verifier. The second is the fixture manuscript
`vscode/scripts/export_fixtures.py` builds — two Claims, three anchors, one unattached
sentence — because the Manuscript view needs a manuscript and the Gate P11 corpus has none.
Pinning both clients to the same manuscript is what makes "the cockpit and the editor agree"
mean something. Nothing here talks to a network or a model.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "web"
FIXTURES = WEB_ROOT / "src" / "test" / "fixtures"

if str(REPO_ROOT) not in sys.path:  # the fixture builders live in `tests/`
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    """Write every snapshot, and report what changed."""
    from starlette.testclient import TestClient
    from tests.e2e.test_web_gate import SUPPORTS, build_corpus, stage_candidates

    from research_harness.capabilities.registry import build_default_registry
    from research_harness.server.app import create_app, ensure_token

    registry = build_default_registry()
    scratch = Path(tempfile.mkdtemp(prefix="research-harness-web-fixtures-"))
    root = build_corpus(scratch / "cockpit", registry)
    stage_candidates(root)

    app = create_app(root, registry=registry)
    write(WEB_ROOT / "openapi.json", app.openapi())

    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {ensure_token(root)}"
        write(WEB_ROOT / "capabilities.json", client.get("/capabilities").json())
        write(FIXTURES / "health.json", client.get("/health").json())
        write(FIXTURES / "overview-empty.json", client.get("/overview").json())

        queue = invoke(client, "review.inbox", {})
        write(FIXTURES / "review-inbox.json", queue)
        first = queue["items"][0]
        candidate = client.get(f"/candidates/{first['candidate_id']}").json()
        write(FIXTURES / "candidate.json", candidate)
        write(FIXTURES / "blocks.json", client.get(f"/blocks/{first['artifact']}").json())

        invoke(
            client,
            "review.resolve_conflict",
            {
                "candidate_id": first["candidate_id"],
                "choice": "accept",
                "reason": "row TrafficLM, column F1 of Table 1, read on page 4",
            },
        )
        invoke(client, "claim.create", {"claim": claim_payload()})
        invoke(client, "claim.relate", {"claim_id": "C0001", "relation": SUPPORTS})
        invoke(
            client,
            "claim.audit",
            {
                "claim_id": "C0001",
                "status": "supported",
                "allowed_strength": "individual",
                "maximum_defensible_wording": "one system on one held-out split",
            },
        )
        support = invoke(client, "claim.find_support", {"claim_id": "C0001"})
        write(FIXTURES / "claim-support.json", support)
        write(FIXTURES / "claim.json", client.get("/objects/C0001").json())
        write(FIXTURES / "overview.json", client.get("/overview").json())
        write(FIXTURES / "index.json", client.get("/index").json())

    manuscript = manuscript_snapshots(registry, scratch / "manuscript")
    print(f"snapshots refreshed from {root} and {manuscript}")
    return 0


def manuscript_snapshots(registry: Any, root: Path) -> Path:
    """The three manuscript reads, from the workspace the VS Code fixtures are built in."""
    from starlette.testclient import TestClient

    from research_harness.server.app import create_app, ensure_token

    builder = load_vscode_fixture_builder()
    builder.build_workspace(root)
    project = {"project_root": None, "main_tex": "main.tex"}

    with TestClient(create_app(root, registry=registry)) as client:
        client.headers["Authorization"] = f"Bearer {ensure_token(root)}"
        write(FIXTURES / "manuscript-anchors.json", invoke(client, "manuscript.anchors", project))
        write(FIXTURES / "manuscript-audit.json", invoke(client, "manuscript.audit", project))
        write(
            FIXTURES / "manuscript-trace.json",
            invoke(client, "manuscript.trace", {**project, "file": "main.tex", "line": 17}),
        )
    return root


def load_vscode_fixture_builder() -> ModuleType:
    """Import `vscode/scripts/export_fixtures.py` by path; it is not an installed package."""
    path = REPO_ROOT / "vscode" / "scripts" / "export_fixtures.py"
    spec = importlib.util.spec_from_file_location("vscode_export_fixtures", path)
    if spec is None or spec.loader is None:  # pragma: no cover - only if the file is deleted
        raise SystemExit(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def invoke(client: Any, capability: str, request: dict[str, Any]) -> dict[str, Any]:
    """One capability call, insisting it succeeded: a snapshot of a refusal helps nobody."""
    body = client.post(f"/capabilities/{capability}", json=request).json()
    if not body["ok"]:
        raise SystemExit(f"{capability} refused: {body['error']}")
    result: dict[str, Any] = body["result"]
    return result


def claim_payload() -> dict[str, Any]:
    """The claim the fixtures are built around, at the strength the researcher asks for."""
    from research_harness.domain.transitions import HUMAN_ACTOR

    return {
        "id": "C0001",
        "statement": "TrafficLM reaches an F1 of 94.32 on CICIDS2017",
        "type": "descriptive",
        "semantics": {"subject": "TrafficLM", "predicate": "reaches", "object": "F1 94.32"},
        "scope": {"level": "observed_subset", "corpus": "encrypted traffic classifiers"},
        "assessment": {"requested_strength": "observed_subset", "allowed_strength": "individual"},
        "provenance": {"source": "human", "actor": HUMAN_ACTOR},
    }


def write(path: Path, payload: Any) -> None:
    """Write one snapshot, stably ordered so a rerun that changes nothing produces no diff."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    previous = path.read_text(encoding="utf-8") if path.is_file() else None
    path.write_text(body, encoding="utf-8")
    state = "unchanged" if previous == body else "written"
    print(f"  {state:9} {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    raise SystemExit(main())

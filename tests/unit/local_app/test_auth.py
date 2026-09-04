"""The local app's authentication: one token, one-time nonces, and same-origin control."""

from __future__ import annotations

import os
import stat
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from research_harness.capabilities.permissions import Permission, PrincipalKind
from research_harness.local_app.auth import (
    APP_HOST,
    APP_TOKEN_FILENAME,
    BootstrapIssued,
    BootstrapStore,
    SessionExchange,
    SessionIssued,
    allowed_origins,
    app_principal_resolver,
    app_token_path,
    bearer_token,
    ensure_app_token,
    require_app_token,
    require_control_mutation,
    require_same_origin,
)
from research_harness.server.app import DEV_ORIGINS

PORT = 8765

RequestFactory = Callable[..., Request]


@pytest.fixture
def token(tmp_path: Path) -> str:
    """The app token an authenticated caller presents."""
    return ensure_app_token(tmp_path)


@pytest.fixture
def app_request(token: str) -> RequestFactory:
    """A Starlette request against an app whose state carries the token and port."""

    def make(
        headers: Mapping[str, str] | None = None,
        *,
        port: int = PORT,
        state_token: str | None = token,
    ) -> Request:
        host = FastAPI()
        if state_token is not None:
            host.state.app_token = state_token
        host.state.app_port = port
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/projects/open",
            "headers": [
                (name.lower().encode("latin-1"), value.encode("latin-1"))
                for name, value in (headers or {}).items()
            ],
            "app": host,
        }
        return Request(scope)

    return make


# -- the persisted app token -------------------------------------------------


def test_the_app_token_is_stable_across_calls(tmp_path: Path) -> None:
    first = ensure_app_token(tmp_path)
    second = ensure_app_token(tmp_path)
    assert first == second
    assert app_token_path(tmp_path).read_text(encoding="utf-8").strip() == first


def test_the_app_token_lives_beside_the_data_dir_under_a_known_name(tmp_path: Path) -> None:
    assert app_token_path(tmp_path) == tmp_path / APP_TOKEN_FILENAME


def test_the_app_token_is_created_in_a_data_dir_that_does_not_exist_yet(tmp_path: Path) -> None:
    nested = tmp_path / "missing" / "app"
    assert ensure_app_token(nested)
    assert app_token_path(nested).is_file()


def test_the_app_token_is_opaque_and_long_enough_to_resist_guessing(tmp_path: Path) -> None:
    assert len(ensure_app_token(tmp_path)) >= 32


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_the_app_token_file_is_readable_only_by_its_owner(tmp_path: Path) -> None:
    ensure_app_token(tmp_path)
    mode = stat.S_IMODE(app_token_path(tmp_path).stat().st_mode)
    assert mode == 0o600


def test_the_app_token_is_never_written_into_the_project_registry(tmp_path: Path) -> None:
    registry = tmp_path / "projects.json"
    registry.write_text('{"version": 1, "projects": []}\n', encoding="utf-8")
    issued = ensure_app_token(tmp_path)
    assert issued not in registry.read_text(encoding="utf-8")
    assert "token" not in registry.read_text(encoding="utf-8")


def test_writing_the_app_token_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    ensure_app_token(tmp_path)
    assert [path.name for path in tmp_path.iterdir()] == [APP_TOKEN_FILENAME]


# -- who a token makes you ---------------------------------------------------


def test_the_app_token_resolves_the_human_and_no_token_resolves_an_agent_host(
    tmp_path: Path,
) -> None:
    issued = ensure_app_token(tmp_path)
    resolve = app_principal_resolver(issued)
    assert resolve(issued).kind == PrincipalKind.HUMAN
    assert resolve(None).kind == PrincipalKind.AGENT_HOST


def test_a_wrong_token_resolves_the_app_agent_host_and_cannot_accept(token: str) -> None:
    principal = app_principal_resolver(token)("not-the-token")
    assert principal.kind == PrincipalKind.AGENT_HOST
    assert principal.host == APP_HOST
    assert Permission.MUTATE not in principal.granted


def test_the_resolved_human_keeps_the_existing_researcher_authority(token: str) -> None:
    assert Permission.MUTATE in app_principal_resolver(token)(token).granted


# -- bearer parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer abc", "abc"),
        ("bearer abc", "abc"),
        ("Bearer  abc ", "abc"),
        ("Basic abc", None),
        ("Bearer", None),
        ("Bearer   ", None),
        ("", None),
        (None, None),
    ],
)
def test_bearer_token_reads_only_a_bearer_credential(
    header: str | None, expected: str | None
) -> None:
    assert bearer_token(header) == expected


# -- one-time bootstrap nonces -----------------------------------------------


class FakeClock:
    """A monotonic clock the test advances by hand; no sleeps in the suite."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_bootstrap_nonce_is_single_use() -> None:
    store = BootstrapStore(ttl_seconds=60, clock=FakeClock())
    nonce = store.issue()
    assert store.exchange(nonce) is True
    assert store.exchange(nonce) is False


def test_every_issued_bootstrap_nonce_is_distinct_and_opaque() -> None:
    store = BootstrapStore()
    nonces = {store.issue() for _ in range(5)}
    assert len(nonces) == 5
    assert all(len(nonce) >= 32 for nonce in nonces)


def test_a_bootstrap_nonce_expires_after_its_ttl() -> None:
    clock = FakeClock()
    store = BootstrapStore(ttl_seconds=60, clock=clock)
    nonce = store.issue()
    clock.now = 60.0
    assert store.exchange(nonce) is False


def test_a_bootstrap_nonce_still_works_inside_its_ttl() -> None:
    clock = FakeClock()
    store = BootstrapStore(ttl_seconds=60, clock=clock)
    nonce = store.issue()
    clock.now = 59.0
    assert store.exchange(nonce) is True


def test_an_unknown_bootstrap_value_is_refused() -> None:
    store = BootstrapStore()
    store.issue()
    assert store.exchange("not-a-nonce") is False
    assert store.exchange("") is False


def test_expired_bootstrap_nonces_are_pruned_rather_than_accumulated() -> None:
    clock = FakeClock()
    store = BootstrapStore(ttl_seconds=60, clock=clock)
    store.issue()
    store.issue()
    clock.now = 120.0
    store.issue()
    assert len(store) == 1


def test_a_bootstrap_nonce_is_consumed_exactly_once_under_concurrency() -> None:
    store = BootstrapStore(ttl_seconds=60)
    nonce = store.issue()
    results: list[bool] = []
    guard = threading.Lock()
    start = threading.Barrier(8)

    def attempt() -> None:
        start.wait()
        outcome = store.exchange(nonce)
        with guard:
            results.append(outcome)

    workers = [threading.Thread(target=attempt) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert results.count(True) == 1


def test_a_datetime_clock_is_accepted_for_the_bootstrap_ttl() -> None:
    from datetime import UTC, datetime, timedelta

    moment = datetime(2026, 9, 4, tzinfo=UTC)

    def clock() -> datetime:
        return moment

    store = BootstrapStore(ttl_seconds=60, clock=clock)
    nonce = store.issue()
    moment += timedelta(seconds=120)
    assert store.exchange(nonce) is False


# -- origins -----------------------------------------------------------------


def test_the_allowed_origins_are_loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCH_HARNESS_DEV", raising=False)
    assert allowed_origins(PORT) == frozenset(
        {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
    )


def test_dev_mode_widens_the_allowed_origins_to_the_dev_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_HARNESS_DEV", "1")
    assert set(DEV_ORIGINS) <= allowed_origins(PORT)


# -- the request dependencies ------------------------------------------------


def test_a_control_read_without_a_token_is_refused_as_unauthenticated(
    app_request: RequestFactory,
) -> None:
    with pytest.raises(HTTPException, match="authentication") as raised:
        require_app_token(app_request({}))
    assert raised.value.status_code == 401
    assert raised.value.detail == {
        "code": "control_permission_denied",
        "message": "app authentication required",
    }


def test_a_control_read_with_a_wrong_token_is_refused(app_request: RequestFactory) -> None:
    with pytest.raises(HTTPException) as raised:
        require_app_token(app_request({"Authorization": "Bearer wrong"}))
    assert raised.value.status_code == 401


def test_a_control_read_with_the_app_token_is_allowed(
    app_request: RequestFactory, token: str
) -> None:
    assert require_app_token(app_request({"Authorization": f"Bearer {token}"})) is None


def test_a_control_read_is_refused_when_the_host_carries_no_token(
    app_request: RequestFactory,
) -> None:
    with pytest.raises(HTTPException) as raised:
        require_app_token(app_request({"Authorization": "Bearer anything"}, state_token=None))
    assert raised.value.status_code == 401


def test_a_control_mutation_from_a_foreign_origin_is_refused(
    app_request: RequestFactory, token: str
) -> None:
    request = app_request(
        {"Authorization": f"Bearer {token}", "Origin": "https://evil.test"},
    )
    with pytest.raises(HTTPException, match="origin") as raised:
        require_control_mutation(request)
    assert raised.value.status_code == 403
    assert raised.value.detail == {
        "code": "control_permission_denied",
        "message": "request origin is not allowed",
    }


def test_a_control_mutation_without_an_origin_is_refused(
    app_request: RequestFactory, token: str
) -> None:
    with pytest.raises(HTTPException, match="origin") as raised:
        require_control_mutation(app_request({"Authorization": f"Bearer {token}"}))
    assert raised.value.status_code == 403


def test_a_control_mutation_on_another_port_is_refused(
    app_request: RequestFactory, token: str
) -> None:
    request = app_request(
        {"Authorization": f"Bearer {token}", "Origin": "http://127.0.0.1:9999"},
        port=PORT,
    )
    with pytest.raises(HTTPException) as raised:
        require_control_mutation(request)
    assert raised.value.status_code == 403


@pytest.mark.parametrize("origin", [f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"])
def test_a_same_origin_control_mutation_with_the_token_is_allowed(
    app_request: RequestFactory, token: str, origin: str
) -> None:
    request = app_request({"Authorization": f"Bearer {token}", "Origin": origin})
    assert require_control_mutation(request) is None


def test_a_control_mutation_is_authenticated_before_its_origin_is_judged(
    app_request: RequestFactory,
) -> None:
    request = app_request({"Origin": f"http://127.0.0.1:{PORT}"})
    with pytest.raises(HTTPException, match="authentication") as raised:
        require_control_mutation(request)
    assert raised.value.status_code == 401


def test_same_origin_alone_does_not_require_the_app_token(app_request: RequestFactory) -> None:
    assert require_same_origin(app_request({"Origin": f"http://127.0.0.1:{PORT}"})) is None


def test_a_refusal_never_leaks_a_filesystem_path(
    app_request: RequestFactory, tmp_path: Path
) -> None:
    with pytest.raises(HTTPException) as raised:
        require_app_token(app_request({}))
    detail = str(raised.value.detail)
    assert str(tmp_path) not in detail
    assert APP_TOKEN_FILENAME not in detail
    assert "/" not in detail and "\\" not in detail


# -- used as FastAPI dependencies --------------------------------------------


def _dependency_app(token: str) -> FastAPI:
    host = FastAPI()
    host.state.app_token = token
    host.state.app_port = PORT

    @host.get("/api/projects", dependencies=[Depends(require_app_token)])
    def projects() -> dict[str, list[str]]:
        return {"projects": []}

    @host.post("/api/projects/open", dependencies=[Depends(require_control_mutation)])
    def open_project() -> dict[str, bool]:
        return {"ok": True}

    return host


def test_the_dependencies_gate_real_routes(token: str) -> None:
    client = TestClient(_dependency_app(token))
    authorization = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", headers=authorization).status_code == 200
    assert client.post("/api/projects/open", headers=authorization).status_code == 403
    allowed = {**authorization, "Origin": f"http://127.0.0.1:{PORT}"}
    assert client.post("/api/projects/open", headers=allowed).status_code == 200


def test_an_unauthenticated_control_read_says_nothing_about_projects(token: str) -> None:
    response = TestClient(_dependency_app(token)).get("/api/projects")
    assert response.status_code == 401
    assert response.json() == {
        "detail": {"code": "control_permission_denied", "message": "app authentication required"}
    }


# -- the control-plane bodies ------------------------------------------------


def test_the_bootstrap_and_session_bodies_are_closed() -> None:
    issued = BootstrapIssued(bootstrap="nonce", expires_in=60.0)
    assert issued.bootstrap == "nonce"
    assert SessionExchange(bootstrap="nonce").bootstrap == "nonce"
    assert SessionIssued(token="tok").token == "tok"
    with pytest.raises(ValueError):
        SessionExchange(bootstrap="nonce", token="tok")  # type: ignore[call-arg]

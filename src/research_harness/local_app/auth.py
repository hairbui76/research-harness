"""Authentication for the multi-project local app: one token, nonces, and same-origin.

The app holds application state (which folders a researcher has opened), so an
unauthenticated caller must not be able to enumerate paths, open a picker, or register a
folder (design §8.1). Three checks do that work:

* one random **app token**, persisted beside the app's data with owner-only permissions and
  never written into `projects.json` - secrets never live in canonical or registry files;
* short-lived, single-use **bootstrap nonces**, so the launch URL carries no durable secret;
* an exact **Origin** check on control mutations, so a page on another origin cannot drive
  the loopback app from the researcher's own browser.

This module widens nobody's authority: a valid token resolves the same `Principal.human()`
the one-workspace daemon resolves, and everything else is the read-and-stage agent host
(design §8.2). Workspace routes below `/api/projects/{project_id}` keep the legacy
behaviour where a missing token simply means an agent host.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from research_harness.capabilities.permissions import Principal
from research_harness.server.app import DEV_ORIGINS, PrincipalResolver, dev_mode
from research_harness.workspace.atomic import fsync_directory

__all__ = [
    "APP_HOST",
    "APP_TOKEN_FILENAME",
    "BOOTSTRAP_TTL_SECONDS",
    "PERMISSION_DENIED",
    "BootstrapIssued",
    "BootstrapStore",
    "SessionExchange",
    "SessionIssued",
    "allowed_origins",
    "app_principal_resolver",
    "app_token_path",
    "bearer_token",
    "ensure_app_token",
    "require_app_token",
    "require_control_mutation",
    "require_same_origin",
]

logger = logging.getLogger(__name__)

APP_TOKEN_FILENAME = "app-token"
"""Where the app token lives, under the app data directory. Never a canonical file."""

APP_HOST = "app"
"""The agent host recorded for a caller of the app with no valid app token."""

PERMISSION_DENIED = "control_permission_denied"
"""The stable error code every control-plane refusal carries."""

BOOTSTRAP_TTL_SECONDS = 60.0
"""How long a launch nonce stays exchangeable: long enough for a browser to start."""

TOKEN_BYTES = 32
"""Entropy for the app token and for each bootstrap nonce."""

Clock = Callable[[], float] | Callable[[], datetime]
"""A monotonic seconds clock, or a wall clock, so tests can advance time by hand."""


# -- the persisted app token -------------------------------------------------


def app_token_path(data_dir: Path) -> Path:
    """The app token file for an app data directory."""
    return Path(data_dir) / APP_TOKEN_FILENAME


def ensure_app_token(data_dir: Path) -> str:
    """Read the app token, creating one on first launch.

    The token is regenerable runtime state: deleting it costs a relaunch and nothing else,
    and it carries no scientific authority of its own - it only says "this caller is the
    local researcher". It is stored on its own so that no registry or canonical file ever
    holds a secret.
    """
    path = app_token_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    if existing:
        return existing
    token = secrets.token_urlsafe(TOKEN_BYTES)
    _write_secret(path, f"{token}\n")
    return token


def _write_secret(path: Path, text: str) -> None:
    """Write a secret atomically, owner-only from the moment it first has bytes."""
    directory = path.parent
    temp = directory / f".tmp-{path.name}.{uuid4().hex}"
    try:
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _with_permissions(temp)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    fsync_directory(directory)


def _with_permissions(path: Path) -> None:
    """Restrict a secret to its owner where the platform supports it."""
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - platforms without POSIX permissions
        logger.debug("could not restrict permissions on the app token")


# -- who a token makes you ---------------------------------------------------


def app_principal_resolver(token: str) -> PrincipalResolver:
    """The app token means the local researcher; anything else is an agent host."""

    def resolve(presented: str | None) -> Principal:
        if presented is not None and secrets.compare_digest(presented, token):
            return Principal.human()
        return Principal.agent_host(APP_HOST)

    return resolve


def bearer_token(authorization: str | None) -> str | None:
    """The token out of an ``Authorization: Bearer <token>`` header."""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


# -- one-time bootstrap nonces -----------------------------------------------


@dataclass(frozen=True, slots=True)
class _Pending:
    """One issued nonce: its digest, and when it stops being exchangeable."""

    digest: bytes
    expires_at: float


class BootstrapStore:
    """Short-lived, single-use nonces that hand the app token to the local browser once.

    Only SHA-256 digests are held, and only in memory: a nonce is never persisted, never
    logged, and never survives the process that issued it. Expired entries are pruned on
    every issue and exchange, so a long-running app does not accumulate them.
    """

    def __init__(
        self, ttl_seconds: float = BOOTSTRAP_TTL_SECONDS, *, clock: Clock = time.monotonic
    ) -> None:
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: list[_Pending] = []

    def issue(self) -> str:
        """Mint a nonce valid for ``ttl_seconds``; the caller sees it exactly once."""
        value = secrets.token_urlsafe(TOKEN_BYTES)
        with self._lock:
            now = self._now()
            self._prune(now)
            self._pending.append(_Pending(_digest(value), now + self.ttl_seconds))
        return value

    def exchange(self, value: str) -> bool:
        """Consume a nonce. True once, for an unexpired value; False every other time."""
        if not value:
            return False
        presented = _digest(value)
        with self._lock:
            self._prune(self._now())
            matched = -1
            for index, pending in enumerate(self._pending):
                if secrets.compare_digest(pending.digest, presented):
                    matched = index
            if matched < 0:
                return False
            del self._pending[matched]
            return True

    def __len__(self) -> int:
        """How many nonces are still exchangeable; expired ones are dropped first."""
        with self._lock:
            self._prune(self._now())
            return len(self._pending)

    def _prune(self, now: float) -> None:
        self._pending = [pending for pending in self._pending if pending.expires_at > now]

    def _now(self) -> float:
        moment = self._clock()
        return moment.timestamp() if isinstance(moment, datetime) else float(moment)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


# -- control-plane bodies ----------------------------------------------------


class BootstrapIssued(BaseModel):
    """What `POST /api/app/bootstrap` returns to the CLI: a nonce and its lifetime."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bootstrap: str
    expires_in: float = Field(gt=0)


class SessionExchange(BaseModel):
    """What the browser posts to `POST /api/app/session`: the nonce from its launch URL."""

    model_config = ConfigDict(extra="forbid")

    bootstrap: str = Field(min_length=1, max_length=256)


class SessionIssued(BaseModel):
    """The app token, handed to the browser once in exchange for a valid nonce."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str


# -- request dependencies ----------------------------------------------------


def allowed_origins(port: int) -> frozenset[str]:
    """The origins this app answers control mutations for: loopback on its own port.

    Both spellings of loopback are allowed because a browser sends whichever the researcher
    typed. Development mode additionally allows the Vite dev server, exactly as the
    one-workspace daemon does; nothing here ever allows a remote origin.
    """
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    if dev_mode():
        origins.update(DEV_ORIGINS)
    return frozenset(origins)


def require_app_token(request: Request) -> None:
    """Refuse a control-plane call that does not present the app token.

    Reads `request.app.state.app_token`. The refusal names no path and no project: an
    unauthenticated caller learns only that authentication is required.
    """
    expected = getattr(request.app.state, "app_token", None)
    presented = bearer_token(request.headers.get("authorization"))
    if (
        not isinstance(expected, str)
        or not expected
        or presented is None
        or not secrets.compare_digest(presented, expected)
    ):
        raise _denied(401, "app authentication required")


def require_same_origin(request: Request) -> None:
    """Refuse a call whose `Origin` is not this app's own loopback origin.

    Reads `request.app.state.app_port`. A missing `Origin` is refused too: a browser sends
    one on every cross-site-capable request, so its absence is not evidence of safety.
    """
    port = getattr(request.app.state, "app_port", None)
    origin = request.headers.get("origin")
    if not isinstance(port, int) or origin is None or origin not in allowed_origins(port):
        raise _denied(403, "request origin is not allowed")


def require_control_mutation(request: Request) -> None:
    """Both checks, in order: authentication first, then the browser's origin.

    Every control-plane mutation (create, open, initialize, locate, rename, forget, reveal,
    folder dialog) goes through this. Authentication is judged first so that a same-origin
    page without the token still learns nothing about the origin policy.
    """
    require_app_token(request)
    require_same_origin(request)


def _denied(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": PERMISSION_DENIED, "message": message})

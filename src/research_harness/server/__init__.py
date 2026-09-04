"""The local FastAPI daemon (Product 35, ADR-009).

One workspace, loopback only, and no route that writes anything the named capabilities do
not write. `server/` is a transport: it never touches canonical files or SQLite itself.

`create_workspace_app` is the one implementation of those routes; `create_app` is the
one-workspace daemon around it, and the multi-project host mounts one per open project.
"""

from __future__ import annotations

from research_harness.server.app import (
    DAEMON_TOKEN_FILENAME,
    bearer_token,
    create_app,
    create_workspace_app,
    ensure_token,
    token_path,
)

__all__ = [
    "DAEMON_TOKEN_FILENAME",
    "bearer_token",
    "create_app",
    "create_workspace_app",
    "ensure_token",
    "token_path",
]

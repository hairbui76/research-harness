"""The local FastAPI daemon (Product 35, ADR-009).

One workspace, loopback only, and no route that writes anything the named capabilities do
not write. `server/` is a transport: it never touches canonical files or SQLite itself.
"""

from __future__ import annotations

from research_harness.server.app import (
    DAEMON_TOKEN_FILENAME,
    create_app,
    ensure_token,
    token_path,
)

__all__ = ["DAEMON_TOKEN_FILENAME", "create_app", "ensure_token", "token_path"]

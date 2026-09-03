"""`GET /runs/{run_id}/events`: the server-sent event stream of one model call.

This is a **read**. The write that produced it was `session.send`, a named capability; the
daemon publishes no route that appends to a transcript (ADR-004). What this route does is
replay what the run already persisted and keep replaying it until the run reaches a
terminal state.

That ordering is the contract, not an implementation detail. Every delta is written into
the run *before* it is emitted (v1.1 plan SS0.4), so:

* a client that reconnects reads the same content from `session.get`, byte for byte;
* a client that opens the stream after the run finished gets the whole answer replayed and
  then the terminal `status`, which is why "watch a finished run" needs no special case;
* a stream that ends without a terminal status means the connection dropped, never that
  the run succeeded -- the client reconciles through `session.get`.

Frames are exactly the three of plan SS0.4 -- `delta`, `status`, `error` -- and the stream
ends after the terminal `status`.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from research_harness.capabilities.context import open_context
from research_harness.capabilities.permissions import Permission, Principal
from research_harness.conversation.send import TERMINAL_STATES, stream_events
from research_harness.workspace.runs import RunNotFoundError, RunStore, RunStoreError

if TYPE_CHECKING:  # pragma: no cover - `server/app.py` imports this module, not the reverse
    from fastapi import FastAPI

__all__ = [
    "EVENT_MEDIA_TYPE",
    "POLL_SECONDS",
    "STREAM_TIMEOUT_SECONDS",
    "register_session_routes",
    "sse_frame",
]

logger = logging.getLogger(__name__)

EVENT_MEDIA_TYPE = "text/event-stream"

POLL_SECONDS = 0.05
"""How often a live run is re-read. The run store is a small local file; this is cheap."""

STREAM_TIMEOUT_SECONDS = 900.0
"""How long a stream waits for a terminal state before disconnecting. A client that is
cut off reconciles through `session.get`, which already holds every delta."""

#: Streaming defeats every cache between here and the browser, and says so.
_STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _caller(request: Request) -> Principal:
    """Who is calling, resolved exactly as every other daemon route resolves it."""
    resolve: Callable[[str | None], Principal] = request.app.state.principal_resolver
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    return resolve(token.strip() if scheme.lower() == "bearer" and token.strip() else None)


Caller = Annotated[Principal, Depends(_caller)]

AfterQuery = Annotated[
    int,
    Query(ge=0, description="Replay deltas from this index; 0 replays the whole answer."),
]


def sse_frame(event: str, payload: dict[str, Any]) -> str:
    """One server-sent event: the named event and one JSON object, terminated by a blank line."""
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n"


def register_session_routes(app: FastAPI, root: Path) -> None:
    """Add the run event stream to ``app``. Called once from `create_app`."""

    @app.get("/runs/{run_id}/events")
    def run_events(run_id: str, request: Request, caller: Caller, after: AfterQuery = 0) -> Any:
        """Stream one run's deltas and its terminal status (v1.1 plan SS0.4).

        A read: `read` permission, like every other run route, and the same principal
        resolution. Watching an answer arrive is not authority to have asked for it.
        """
        caller.authorize(f"runs.events:{run_id}", Permission.READ, human_only=False)
        store = RunStore(open_context(root, caller.actor).repo.layout.research_dir)
        try:
            store.load(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StreamingResponse(
            _events(store, run_id, after=after, request=request),
            media_type=EVENT_MEDIA_TYPE,
            headers=dict(_STREAM_HEADERS),
        )


def _events(
    store: RunStore, run_id: str, *, after: int, request: Request | None = None
) -> Iterator[str]:
    """Yield frames until the run reaches a terminal state, the client leaves, or time runs out.

    The generator holds no lock and keeps no state beyond how many deltas it has already
    sent, so two clients watching the same run see the same frames in the same order.
    """
    sent = after
    announced: str | None = None
    deadline = time.monotonic() + STREAM_TIMEOUT_SECONDS
    while True:
        try:
            frames = list(stream_events(store, run_id, after=sent))
        except (RunNotFoundError, RunStoreError) as exc:  # pragma: no cover - deleted mid-stream
            yield sse_frame(
                "error", {"code": "run_unreadable", "message": str(exc), "retryable": False}
            )
            return
        finished = False
        for event, payload in frames:
            if event == "delta":
                sent += 1
            elif event == "status":
                state = str(payload.get("state"))
                finished = state in TERMINAL_STATES
                if not finished and state == announced:
                    # A run still working reports the same state on every poll; saying so
                    # once is information, saying so twenty times a second is noise.
                    continue
                announced = state
            yield sse_frame(event, payload)
        if finished:
            return
        if time.monotonic() >= deadline:  # pragma: no cover - a 15 minute answer
            logger.info("run %s event stream timed out waiting for a terminal state", run_id)
            return
        if request is not None and _disconnected(request):  # pragma: no cover - client left
            return
        time.sleep(POLL_SECONDS)


def _disconnected(request: Request) -> bool:
    """Whether the client has gone away, without awaiting anything in a sync generator."""
    return bool(getattr(request, "_is_disconnected", False))

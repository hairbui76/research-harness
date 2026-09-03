"""The daemon's manuscript byte route: the compiled PDF, and nothing else.

A PDF preview cannot be assembled from JSON, so the one thing the capability surface cannot
carry is the file itself. This route is the counterpart of `GET /artifacts/{id}/bytes`:
read-only, streamed with the right media type, and inline, so a viewer opens the page
rather than downloading it.

There is deliberately no route that *writes* a manuscript file. Saving goes through
`manuscript.write_file` and applying a candidate through `manuscript.apply_suggestion`, so
the capability layer stays the only surface that changes source (ADR-004).

``latest`` and ``last-good`` are accepted where a build id is expected, because the two
questions a preview asks - "show me what I just compiled" and "show me the last thing that
worked" - are exactly the ones a failed build makes different, and a client should not have
to read a build record to ask either of them (LaTeX spec 5, 9).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse

from research_harness.capabilities.permissions import Permission, Principal
from research_harness.domain.errors import ResearchHarnessError
from research_harness.manuscript.workspace import LAST_GOOD_BUILD, LATEST_BUILD

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

__all__ = [
    "LAST_GOOD_ALIAS",
    "LATEST_ALIAS",
    "MANUSCRIPT_PDF_ROUTE",
    "PDF_MEDIA_TYPE",
    "manuscript_pdf",
    "register_manuscript_routes",
]

logger = logging.getLogger(__name__)

PDF_MEDIA_TYPE = "application/pdf"

MANUSCRIPT_PDF_ROUTE = "/manuscript/builds/{build_id}/pdf"

LATEST_ALIAS = LATEST_BUILD
"""``/manuscript/builds/latest/pdf`` - the newest build's PDF, else the last good one."""

LAST_GOOD_ALIAS = LAST_GOOD_BUILD
"""``/manuscript/builds/last-good/pdf`` - the newest build that really produced a PDF.

Both names come from `manuscript/workspace.py`, which is also where `manuscript.build`
reads them, so the route and the capability cannot disagree about what `latest` means."""


def _caller(request: Request) -> Principal:
    """Who is calling, resolved exactly as every other daemon route resolves it."""
    resolve: Callable[[str | None], Principal] = request.app.state.principal_resolver
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    return resolve(token.strip() if scheme.lower() == "bearer" and token.strip() else None)


Caller = Annotated[Principal, Depends(_caller)]


def register_manuscript_routes(app: FastAPI, root: Path) -> None:
    """Mount `GET /manuscript/builds/{build_id}/pdf` on ``app``."""

    @app.get(MANUSCRIPT_PDF_ROUTE)
    def manuscript_build_pdf(build_id: str, caller: Caller) -> FileResponse:
        """The PDF of one build, inline. `latest` and `last-good` are accepted as ids.

        A failed build has no PDF of its own; the response is then the last good one, which
        is what the preview keeps showing while the diagnostics describe the source as it
        is now. A workspace that has never compiled answers 404 rather than an empty file.
        """
        caller.authorize(f"manuscript.builds.pdf:{build_id}", Permission.READ, human_only=False)
        return manuscript_pdf(root, build_id)


def manuscript_pdf(root: Path, build_id: str) -> FileResponse:
    """Stream the PDF a build should show, or refuse with the reason there is none."""
    from research_harness.capabilities.manuscript_workspace import pdf_path_for

    try:
        path = pdf_path_for(
            root,
            None if build_id in {LATEST_ALIAS, LAST_GOOD_ALIAS} else build_id,
            last_good_only=build_id == LAST_GOOD_ALIAS,
        )
    except ResearchHarnessError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=PDF_MEDIA_TYPE,
        filename=path.name,
        content_disposition_type="inline",
    )

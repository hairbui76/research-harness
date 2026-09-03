"""Deterministic tiny attachment fixtures: one PNG, one two-page PDF.

The attachment tests need files that are unmistakably an image and unmistakably a document
without shipping anything large or copyrighted. Both are built with PyMuPDF, which the
harness already depends on, and the results are checked in so a test run needs no
generation step.

Usage::

    uv run python -m tests.fixtures.attachments.make_attachments
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

__all__ = ["TINY_PDF", "TINY_PNG", "build_pdf", "build_png", "main"]

FIXTURES_DIR = Path(__file__).resolve().parent
TINY_PNG = FIXTURES_DIR / "tiny.png"
TINY_PDF = FIXTURES_DIR / "tiny.pdf"

PNG_EDGE = 64
PDF_PAGES = ("Attachment fixture page one.", "Attachment fixture page two.")


def build_png() -> bytes:
    """A 64x64 PNG with two flat colour bands, so a thumbnail is visibly correct."""
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page(width=PNG_EDGE, height=PNG_EDGE)  # type: ignore[no-untyped-call]
    page.draw_rect(  # type: ignore[no-untyped-call]
        pymupdf.Rect(0, 0, PNG_EDGE, PNG_EDGE / 2), color=None, fill=(0.15, 0.35, 0.75)
    )
    page.draw_rect(  # type: ignore[no-untyped-call]
        pymupdf.Rect(0, PNG_EDGE / 2, PNG_EDGE, PNG_EDGE), color=None, fill=(0.95, 0.75, 0.2)
    )
    pixmap = page.get_pixmap(dpi=72)  # type: ignore[no-untyped-call]
    data: bytes = pixmap.tobytes("png")  # type: ignore[no-untyped-call]
    document.close()
    return data


def build_pdf() -> bytes:
    """A two-page PDF, so page previews and page navigation have something to navigate."""
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    for text in PDF_PAGES:
        page = document.new_page(width=300, height=200)  # type: ignore[no-untyped-call]
        page.insert_text((40, 100), text, fontsize=12)  # type: ignore[no-untyped-call]
    data: bytes = document.tobytes()  # type: ignore[no-untyped-call]
    document.close()
    return data


def main() -> None:
    """Regenerate both fixtures in place."""
    TINY_PNG.write_bytes(build_png())
    TINY_PDF.write_bytes(build_pdf())
    print(f"wrote {TINY_PNG.name} and {TINY_PDF.name} to {FIXTURES_DIR}")


if __name__ == "__main__":  # pragma: no cover - a maintenance entry point
    main()

"""Tiny attachment fixtures: a PNG, a two-page PDF, and the paths tests read them from."""

from __future__ import annotations

from pathlib import Path

__all__ = ["ATTACHMENTS_DIR", "TINY_PDF", "TINY_PNG", "pdf_bytes", "png_bytes"]

ATTACHMENTS_DIR = Path(__file__).resolve().parent
TINY_PNG = ATTACHMENTS_DIR / "tiny.png"
TINY_PDF = ATTACHMENTS_DIR / "tiny.pdf"


def png_bytes() -> bytes:
    """The checked-in tiny PNG."""
    return TINY_PNG.read_bytes()


def pdf_bytes() -> bytes:
    """The checked-in tiny two-page PDF."""
    return TINY_PDF.read_bytes()

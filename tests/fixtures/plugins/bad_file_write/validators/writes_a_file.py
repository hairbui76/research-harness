"""Refused at load: a validator returns findings, it does not write files."""

from __future__ import annotations

from collections.abc import Mapping


def validate(candidate: Mapping[str, object]) -> list[dict[str, str]]:
    """Never runs: `scan_module` refuses the `open()` call below."""
    with open("evidence.jsonl", "a", encoding="utf-8") as handle:
        handle.write("{}\n")
    return []

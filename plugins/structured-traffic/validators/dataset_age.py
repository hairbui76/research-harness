"""Check the two corpus-provenance answers the review argues about most.

`traffic.dataset_age` must be a capture year or a range of years, and `traffic.encryption_status`
must be one of five recorded states. They live in one module because they fail the same way:
both are routinely *inferred* — the dataset's publication year read as its capture year, the
dataset's reputation read as its encryption — and an inferred answer is indistinguishable
from a quoted one once it is in a cell.

So the rule is shape, not plausibility. A validator cannot tell whether `2016` was quoted or
guessed; it can refuse `mid-2010s`, `see Table 1`, and `TLS traffic`, which is what stops a
free-text hedge from being counted later as a year.

A validator is a pure function over a plain dict: no repository, no path, no capability
handle, and no harness import.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

DATASET_AGE_FIELD = "traffic.dataset_age"
ENCRYPTION_FIELD = "traffic.encryption_status"

YEAR_MIN = 1980
YEAR_MAX = 2100
"""Traffic captures start with the public internet and end before a typo does."""

ENCRYPTION_STATES: tuple[str, ...] = (
    "plaintext",
    "partially_encrypted",
    "encrypted",
    "mixed",
    "unclear",
)

#: `2016`, `2015-2017`, `2015--2017`, `2015 to 2017`. Nothing else is a capture date.
YEAR_RE = re.compile(r"^\d{4}$")
RANGE_RE = re.compile("^(\\d{4})\\s*(?:-{1,2}|\u2013|\u2014|to)\\s*(\\d{4})$")

UNKNOWN = "unclear"


def validate(candidate: Mapping[str, object]) -> list[dict[str, str]]:
    """Return findings for one candidate answer to either corpus-provenance field."""
    field = candidate.get("field")
    if field == DATASET_AGE_FIELD:
        return _dataset_age(candidate.get("value"))
    if field == ENCRYPTION_FIELD:
        return _encryption_status(candidate.get("value"))
    return []


def _issue(field: str, message: str, severity: str = "error") -> dict[str, str]:
    return {"field": field, "message": message, "severity": severity}


def _missing(field: str) -> list[dict[str, str]]:
    return [
        _issue(
            field,
            "no value was recorded for this candidate; record `unclear` when the paper "
            "does not say, and leave absence to an audited decision",
            "warning",
        )
    ]


def _dataset_age(value: object) -> list[dict[str, str]]:
    """A capture year, a range of years, or an honest `unclear`."""
    if value is None or value == "":
        return _missing(DATASET_AGE_FIELD)
    if isinstance(value, int) and not isinstance(value, bool):
        return _year_range(str(value), str(value))
    if not isinstance(value, str):
        return [
            _issue(
                DATASET_AGE_FIELD,
                f"dataset age must be written as a year or a range of years, not "
                f"{type(value).__name__}",
            )
        ]
    text = value.strip()
    if text.casefold() == UNKNOWN:
        return []
    if YEAR_RE.match(text):
        return _year_range(text, text)
    matched = RANGE_RE.match(text)
    if matched is not None:
        return _year_range(matched.group(1), matched.group(2))
    return [
        _issue(
            DATASET_AGE_FIELD,
            f"{text!r} is not a capture year; write a year (`2016`), a range "
            f"(`2015-2017`), or `unclear` when the paper does not state when the traffic "
            "was captured. The publication year is not the capture year.",
        )
    ]


def _year_range(first: str, last: str) -> list[dict[str, str]]:
    start, end = int(first), int(last)
    findings = [
        _issue(DATASET_AGE_FIELD, f"{year} is not a plausible capture year")
        for year in (start, end)
        if not YEAR_MIN <= year <= YEAR_MAX
    ]
    if start > end:
        findings.append(
            _issue(DATASET_AGE_FIELD, f"capture range {start}-{end} ends before it begins")
        )
    return findings


def _encryption_status(value: object) -> list[dict[str, str]]:
    """One of the five recorded states; `unclear` is an answer, not a gap."""
    if value is None or value == "":
        return _missing(ENCRYPTION_FIELD)
    if not isinstance(value, str):
        return [
            _issue(
                ENCRYPTION_FIELD,
                f"encryption status must be one of {', '.join(ENCRYPTION_STATES)}, not "
                f"{type(value).__name__}; a corpus with both carries `mixed`",
            )
        ]
    if value.strip() in ENCRYPTION_STATES:
        return []
    return [
        _issue(
            ENCRYPTION_FIELD,
            f"{value!r} is not a recorded encryption status; use one of "
            f"{', '.join(ENCRYPTION_STATES)}. Do not infer it from the dataset's name.",
        )
    ]

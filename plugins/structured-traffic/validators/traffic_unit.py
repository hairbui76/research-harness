"""Check a traffic-unit or representation-family answer against the project taxonomy.

These are the two questions of `interrogation/paper.yaml` whose answers are taxonomy
placements, and the two where a hybrid system carries more than one value. Both are handled
here because they share one rule: an answer is a category, or a list of categories, and
every element must be a term the project has agreed to. Nothing else about them is alike,
and nothing else in the schema needs this rule.

A validator is a pure function over a plain dict. It gets no repository, no workspace path,
and no capability handle; findings are plain mappings, so this module imports nothing from
the harness at all.

Two deliberate non-behaviours:

* An empty answer is a **warning**, not an error and not an absence claim. "Nobody recorded
  a traffic unit" and "this paper has no traffic unit" are different statements, and only a
  researcher may make the second (PRODUCT.md 11).
* `unclear` is accepted. A paper that does not say is an honest answer to record, and
  forcing a choice here is how a blank cell becomes a fact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

TAXONOMIES: dict[str, tuple[str, ...]] = {
    "traffic.traffic_unit": (
        "packet",
        "flow",
        "session",
        "connection",
        "burst",
        "host_window",
        "message",
        "unclear",
    ),
    # SUGGESTED starting terms (PRODUCT.md 33). The accepted taxonomy is a researcher
    # Decision; this list is what the plugin proposes until that Decision exists.
    "traffic.representation_family": (
        "raw sequential",
        "field-based",
        "behavior-aware",
        "unclear",
    ),
}

MULTI_LABEL: frozenset[str] = frozenset(TAXONOMIES)
"""Both fields accept a list: a hybrid representation is recorded, never collapsed."""


def _values(value: object) -> list[object]:
    """One answer or several, as a list. A string is one answer even though it iterates."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return list(value)
    return [value]


def validate(candidate: Mapping[str, object]) -> list[dict[str, str]]:
    """Return one finding per value outside the project taxonomy for this field."""
    field = candidate.get("field")
    if not isinstance(field, str) or field not in TAXONOMIES:
        return []
    allowed = TAXONOMIES[field]
    value = candidate.get("value")
    if value is None or value == "" or value == []:
        return [
            {
                "field": field,
                "message": (
                    "no value was recorded for this candidate; record `unclear` when the "
                    "paper does not say, and leave absence to an audited decision"
                ),
                "severity": "warning",
            }
        ]
    findings: list[dict[str, str]] = []
    items = _values(value)
    if len(items) > 1 and field not in MULTI_LABEL:
        findings.append(
            {
                "field": field,
                "message": f"{field} takes one value; {len(items)} were recorded",
                "severity": "error",
            }
        )
    for item in items:
        if item not in allowed:
            findings.append(
                {
                    "field": field,
                    "message": (
                        f"{item!r} is not a project term for {field}; the proposed taxonomy "
                        f"is {', '.join(allowed)}, and widening it is a researcher Decision"
                    ),
                    "severity": "error",
                }
            )
    if len(items) != len(set(map(str, items))):
        findings.append(
            {
                "field": field,
                "message": f"{field} repeats a value; a hybrid is a set, not a multiset",
                "severity": "warning",
            }
        )
    return findings

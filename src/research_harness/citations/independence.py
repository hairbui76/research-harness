"""Independent-support accounting: how many *independent* sources back a claim.

Counting supporting evidence objects overstates support, and it is the easiest way for a
literature review to convince itself of something false. Four things make two pieces of
support the same piece (Product 17, ADR-002):

* they are anchored in two Versions or Artifacts of one Work;
* two node keys resolved to one Work (:func:`~research_harness.citations.graph.resolve_same_work`);
* the works share most of their authors - the same group reporting twice;
* one work cites the other *and* shares an author with it, so the second is derivative.

:func:`independent_support` partitions the supporting evidence under exactly those rules
and reports `effective_support` as the number of partitions, with a warning naming every
collapse. It reads accepted state and computes; it never writes, and it never decides
that a claim is true.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Literal

from pydantic import Field

from research_harness.citations.graph import CitationGraph, NodeKey
from research_harness.domain.base import DomainModel, NonEmptyStr
from research_harness.domain.claim import Claim
from research_harness.domain.enums import EvidenceStatus
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import EvidenceId, WorkId
from research_harness.domain.work import Work
from research_harness.ingest.identity import (
    AUTHOR_OVERLAP_THRESHOLD,
    author_surnames,
    surname_overlap,
)

__all__ = [
    "AUTHOR_OVERLAP_THRESHOLD",
    "DependentGroup",
    "DependentGroupKind",
    "IndependenceReport",
    "double_counting_risks",
    "independent_support",
]

logger = logging.getLogger(__name__)

DependentGroupKind = Literal["same_work", "same_authors", "citation_chain"]


class DependentGroup(DomainModel):
    """Sources of support that are not independent of each other, and why.

    ``members`` are the identities that collapsed into one unit of support: Version ids
    or node keys for a `same_work` group, Work-level node keys otherwise. ``note`` is the
    sentence a researcher reads in the warning, so it is required.
    """

    kind: DependentGroupKind
    members: tuple[NonEmptyStr, ...] = Field(min_length=2)
    note: NonEmptyStr


class IndependenceReport(DomainModel):
    """How much genuinely independent support a claim has, and what was collapsed.

    ``effective_support`` is the number of independent units: every entry of
    ``independent_works`` plus every entry of ``dependent_groups``, each counted once.
    """

    independent_works: tuple[NonEmptyStr, ...] = ()
    dependent_groups: tuple[DependentGroup, ...] = ()
    effective_support: int = Field(default=0, ge=0)
    warnings: tuple[str, ...] = ()

    @property
    def has_dependence(self) -> bool:
        """True when at least one collapse happened; the caller should show the warnings."""
        return bool(self.dependent_groups)


def independent_support(
    claim: Claim,
    evidence: Mapping[EvidenceId, Evidence],
    works: Mapping[WorkId, Work],
    graph: CitationGraph,
    *,
    same_work: Mapping[NodeKey, NodeKey] | None = None,
) -> IndependenceReport:
    """Partition the claim's supporting evidence into independent units (Product 17).

    Every supporting relation of ``claim`` is grouped by the Work its evidence is
    anchored in - so two Versions of one paper are one unit by construction (ADR-002) -
    and units are then merged when their authors overlap by
    ``AUTHOR_OVERLAP_THRESHOLD`` or when one cites the other and shares an author.
    Evidence that is not accepted still counts, because independence is a structural
    question, but every such case is named in ``warnings`` so acceptance status is not
    silently glossed over (ADR-003).

    ``graph`` must be keyed the same way as the result of applying ``same_work`` to the
    evidence anchors - a graph whose nodes are still discovery candidate keys simply
    contributes no citation chains rather than wrong ones.
    """
    mapping = dict(same_work or {})
    units, warnings = _support_units(claim, evidence, mapping)
    if not units:
        return IndependenceReport(warnings=tuple(warnings))

    surnames = {key: _surnames_of(unit, works) for key, unit in units.items()}
    warnings.extend(
        f"{key} has no known author list, so author-independence could not be checked"
        for key in sorted(units)
        if not surnames[key]
    )

    links, reasons = _dependency_links(units, surnames, graph)
    groups: list[DependentGroup] = []
    independent: list[str] = []
    for component in _components(sorted(units), links):
        if len(component) == 1:
            group = _same_work_group(units[component[0]])
            if group is None:
                independent.append(component[0])
                continue
            groups.append(group)
            continue
        groups.append(_cross_work_group(component, reasons, units))

    warnings.extend(f"{group.kind}: {group.note}" for group in groups)
    return IndependenceReport(
        independent_works=tuple(independent),
        dependent_groups=tuple(groups),
        effective_support=len(independent) + len(groups),
        warnings=tuple(warnings),
    )


def double_counting_risks(
    graph: CitationGraph, work_ids: Iterable[NodeKey]
) -> tuple[DependentGroup, ...]:
    """Same-work collapses recorded in ``graph`` that touch ``work_ids``.

    Reads :meth:`CitationGraph.merges`, so it reports what a merge actually did rather
    than re-guessing identity: each group names a Work and the discovery identities that
    would have counted as separate support had they not been resolved onto it.
    """
    merges = graph.merges()
    risks: list[DependentGroup] = []
    for key in sorted(set(work_ids)):
        collapsed = merges.get(key, ())
        if not collapsed:
            continue
        listed = ", ".join(collapsed)
        risks.append(
            DependentGroup(
                kind="same_work",
                members=tuple(sorted({key, *collapsed})),
                note=(
                    f"{len(collapsed)} discovery identit"
                    f"{'y' if len(collapsed) == 1 else 'ies'} ({listed}) resolved to {key}; "
                    "they are one work and support it once"
                ),
            )
        )
    return tuple(risks)


# -- internals ---------------------------------------------------------------


@dataclass
class _Unit:
    """One Work's contribution to a claim, and every identity that fed into it."""

    key: str
    source_keys: set[str] = field(default_factory=set)
    works: set[WorkId] = field(default_factory=set)
    versions: set[str] = field(default_factory=set)
    evidence: set[str] = field(default_factory=set)


def _support_units(
    claim: Claim,
    evidence: Mapping[EvidenceId, Evidence],
    mapping: Mapping[str, str],
) -> tuple[dict[str, _Unit], list[str]]:
    """Group the claim's supporting evidence by Work, collecting warnings as it goes."""
    units: dict[str, _Unit] = {}
    warnings: list[str] = []
    for evidence_id in claim.supporting:
        item = evidence.get(evidence_id)
        if item is None:
            warnings.append(
                f"{evidence_id} supports {claim.id} but was not supplied; it is uncounted"
            )
            continue
        if item.status is not EvidenceStatus.ACCEPTED:
            warnings.append(
                f"{evidence_id} is counted as support but is {item.status.value}, not accepted"
            )
        raw = str(item.source.work)
        key = mapping.get(raw, raw)
        unit = units.setdefault(key, _Unit(key=key))
        unit.source_keys.add(raw)
        unit.works.add(item.source.work)
        unit.versions.add(str(item.source.version))
        unit.evidence.add(str(evidence_id))
    return units, warnings


def _surnames_of(unit: _Unit, works: Mapping[WorkId, Work]) -> frozenset[str]:
    """Author surnames across every Work collapsed into this unit."""
    names: set[str] = set()
    for work_id in sorted(unit.works):
        work = works.get(work_id)
        if work is not None:
            names.update(author_surnames(work.authors))
    return frozenset(names)


def _dependency_links(
    units: Mapping[str, _Unit],
    surnames: Mapping[str, frozenset[str]],
    graph: CitationGraph,
) -> tuple[dict[str, set[str]], dict[tuple[str, str], set[str]]]:
    """Undirected dependency links between units, with the reason for each."""
    links: dict[str, set[str]] = {key: set() for key in units}
    reasons: dict[tuple[str, str], set[str]] = {}
    for left, right in combinations(sorted(units), 2):
        shared = surnames[left] & surnames[right]
        kinds: set[str] = set()
        if surname_overlap(surnames[left], surnames[right]) >= AUTHOR_OVERLAP_THRESHOLD:
            kinds.add("same_authors")
        elif shared and _cites_either_way(graph, left, right):
            kinds.add("citation_chain")
        if not kinds:
            continue
        links[left].add(right)
        links[right].add(left)
        reasons[(left, right)] = kinds
    return links, reasons


def _cites_either_way(graph: CitationGraph, left: str, right: str) -> bool:
    """True when either work cites the other; direction does not change the dependence."""
    return right in graph.references_of(left) or left in graph.references_of(right)


def _components(keys: Sequence[str], links: Mapping[str, set[str]]) -> list[list[str]]:
    """Connected components of the dependency links, each sorted, in key order."""
    seen: set[str] = set()
    components: list[list[str]] = []
    for start in keys:
        if start in seen:
            continue
        seen.add(start)
        component = [start]
        queue = [start]
        while queue:
            node = queue.pop()
            for neighbour in sorted(links.get(node, set())):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                component.append(neighbour)
                queue.append(neighbour)
        components.append(sorted(component))
    return components


def _same_work_group(unit: _Unit) -> DependentGroup | None:
    """A group when one Work reached the claim through several identities, else ``None``.

    Members are reported at the coarsest identity that collapsed: two Work keys that
    resolved to one Work if that happened, otherwise the Versions the evidence came from.
    Listing both would name a Version *and* the work identity it already belongs to.
    """
    versions = len(unit.versions)
    if len(unit.source_keys) > 1:
        members = sorted(unit.source_keys)
        spread = f", across {versions} versions" if versions > len(unit.source_keys) else ""
        note = f"{len(members)} work identities resolved to {unit.key}{spread}"
    elif versions > 1:
        members = sorted(unit.versions)
        note = f"evidence from {versions} versions of {unit.key}"
    else:
        return None
    return DependentGroup(kind="same_work", members=tuple(members), note=f"{note} - counted once")


def _cross_work_group(
    component: Sequence[str],
    reasons: Mapping[tuple[str, str], set[str]],
    units: Mapping[str, _Unit],
) -> DependentGroup:
    """One dependent group for a component spanning more than one Work."""
    kinds = {
        kind
        for pair, found in reasons.items()
        if pair[0] in component and pair[1] in component
        for kind in found
    }
    kind: DependentGroupKind = "same_authors" if "same_authors" in kinds else "citation_chain"
    detail = (
        f"author lists overlap by at least {AUTHOR_OVERLAP_THRESHOLD:.0%}"
        if kind == "same_authors"
        else "one cites the other and they share an author, so the support is derivative"
    )
    versions = sum(len(units[key].versions) for key in component)
    spread = f" across {versions} versions" if versions > len(component) else ""
    return DependentGroup(
        kind=kind,
        members=tuple(component),
        note=f"{len(component)} works{spread} count once: {detail}",
    )

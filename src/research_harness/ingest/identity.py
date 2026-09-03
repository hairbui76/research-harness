"""Deterministic Work/Version/Artifact identity resolution (Product 13; ADR-002).

Resolution is a pure function of the candidate and the records handed to it: the same
inputs always produce the same outcome, no index or model is consulted, and conflicting
metadata is recorded as a :class:`FieldConflict` rather than overwritten. External
metadata services stay behind :class:`MetadataLookup`, which only enriches a candidate
*before* matching and never decides the outcome.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Protocol, runtime_checkable

from research_harness.domain.base import DomainModel, NonEmptyStr
from research_harness.domain.enums import IdentityResolutionOutcome
from research_harness.domain.ids import ArtifactId, VersionId, WorkId
from research_harness.domain.work import (
    Artifact,
    CandidateMetadata,
    IdentifierField,
    Version,
    Work,
    WorkCandidate,
    WorkIdentifiers,
)

__all__ = [
    "AUTHOR_OVERLAP_THRESHOLD",
    "IDENTIFIER_FIELDS",
    "TITLE_SIMILARITY_THRESHOLD",
    "YEAR_TOLERANCE",
    "YEAR_TOLERANCE_WITH_AUTHORS",
    "ExistingRecord",
    "FieldConflict",
    "IdentityResolution",
    "MetadataLookup",
    "NullMetadataLookup",
    "arxiv_base_id",
    "arxiv_version_label",
    "arxiv_year",
    "author_surnames",
    "merge_identifiers",
    "normalize_arxiv_id",
    "normalize_doi",
    "normalize_title",
    "resolve_identity",
    "surname_overlap",
    "title_similarity",
]

logger = logging.getLogger(__name__)

#: `difflib` ratio at or above which two titles are "the same paper, maybe".
TITLE_SIMILARITY_THRESHOLD = 0.9
#: Fraction of the smaller author list that must share surnames to corroborate a title.
AUTHOR_OVERLAP_THRESHOLD = 0.5
#: Publication years this far apart still describe the same work (preprint vs proceedings).
YEAR_TOLERANCE = 1
#: Wider tolerance for a title match the author list already corroborates: a preprint and
#: its proceedings version can be two years apart, and with the authors agreeing the year is
#: the weakest of the three signals rather than a veto (dogfood F4).
YEAR_TOLERANCE_WITH_AUTHORS = 2
#: Identifier fields, in the order the domain declares them, so merges are deterministic.
IDENTIFIER_FIELDS: tuple[str, ...] = tuple(WorkIdentifiers.model_fields)

_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi.org/",
    "dx.doi.org/",
    "doi:",
)
_ARXIV_VERSION = re.compile(r"v\d+$", re.IGNORECASE)
#: The two forms arXiv has ever minted: `YYMM.NNNNN` since 2007, `archive[.SC]/YYMMNNN`
#: before it. Anything else is not an arXiv identifier, however much prose surrounds it.
_ARXIV_ANY_ID = re.compile(
    r"(?<![\w.])(?:\d{4}\.\d{4,5}|[a-z][a-z-]*(?:\.[a-z]{2})?/\d{7})(?:v\d+)?(?!\w)(?!\.\d)",
    re.IGNORECASE,
)


# -- result types ------------------------------------------------------------


class FieldConflict(DomainModel):
    """An incoming value that disagrees with the value already recorded for a field."""

    field: NonEmptyStr
    existing: IdentifierField
    incoming: IdentifierField


class ExistingRecord(DomainModel):
    """One corpus work with the versions and artifacts already registered under it."""

    work: Work
    versions: tuple[Version, ...] = ()
    artifacts: tuple[Artifact, ...] = ()


class IdentityResolution(DomainModel):
    """What a candidate resolved to, why, and which metadata disagreed."""

    outcome: IdentityResolutionOutcome
    work: WorkId | None = None
    version: VersionId | None = None
    artifact: ArtifactId | None = None
    reasons: tuple[str, ...] = ()
    merged_identifiers: WorkIdentifiers | None = None
    conflicts: tuple[FieldConflict, ...] = ()

    def applied_to(self, candidate: WorkCandidate) -> WorkCandidate:
        """Return ``candidate`` carrying this outcome and exactly the links it asserts."""
        return candidate.touch(
            resolution=self.outcome,
            matched_work=self.work,
            matched_version=self.version,
            matched_artifact=self.artifact,
        )


@runtime_checkable
class MetadataLookup(Protocol):
    """Adapter hook for an external metadata service (Roadmap 2.2).

    Implementations only enrich a candidate before matching; they never choose an outcome.
    """

    def lookup(self, identifiers: WorkIdentifiers) -> CandidateMetadata | None:
        """Metadata for ``identifiers``, or ``None`` when nothing is known."""


class NullMetadataLookup:
    """The offline default: never enriches, so resolution stays local and deterministic."""

    def lookup(self, identifiers: WorkIdentifiers) -> CandidateMetadata | None:
        """Always ``None``."""
        del identifiers
        return None


# -- normalization -----------------------------------------------------------


def normalize_doi(value: str) -> str:
    """Lowercase a DOI and drop resolver prefixes so `https://doi.org/10.1/A` == `10.1/a`."""
    text = value.strip().casefold()
    changed = True
    while changed:
        changed = False
        for prefix in _DOI_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                changed = True
                break
    return text.rstrip(".,;")


def normalize_arxiv_id(value: str) -> str | None:
    """The arXiv identifier inside ``value`` including any `vN` suffix, lowercased.

    The id is *extracted*, not merely stripped of prefixes: bibliographies and PDF banners
    wrap it in prose (`arXiv preprint arXiv:2304.09513`, `arXiv:2301.01234v3 [cs.CR] 12 Mar
    2025`), and lowercasing such a string yields a key that can never match anything
    (dogfood F4). Text holding no arXiv identifier returns ``None`` rather than itself.
    """
    match = _ARXIV_ANY_ID.search(value)
    return match.group(0).casefold() if match is not None else None


def arxiv_base_id(value: str) -> str | None:
    """arXiv identifier without its `vN` suffix: the work's id, not the revision's.

    ``None`` when ``value`` holds no arXiv identifier, so a caller can never build a lookup
    key out of arbitrary prose.
    """
    full = normalize_arxiv_id(value)
    return None if full is None else _ARXIV_VERSION.sub("", full)


def arxiv_version_label(value: str) -> str | None:
    """The `vN` revision label of an arXiv identifier, or ``None`` when it carries none."""
    full = normalize_arxiv_id(value)
    if full is None:
        return None
    match = _ARXIV_VERSION.search(full)
    return match.group(0) if match else None


def arxiv_year(value: str) -> int | None:
    """Publication year encoded in an arXiv id's `YYMM` prefix, or ``None``.

    A modern id is `YYMM.NNNNN` and an old-style one `archive/YYMMNNN`; both start with the
    two-digit year of the *first* submission, which is the year the work was published as a
    preprint. It is therefore a better year than the date on a later version's banner, which
    is what put a 2023 paper into the corpus as 2025 (dogfood F4).
    """
    base = arxiv_base_id(value)
    if base is None:
        return None
    digits = base.split("/")[-1] if "/" in base else base.split(".")[0]
    if len(digits) < 4 or not digits[:4].isdigit():
        return None
    yy, mm = int(digits[:2]), int(digits[2:4])
    if not 1 <= mm <= 12:
        return None
    # arXiv started in 1991; two-digit years below that belong to the 2000s.
    return 1900 + yy if yy >= 91 else 2000 + yy


def normalize_title(value: str) -> str:
    """Casefold, strip accents and punctuation, and collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    spaced = "".join(char if char.isalnum() or char.isspace() else " " for char in without_marks)
    return " ".join(spaced.split())


def title_similarity(left: str, right: str) -> float:
    """Normalized-title similarity in ``[0, 1]``; symmetric and index-independent."""
    matcher = SequenceMatcher(None, normalize_title(left), normalize_title(right), autojunk=False)
    return matcher.ratio()


def author_surnames(names: Iterable[str]) -> frozenset[str]:
    """Casefolded surnames, accepting both `Jane Doe` and `Doe, Jane`."""
    surnames: set[str] = set()
    for name in names:
        head = name.split(",")[0] if "," in name else name
        cleaned = normalize_title(head)
        if cleaned:
            surnames.add(cleaned.split()[-1])
    return frozenset(surnames)


def surname_overlap(left: frozenset[str], right: frozenset[str]) -> float:
    """Share of the shorter author list whose surnames also appear in the longer one."""
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def merge_identifiers(
    existing: WorkIdentifiers, incoming: WorkIdentifiers
) -> tuple[WorkIdentifiers, tuple[FieldConflict, ...]]:
    """Fill gaps from ``incoming`` while keeping every recorded value and its provenance.

    An existing value is never replaced: a disagreement becomes a :class:`FieldConflict`
    so the researcher, not the resolver, decides which one is right.
    """
    merged: dict[str, IdentifierField | None] = {}
    conflicts: list[FieldConflict] = []
    for name in IDENTIFIER_FIELDS:
        current: IdentifierField | None = getattr(existing, name)
        offered: IdentifierField | None = getattr(incoming, name)
        if current is None:
            merged[name] = offered
            continue
        merged[name] = current
        if offered is not None and not _equivalent(name, current.value, offered.value):
            conflicts.append(FieldConflict(field=name, existing=current, incoming=offered))
    return WorkIdentifiers(**merged), tuple(conflicts)


# -- resolution --------------------------------------------------------------


def resolve_identity(
    candidate: WorkCandidate,
    existing: Iterable[ExistingRecord],
    *,
    lookup: MetadataLookup | None = None,
) -> IdentityResolution:
    """Resolve ``candidate`` against ``existing`` records into exactly one outcome.

    Rules are applied in order and the first that fires wins: identical artifact bytes,
    then a version-level identifier match, then a work-level match (DOI, arXiv base id, or
    a corroborated title), then an ambiguous near-title match, then a distinct work.
    """
    records = sorted(existing, key=lambda record: str(record.work.id))
    facts = _CandidateFacts.build(candidate, lookup)

    same_artifact = _match_artifact(facts, records)
    if same_artifact is not None:
        return same_artifact

    matches = [match for match in (_match_work(facts, record) for record in records) if match]
    if len(matches) > 1:
        names = ", ".join(str(match.record.work.id) for match in matches)
        return IdentityResolution(
            outcome=IdentityResolutionOutcome.UNRESOLVED,
            reasons=(f"candidate matches multiple works: {names}",),
        )
    if matches:
        return _resolve_matched(facts, matches[0])

    ambiguous = _match_ambiguous_title(facts, records)
    if ambiguous is not None:
        return ambiguous

    return IdentityResolution(
        outcome=IdentityResolutionOutcome.DISTINCT_WORK,
        reasons=("no existing work matched by identifier, title, or artifact hash",),
    )


@dataclass(frozen=True)
class _CandidateFacts:
    """Everything matching reads off a candidate, normalized once."""

    file_hash: str | None
    doi: str | None
    arxiv_full: str | None
    arxiv_base: str | None
    arxiv_label: str | None
    raw_title: str | None
    title: str | None
    year: int | None
    """The year matching uses: the arXiv id's `YYMM` when it contradicts the stated one."""
    stated_year: int | None
    surnames: frozenset[str]
    identifiers: WorkIdentifiers

    @classmethod
    def build(cls, candidate: WorkCandidate, lookup: MetadataLookup | None) -> _CandidateFacts:
        metadata = _enriched(candidate.metadata, lookup)
        doi = metadata.identifiers.doi
        arxiv = metadata.identifiers.arxiv
        title = metadata.title.value if metadata.title is not None else None
        stated = _as_year(metadata.year)
        from_id = arxiv_year(arxiv.value) if arxiv is not None else None
        return cls(
            file_hash=candidate.candidate_file_hash,
            doi=normalize_doi(doi.value) if doi is not None else None,
            arxiv_full=normalize_arxiv_id(arxiv.value) if arxiv is not None else None,
            arxiv_base=arxiv_base_id(arxiv.value) if arxiv is not None else None,
            arxiv_label=arxiv_version_label(arxiv.value) if arxiv is not None else None,
            raw_title=title,
            title=normalize_title(title) if title else None,
            year=_preferred_year(stated, from_id),
            stated_year=stated,
            surnames=author_surnames(field.value for field in metadata.authors),
            identifiers=metadata.identifiers,
        )


@dataclass(frozen=True)
class _WorkMatch:
    """A record the candidate matched, and the evidence for the match."""

    record: ExistingRecord
    reasons: tuple[str, ...]

    def __bool__(self) -> bool:
        return bool(self.reasons)


def _enriched(metadata: CandidateMetadata, lookup: MetadataLookup | None) -> CandidateMetadata:
    """Fill only the fields the candidate lacks; looked-up values keep their provenance."""
    if lookup is None:
        return metadata
    found = lookup.lookup(metadata.identifiers)
    if found is None:
        return metadata
    identifiers = WorkIdentifiers(
        **{
            name: getattr(metadata.identifiers, name) or getattr(found.identifiers, name)
            for name in IDENTIFIER_FIELDS
        }
    )
    return CandidateMetadata(
        title=metadata.title or found.title,
        authors=metadata.authors or found.authors,
        year=metadata.year or found.year,
        venue=metadata.venue or found.venue,
        identifiers=identifiers,
    )


def _match_artifact(
    facts: _CandidateFacts, records: Sequence[ExistingRecord]
) -> IdentityResolution | None:
    if facts.file_hash is None:
        return None
    hits = [
        (record, artifact)
        for record in records
        for artifact in record.artifacts
        if artifact.file_hash == facts.file_hash
    ]
    if not hits:
        return None
    if len({artifact.work for _, artifact in hits}) > 1:
        names = ", ".join(sorted({str(artifact.work) for _, artifact in hits}))
        return IdentityResolution(
            outcome=IdentityResolutionOutcome.UNRESOLVED,
            reasons=(f"artifact hash is registered under multiple works: {names}",),
        )
    record, artifact = min(hits, key=lambda hit: str(hit[1].id))
    merged, conflicts = merge_identifiers(record.work.identifiers, facts.identifiers)
    return IdentityResolution(
        outcome=IdentityResolutionOutcome.SAME_ARTIFACT,
        work=artifact.work,
        version=artifact.version,
        artifact=artifact.id,
        reasons=(f"file hash matches artifact {artifact.id}",),
        merged_identifiers=merged,
        conflicts=conflicts,
    )


def _match_work(facts: _CandidateFacts, record: ExistingRecord) -> _WorkMatch:
    reasons: list[str] = []
    work = record.work
    if facts.doi is not None and facts.doi in _record_dois(record):
        reasons.append(f"doi matches {work.id}: {facts.doi}")
    if facts.arxiv_base and facts.arxiv_base in _record_arxiv_bases(record):
        reasons.append(f"arxiv base id matches {work.id}: {facts.arxiv_base}")
    if facts.title is not None and facts.title == normalize_title(work.title):
        reasons.extend(_title_corroboration(facts, work))
    return _WorkMatch(record=record, reasons=tuple(reasons))


def _title_corroboration(facts: _CandidateFacts, work: Work) -> list[str]:
    """Why an identical title is (or is not) enough on its own.

    A year within tolerance corroborates; a year outside it never *defeats* a match, it
    simply adds no reason of its own. The tolerance widens to
    `YEAR_TOLERANCE_WITH_AUTHORS` once the author lists agree, because a preprint and its
    proceedings version are routinely two years apart and the year is then the weakest of
    the three signals (dogfood F4).
    """
    reasons: list[str] = []
    overlap = surname_overlap(facts.surnames, author_surnames(work.authors))
    corroborated = overlap >= AUTHOR_OVERLAP_THRESHOLD
    if corroborated:
        reasons.append(f"title matches {work.id} with {overlap:.0%} author surname overlap")
    tolerance = YEAR_TOLERANCE_WITH_AUTHORS if corroborated else YEAR_TOLERANCE
    for year in _candidate_years(facts):
        if work.year is not None and abs(year - work.year) <= tolerance:
            reasons.append(f"title matches {work.id} with year within {tolerance}")
            break
    return reasons


def _candidate_years(facts: _CandidateFacts) -> tuple[int, ...]:
    """Years this candidate could legitimately be published under, nearest source first."""
    years = [year for year in (facts.year, facts.stated_year) if year is not None]
    return tuple(dict.fromkeys(years))


def _preferred_year(stated: int | None, from_arxiv_id: int | None) -> int | None:
    """The year matching should use: the arXiv id's when the stated one contradicts it.

    An arXiv PDF carries the current version's banner date, so a v3 stamped in 2025 makes a
    2023 paper look like a 2025 one. The id's `YYMM` is the first submission and cannot
    drift, so it wins whenever the two disagree at all (dogfood F4).
    """
    if from_arxiv_id is None:
        return stated
    if stated is None or abs(stated - from_arxiv_id) >= 1:
        return from_arxiv_id
    return stated


def _resolve_matched(facts: _CandidateFacts, match: _WorkMatch) -> IdentityResolution:
    record = match.record
    merged, conflicts = merge_identifiers(record.work.identifiers, facts.identifiers)
    pinned = _match_versions(facts, record)
    if len(pinned) == 1:
        version, why = pinned[0]
        return IdentityResolution(
            outcome=IdentityResolutionOutcome.SAME_VERSION,
            work=record.work.id,
            version=version.id,
            reasons=(*match.reasons, f"version {version.id} matches on {why}"),
            merged_identifiers=merged,
            conflicts=conflicts,
        )
    reasons = match.reasons
    if len(pinned) > 1:
        names = ", ".join(str(version.id) for version, _ in pinned)
        reasons = (*reasons, f"no single version pinned; candidates: {names}")
    return IdentityResolution(
        outcome=IdentityResolutionOutcome.SAME_WORK,
        work=record.work.id,
        reasons=reasons,
        merged_identifiers=merged,
        conflicts=conflicts,
    )


def _match_versions(facts: _CandidateFacts, record: ExistingRecord) -> list[tuple[Version, str]]:
    """Versions whose own identifiers pin the candidate to that exact revision."""
    pinned: list[tuple[Version, str]] = []
    for version in sorted(record.versions, key=lambda item: str(item.id)):
        arxiv = version.identifiers.arxiv
        if (
            facts.arxiv_full
            and arxiv is not None
            and normalize_arxiv_id(arxiv.value) == facts.arxiv_full
        ):
            pinned.append((version, "arxiv id including version suffix"))
            continue
        doi = version.identifiers.doi
        if facts.doi is not None and doi is not None and normalize_doi(doi.value) == facts.doi:
            if _label_disagrees(facts.arxiv_label, version.label):
                continue
            pinned.append((version, "doi"))
    return pinned


def _match_ambiguous_title(
    facts: _CandidateFacts, records: Sequence[ExistingRecord]
) -> IdentityResolution | None:
    """A title this close is either the same paper or a trap; ask instead of guessing."""
    if facts.raw_title is None:
        return None
    ranked = [(title_similarity(facts.raw_title, record.work.title), record) for record in records]
    scored = [pair for pair in ranked if pair[0] >= TITLE_SIMILARITY_THRESHOLD]
    if not scored:
        return None
    ratio, record = max(scored, key=lambda item: (item[0], str(item[1].work.id)))
    _, conflicts = merge_identifiers(record.work.identifiers, facts.identifiers)
    reasons = [f"title similarity {ratio:.2f} with {record.work.id} but no match rule fired"]
    reasons.extend(
        f"{conflict.field} differs: existing {conflict.existing.value!r}, "
        f"incoming {conflict.incoming.value!r}"
        for conflict in conflicts
    )
    return IdentityResolution(
        outcome=IdentityResolutionOutcome.UNRESOLVED,
        reasons=tuple(reasons),
        conflicts=conflicts,
    )


# -- small helpers -----------------------------------------------------------


def _record_dois(record: ExistingRecord) -> frozenset[str]:
    sources = [record.work.identifiers, *(version.identifiers for version in record.versions)]
    return frozenset(normalize_doi(ids.doi.value) for ids in sources if ids.doi is not None)


def _record_arxiv_bases(record: ExistingRecord) -> frozenset[str]:
    sources = [record.work.identifiers, *(version.identifiers for version in record.versions)]
    bases = (arxiv_base_id(ids.arxiv.value) for ids in sources if ids.arxiv is not None)
    return frozenset(base for base in bases if base is not None)


def _label_disagrees(candidate_label: str | None, version_label: str | None) -> bool:
    if candidate_label is None or version_label is None:
        return False
    return candidate_label.casefold() != version_label.casefold()


def _equivalent(field: str, left: str, right: str) -> bool:
    if field == "doi":
        return normalize_doi(left) == normalize_doi(right)
    if field == "arxiv":
        # Work-level identity is the base id; the `vN` suffix belongs to the Version.
        # Two values holding no extractable id are compared as the strings they are, so
        # unparsable text is never silently declared equivalent to other unparsable text.
        left_base, right_base = arxiv_base_id(left), arxiv_base_id(right)
        if left_base is None or right_base is None:
            return left.strip().casefold() == right.strip().casefold()
        return left_base == right_base
    return left.strip().casefold() == right.strip().casefold()


def _as_year(field: IdentifierField | None) -> int | None:
    if field is None:
        return None
    try:
        return int(field.value.strip())
    except ValueError:
        logger.debug("candidate year is not an integer: %r", field.value)
        return None

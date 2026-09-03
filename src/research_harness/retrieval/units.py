"""Retrieval units: the text chunks the local indexes embed and search.

A retrieval chunk is an implementation artifact, not a research object (Product SS15.4,
ADR-006). Nothing here is canonical: a unit carries only enough identity to point back at
the object or parsed block it was derived from, ids are composite where no single
canonical id exists, and re-chunking is an operational act rather than a scientific
event. `IndexUnitKind` therefore lives here and not in `domain/enums.py` — the domain has
no opinion about how text is cut up for a similarity search.

Granularity follows Product SS15.4: Work, Section, Paragraph, Table, figure Caption,
Evidence span, Claim. Equations, references and footnotes are deliberately not indexed;
they are looked up structurally, not by similarity.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from research_harness.domain.base import Sha256
from research_harness.domain.claim import Claim
from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import DocumentBlockKind
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import ArtifactId, BlockId, WorkId
from research_harness.domain.work import Work
from research_harness.parsing.text import text_sha256

__all__ = [
    "MAX_SECTION_CHARS",
    "IndexUnit",
    "IndexUnitKind",
    "block_unit_id",
    "unit_from_work",
    "units_from_claim",
    "units_from_document",
    "units_from_evidence",
]

MAX_SECTION_CHARS = 2000
"""Character budget for a section unit. A section exists to catch queries no single
paragraph answers; past a couple of thousand characters the vector stops discriminating
and the paragraph units serve better anyway."""


class IndexUnitKind(StrEnum):
    """What a retrieval unit is a unit *of* (Product SS15.4)."""

    WORK = "work"
    SECTION = "section"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    CAPTION = "caption"
    EVIDENCE = "evidence"
    CLAIM = "claim"


#: Parser block kinds that become a unit of their own, and the unit kind they become.
#: Every other kind (equation, reference, footnote, table cell) is left out on purpose.
#: A `TABLE_CAPTION` the parser could not attach to a table is still the sentence that
#: names the metric, so it is indexed as a caption rather than lost.
_BLOCK_UNIT_KINDS: dict[DocumentBlockKind, IndexUnitKind] = {
    DocumentBlockKind.PARAGRAPH: IndexUnitKind.PARAGRAPH,
    DocumentBlockKind.TABLE: IndexUnitKind.TABLE,
    DocumentBlockKind.FIGURE_CAPTION: IndexUnitKind.CAPTION,
    DocumentBlockKind.TABLE_CAPTION: IndexUnitKind.CAPTION,
}


class IndexUnit(BaseModel):
    """One indexable chunk: where it came from, and the text that represents it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    """Canonical id (`W0017`, `E0482`, `C0041`) for a unit that *is* one object, or the
    composite `B0081@A0017-3` for a parsed block, which has no id of its own outside the
    artifact it was parsed from."""

    kind: IndexUnitKind
    work: WorkId | None = None
    artifact: ArtifactId | None = None
    page: int | None = Field(default=None, ge=1)
    section_path: tuple[str, ...] = ()
    text: str

    @property
    def text_hash(self) -> Sha256:
        """`sha256:<hex>` of the unit text; what tells an index a re-embed is needed."""
        return text_sha256(self.text)


def block_unit_id(block: BlockId, artifact: ArtifactId) -> str:
    """`B0081@A0017-3` — a block id is only unique inside its artifact."""
    return f"{block}@{artifact}"


def units_from_document(
    doc: ParsedDocument,
    *,
    work: WorkId | None = None,
    max_section_chars: int = MAX_SECTION_CHARS,
) -> list[IndexUnit]:
    """Paragraph, table and caption units, plus one section unit per heading.

    Units come back in document order, with a section's aggregate unit at the position of
    its heading. A section unit is the heading plus the paragraphs beneath it — including
    those of its subsections, because a reader looking for "the Experiments section" means
    all of it — truncated to `max_section_chars` on a word boundary. Table units are
    prefixed with the table's caption, which is usually where the metric is named.

    `work` defaults to `doc.work`; pass it only to index an artifact under a different
    Work than the parse recorded.
    """
    work_id = work if work is not None else doc.work
    units: list[IndexUnit] = []
    for block in doc.blocks:
        if block.kind is DocumentBlockKind.SECTION:
            section = _section_unit(doc, block, work=work_id, budget=max_section_chars)
            if section is not None:
                units.append(section)
            continue
        kind = _BLOCK_UNIT_KINDS.get(block.kind)
        if kind is None:
            continue
        text = _block_text(block)
        if not text:
            continue
        units.append(
            IndexUnit(
                id=block_unit_id(block.id, block.artifact),
                kind=kind,
                work=work_id,
                artifact=block.artifact,
                page=block.page,
                section_path=block.section_path,
                text=text,
            )
        )
    return units


def units_from_evidence(evidence: Evidence) -> list[IndexUnit]:
    """The unit that represents one accepted or candidate Evidence object.

    The text is the quoted span, followed by the number with its metric, dataset and
    source table when the evidence is numeric, and by the absence state when it records
    one — a naked number retrieves nothing, and an absence with no text would be an empty
    unit. Returns a list so that indexing more than one representation per evidence later
    is not a signature change.
    """
    content = evidence.content
    parts = [content.exact_text.strip()]
    numeric = content.numeric
    if numeric is not None:
        measured = f"{numeric.metric} {numeric.raw}{f' {numeric.unit}' if numeric.unit else ''}"
        context = [
            numeric.dataset or "",
            *(f"{k}={v}" for k, v in sorted(numeric.condition.items())),
        ]
        parts.append(" ".join(filter(None, [measured, *context, numeric.source_table])))
    if content.negative_state is not None:
        parts.append(f"absence: {content.negative_state.value}")
    source = evidence.source
    return [
        IndexUnit(
            id=str(evidence.id),
            kind=IndexUnitKind.EVIDENCE,
            work=source.work,
            artifact=source.artifact,
            page=source.page,
            section_path=source.section_path,
            text=_join(parts),
        )
    ]


def units_from_claim(claim: Claim) -> list[IndexUnit]:
    """The unit that represents one Claim: its statement plus its structured proposition.

    The subject/predicate/object triple and its qualifiers are indexed alongside the
    prose because the wording of a claim is deliberately conservative while the triple
    carries the terms a researcher searches for.
    """
    semantics = claim.semantics
    triple = " ".join((semantics.subject, semantics.predicate, semantics.object))
    qualifiers = " ".join(f"{key}={value}" for key, value in sorted(semantics.qualifier.items()))
    return [
        IndexUnit(
            id=str(claim.id),
            kind=IndexUnitKind.CLAIM,
            text=_join([claim.statement, triple, qualifiers]),
        )
    ]


def unit_from_work(work: Work, *, abstract: str | None = None) -> IndexUnit:
    """The work-level unit: title, authors, venue and year, plus an abstract when known.

    `Work` holds no abstract — it is version- and artifact-scoped text — so a caller that
    has one (from parsing or from a discovery provider) passes it in.
    """
    venue_year = " ".join(filter(None, [work.venue or "", str(work.year) if work.year else ""]))
    return IndexUnit(
        id=str(work.id),
        kind=IndexUnitKind.WORK,
        work=work.id,
        text=_join([work.title, "; ".join(work.authors), venue_year, abstract or ""]),
    )


def _section_unit(
    doc: ParsedDocument, heading: DocumentBlock, *, work: WorkId | None, budget: int
) -> IndexUnit | None:
    """Heading plus the paragraphs under it, truncated; `None` when it has no body.

    A heading with no paragraphs beneath it — References, or a section that holds only a
    table — yields no unit: a vector built from three heading words matches short queries
    far too well for something that carries no content.
    """
    if not heading.section_path:
        return None
    paragraphs = list(_section_body(doc, heading.section_path))
    if not paragraphs:
        return None
    body = _truncate(_join([heading.text, *paragraphs]), budget)
    if not body:
        return None
    return IndexUnit(
        id=block_unit_id(heading.id, heading.artifact),
        kind=IndexUnitKind.SECTION,
        work=work,
        artifact=heading.artifact,
        page=heading.page,
        section_path=heading.section_path,
        text=body,
    )


def _section_body(doc: ParsedDocument, path: tuple[str, ...]) -> Iterator[str]:
    depth = len(path)
    for block in doc.blocks:
        if block.kind is not DocumentBlockKind.PARAGRAPH:
            continue
        if block.section_path[:depth] == path and block.text.strip():
            yield block.text.strip()


def _block_text(block: DocumentBlock) -> str:
    """Block text, with a table's caption in front of its flattened cells."""
    if block.kind is DocumentBlockKind.TABLE and block.caption:
        return _join([block.caption, block.text])
    return block.text.strip()


def _join(parts: Iterable[str]) -> str:
    """One space-separated line per non-empty part; unit text is never structured."""
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _truncate(text: str, limit: int) -> str:
    """Cut to `limit` characters on the last word boundary; no ellipsis is added."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rfind(" ")
    return (head[:cut] if cut > 0 else head).rstrip()

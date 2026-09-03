"""Local file ingestion and parsing, persisted through the capability layer (Roadmap 2.1).

Ingestion is deliberately split in two: `ingest/` decides *what a file is* (hash, metadata,
identity) and this service decides *what that means for the corpus*, then asks the
capability layer to write it. Re-ingesting identical bytes changes nothing, a new revision
never overwrites a registered Artifact (ADR-002), and an ambiguous identity is handed back
to the researcher instead of guessed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import (
    AddArtifactRequest,
    IngestLocalPdfRequest,
    MutationResult,
    ParseWorkRequest,
    RegisterWorkRequest,
    StoreParsedDocumentRequest,
)
from research_harness.capabilities.handlers import (
    add_version_artifact,
    register_work,
    store_parsed_document,
)
from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import (
    ArtifactKind,
    IdentityResolutionOutcome,
    ProvenanceSource,
    VersionKind,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import ArtifactId, VersionId, WorkId
from research_harness.domain.work import (
    Artifact,
    IdentifierField,
    WorkCandidate,
    WorkIdentifiers,
)
from research_harness.ingest.hashing import (
    ArtifactFingerprint,
    artifact_kind_for_mime,
    fingerprint_file,
)
from research_harness.ingest.identity import (
    ExistingRecord,
    IdentityResolution,
    arxiv_version_label,
    resolve_identity,
)
from research_harness.ingest.metadata import (
    NOTE_DECODABILITY_LOW,
    FieldNote,
    PdfInspection,
    build_work_candidate,
    inspect_pdf_detail,
)
from research_harness.parsing.base import DocumentParser, ParseTarget, select_parser
from research_harness.parsing.pymupdf_parser import PyMuPdfParser
from research_harness.workspace.repository import ObjectNotFoundError

__all__ = [
    "CreatedKind",
    "IngestResult",
    "IngestService",
    "ParseResult",
    "ingest_local_pdf",
    "parse_work",
]

logger = logging.getLogger(__name__)

#: What one ingest added to the corpus. `nothing` is the idempotent re-ingest.
CreatedKind = Literal["nothing", "artifact", "version", "work"]


@dataclass(frozen=True, slots=True)
class IngestResult:
    """One ingested file: what it was, what it resolved to, and what that created."""

    candidate: WorkCandidate
    resolution: IdentityResolution
    work: WorkId
    version: VersionId
    artifact: ArtifactId
    created: CreatedKind
    mutation: MutationResult | None = None
    metadata_notes: tuple[FieldNote, ...] = ()
    """Where each extracted metadata field came from, and which ones were unreadable.

    Kept on the result so a transport can tell the researcher that a field is empty
    *because the font could not be decoded* rather than because the PDF omitted it
    (dogfood F6); an empty field with a `decodability:low` note is one discovery can fill.
    """

    @property
    def idempotent(self) -> bool:
        """True when these exact bytes were already registered and nothing was written."""
        return self.created == "nothing"

    @property
    def undecodable_fields(self) -> tuple[str, ...]:
        """Metadata fields the parser could not read, so they were left empty."""
        return tuple(
            note.field for note in self.metadata_notes if note.note == NOTE_DECODABILITY_LOW
        )


@dataclass(frozen=True, slots=True)
class ParseResult:
    """One parse: the document IR that was stored and the mutation that stored it."""

    work: WorkId
    artifact: ArtifactId
    document: ParsedDocument
    page_count: int
    mutation: MutationResult

    @property
    def blocks(self) -> tuple[DocumentBlock, ...]:
        """The structural blocks the parse produced, in reading order."""
        return self.document.blocks


class IngestService:
    """Turns local files into corpus state through the capability handlers."""

    def __init__(
        self, ctx: CapabilityContext, *, parsers: Sequence[DocumentParser] | None = None
    ) -> None:
        self._ctx = ctx
        self._parsers: tuple[DocumentParser, ...] = (
            tuple(parsers) if parsers is not None else (PyMuPdfParser(),)
        )

    # -- ingest --------------------------------------------------------------

    def ingest(self, request: IngestLocalPdfRequest) -> IngestResult:
        """`corpus.ingest` for one local file."""
        return self.ingest_local_pdf(
            request.path, as_new=request.as_new, attach_to=request.attach_to
        )

    def ingest_local_pdf(
        self,
        path: Path | str,
        *,
        as_new: bool = False,
        attach_to: WorkId | None = None,
    ) -> IngestResult:
        """Hash, inspect, and resolve ``path``, then register exactly what it turned out to be.

        ``as_new`` and ``attach_to`` are the researcher's answer to an unresolved identity;
        without one of them an ambiguous file raises rather than guessing (Product 13).
        """
        source = Path(path)
        if not source.is_file():
            raise CapabilityError(f"corpus.ingest: no file at {source}")
        fingerprint = fingerprint_file(source)
        inspection = _inspect(source, fingerprint)
        notes = inspection.notes
        candidate = build_work_candidate(source, fingerprint, inspection.metadata)
        resolution = resolve_identity(candidate, self._existing_records())
        logger.info(
            "%s resolved as %s (%s)",
            source.name,
            resolution.outcome.value,
            "; ".join(resolution.reasons) or "no reason recorded",
        )
        if attach_to is not None:
            return _with_notes(
                self._attach(candidate, resolution, fingerprint, source, attach_to), notes
            )
        if as_new:
            return _with_notes(self._register(candidate, resolution, fingerprint, source), notes)
        match resolution.outcome:
            case IdentityResolutionOutcome.SAME_ARTIFACT:
                return _with_notes(self._already_registered(candidate, resolution), notes)
            case IdentityResolutionOutcome.SAME_VERSION:
                return _with_notes(
                    self._add_artifact(candidate, resolution, fingerprint, source), notes
                )
            case IdentityResolutionOutcome.SAME_WORK:
                return _with_notes(
                    self._add_version(candidate, resolution, fingerprint, source), notes
                )
            case IdentityResolutionOutcome.DISTINCT_WORK:
                return _with_notes(
                    self._register(candidate, resolution, fingerprint, source), notes
                )
            case _:
                raise CapabilityError(
                    f"corpus.ingest: identity is unresolved for {source.name}: "
                    f"{'; '.join(resolution.reasons) or 'no candidate matched cleanly'}. "
                    "Decide it: --as-new registers a new Work, --attach-to W#### adds the "
                    "file to an existing one."
                )

    # -- parse ---------------------------------------------------------------

    def parse(self, request: ParseWorkRequest) -> ParseResult:
        """`work.parse` for one Work."""
        return self.parse_work(request.work, artifact=request.artifact)

    def parse_work(self, work: WorkId, *, artifact: ArtifactId | None = None) -> ParseResult:
        """Parse a Work's artifact into blocks and store them.

        A `ParseError` leaves canonical state untouched: parsing happens before the
        transaction opens, and a failed parse never reaches it.
        """
        repo = self._ctx.repo
        try:
            repo.get_work(work)
        except ObjectNotFoundError as exc:
            raise CapabilityError(f"work.parse: {exc}") from exc
        chosen = self._select_artifact(work, artifact)
        target = ParseTarget(
            work=chosen.work,
            version=chosen.version,
            artifact=chosen.id,
            file_hash=chosen.file_hash,
            path=repo.layout.artifact_bytes_file(chosen),
            mime_type=chosen.mime_type,
        )
        parser = select_parser(self._parsers, chosen.mime_type)
        document = parser.parse(target)
        mutation = store_parsed_document(
            self._ctx, StoreParsedDocumentRequest(document=document, work=chosen.work)
        )
        return ParseResult(
            work=chosen.work,
            artifact=chosen.id,
            document=document,
            page_count=document.page_count,
            mutation=mutation,
        )

    # -- outcomes ------------------------------------------------------------

    def _already_registered(
        self, candidate: WorkCandidate, resolution: IdentityResolution
    ) -> IngestResult:
        if resolution.work is None or resolution.version is None or resolution.artifact is None:
            raise CapabilityError(  # pragma: no cover - the resolution model guarantees these
                "corpus.ingest: same_artifact without a complete match"
            )
        return IngestResult(
            candidate=resolution.applied_to(candidate),
            resolution=resolution,
            work=resolution.work,
            version=resolution.version,
            artifact=resolution.artifact,
            created="nothing",
            mutation=None,
        )

    def _register(
        self,
        candidate: WorkCandidate,
        resolution: IdentityResolution,
        fingerprint: ArtifactFingerprint,
        path: Path,
    ) -> IngestResult:
        mutation = register_work(
            self._ctx,
            RegisterWorkRequest(
                candidate=candidate,
                artifact_path=path,
                version_kind=_version_kind(candidate),
                version_label=_version_label(candidate),
                mime_type=fingerprint.mime_type,
                artifact_kind=artifact_kind_for_mime(fingerprint.mime_type),
                version_identifiers=_version_identifiers(candidate),
            ),
        )
        return self._result(candidate, resolution, "work", mutation)

    def _add_version(
        self,
        candidate: WorkCandidate,
        resolution: IdentityResolution,
        fingerprint: ArtifactFingerprint,
        path: Path,
    ) -> IngestResult:
        if resolution.work is None:  # pragma: no cover - same_work always names a work
            raise CapabilityError("corpus.ingest: same_work without a matched work")
        return self._attach(candidate, resolution, fingerprint, path, resolution.work)

    def _add_artifact(
        self,
        candidate: WorkCandidate,
        resolution: IdentityResolution,
        fingerprint: ArtifactFingerprint,
        path: Path,
    ) -> IngestResult:
        if resolution.work is None:  # pragma: no cover - same_version always names both
            raise CapabilityError("corpus.ingest: same_version without a matched work")
        mutation = add_version_artifact(
            self._ctx,
            AddArtifactRequest(
                work=resolution.work,
                artifact_path=path,
                version=resolution.version,
                mime_type=fingerprint.mime_type,
                artifact_kind=artifact_kind_for_mime(fingerprint.mime_type),
                identifiers=resolution.merged_identifiers,
            ),
        )
        return self._result(candidate, resolution, "artifact", mutation)

    def _attach(
        self,
        candidate: WorkCandidate,
        resolution: IdentityResolution,
        fingerprint: ArtifactFingerprint,
        path: Path,
        work: WorkId,
    ) -> IngestResult:
        """Register a new Version and Artifact for ``work``; nothing existing is rewritten."""
        mutation = add_version_artifact(
            self._ctx,
            AddArtifactRequest(
                work=work,
                artifact_path=path,
                version_kind=_version_kind(candidate),
                version_label=_version_label(candidate),
                mime_type=fingerprint.mime_type,
                artifact_kind=artifact_kind_for_mime(fingerprint.mime_type),
                identifiers=resolution.merged_identifiers,
                version_identifiers=_version_identifiers(candidate),
            ),
        )
        return self._result(candidate, resolution, "version", mutation)

    # -- helpers -------------------------------------------------------------

    def _result(
        self,
        candidate: WorkCandidate,
        resolution: IdentityResolution,
        created: CreatedKind,
        mutation: MutationResult,
    ) -> IngestResult:
        """Read back what was written, so the ids reported are the canonical ones."""
        registered = next(
            (subject for subject in mutation.event.subjects if isinstance(subject, ArtifactId)),
            None,
        )
        if registered is None:  # pragma: no cover - every register event names its artifact
            raise CapabilityError("corpus.ingest: the mutation registered no artifact")
        artifact = self._ctx.repo.get_artifact(registered)
        return IngestResult(
            candidate=resolution.applied_to(candidate),
            resolution=resolution,
            work=artifact.work,
            version=artifact.version,
            artifact=artifact.id,
            created=created,
            mutation=mutation,
        )

    def _existing_records(self) -> list[ExistingRecord]:
        repo = self._ctx.repo
        return [
            ExistingRecord(
                work=work,
                versions=tuple(repo.list_versions(work.id)),
                artifacts=tuple(repo.list_artifacts(work.id)),
            )
            for work in repo.list_works()
        ]

    def _select_artifact(self, work: WorkId, artifact: ArtifactId | None) -> Artifact:
        """The artifact to parse: the requested one, else the newest parsable file."""
        artifacts = self._ctx.repo.list_artifacts(work)
        if artifact is not None:
            chosen = next((item for item in artifacts if item.id == artifact), None)
            if chosen is None:
                raise CapabilityError(f"work.parse: {work} has no artifact {artifact}")
            return chosen
        parsable = [item for item in artifacts if item.kind is ArtifactKind.PDF]
        if not parsable:
            raise CapabilityError(f"work.parse: {work} has no PDF artifact to parse")
        return max(parsable, key=lambda item: (item.id.number, item.id.suffix or 0))


def ingest_local_pdf(
    ctx: CapabilityContext,
    path: Path | str,
    *,
    as_new: bool = False,
    attach_to: WorkId | None = None,
) -> IngestResult:
    """Ingest one local file into ``ctx``'s workspace."""
    return IngestService(ctx).ingest_local_pdf(path, as_new=as_new, attach_to=attach_to)


def parse_work(
    ctx: CapabilityContext, work: WorkId, artifact: ArtifactId | None = None
) -> ParseResult:
    """Parse ``work``'s artifact and store its blocks."""
    return IngestService(ctx).parse_work(work, artifact=artifact)


def _inspect(path: Path, fingerprint: ArtifactFingerprint) -> PdfInspection:
    """Best-effort bibliographic metadata and its per-field notes; a bad file has none."""
    if fingerprint.artifact_kind is not ArtifactKind.PDF:
        return PdfInspection()
    try:
        return inspect_pdf_detail(path)
    except Exception:  # PyMuPDF reports every corruption as a plain exception
        logger.warning("could not read metadata from %s; ingesting it without any", path.name)
        return PdfInspection()


def _with_notes(result: IngestResult, notes: tuple[FieldNote, ...]) -> IngestResult:
    """The same result carrying the extraction notes of the file it read."""
    return replace(result, metadata_notes=notes)


def _arxiv(candidate: WorkCandidate) -> IdentifierField | None:
    return candidate.metadata.identifiers.arxiv


def _version_kind(candidate: WorkCandidate) -> VersionKind:
    """arXiv identifiers name an arXiv revision; everything else stays unclassified."""
    return VersionKind.ARXIV if _arxiv(candidate) is not None else VersionKind.OTHER


def _version_label(candidate: WorkCandidate) -> str | None:
    arxiv = _arxiv(candidate)
    return None if arxiv is None else arxiv_version_label(arxiv.value)


def _version_identifiers(candidate: WorkCandidate) -> WorkIdentifiers | None:
    """Identifiers that pin this exact revision: an arXiv id carrying its `vN` suffix.

    A work-level identifier (a DOI, or an arXiv id without a suffix) is deliberately left
    off the Version: it belongs to the paper, and putting it here would make the next
    revision of the same paper look like the same file.
    """
    arxiv = _arxiv(candidate)
    if arxiv is None or arxiv_version_label(arxiv.value) is None:
        return None
    return WorkIdentifiers(
        arxiv=IdentifierField(
            value=arxiv.value,
            source=arxiv.source if arxiv.source else ProvenanceSource.EXTERNAL_METADATA,
            confidence=arxiv.confidence,
        )
    )

"""`Save to corpus`: the one explicit path from a session attachment to corpus identity.

Attaching a file creates nothing in the corpus (attachments design SS3). This module is the
deliberate crossing, and it is built so that the crossing cannot be made by accident, made
twice, or made half-way:

* **Resolution is a read.** `resolve` hashes the session copy, reads what bibliographic
  metadata the file offers, and asks the existing identity resolver what it matches --
  an exact Artifact, a Version, a Work, or nothing yet. It writes nothing, so the
  researcher can look before choosing (Product 13, ADR-002).
* **Ingestion is not reimplemented.** `save` stages the immutable bytes and hands them to
  `IngestService`, which registers them through the same `work.register` /
  `work.add_artifact` capabilities `corpus.ingest` uses, and then parses them the same way.
  Saving the same bytes twice therefore resolves to the existing Artifact and writes
  nothing, because that is already what re-ingesting identical bytes does.
* **A failure keeps the session copy.** The attachment moves `promoting -> in_corpus` only
  after the corpus write succeeded; any failure records `promoting -> failed` with the
  reason, leaves the bytes in the session, and leaves the operation retryable
  (`failed -> promoting` is a legal transition).

What this module deliberately does *not* do is accept anything scientific. Corpus identity
is not evidence: no Evidence, Claim, or interpretation is created here, and extraction from
the saved artifact still goes through candidate, verification, and review with exact
anchors (attachments design SS7, Product 42 N).
"""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import MutationResult
from research_harness.conversation.attachments import AttachmentError, display_filename
from research_harness.domain.conversation import (
    STORED_ATTACHMENT_STATES,
    AttachmentState,
    SessionAttachment,
    transition_attachment,
)
from research_harness.domain.enums import ArtifactKind, IdentityResolutionOutcome
from research_harness.domain.ids import ArtifactId, VersionId, WorkId
from research_harness.domain.work import WorkCandidate
from research_harness.ingest.hashing import ArtifactFingerprint, artifact_kind_for_mime
from research_harness.ingest.identity import ExistingRecord, IdentityResolution, resolve_identity
from research_harness.ingest.metadata import PdfInspection, build_work_candidate, inspect_pdf_detail
from research_harness.ingest.service import CreatedKind, IngestService
from research_harness.workspace.conversations import ConversationStore

__all__ = [
    "AttachmentIdentity",
    "AttachmentPromotion",
    "AttachmentPromotionService",
    "IdentityChoice",
]

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^A-Za-z0-9 ._-]")

#: States a promotion may start from. `failed` is here on purpose: a promotion that broke
#: half-way left the session copy intact, and retrying it is the documented recovery.
_PROMOTABLE: frozenset[AttachmentState] = frozenset(
    {AttachmentState.READY, AttachmentState.SESSION_ONLY, AttachmentState.FAILED}
)


class IdentityChoice(StrEnum):
    """What saving this attachment would mean for corpus identity."""

    EXISTING_ARTIFACT = "existing_artifact"
    """These exact bytes are already registered; saving links to them and copies nothing."""
    EXISTING_VERSION = "existing_version"
    """A known revision of a known Work; the file becomes another Artifact of it."""
    EXISTING_WORK = "existing_work"
    """A known Work; the file becomes a new Version and Artifact under it."""
    NEW_WORK = "new_work"
    """Nothing in the corpus matches; saving registers a new Work."""
    UNDECIDED = "undecided"
    """The metadata matches more than one Work, or matches one only partially. The
    researcher decides with `as_new` or `attach_to`; nothing is guessed (Product 13)."""


_CHOICES: dict[IdentityResolutionOutcome, IdentityChoice] = {
    IdentityResolutionOutcome.SAME_ARTIFACT: IdentityChoice.EXISTING_ARTIFACT,
    IdentityResolutionOutcome.SAME_VERSION: IdentityChoice.EXISTING_VERSION,
    IdentityResolutionOutcome.SAME_WORK: IdentityChoice.EXISTING_WORK,
    IdentityResolutionOutcome.DISTINCT_WORK: IdentityChoice.NEW_WORK,
    IdentityResolutionOutcome.UNRESOLVED: IdentityChoice.UNDECIDED,
}


@dataclass(frozen=True, slots=True)
class AttachmentIdentity:
    """What one session attachment resolves to, and what the researcher must confirm."""

    attachment: SessionAttachment
    choice: IdentityChoice
    outcome: IdentityResolutionOutcome
    content_hash: str
    reasons: tuple[str, ...] = ()
    work: WorkId | None = None
    version: VersionId | None = None
    artifact: ArtifactId | None = None
    title: str | None = None
    doi: str | None = None
    arxiv: str | None = None
    year: int | None = None
    parsable: bool = False
    """True when the file is one the corpus parser can turn into anchored blocks."""

    @property
    def requires_confirmation(self) -> bool:
        """True when saving needs an explicit `as_new` or `attach_to` from the researcher."""
        return self.choice is IdentityChoice.UNDECIDED

    @property
    def duplicate(self) -> bool:
        """True when these exact bytes are already an Artifact of this corpus."""
        return self.choice is IdentityChoice.EXISTING_ARTIFACT


@dataclass(frozen=True, slots=True)
class AttachmentPromotion:
    """The result of a `Save to corpus`: what it linked, and what it created."""

    attachment: SessionAttachment
    work: WorkId
    version: VersionId
    artifact: ArtifactId
    created: CreatedKind
    outcome: IdentityResolutionOutcome
    reasons: tuple[str, ...] = ()
    parsed: bool = False
    mutation: MutationResult | None = None

    @property
    def linked_existing(self) -> bool:
        """True when nothing was copied: the same bytes were already in the corpus."""
        return self.created == "nothing"


class AttachmentPromotionService:
    """Resolves and performs `Save to corpus` for one workspace's session attachments."""

    def __init__(
        self,
        ctx: CapabilityContext,
        *,
        store: ConversationStore | None = None,
        ingest: IngestService | None = None,
    ) -> None:
        self._ctx = ctx
        # Shares the repository's reentrant lock, so the corpus write and the attachment
        # record it links can happen inside one held workspace lock.
        self._store = store if store is not None else ConversationStore.for_repository(ctx.repo)
        self._ingest = ingest if ingest is not None else IngestService(ctx)

    @property
    def store(self) -> ConversationStore:
        return self._store

    # -- resolution (a read) -------------------------------------------------

    def resolve(self, attachment: SessionAttachment) -> AttachmentIdentity:
        """What this attachment would become in the corpus. Writes nothing."""
        self._require_stored(attachment, "attachment.resolve_identity")
        fingerprint = self._fingerprint(attachment)
        inspection = self._inspect(attachment, fingerprint)
        candidate = build_work_candidate(
            self._store.attachment_bytes_path(attachment), fingerprint, inspection.metadata
        )
        resolution = resolve_identity(candidate, self._existing_records())
        return _identity(attachment, candidate, resolution, fingerprint)

    # -- promotion (a mutation) ----------------------------------------------

    def save(
        self,
        attachment: SessionAttachment,
        *,
        as_new: bool = False,
        attach_to: WorkId | None = None,
        parse: bool = True,
    ) -> AttachmentPromotion:
        """Copy this attachment into the corpus under a resolved identity.

        ``as_new`` and ``attach_to`` are the researcher's confirmation for an identity the
        resolver could not decide; without one of them an ambiguous file is refused rather
        than guessed. An attachment already in the corpus is returned as it stands: the
        corpus copy is immutable, so there is nothing to do twice.
        """
        if attachment.state is AttachmentState.IN_CORPUS:
            return _already_saved(attachment)
        self._require_stored(attachment, "attachment.save_to_corpus")
        if attachment.state not in _PROMOTABLE:
            raise AttachmentError(
                f"attachment.save_to_corpus: {attachment.id} is {attachment.state.value}; "
                "only a ready, session-only, or failed attachment can be promoted"
            )
        promoting = self._store.put_attachment(
            transition_attachment(attachment, AttachmentState.PROMOTING)
        )
        try:
            return self._promote(promoting, as_new=as_new, attach_to=attach_to, parse=parse)
        except Exception as exc:
            # The session copy is untouched, so the researcher retries rather than
            # re-attaches (attachments design SS6; `failed -> promoting` is legal).
            self._store.put_attachment(
                transition_attachment(
                    promoting,
                    AttachmentState.FAILED,
                    failure_reason=f"save to corpus failed: {exc}",
                )
            )
            logger.warning("promotion of %s failed: %s", attachment.id, exc)
            raise

    def _promote(
        self,
        attachment: SessionAttachment,
        *,
        as_new: bool,
        attach_to: WorkId | None,
        parse: bool,
    ) -> AttachmentPromotion:
        """The corpus half of a save: stage the bytes, ingest them, then parse."""
        data = self._store.read_attachment_bytes(attachment)
        with tempfile.TemporaryDirectory(prefix="rh-save-to-corpus-") as directory:
            # Staged under the *display* filename so the registered Artifact records the
            # name the researcher knows, not the `SA####` the session stored it under.
            staged = Path(directory) / _staged_name(attachment)
            staged.write_bytes(data)
            result = self._ingest.ingest_local_pdf(staged, as_new=as_new, attach_to=attach_to)
        parsed = self._parse_if_needed(result.work, result.artifact) if parse else False
        saved = self._store.put_attachment(
            transition_attachment(
                attachment,
                AttachmentState.IN_CORPUS,
                work=result.work,
                version=result.version,
                artifact=result.artifact,
            )
        )
        logger.info(
            "saved attachment %s to the corpus as %s (%s)",
            attachment.id,
            result.artifact,
            result.created,
        )
        return AttachmentPromotion(
            attachment=saved,
            work=result.work,
            version=result.version,
            artifact=result.artifact,
            created=result.created,
            outcome=result.resolution.outcome,
            reasons=tuple(result.resolution.reasons),
            parsed=parsed,
            mutation=result.mutation,
        )

    def _parse_if_needed(self, work: WorkId, artifact: ArtifactId) -> bool:
        """Parse the saved artifact unless it is not parsable or already parsed."""
        registered = self._ctx.repo.get_artifact(artifact)
        if registered.kind is not ArtifactKind.PDF:
            return False
        if self._ctx.repo.layout.blocks_file(work, artifact).is_file():
            return False
        self._ingest.parse_work(work, artifact=artifact)
        return True

    # -- helpers -------------------------------------------------------------

    def _require_stored(self, attachment: SessionAttachment, capability: str) -> None:
        """Refuse an attachment that never became ready; a failed *promotion* is fine.

        `failed` covers both "the file was never usable" and "the corpus write broke
        half-way", and only the second is retryable. The content hash tells them apart: it
        is written by the transition into `ready` and never by a validation failure.
        """
        stored = attachment.state in STORED_ATTACHMENT_STATES or (
            attachment.state is AttachmentState.FAILED and attachment.content_hash is not None
        )
        if not stored:
            raise AttachmentError(
                f"{capability}: {attachment.id} is {attachment.state.value} and has no "
                "validated bytes to save"
            )

    def _fingerprint(self, attachment: SessionAttachment) -> ArtifactFingerprint:
        """The attachment as the ingest layer sees a file, keeping its display filename."""
        if attachment.content_hash is None:  # pragma: no cover - stored states carry a hash
            raise AttachmentError(f"{attachment.id} has no content hash")
        return ArtifactFingerprint(
            sha256=attachment.content_hash,
            size_bytes=attachment.size_bytes,
            mime_type=attachment.media_type,
            original_filename=attachment.filename,
        )

    def _inspect(
        self, attachment: SessionAttachment, fingerprint: ArtifactFingerprint
    ) -> PdfInspection:
        """Best-effort bibliographic metadata; anything but a readable PDF has none."""
        if fingerprint.artifact_kind is not ArtifactKind.PDF:
            return PdfInspection()
        try:
            return inspect_pdf_detail(self._store.attachment_bytes_path(attachment))
        except Exception:  # PyMuPDF reports every corruption as a plain exception
            logger.warning("could not read metadata from attachment %s", attachment.id)
            return PdfInspection()

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


def _identity(
    attachment: SessionAttachment,
    candidate: WorkCandidate,
    resolution: IdentityResolution,
    fingerprint: ArtifactFingerprint,
) -> AttachmentIdentity:
    """Render one resolution as the answer a researcher confirms."""
    metadata = candidate.metadata
    identifiers = metadata.identifiers
    return AttachmentIdentity(
        attachment=attachment,
        choice=_CHOICES[resolution.outcome],
        outcome=resolution.outcome,
        content_hash=fingerprint.sha256,
        reasons=tuple(resolution.reasons),
        work=resolution.work,
        version=resolution.version,
        artifact=resolution.artifact,
        title=metadata.title.value if metadata.title is not None else None,
        doi=identifiers.doi.value if identifiers.doi is not None else None,
        arxiv=identifiers.arxiv.value if identifiers.arxiv is not None else None,
        year=_year(metadata.year),
        parsable=artifact_kind_for_mime(fingerprint.mime_type) is ArtifactKind.PDF,
    )


def _already_saved(attachment: SessionAttachment) -> AttachmentPromotion:
    """The idempotent answer for an attachment that is already in the corpus."""
    if attachment.work is None or attachment.version is None or attachment.artifact is None:
        raise AttachmentError(  # pragma: no cover - the schema guarantees the links
            f"{attachment.id} is in the corpus without complete links"
        )
    return AttachmentPromotion(
        attachment=attachment,
        work=attachment.work,
        version=attachment.version,
        artifact=attachment.artifact,
        created="nothing",
        outcome=IdentityResolutionOutcome.SAME_ARTIFACT,
        reasons=("the attachment was already saved to the corpus",),
    )


def _staged_name(attachment: SessionAttachment) -> str:
    """A filesystem-safe version of the display filename, for the staging copy only."""
    name = _UNSAFE.sub("_", display_filename(attachment.filename)).strip()
    if not name or name.startswith("."):
        suffix = PurePosixPath(attachment.filename).suffix.lower()
        return f"{attachment.id}{suffix if re.fullmatch(r'\.[A-Za-z0-9]{1,16}', suffix) else ''}"
    return name[:120]


def _year(value: object) -> int | None:
    """The candidate's year as an int, whatever shape the metadata field has."""
    raw = getattr(value, "value", value)
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return None

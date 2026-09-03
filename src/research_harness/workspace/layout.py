"""The canonical workspace file layout of Product 8.1, expressed as typed path accessors.

Nothing in the harness composes canonical paths by hand: `WorkspaceLayout` is the single
place that knows a Claim lives in `claims/C0041.yaml` and that everything regenerable lives
under `.research/`. Paths are pure values — no accessor touches the filesystem.

Layout::

    research.yaml
    corpus/works/W0001/work.yaml
    corpus/works/W0001/versions/V0001-1.yaml
    corpus/works/W0001/artifacts/A0001-1.yaml      metadata
    corpus/works/W0001/artifacts/A0001-1.pdf       immutable original bytes
    corpus/works/W0001/evidence.jsonl
    corpus/works/W0001/rejections.jsonl            candidates the researcher refused
    corpus/works/W0001/parsed/A0001-1.blocks.jsonl derived, but canonical: anchors resolve
                                                   without re-parsing the artifact
    claims/C0001.yaml         questions/RQ0001.yaml    taxonomy/<name>.yaml
    decisions/D0001.yaml      matrices/S0001.yaml      notes/<key>.yaml
    searches/SR0001.yaml      manuscript/ (+ anchors.jsonl)
    events/research.jsonl
    conversations/CS0001/     session.yaml, messages.jsonl, attachments/, context/,
                              summary.md -- durable, private, not scientific state
    .research/                research.db, index/, cache/, staging/, traces/, runs/,
                              journal/, lock  -- regenerable, no scientific authority

Three tiers, not two. `CANONICAL_DIRECTORIES` holds *canonical scientific state*: files with
scientific authority, meant to be committed, created by `init`. `.research/` holds
regenerable machine state with no authority at all. `conversations/` is the third tier and
belongs to neither: a transcript, its attachments, and its context receipts are durable
source records that deleting `.research/` may never lose (Product 8.2), but they are private
working context rather than accepted conclusions, so they are listed in the generated
`.gitignore`, are not created by `init`, and stay out of `path_for`/`id_from_path` -- a
conversation object is never written through a canonical transaction. `DURABLE_DIRECTORIES`
names them.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path, PurePosixPath

from research_harness.domain.claim import Claim
from research_harness.domain.conversation import SessionAttachment
from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.errors import DomainValidationError, WorkspaceError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import (
    ArtifactId,
    ClaimId,
    ContextPackId,
    ConversationSessionId,
    DecisionId,
    QuestionId,
    ResearchId,
    SearchRunId,
    SessionAttachmentId,
    SynthesisId,
    VersionId,
    WorkId,
    parse_id,
)
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.domain.research import (
    Decision,
    ResearchEvent,
    ResearchNote,
    ResearchQuestion,
    SearchRun,
    SynthesisMatrix,
    Taxonomy,
)
from research_harness.domain.work import Artifact, Version, Work
from research_harness.workspace.rejections import REJECTIONS_FILENAME, RejectionRecord

__all__ = [
    "CANONICAL_DIRECTORIES",
    "CONVERSATIONS_DIRNAME",
    "DURABLE_DIRECTORIES",
    "GITIGNORE_CONTENT",
    "NOTE_KEY_PATTERN",
    "RESEARCH_DIRECTORIES",
    "RESEARCH_DIRNAME",
    "RESEARCH_FILENAME",
    "WorkspaceLayout",
    "artifact_extension",
    "attachment_extension",
    "note_key",
]

RESEARCH_FILENAME = "research.yaml"
RESEARCH_DIRNAME = ".research"
CONVERSATIONS_DIRNAME = "conversations"
GITIGNORE_FILENAME = ".gitignore"
EVENTS_FILENAME = "research.jsonl"
EVIDENCE_FILENAME = "evidence.jsonl"
ANCHORS_FILENAME = "anchors.jsonl"
WORK_FILENAME = "work.yaml"
SESSION_FILENAME = "session.yaml"
MESSAGES_FILENAME = "messages.jsonl"
SUMMARY_FILENAME = "summary.md"
LOCK_FILENAME = "lock"
DATABASE_FILENAME = "research.db"
BLOCKS_SUFFIX = ".blocks.jsonl"

#: Directories holding canonical scientific state, created by `init` in this order.
CANONICAL_DIRECTORIES: tuple[str, ...] = (
    "corpus",
    "corpus/works",
    "claims",
    "questions",
    "taxonomy",
    "decisions",
    "matrices",
    "notes",
    "searches",
    "manuscript",
    "manuscript/figures",
    "events",
)

#: Durable private working context: transcripts, session attachments, context receipts.
#: Not canonical scientific state, and not regenerable either -- see the module docstring.
#: `init` does not create it; `ConversationStore` creates a session directory when the
#: researcher opens a session.
DURABLE_DIRECTORIES: tuple[str, ...] = (CONVERSATIONS_DIRNAME,)

#: Regenerable machine state; deleting the whole tree must never lose a conclusion.
RESEARCH_DIRECTORIES: tuple[str, ...] = (
    RESEARCH_DIRNAME,
    f"{RESEARCH_DIRNAME}/index",
    f"{RESEARCH_DIRNAME}/cache",
    f"{RESEARCH_DIRNAME}/staging",
    f"{RESEARCH_DIRNAME}/traces",
    f"{RESEARCH_DIRNAME}/runs",
    f"{RESEARCH_DIRNAME}/journal",
)

GITIGNORE_CONTENT = (
    "# Regenerable machine state: SQLite projection, indexes, caches, staging, traces.\n"
    "# Canonical scientific state lives outside it and is meant to be committed.\n"
    f"{RESEARCH_DIRNAME}/\n"
    "\n"
    "# Durable but private: conversation transcripts, their attachments, and the context\n"
    "# receipts of model calls. Sharing them is a separate, explicit export.\n"
    f"{CONVERSATIONS_DIRNAME}/\n"
)

NOTE_KEY_PATTERN = re.compile(r"^note-\d{8}-\d{6}-[0-9a-f]{6}$")
"""Shape of the key assigned to a note captured without one."""
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def note_key(created_at: object, token: str) -> str:
    """Build the capture key ``note-YYYYMMDD-HHMMSS-<6hex>`` for a keyless note."""
    stamp = getattr(created_at, "strftime", None)
    if stamp is None:  # pragma: no cover - guarded by the type checker
        raise WorkspaceError("a note key needs the note's created_at timestamp")
    return f"note-{stamp('%Y%m%d-%H%M%S')}-{token}"


def _stored_extension(filename: str, mime_type: str) -> str:
    """Suffix for stored bytes: the original filename's, else one guessed from the type.

    The filename is display metadata and never a path, so only its suffix is used and
    anything that is not a short alphanumeric extension becomes `.bin`.
    """
    suffix = PurePosixPath(filename).suffix.lower()
    if not suffix:
        suffix = mimetypes.guess_extension(mime_type) or ".bin"
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,16}", suffix):
        return ".bin"
    return suffix


def artifact_extension(artifact: Artifact) -> str:
    """File suffix for an artifact's immutable bytes, taken from its original filename."""
    return _stored_extension(artifact.original_filename, artifact.mime_type)


def attachment_extension(attachment: SessionAttachment) -> str:
    """File suffix for a session attachment's bytes, taken from its display filename."""
    return _stored_extension(attachment.filename, attachment.media_type)


class WorkspaceLayout:
    """Typed path accessors for one workspace root. Pure values; touches no files."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def __repr__(self) -> str:
        return f"WorkspaceLayout({str(self._root)!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, WorkspaceLayout) and other._root == self._root

    def __hash__(self) -> int:
        return hash(self._root)

    # -- roots ---------------------------------------------------------------

    @property
    def root(self) -> Path:
        """Workspace root; everything canonical lives directly under it."""
        return self._root

    @property
    def research_file(self) -> Path:
        """`research.yaml` — project identity, schema version, review policy, id counters."""
        return self._root / RESEARCH_FILENAME

    @property
    def gitignore_file(self) -> Path:
        return self._root / GITIGNORE_FILENAME

    @property
    def corpus_dir(self) -> Path:
        return self._root / "corpus"

    @property
    def works_dir(self) -> Path:
        return self.corpus_dir / "works"

    @property
    def claims_dir(self) -> Path:
        return self._root / "claims"

    @property
    def questions_dir(self) -> Path:
        return self._root / "questions"

    @property
    def taxonomy_dir(self) -> Path:
        return self._root / "taxonomy"

    @property
    def decisions_dir(self) -> Path:
        return self._root / "decisions"

    @property
    def matrices_dir(self) -> Path:
        return self._root / "matrices"

    @property
    def notes_dir(self) -> Path:
        return self._root / "notes"

    @property
    def searches_dir(self) -> Path:
        return self._root / "searches"

    @property
    def manuscript_dir(self) -> Path:
        """User-owned LaTeX/BibTeX; the harness only writes `anchors.jsonl` here."""
        return self._root / "manuscript"

    @property
    def anchors_file(self) -> Path:
        """`manuscript/anchors.jsonl`, keyed by `(file, sentence_fingerprint)`."""
        return self.manuscript_dir / ANCHORS_FILENAME

    @property
    def events_dir(self) -> Path:
        return self._root / "events"

    @property
    def events_file(self) -> Path:
        """`events/research.jsonl` — the Git-visible semantic audit companion."""
        return self.events_dir / EVENTS_FILENAME

    # -- durable conversation state ------------------------------------------

    @property
    def conversations_dir(self) -> Path:
        """`conversations/` — durable, private session records; never Git-published."""
        return self._root / CONVERSATIONS_DIRNAME

    def session_dir(self, session: ConversationSessionId) -> Path:
        return self.conversations_dir / str(session)

    def session_file(self, session: ConversationSessionId) -> Path:
        """`conversations/CS0001/session.yaml` — title, timestamps, visibility, defaults."""
        return self.session_dir(session) / SESSION_FILENAME

    def messages_file(self, session: ConversationSessionId) -> Path:
        """`conversations/CS0001/messages.jsonl` — the append-only transcript."""
        return self.session_dir(session) / MESSAGES_FILENAME

    def session_summary_file(self, session: ConversationSessionId) -> Path:
        """`conversations/CS0001/summary.md` — derived; never outranks the transcript."""
        return self.session_dir(session) / SUMMARY_FILENAME

    def session_attachments_dir(self, session: ConversationSessionId) -> Path:
        return self.session_dir(session) / "attachments"

    def session_attachment_file(
        self, session: ConversationSessionId, attachment: SessionAttachmentId
    ) -> Path:
        """Attachment *metadata*; the original bytes sit beside it under the same stem."""
        return self.session_attachments_dir(session) / f"{attachment}.yaml"

    def session_attachment_bytes_file(self, attachment: SessionAttachment) -> Path:
        """Original attachment bytes, e.g. `attachments/SA0001.pdf`; immutable once ready."""
        return (
            self.session_attachments_dir(attachment.session)
            / f"{attachment.id}{attachment_extension(attachment)}"
        )

    def session_context_dir(self, session: ConversationSessionId) -> Path:
        return self.session_dir(session) / "context"

    def context_pack_file(self, session: ConversationSessionId, pack: ContextPackId) -> Path:
        """`conversations/CS0001/context/CP0001.json` — one call's pack and its receipt."""
        return self.session_context_dir(session) / f"{pack}.json"

    # -- regenerable machine state -------------------------------------------

    @property
    def research_dir(self) -> Path:
        """`.research/` — regenerable projections and runtime state, never authoritative."""
        return self._root / RESEARCH_DIRNAME

    @property
    def database_file(self) -> Path:
        return self.research_dir / DATABASE_FILENAME

    @property
    def index_dir(self) -> Path:
        return self.research_dir / "index"

    @property
    def cache_dir(self) -> Path:
        return self.research_dir / "cache"

    @property
    def attachment_cache_dir(self) -> Path:
        """Thumbnails and page previews for session attachments; rebuilt on demand."""
        return self.cache_dir / "attachments"

    def attachment_preview_dir(self, attachment: SessionAttachmentId) -> Path:
        """One attachment's previews. A projection of the original bytes, never the source."""
        return self.attachment_cache_dir / str(attachment)

    @property
    def staging_dir(self) -> Path:
        """Where model candidates live before acceptance (Product 8.3)."""
        return self.research_dir / "staging"

    @property
    def traces_dir(self) -> Path:
        """Prompts, latency, retrieval traces — disposable, never the event log."""
        return self.research_dir / "traces"

    @property
    def runs_dir(self) -> Path:
        return self.research_dir / "runs"

    @property
    def journal_dir(self) -> Path:
        return self.research_dir / "journal"

    @property
    def lock_file(self) -> Path:
        return self.research_dir / LOCK_FILENAME

    # -- work-scoped paths ---------------------------------------------------

    def work_dir(self, work: WorkId) -> Path:
        return self.works_dir / str(work)

    def work_file(self, work: WorkId) -> Path:
        return self.work_dir(work) / WORK_FILENAME

    def versions_dir(self, work: WorkId) -> Path:
        return self.work_dir(work) / "versions"

    def version_file(self, work: WorkId, version: VersionId) -> Path:
        return self.versions_dir(work) / f"{version}.yaml"

    def artifacts_dir(self, work: WorkId) -> Path:
        return self.work_dir(work) / "artifacts"

    def artifact_file(self, work: WorkId, artifact: ArtifactId) -> Path:
        """Artifact *metadata*; the original bytes sit beside it under the same stem."""
        return self.artifacts_dir(work) / f"{artifact}.yaml"

    def artifact_bytes_file(self, artifact: Artifact) -> Path:
        """Immutable original bytes, e.g. `artifacts/A0001-1.pdf`."""
        return self.artifacts_dir(artifact.work) / f"{artifact.id}{artifact_extension(artifact)}"

    def evidence_file(self, work: WorkId) -> Path:
        return self.work_dir(work) / EVIDENCE_FILENAME

    def rejections_path(self, work: WorkId) -> Path:
        """`rejections.jsonl` — candidates refused for this Work, kept out of evidence."""
        return self.work_dir(work) / REJECTIONS_FILENAME

    def parsed_dir(self, work: WorkId) -> Path:
        return self.work_dir(work) / "parsed"

    def blocks_file(self, work: WorkId, artifact: ArtifactId) -> Path:
        """Parsed blocks for one artifact: derived, but canonical so anchors resolve."""
        return self.parsed_dir(work) / f"{artifact}{BLOCKS_SUFFIX}"

    # -- flat canonical collections ------------------------------------------

    def claim_file(self, claim: ClaimId) -> Path:
        return self.claims_dir / f"{claim}.yaml"

    def question_file(self, question: QuestionId) -> Path:
        return self.questions_dir / f"{question}.yaml"

    def decision_file(self, decision: DecisionId) -> Path:
        return self.decisions_dir / f"{decision}.yaml"

    def matrix_file(self, matrix: SynthesisId) -> Path:
        return self.matrices_dir / f"{matrix}.yaml"

    def search_run_file(self, search_run: SearchRunId) -> Path:
        return self.searches_dir / f"{search_run}.yaml"

    def taxonomy_file(self, name: str) -> Path:
        return self.taxonomy_dir / f"{_safe_name(name, 'taxonomy name')}.yaml"

    def note_file(self, key: str) -> Path:
        return self.notes_dir / f"{_safe_name(key, 'note key')}.yaml"

    # -- dispatch ------------------------------------------------------------

    def path_for(self, obj: object) -> Path:
        """Canonical file that holds ``obj``, dispatching on its type.

        Append-only members (Evidence, RejectionRecord, DocumentBlock, ManuscriptAnchor,
        ResearchEvent) resolve to the collection file they are appended to.
        """
        match obj:
            case Work():
                return self.work_file(obj.id)
            case Version():
                return self.version_file(obj.work, obj.id)
            case Artifact():
                return self.artifact_file(obj.work, obj.id)
            case Evidence():
                return self.evidence_file(obj.source.work)
            case RejectionRecord():
                return self.rejections_path(obj.work)
            case DocumentBlock():
                return self.blocks_file(obj.work, obj.artifact)
            case ParsedDocument():
                return self.blocks_file(_parsed_document_work(obj), obj.artifact)
            case Claim():
                return self.claim_file(obj.id)
            case ResearchQuestion():
                return self.question_file(obj.id)
            case Decision():
                return self.decision_file(obj.id)
            case SynthesisMatrix():
                return self.matrix_file(obj.id)
            case SearchRun():
                return self.search_run_file(obj.id)
            case Taxonomy():
                return self.taxonomy_file(obj.name)
            case ResearchNote():
                if obj.key is None:
                    raise WorkspaceError("a research note needs a key before it has a path")
                return self.note_file(obj.key)
            case ManuscriptAnchor():
                return self.anchors_file
            case ResearchEvent():
                return self.events_file
            case _:
                raise WorkspaceError(f"no canonical path for {type(obj).__name__}")

    def id_from_path(self, path: Path | str) -> ResearchId | None:
        """Inverse of :meth:`path_for` where the filename carries a stable id.

        Returns ``None`` for files keyed by something other than a research id
        (`taxonomy/<name>.yaml`, `notes/<key>.yaml`) and for append-only collections.
        """
        candidate = Path(path)
        if candidate.suffix != ".yaml":
            return None
        try:
            relative = self.relative(candidate)
        except WorkspaceError:
            return None
        parts = relative.parts
        if relative.name == WORK_FILENAME:
            return WorkId(parts[-2]) if len(parts) >= 2 else None
        if parts[0] in {"taxonomy", "notes", CONVERSATIONS_DIRNAME}:
            # `path_for` never produces a conversation path (a session is durable working
            # context, not canonical state), so its inverse does not claim one either.
            return None
        try:
            return parse_id(relative.stem)
        except DomainValidationError:
            return None

    # -- containment ---------------------------------------------------------

    def relative(self, path: Path | str) -> PurePosixPath:
        """Workspace-relative POSIX path, refusing anything outside the root."""
        candidate = Path(path)
        for base, target in ((self._root, candidate), (self._root.resolve(), _resolve(candidate))):
            try:
                relative = target.relative_to(base)
            except ValueError:
                continue
            if not relative.parts or ".." in relative.parts:
                break
            return PurePosixPath(relative.as_posix())
        raise WorkspaceError(f"{candidate} is outside the workspace at {self._root}")

    def resolve(self, relative: PurePosixPath | str) -> Path:
        """Absolute path for a workspace-relative POSIX path."""
        return self._root / Path(str(relative))

    def is_regenerable(self, path: Path | str) -> bool:
        """True when ``path`` lives under `.research/` and therefore has no authority."""
        try:
            relative = self.relative(path)
        except WorkspaceError:
            return False
        return relative.parts[0] == RESEARCH_DIRNAME


def _parsed_document_work(document: ParsedDocument) -> WorkId:
    if not document.blocks:
        raise WorkspaceError(
            f"parsed document for {document.artifact} has no blocks, so its work is unknown"
        )
    return document.blocks[0].work


def _safe_name(name: str, label: str) -> str:
    if not _SAFE_NAME.match(name):
        raise WorkspaceError(f"unsafe {label} {name!r}")
    return name


def _resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - unresolvable paths simply stay outside the root
        return path

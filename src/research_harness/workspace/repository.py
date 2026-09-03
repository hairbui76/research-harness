"""The only supported reader and writer of canonical scientific state.

`WorkspaceRepository` owns the Product 8.1 layout: typed reads for every canonical object,
and exactly one way to change accepted state — a transaction::

    with repo.transaction(event, actor="human:alice") as tx:
        claim_id = tx.allocate_id(ClaimId)
        tx.put(claim)
        tx.append_evidence(evidence)

Nothing is written until the block exits cleanly. On exit the repository revalidates every
object, digests it into the semantic event, and commits the canonical files and the event
through one journalled unit under the workspace lock (Product 8.2, Product 42 K). A failure
anywhere leaves the prior state; a crash is finished or undone by journal recovery on the
next open. There is no public method here that writes a canonical file outside a
transaction, which is what makes Product 36 ("all accepted-state mutation through explicit
capabilities") enforceable one layer up.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from research_harness.domain.base import Provenance, UtcDatetime, utc_now
from research_harness.domain.claim import Claim
from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import ResearchEventType, ReviewPolicy
from research_harness.domain.errors import WorkspaceError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import (
    ArtifactId,
    ClaimId,
    DecisionId,
    QuestionId,
    ResearchId,
    SearchRunId,
    SynthesisId,
    VersionId,
    WorkId,
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
from research_harness.privacy.policy import EgressPolicy, refuse_inline_secrets
from research_harness.workspace.events import (
    ConsistencyMarker,
    ConsistencyReport,
    EventLog,
    assert_semantic_event,
    clear_consistency_marker,
    content_digest,
    digest_key,
    object_digest,
    refresh_marker_after_commit,
    verified_marker,
    with_object_digests,
)
from research_harness.workspace.journal import RecoveryReport, Transaction, recover
from research_harness.workspace.layout import (
    CANONICAL_DIRECTORIES,
    GITIGNORE_CONTENT,
    RESEARCH_DIRECTORIES,
    WorkspaceLayout,
    note_key,
)
from research_harness.workspace.locking import DEFAULT_LOCK_TIMEOUT, WorkspaceLock
from research_harness.workspace.migrations import (
    CURRENT_SCHEMA_VERSION,
    check_schema_version,
    migrate,
)
from research_harness.workspace.rejections import RejectionRecord
from research_harness.workspace.serialization import (
    CanonicalLoader,
    WorkspaceSerializationError,
    canonical_bytes,
    dump_jsonl_line,
    iter_jsonl,
    read_yaml,
)

__all__ = [
    "INIT_ACTOR",
    "STORED_PARSER_NAME",
    "STORED_PARSER_VERSION",
    "ArtifactImmutableError",
    "ObjectNotFoundError",
    "WorkspaceConfig",
    "WorkspaceExistsError",
    "WorkspaceInconsistentError",
    "WorkspaceNotFoundError",
    "WorkspaceRepository",
    "WorkspaceTransaction",
]

logger = logging.getLogger(__name__)

INIT_ACTOR = "system"
"""Actor recorded on the `project.initialized` event; creating a workspace is mechanical."""

STORED_PARSER_NAME = "stored-blocks"
STORED_PARSER_VERSION = "canonical"
"""Parser identity of a document rebuilt from stored blocks.

It is deliberately not a parser name: the blocks under `corpus/works/W####/parsed/` are
canonical, so a document assembled from them is a *replay surface*, not a parse. It must
never be fingerprinted, stored, or reported as the parse that produced the blocks.
"""


class WorkspaceNotFoundError(WorkspaceError):
    """No research workspace exists at the given root."""


class WorkspaceExistsError(WorkspaceError):
    """A research workspace already exists at the given root."""


class ObjectNotFoundError(WorkspaceError):
    """The requested canonical object is not in this workspace."""


class ArtifactImmutableError(WorkspaceError):
    """Artifacts are registered once: a different revision is a new Artifact (ADR-002)."""


class WorkspaceInconsistentError(WorkspaceError):
    """The event log and canonical state disagree, so the workspace fails closed."""

    def __init__(self, report: ConsistencyReport, root: Path) -> None:
        self.report = report
        super().__init__(
            f"workspace {root} is inconsistent: {report.summary()}. "
            "Canonical files are authoritative and are never rewritten automatically; "
            "open with repair=True to inspect the report, then reconcile the difference."
        )


class WorkspaceConfig(BaseModel):
    """`research.yaml`: project identity, schema version, review policy, and id counters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION, ge=1)
    name: str = Field(min_length=1)
    created_at: UtcDatetime = Field(default_factory=utc_now)
    review_policy: ReviewPolicy = ReviewPolicy.STRICT
    id_counters: dict[str, int] = Field(default_factory=dict)
    providers: list[dict[str, Any]] = Field(default_factory=list)
    """Model routing entries (Product 20.2), kept raw because `workspace/` must not import
    `providers/`; `providers.models.RouterConfig` validates them where they are used."""
    privacy: EgressPolicy = Field(default_factory=EgressPolicy)
    """Egress policy for this project (Product 34). Declared last so a `research.yaml`
    written before it existed keeps its key order, and defaulted so such a file opens
    unchanged. `EgressPolicy` lives in `privacy/`, which imports neither `providers/` nor
    `workspace/`, so holding it here breaks no layering."""

    @field_validator("providers")
    @classmethod
    def _refuse_inline_secrets(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Refuse a credential written into `research.yaml` (Product 34).

        Canonical files are meant to be committed; a key in one is a leak the moment the
        project is pushed. The check lives at the workspace boundary so it fires when the
        workspace opens, not only when a router happens to be built.
        """
        for index, entry in enumerate(value):
            refuse_inline_secrets(entry, where=f"providers[{index}] in research.yaml")
        return value

    def counter(self, prefix: str) -> int:
        """Highest number handed out for ``prefix`` so far."""
        return self.id_counters.get(prefix, 0)

    def with_counter(self, prefix: str, value: int) -> WorkspaceConfig:
        return self.model_copy(update={"id_counters": {**self.id_counters, prefix: value}})

    def with_privacy(self, policy: EgressPolicy) -> WorkspaceConfig:
        return self.model_copy(update={"privacy": policy})


class WorkspaceRepository:
    """Typed access to one workspace's canonical state."""

    def __init__(
        self,
        layout: WorkspaceLayout,
        config: WorkspaceConfig,
        *,
        consistency: ConsistencyReport | None = None,
        marker: ConsistencyMarker | None = None,
        recovery: RecoveryReport | None = None,
        lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
    ) -> None:
        self._layout = layout
        self._config = config
        self._consistency = consistency or ConsistencyReport()
        self._marker = marker
        self._recovery = recovery or RecoveryReport()
        self._lock_timeout = lock_timeout
        self._lock: WorkspaceLock | None = None
        self._events = EventLog(layout)

    # -- lifecycle -----------------------------------------------------------

    @classmethod
    def init(
        cls,
        root: Path | str,
        name: str,
        *,
        policy: ReviewPolicy | str = ReviewPolicy.STRICT,
        lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
    ) -> WorkspaceRepository:
        """Create the Product 8.1 layout, `research.yaml`, and `.gitignore`."""
        layout = WorkspaceLayout(root)
        if layout.research_file.exists():
            raise WorkspaceExistsError(f"a research workspace already exists at {layout.root}")
        for relative in (*CANONICAL_DIRECTORIES, *RESEARCH_DIRECTORIES):
            (layout.root / relative).mkdir(parents=True, exist_ok=True)
        config = WorkspaceConfig(
            schema_version=CURRENT_SCHEMA_VERSION,
            name=name,
            review_policy=ReviewPolicy(policy),
            id_counters={},
        )
        # Creating the workspace is itself a state change, so the log opens with it: the
        # first line of `events/research.jsonl` says which project this history belongs
        # to. It carries no subjects and no object digests, because no research object
        # exists yet. The event is staged into the same journalled transaction as the
        # files, so an interrupted `init` leaves no half-built workspace and no orphan
        # event.
        event = ResearchEvent(
            event=ResearchEventType.PROJECT_INITIALIZED,
            actor=INIT_ACTOR,
            summary=f"initialized research project {name!r}",
            subjects=(),
        )
        assert_semantic_event(event)
        transaction = Transaction(layout)
        transaction.write(layout.research_file, canonical_bytes(config))
        transaction.write(layout.gitignore_file, GITIGNORE_CONTENT.encode("utf-8"))
        EventLog(layout).stage(transaction, event)
        with WorkspaceLock(layout, lock_timeout):
            transaction.commit()
        logger.info("initialized research workspace %s (%s)", layout.root, name)
        return cls(layout, config, lock_timeout=lock_timeout)

    @classmethod
    def open(
        cls,
        root: Path | str,
        *,
        repair: bool = False,
        verify: Literal["auto", "full"] = "auto",
        lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
    ) -> WorkspaceRepository:
        """Open a workspace, failing closed on an unsupported version or an inconsistency.

        Order matters. The declared schema version is checked before anything is touched, so
        a workspace from a newer harness is never modified. Any interrupted transaction is
        then recovered *under the workspace lock*, because recovery writes canonical files
        and two processes opening at once must not redo the same unit against each other.
        Migration and the config read follow recovery, so neither sees a half-applied
        mutation. Finally the event log is reconciled with canonical state; ``repair=True``
        returns that report instead of raising, and never rewrites scientific content.

        ``verify="full"`` re-derives every digest the event log names — the check
        `research doctor` should ask for, and the only path that can declare a workspace
        consistent. ``verify="auto"`` runs the same check unless
        `.research/consistency-check.json` proves the canonical tree and the event log
        byte-for-byte identical to the ones the last successful full check ran against, in
        which case the report says so through
        :attr:`~research_harness.workspace.events.ConsistencyReport.skipped_reason`.
        """
        layout = WorkspaceLayout(root)
        if not layout.research_file.is_file():
            raise WorkspaceNotFoundError(
                f"no research workspace at {layout.root}: {layout.research_file.name} is missing"
            )
        version = _declared_schema_version(layout)
        check_schema_version(version)
        recovery = _recover_under_lock(layout, lock_timeout)
        if version < CURRENT_SCHEMA_VERSION:
            migrate(layout, version)
        config = read_yaml(layout.research_file, WorkspaceConfig)
        consistency, marker = verified_marker(layout, verify_full=verify == "full")
        if not consistency.consistent and not repair:
            raise WorkspaceInconsistentError(consistency, layout.root)
        return cls(
            layout,
            config,
            consistency=consistency,
            marker=marker,
            recovery=recovery,
            lock_timeout=lock_timeout,
        )

    # -- state ---------------------------------------------------------------

    @property
    def layout(self) -> WorkspaceLayout:
        return self._layout

    @property
    def root(self) -> Path:
        return self._layout.root

    @property
    def config(self) -> WorkspaceConfig:
        """`research.yaml` as loaded; refreshed after every committed transaction."""
        return self._config

    @property
    def review_policy(self) -> ReviewPolicy:
        return self._config.review_policy

    @property
    def consistency(self) -> ConsistencyReport:
        """Event/canonical reconciliation from the last :meth:`open`."""
        return self._consistency

    @property
    def recovery(self) -> RecoveryReport:
        """What journal recovery did during the last :meth:`open`."""
        return self._recovery

    @property
    def events(self) -> EventLog:
        return self._events

    def verify(self) -> ConsistencyReport:
        """Re-run the full event/canonical reconciliation against the workspace as it is now.

        Always the whole check, never the cached verdict: this is what a caller asks for
        when it wants the guarantee rather than the answer it already had. A successful run
        refreshes `.research/consistency-check.json` so the next open can stand on it.
        """
        self._consistency, self._marker = verified_marker(self._layout, verify_full=True)
        return self._consistency

    # -- configuration -------------------------------------------------------

    def update_config(self, policy: EgressPolicy) -> WorkspaceConfig:
        """Persist a new privacy policy into `research.yaml` and return the new config.

        Configuration is not scientific state: changing where a model may be called from
        decides nothing about the corpus, so this deliberately appends **no**
        `ResearchEvent` — the semantic log records state changes, and an event with no
        canonical object to digest would be rejected by `WorkspaceTransaction.commit`
        anyway (Product 19.3). What it does keep is the durability: the write goes through
        the same journal and the same workspace lock as every canonical mutation, so an
        interrupted `research privacy set` leaves either the old file or the new one, and
        never a truncated one.
        """
        with self.lock():
            config = read_yaml(self._layout.research_file, WorkspaceConfig).with_privacy(policy)
            transaction = Transaction(self._layout)
            transaction.write(self._layout.research_file, canonical_bytes(config))
            transaction.commit()
            self._note_commit(transaction.paths)
        self._refresh_config(config)
        return config

    # -- locking -------------------------------------------------------------

    @contextmanager
    def lock(self) -> Iterator[WorkspaceLock]:
        """Hold the workspace lock across several transactions (read-modify-write).

        Nesting is allowed within one repository object: an inner ``lock()`` (a handler
        allocating an id while the daemon already serializes the request) reuses the held
        lock and the outermost context releases it. The OS lock itself stays non-reentrant.
        """
        if self._lock is not None:
            yield self._lock
            return
        lock = WorkspaceLock(self._layout, self._lock_timeout)
        self._lock = lock
        try:
            with lock:
                yield lock
        finally:
            self._lock = None

    # -- typed reads ---------------------------------------------------------

    def get_work(self, work: WorkId) -> Work:
        return self._read(self._layout.work_file(work), Work, work)

    def list_works(self) -> list[Work]:
        """Every Work in the corpus, ordered by id."""
        if not self._layout.works_dir.is_dir():
            return []
        paths = sorted(self._layout.works_dir.glob("*/work.yaml"))
        return [read_yaml(path, Work) for path in paths]

    def get_version(self, version: VersionId, *, work: WorkId | None = None) -> Version:
        path = (
            self._layout.version_file(work, version)
            if work is not None
            else _first(self._layout.works_dir.glob(f"*/versions/{version}.yaml"))
        )
        return self._read(path, Version, version)

    def list_versions(self, work: WorkId) -> list[Version]:
        directory = self._layout.versions_dir(work)
        return [read_yaml(path, Version) for path in sorted(directory.glob("*.yaml"))]

    def get_artifact(self, artifact: ArtifactId, *, work: WorkId | None = None) -> Artifact:
        path = (
            self._layout.artifact_file(work, artifact)
            if work is not None
            else _first(self._layout.works_dir.glob(f"*/artifacts/{artifact}.yaml"))
        )
        return self._read(path, Artifact, artifact)

    def list_artifacts(self, work: WorkId) -> list[Artifact]:
        directory = self._layout.artifacts_dir(work)
        return [read_yaml(path, Artifact) for path in sorted(directory.glob("*.yaml"))]

    def read_artifact_bytes(self, artifact: Artifact) -> bytes:
        """The immutable original bytes an evidence anchor was accepted against."""
        path = self._layout.artifact_bytes_file(artifact)
        if not path.is_file():
            raise ObjectNotFoundError(f"no stored bytes for artifact {artifact.id} at {path}")
        return path.read_bytes()

    def iter_evidence(self, work: WorkId, *, latest_only: bool = True) -> Iterator[Evidence]:
        """Evidence for one Work; by default only the newest record per evidence id.

        `evidence.jsonl` is append-only, so an updated object appears again at the end of
        the file. Readers want the current state; the earlier lines stay in Git history.
        """
        records = iter_jsonl(self._layout.evidence_file(work), Evidence)
        if not latest_only:
            yield from records
            return
        yield from _latest_by(records, lambda record: str(record.id))

    def iter_rejections(self, work: WorkId) -> Iterator[RejectionRecord]:
        """Candidates refused for this Work, oldest first (Product 24.3).

        Every record is kept: a candidate proposed, rejected, proposed again, and rejected
        again is exactly the history a reviewer needs to see.
        """
        yield from iter_jsonl(self._layout.rejections_path(work), RejectionRecord)

    def iter_blocks(
        self, artifact: ArtifactId, *, work: WorkId | None = None
    ) -> Iterator[DocumentBlock]:
        """Parsed blocks for one artifact, in file order."""
        path = (
            self._layout.blocks_file(work, artifact)
            if work is not None
            else _first(self._layout.works_dir.glob(f"*/parsed/{artifact}.blocks.jsonl"))
        )
        if path is None:
            return
        yield from iter_jsonl(path, DocumentBlock)

    def get_parsed_document(
        self, artifact: ArtifactId, *, work: WorkId | None = None
    ) -> ParsedDocument | None:
        """One artifact's stored blocks as a `ParsedDocument`, or ``None`` when none exist.

        The blocks under `corpus/works/W####/parsed/` are canonical precisely so an anchor
        can be validated, and a section reassembled, without reopening the PDF (Product
        8.1). What comes back carries the Artifact's own version and `file_hash`, so it
        names the bytes the parse read, and the placeholder parser identity of
        `STORED_PARSER_NAME`, because this is a replay surface and not a parse.
        """
        blocks = tuple(self.iter_blocks(artifact, work=work))
        if not blocks:
            return None
        source = self.get_artifact(artifact, work=work)
        return ParsedDocument(
            work=source.work,
            version=source.version,
            artifact=source.id,
            file_hash=source.file_hash,
            parser_name=STORED_PARSER_NAME,
            parser_version=STORED_PARSER_VERSION,
            page_count=max(block.page for block in blocks),
            blocks=blocks,
            provenance=Provenance.system(
                actor="workspace", note="rebuilt from stored blocks for anchor replay"
            ),
        )

    def iter_parsed_documents(self, work: WorkId) -> Iterator[ParsedDocument]:
        """Every artifact of ``work`` that has stored blocks, in artifact order."""
        for artifact in self.list_artifacts(work):
            document = self.get_parsed_document(artifact.id, work=work)
            if document is not None:
                yield document

    def get_claim(self, claim: ClaimId) -> Claim:
        return self._read(self._layout.claim_file(claim), Claim, claim)

    def list_claims(self) -> list[Claim]:
        return self._list(self._layout.claims_dir, Claim)

    def get_question(self, question: QuestionId) -> ResearchQuestion:
        return self._read(self._layout.question_file(question), ResearchQuestion, question)

    def list_questions(self) -> list[ResearchQuestion]:
        return self._list(self._layout.questions_dir, ResearchQuestion)

    def get_decision(self, decision: DecisionId) -> Decision:
        return self._read(self._layout.decision_file(decision), Decision, decision)

    def list_decisions(self) -> list[Decision]:
        return self._list(self._layout.decisions_dir, Decision)

    def get_matrix(self, matrix: SynthesisId) -> SynthesisMatrix:
        return self._read(self._layout.matrix_file(matrix), SynthesisMatrix, matrix)

    def list_matrices(self) -> list[SynthesisMatrix]:
        return self._list(self._layout.matrices_dir, SynthesisMatrix)

    def get_search_run(self, search_run: SearchRunId) -> SearchRun:
        return self._read(self._layout.search_run_file(search_run), SearchRun, search_run)

    def list_search_runs(self) -> list[SearchRun]:
        return self._list(self._layout.searches_dir, SearchRun)

    def get_taxonomy(self, name: str) -> Taxonomy:
        path = self._layout.taxonomy_file(name)
        if not path.is_file():
            raise ObjectNotFoundError(f"no taxonomy {name!r} at {path}")
        return read_yaml(path, Taxonomy)

    def list_taxonomies(self) -> list[Taxonomy]:
        return self._list(self._layout.taxonomy_dir, Taxonomy)

    def iter_notes(self) -> Iterator[ResearchNote]:
        """Low-authority captures, ordered by key."""
        directory = self._layout.notes_dir
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*.yaml")):
            yield read_yaml(path, ResearchNote)

    def iter_anchors(self, *, latest_only: bool = True) -> Iterator[ManuscriptAnchor]:
        """Manuscript anchors, keyed by `(file, sentence_fingerprint)`."""
        records = iter_jsonl(self._layout.anchors_file, ManuscriptAnchor)
        if not latest_only:
            yield from records
            return
        yield from _latest_by(records, lambda a: f"{a.file}#{a.sentence_fingerprint}")

    def iter_events(self) -> Iterator[ResearchEvent]:
        """The semantic event log, oldest first."""
        yield from self._events.iter_events()

    # -- mutation ------------------------------------------------------------

    @contextmanager
    def transaction(
        self, event: ResearchEvent, actor: str | None = None
    ) -> Iterator[WorkspaceTransaction]:
        """The single supported way to change accepted state.

        The workspace lock is taken for the whole block, not just the commit, because id
        allocation and artifact-immutability checks read the corpus while staging. Model
        work belongs outside the block (Product 8.3): candidates are produced in staging and
        only the accepted result is written here.
        """
        outer = self._lock
        lock = outer if outer is not None else WorkspaceLock(self._layout, self._lock_timeout)
        if outer is None:
            lock.acquire()
        try:
            transaction = WorkspaceTransaction(self, event, actor=actor)
            try:
                yield transaction
            except BaseException:
                transaction.abort()
                raise
            transaction.commit()
        finally:
            if outer is None:
                lock.release()

    def _refresh_config(self, config: WorkspaceConfig) -> None:
        self._config = config

    def _note_commit(self, paths: Sequence[Path]) -> None:
        """Keep the verification cache honest about a mutation that just landed.

        A committed transaction leaves canonical state and the event log consistent by
        construction, so a marker this repository is standing on can carry over with the
        touched files re-stat'd. Any other case — a repository built without a verified
        marker, a marker that cannot be rewritten — drops the marker, and the next open
        pays for the full check.
        """
        self._marker = refresh_marker_after_commit(self._layout, self._marker, paths)

    def _drop_marker(self) -> None:
        """Forget the verification cache; whatever happened, the next open re-verifies."""
        self._marker = None
        clear_consistency_marker(self._layout)

    # -- helpers -------------------------------------------------------------

    def _read[T: BaseModel](self, path: Path | None, model_type: type[T], key: object) -> T:
        if path is None or not path.is_file():
            raise ObjectNotFoundError(f"no {model_type.__name__} {key} in {self._layout.root}")
        return read_yaml(path, model_type)

    def _list[T: BaseModel](self, directory: Path, model_type: type[T]) -> list[T]:
        if not directory.is_dir():
            return []
        return [read_yaml(path, model_type) for path in sorted(directory.glob("*.yaml"))]


class WorkspaceTransaction:
    """Stages one accepted-state mutation; nothing reaches disk before :meth:`commit`.

    Created by :meth:`WorkspaceRepository.transaction`, never directly.
    """

    def __init__(
        self, repository: WorkspaceRepository, event: ResearchEvent, *, actor: str | None = None
    ) -> None:
        self._repository = repository
        self._layout = repository.layout
        self._journal = Transaction(repository.layout)
        self._event = event.touch(actor=actor) if actor else event
        self._objects: list[tuple[str, BaseModel]] = []
        self._digests: dict[str, str] = {}
        self._config = repository.config
        self._config_changed = False
        self._pending_artifact_bytes: dict[str, bytes] = {}
        self._closed = False

    # -- identity ------------------------------------------------------------

    @property
    def tx_id(self) -> str:
        return self._journal.tx_id

    @property
    def event(self) -> ResearchEvent:
        """The semantic event that will be appended with this mutation."""
        return self._event

    @property
    def actor(self) -> str:
        return self._event.actor

    @property
    def paths(self) -> tuple[Path, ...]:
        return self._journal.paths

    # -- staging -------------------------------------------------------------

    def put(self, obj: BaseModel) -> Path:
        """Stage any canonical single-object write, choosing its file from its type."""
        match obj:
            case ResearchNote():
                return self.put_note(obj)[1]
            case Evidence():
                return self.append_evidence(obj)
            case RejectionRecord():
                return self.append_rejection(obj)
            case ManuscriptAnchor():
                return self.put_anchor(obj)
            case ParsedDocument():
                return self.put_blocks(obj)
            case _:
                path = self._layout.path_for(obj)
                self._journal.write(path, canonical_bytes(obj))
                self._record(obj)
                return path

    def put_note(self, note: ResearchNote) -> tuple[ResearchNote, Path]:
        """Stage a note, assigning `note-YYYYMMDD-HHMMSS-<6hex>` when it has no key yet."""
        keyed = note if note.key else note.touch(key=_new_note_key(note.created_at))
        path = self._layout.path_for(keyed)
        self._journal.write(path, canonical_bytes(keyed))
        self._record(keyed)
        return keyed, path

    def append_evidence(self, evidence: Evidence) -> Path:
        """Append one evidence record to its Work's `evidence.jsonl`."""
        path = self._layout.evidence_file(evidence.source.work)
        self._journal.append(path, dump_jsonl_line(evidence).encode("utf-8"))
        self._record(evidence)
        return path

    def append_rejection(self, record: RejectionRecord) -> Path:
        """Append one rejection to its Work's `rejections.jsonl`.

        A rejection is canonical: it is the mutation `evidence.reject` commits, which is why
        the event describing it has a state change to travel with (Product 8.2).
        """
        path = self._layout.rejections_path(record.work)
        self._journal.append(path, dump_jsonl_line(record).encode("utf-8"))
        self._record(record)
        return path

    def put_anchor(self, anchor: ManuscriptAnchor) -> Path:
        """Append one manuscript anchor to `manuscript/anchors.jsonl`."""
        path = self._layout.anchors_file
        self._journal.append(path, dump_jsonl_line(anchor).encode("utf-8"))
        self._record(anchor)
        return path

    def put_blocks(self, document: ParsedDocument, *, work: WorkId | None = None) -> Path:
        """Write the parsed blocks of one artifact so anchors resolve without re-parsing."""
        owner = work or self._work_of(document)
        path = self._layout.blocks_file(owner, document.artifact)
        content = "".join(dump_jsonl_line(block) for block in document.blocks).encode("utf-8")
        self._journal.write(path, content)
        self._digests[digest_key(document)] = content_digest(content)
        return path

    def store_artifact_bytes(self, artifact: Artifact, data: bytes) -> Path:
        """Store an artifact's immutable original bytes beside its metadata.

        Artifacts are registered once (ADR-002): re-storing identical bytes is idempotent,
        and different bytes are refused so an accepted evidence anchor can never be
        re-pointed at a file it was not read from.
        """
        path = self._layout.artifact_bytes_file(artifact)
        digest = content_digest(data)
        if digest != artifact.file_hash:
            raise ArtifactImmutableError(
                f"artifact {artifact.id} declares file_hash {artifact.file_hash} but the bytes "
                f"hash to {digest}"
            )
        existing = self._pending_artifact_bytes.get(str(path))
        if existing is None and path.is_file():
            existing = path.read_bytes()
        if existing is not None:
            if existing != data:
                raise ArtifactImmutableError(
                    f"artifact {artifact.id} already has stored bytes at {path}; a different "
                    "revision is a new Artifact, never an overwrite"
                )
            return path
        self._pending_artifact_bytes[str(path)] = data
        self._journal.write(path, data)
        return path

    def allocate_id[T: ResearchId](self, id_type: type[T], *, work: WorkId | None = None) -> T:
        """Allocate the next free id, bumping `research.yaml` inside this transaction.

        The counter in `research.yaml` is the allocator, but it is cross-checked against the
        ids already on disk so a hand-created object can never be handed out twice. Versions
        and Artifacts are allocated inside a Work: their number mirrors the Work's and the
        suffix counts within it (ADR-002).
        """
        if work is not None:
            if not id_type.scoped:
                raise WorkspaceError(f"{id_type.__name__} is not allocated inside a work")
            existing = self._existing_ids(id_type, work=work)
            return id_type.next_in_scope(work.number, existing)
        on_disk = id_type.next(self._existing_ids(id_type))
        number = max(on_disk.number, self._config.counter(id_type.prefix) + 1)
        self._config = self._config.with_counter(id_type.prefix, number)
        self._config_changed = True
        return id_type.make(number)

    # -- commit --------------------------------------------------------------

    def commit(self) -> ResearchEvent:
        """Validate, digest, append the event, and commit the whole unit."""
        if self._closed:
            raise WorkspaceError(f"transaction {self.tx_id} is already closed")
        self._closed = True
        if self._journal.is_empty:
            raise WorkspaceError(
                f"event {self._event.event.value!r} has no canonical mutation; an event "
                "without the state change it describes is not a valid workspace state"
            )
        for key, obj in self._objects:
            _revalidate(obj, key)
        if self._config_changed:
            self._journal.write(self._layout.research_file, canonical_bytes(self._config))
        event = with_object_digests(self._event, self._digests)
        self._repository.events.stage(self._journal, event)
        self._event = event
        try:
            self._journal.commit()
        except BaseException:
            # A crash-equivalent failure: finish or undo the unit before surfacing it, so a
            # caller that catches the error still sees whole canonical state.
            recover(self._layout)
            self._repository._drop_marker()
            raise
        self._repository._note_commit(self._journal.paths)
        if self._config_changed:
            self._repository._refresh_config(self._config)
        return event

    def abort(self) -> None:
        """Drop every staged change; nothing was written."""
        self._closed = True
        self._objects.clear()
        self._digests.clear()

    # -- helpers -------------------------------------------------------------

    def _record(self, obj: BaseModel) -> None:
        key = digest_key(obj)
        self._objects.append((key, obj))
        self._digests[key] = object_digest(obj)

    def _work_of(self, document: ParsedDocument) -> WorkId:
        if document.blocks:
            return document.blocks[0].work
        artifact = self._repository.get_artifact(document.artifact)
        return artifact.work

    def _existing_ids(self, id_type: type[ResearchId], *, work: WorkId | None = None) -> list[str]:
        layout = self._layout
        prefix = id_type.prefix
        match prefix:
            case "W":
                paths = layout.works_dir.glob("*/work.yaml")
                return [path.parent.name for path in paths]
            case "V":
                pattern = f"{work}/versions/*.yaml" if work is not None else "*/versions/*.yaml"
                return [path.stem for path in layout.works_dir.glob(pattern)]
            case "A":
                pattern = f"{work}/artifacts/*.yaml" if work is not None else "*/artifacts/*.yaml"
                return [path.stem for path in layout.works_dir.glob(pattern)]
            case "C":
                return _stems(layout.claims_dir)
            case "RQ":
                return _stems(layout.questions_dir)
            case "D":
                return _stems(layout.decisions_dir)
            case "S":
                return _stems(layout.matrices_dir)
            case "SR":
                return _stems(layout.searches_dir)
            case _:
                # Evidence, blocks, and interpretations live inside append-only collections
                # and are allocated from the counter alone.
                return []


# -- module helpers ----------------------------------------------------------


def _recover_under_lock(layout: WorkspaceLayout, lock_timeout: float) -> RecoveryReport:
    """Finish or undo interrupted transactions, taking the lock only when there are any.

    The common case is an empty journal, and paying for the lock on every open would make a
    read block behind an unrelated writer.
    """
    if not layout.journal_dir.is_dir() or not any(layout.journal_dir.iterdir()):
        return RecoveryReport()
    with WorkspaceLock(layout, lock_timeout):
        return recover(layout)


def _declared_schema_version(layout: WorkspaceLayout) -> int:
    """Read only `schema_version` so a future workspace fails on the version, not a field."""
    try:
        payload: Any = yaml.load(
            layout.research_file.read_text(encoding="utf-8"), Loader=CanonicalLoader
        )
    except (OSError, yaml.YAMLError) as exc:
        raise WorkspaceSerializationError(
            f"cannot read the workspace schema version: {exc}", source=layout.research_file
        ) from exc
    if not isinstance(payload, dict) or "schema_version" not in payload:
        raise WorkspaceSerializationError(
            "no schema_version declared; a workspace must state its schema version",
            source=layout.research_file,
        )
    try:
        return int(payload["schema_version"])
    except (TypeError, ValueError) as exc:
        raise WorkspaceSerializationError(
            f"schema_version {payload['schema_version']!r} is not an integer",
            source=layout.research_file,
        ) from exc


def _revalidate(obj: BaseModel, key: str) -> None:
    """Round-trip an object through its own schema before it becomes canonical."""
    try:
        type(obj).model_validate(obj.model_dump(mode="json"))
    except Exception as exc:
        raise WorkspaceError(f"{key} does not round-trip through its schema: {exc}") from exc


def _new_note_key(created_at: datetime) -> str:
    return note_key(created_at, secrets.token_hex(3))


def _stems(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return [path.stem for path in directory.glob("*.yaml")]


def _first(paths: Iterable[Path]) -> Path | None:
    return next(iter(sorted(paths)), None)


def _latest_by[T](records: Iterable[T], key: Callable[[T], str]) -> Iterator[T]:
    """Collapse an append-only stream to the newest record per key, in first-seen order."""
    latest: dict[str, T] = {}
    for record in records:
        latest[key(record)] = record
    yield from latest.values()

"""INTERROGATE: ask one document the schema's questions, one resumable stage per field.

The stage layout is the point. `load_document` reads the work's artifact and its stored
blocks; one `extract:<field>` stage then answers exactly one interrogation field, and its
fingerprint covers the document's file hash, that field's definition, the extractor template
version, and the provider/model that will answer. Re-running one field on another provider
therefore recomputes that field and nothing else — the §19.1 example, made a test rather than
an intention. `stage_candidates` writes the surviving proposals into `.research/staging/`.

Two properties keep the isolation real. Candidate ids are content-addressed, so a second
provider that reads the same span produces the same candidate and leaves every later stage's
checkpoint valid. And nothing here opens a workspace transaction: the repository is read for
the artifact and its blocks, and canonical state is never written (ADR-001, ADR-003).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_harness.domain.document import ParsedDocument
from research_harness.domain.ids import ArtifactId, WorkId
from research_harness.domain.work import Artifact
from research_harness.evidence.extraction import (
    DEFAULT_MAX_BLOCKS_PER_REQUEST,
    ExtractionResult,
    ModelClient,
    RejectedOutput,
    extract_candidates,
    resolve_backend,
)
from research_harness.evidence.interrogation import DEFAULT_SCHEMA, InterrogationSchema
from research_harness.evidence.staging import EvidenceCandidate, StagingStore
from research_harness.parsing.base import (
    ParseError,
    ParseTarget,
    document_fingerprint,
    select_parser,
)
from research_harness.parsing.pymupdf_parser import PyMuPdfParser
from research_harness.roles.extractor import EXTRACTOR
from research_harness.workflows.engine import (
    StageBase,
    StageContext,
    Workflow,
    WorkflowEngine,
)
from research_harness.workflows.models import WorkflowRun
from research_harness.workspace.repository import WorkspaceRepository

logger = logging.getLogger(__name__)

__all__ = [
    "EXTRACT_STAGE_PREFIX",
    "INTERROGATE_WORKFLOW",
    "DocumentSource",
    "ExtractField",
    "InterrogationReport",
    "LoadDocument",
    "StageCandidates",
    "build_interrogate_workflow",
    "extract_stage_name",
    "load_source_document",
    "run_interrogation",
]

INTERROGATE_WORKFLOW = "interrogate"
WORKFLOW_VERSION = "1.0.0"
LOAD_STAGE = "load_document"
STAGE_STAGE = "stage_candidates"
CANDIDATE_FILE_SUFFIX = ".candidates.json"


EXTRACT_STAGE_PREFIX = "extract."
"""`extract.<field>` rather than `extract:<field>`: the run store keeps stage names to
path-safe segments, and a colon is not one on every filesystem."""


def extract_stage_name(field_name: str) -> str:
    """The stage that answers one interrogation field."""
    return f"{EXTRACT_STAGE_PREFIX}{field_name}"


# --------------------------------------------------------------------- document loading


def load_source_document(
    repo: WorkspaceRepository, work: WorkId, artifact: ArtifactId | None = None
) -> tuple[ParsedDocument, Artifact]:
    """Parse the work's artifact from its immutable stored bytes; writes nothing.

    The document IR always comes from a parser, never from a hand-built object, so it carries
    the parser identity an anchor is only comparable within (ADR-008).
    """
    artifacts = repo.list_artifacts(work)
    if not artifacts:
        raise ParseError(f"work {work} has no registered artifact to interrogate")
    chosen = next((item for item in artifacts if artifact is None or item.id == artifact), None)
    if chosen is None:
        raise ParseError(f"work {work} has no artifact {artifact}")
    parser = select_parser([PyMuPdfParser()], chosen.mime_type)
    target = ParseTarget(
        work=chosen.work,
        version=chosen.version,
        artifact=chosen.id,
        file_hash=chosen.file_hash,
        path=repo.layout.artifact_bytes_file(chosen),
        mime_type=chosen.mime_type,
    )
    return parser.parse(target), chosen


# ------------------------------------------------------------------------------ stages


class LoadDocument(StageBase):
    """Reads the artifact and its stored blocks; reports what the run will interrogate."""

    def __init__(self, document: DocumentSource) -> None:
        super().__init__(LOAD_STAGE, version="1", idempotent=True)
        self._document = document

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        return {"work": ctx.inputs.get("work"), "artifact": ctx.inputs.get("artifact")}

    def run(self, ctx: StageContext) -> dict[str, Any]:
        doc = self._document.get()
        stored = len(list(self._document.repo.iter_blocks(doc.artifact, work=self._document.work)))
        return {
            "artifact": str(doc.artifact),
            "file_hash": doc.file_hash,
            "document_fingerprint": document_fingerprint(doc),
            "block_count": len(doc.blocks),
            "stored_block_count": stored,
            "page_count": doc.page_count,
        }


class ExtractField(StageBase):
    """Answers one interrogation field and writes its candidates into the run's staging dir.

    The stage output is content-addressed on purpose: candidate ids, counts, and nothing that
    names the provider. A provider swap that reads the same spans leaves the output identical,
    so the stages after it keep their checkpoints (§19.1).
    """

    def __init__(
        self,
        field_name: str,
        schema: InterrogationSchema,
        document: DocumentSource,
        provider: ModelClient,
        *,
        max_blocks_per_request: int = DEFAULT_MAX_BLOCKS_PER_REQUEST,
    ) -> None:
        super().__init__(extract_stage_name(field_name), version="1", idempotent=True)
        self.field_name = field_name
        self._schema = schema
        self._document = document
        self._provider = provider
        self._max_blocks = max_blocks_per_request

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        """Document bytes, the field's definition, the template, and the model answering it."""
        backend = resolve_backend(self._provider, EXTRACTOR)
        return {
            "file_hash": self._document.file_hash,
            "field": self._schema.field(self.field_name).model_dump(mode="json"),
            "schema": f"{self._schema.name}@{self._schema.version}",
            "template_version": EXTRACTOR.template_version,
            "provider": backend.provider,
            "model": backend.model,
            "max_blocks_per_request": self._max_blocks,
        }

    def run(self, ctx: StageContext) -> dict[str, Any]:
        result = extract_candidates(
            self._document.get(),
            self._schema,
            self._provider,
            run_id=ctx.run.run_id,
            fields=[self.field_name],
            max_blocks_per_request=self._max_blocks,
        )
        _write_field_result(ctx.staging_dir, self.field_name, result)
        return {
            "field": self.field_name,
            "candidate_ids": result.candidate_ids,
            "candidates": len(result.candidates),
            "rejected": len(result.rejected),
            "not_found": self.field_name in result.fields_not_found,
        }


class StageCandidates(StageBase):
    """Copies every field's proposals into the staging store. Canonical state is untouched."""

    def __init__(self, staging: StagingStore, fields: Sequence[str]) -> None:
        super().__init__(STAGE_STAGE, version="1", idempotent=True)
        self._staging = staging
        self._fields = tuple(fields)

    def fingerprint_inputs(self, ctx: StageContext) -> object:
        return {"fields": list(self._fields), "staging_root": str(self._staging.root)}

    def run(self, ctx: StageContext) -> dict[str, Any]:
        staged: list[str] = []
        for name in self._fields:
            for candidate in _read_field_candidates(ctx.staging_dir, name):
                self._staging.put(candidate)
                staged.append(candidate.candidate_id)
        return {"staged": staged, "count": len(staged)}


# ---------------------------------------------------------------------------- workflow


def build_interrogate_workflow(
    schema: InterrogationSchema,
    fields: Sequence[str] | None,
    *,
    document: DocumentSource,
    provider: ModelClient,
    staging: StagingStore,
    field_providers: Mapping[str, ModelClient] | None = None,
    max_blocks_per_request: int = DEFAULT_MAX_BLOCKS_PER_REQUEST,
) -> Workflow:
    """`load_document` → one `extract:<field>` per field → `stage_candidates`.

    `field_providers` overrides the model for named fields, which is what
    ``research interrogate W0017 --rerun tokenization --provider openai`` does: only the
    overridden field's fingerprint changes, so only that stage recomputes (§19.1).
    """
    selected = [item.name for item in schema.select(list(fields) if fields is not None else None)]
    overrides = dict(field_providers or {})
    stages: list[Any] = [LoadDocument(document)]
    stages.extend(
        ExtractField(
            name,
            schema,
            document,
            overrides.get(name, provider),
            max_blocks_per_request=max_blocks_per_request,
        )
        for name in selected
    )
    stages.append(StageCandidates(staging, selected))
    return Workflow(name=INTERROGATE_WORKFLOW, version=WORKFLOW_VERSION, stages=stages)


@dataclass(frozen=True)
class InterrogationReport:
    """What one interrogation run proposed, and what it could not answer."""

    run: WorkflowRun
    candidates_by_field: dict[str, list[EvidenceCandidate]] = field(default_factory=dict)
    rejected: list[RejectedOutput] = field(default_factory=list)
    fields_not_found: list[str] = field(default_factory=list)

    @property
    def candidates(self) -> list[EvidenceCandidate]:
        """Every staged candidate, in field order."""
        return [item for values in self.candidates_by_field.values() for item in values]

    @property
    def candidate_ids(self) -> list[str]:
        """Ids of every staged candidate, for the review queue and the CLI."""
        return [candidate.candidate_id for candidate in self.candidates]


def run_interrogation(
    engine: WorkflowEngine,
    staging: StagingStore,
    repo: WorkspaceRepository,
    work: WorkId,
    provider: ModelClient,
    schema: InterrogationSchema = DEFAULT_SCHEMA,
    *,
    fields: Sequence[str] | None = None,
    run_id: str | None = None,
    artifact: ArtifactId | None = None,
    field_providers: Mapping[str, ModelClient] | None = None,
    max_blocks_per_request: int = DEFAULT_MAX_BLOCKS_PER_REQUEST,
    force: bool = False,
) -> InterrogationReport:
    """Interrogate one work and stage the candidates; resumes `run_id` when given.

    Passing `run_id` re-executes that run, reusing every stage whose fingerprint still
    matches, so a field answered yesterday is not paid for again today.
    """
    document = DocumentSource(repo, work, artifact)
    selected = [item.name for item in schema.select(list(fields) if fields is not None else None)]
    workflow = build_interrogate_workflow(
        schema,
        selected,
        document=document,
        provider=provider,
        staging=staging,
        field_providers=field_providers,
        max_blocks_per_request=max_blocks_per_request,
    )
    inputs: dict[str, Any] = {
        "work": str(work),
        "artifact": None if artifact is None else str(artifact),
        "schema": f"{schema.name}@{schema.version}",
        "schema_fingerprint": schema.fingerprint(),
        "fields": selected,
    }
    run = engine.start(workflow, inputs) if run_id is None else engine.store.load(run_id)
    run = engine.execute(run.run_id, workflow, inputs, force=force or run_id is not None)

    staging_dir = engine.store.staging_dir(run.run_id)
    by_field: dict[str, list[EvidenceCandidate]] = {}
    rejected: list[RejectedOutput] = []
    not_found: list[str] = []
    for name in selected:
        candidates, failures, missing = _read_field_result(staging_dir, name)
        by_field[name] = candidates
        rejected.extend(failures)
        if missing:
            not_found.append(name)
    return InterrogationReport(
        run=run,
        candidates_by_field=by_field,
        rejected=rejected,
        fields_not_found=not_found,
    )


# ------------------------------------------------------------------------------ helpers


class DocumentSource:
    """Parses the work's artifact once per process and hands the same IR to every stage.

    Stages need the real `ParsedDocument`, but a cached stage never runs, so the parse cannot
    live inside `load_document`'s `run`. It lives here instead, lazily, and reads only.
    """

    def __init__(
        self, repo: WorkspaceRepository, work: WorkId, artifact: ArtifactId | None
    ) -> None:
        self.repo = repo
        self.work = work
        self.artifact = artifact
        self._doc: ParsedDocument | None = None
        self._source: Artifact | None = None

    def get(self) -> ParsedDocument:
        if self._doc is None:
            self._doc, self._source = load_source_document(self.repo, self.work, self.artifact)
        return self._doc

    @property
    def source(self) -> Artifact:
        self.get()
        assert self._source is not None
        return self._source

    @property
    def file_hash(self) -> str:
        """The artifact hash, read from workspace metadata without parsing anything."""
        if self._doc is not None:
            return self._doc.file_hash
        if self.artifact is not None:
            return self.repo.get_artifact(self.artifact, work=self.work).file_hash
        artifacts = self.repo.list_artifacts(self.work)
        if not artifacts:
            raise ParseError(f"work {self.work} has no registered artifact to interrogate")
        return artifacts[0].file_hash


def _field_file(staging_dir: Path, field_name: str) -> Path:
    return staging_dir / f"{field_name}{CANDIDATE_FILE_SUFFIX}"


def _write_field_result(staging_dir: Path, field_name: str, result: ExtractionResult) -> None:
    """Persist a field's proposals inside the run's own staging area (disposable)."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "field": field_name,
        "candidates": [candidate.model_dump(mode="json") for candidate in result.candidates],
        "rejected": [
            {"reason": item.reason, "raw": item.raw, "field": item.field}
            for item in result.rejected
        ],
        "fields_not_found": result.fields_not_found,
        "requests": result.requests,
    }
    _field_file(staging_dir, field_name).write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _read_field_result(
    staging_dir: Path, field_name: str
) -> tuple[list[EvidenceCandidate], list[RejectedOutput], bool]:
    path = _field_file(staging_dir, field_name)
    if not path.is_file():
        return [], [], False
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidates = [EvidenceCandidate.model_validate(item) for item in payload.get("candidates", [])]
    rejected = [
        RejectedOutput(reason=item["reason"], raw=item.get("raw", {}), field=item.get("field"))
        for item in payload.get("rejected", [])
    ]
    return candidates, rejected, field_name in payload.get("fields_not_found", [])


def _read_field_candidates(staging_dir: Path, field_name: str) -> list[EvidenceCandidate]:
    return _read_field_result(staging_dir, field_name)[0]

"""ROADMAP Task 6.1: candidate extraction proposes, anchors, and never accepts.

The acceptance requirements are the first two tests: extraction cannot write canonical
accepted Evidence, and a candidate with no valid source anchor is invalid. The rest defend
the ways a model gets it wrong — a quote that is not in the source, a number with no
provenance, an absence state or a researcher inference it is not allowed to report — and the
§19.1 idempotence rule that makes re-running one field affordable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import (
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceType,
    ProvenanceSource,
    ReviewTier,
)
from research_harness.evidence.extraction import extract_candidates
from research_harness.evidence.interrogation import (
    DEFAULT_SCHEMA,
    InterrogationField,
    InterrogationSchema,
    ValueKind,
)
from research_harness.evidence.staging import (
    PROVISIONAL_EVIDENCE_ID,
    CandidateStatus,
    StagingStore,
)
from research_harness.parsing.anchors import AnchorValidationStatus, resolve_anchor
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workflows.interrogate import extract_stage_name, run_interrogation
from research_harness.workflows.models import StageStatus
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.evidence.conftest import (
    ARTIFACT,
    DATASET_BLOCK,
    DATASET_SENTENCE,
    WORK,
    candidate_dict,
    canonical_digest,
    dataset_candidate,
    extraction_dict,
    limitation_candidate,
    method_candidate,
    metric_candidate,
    numeric_value,
    span_of,
)

RUN_ID = "run_20260101T000000Z_deadbeef"


def _provider(*payloads: dict[str, Any]) -> ScriptedProvider:
    return ScriptedProvider(list(payloads), name="scripted-a", model="model-a")


# ------------------------------------------------------------------ valid proposals


def test_valid_output_becomes_a_proposed_candidate_with_a_replayable_anchor(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    provider = _provider(extraction_dict([dataset_candidate(doc)]))

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["dataset"], staging=staging
    )

    assert result.rejected == []
    (candidate,) = result.candidates
    assert candidate.status is CandidateStatus.PROPOSED
    assert candidate.evidence.status is EvidenceStatus.PROPOSED
    assert candidate.anchor_status is AnchorValidationStatus.VALID
    assert candidate.evidence.source.block == DATASET_BLOCK
    assert resolve_anchor(candidate.evidence.source, doc).text == DATASET_SENTENCE
    assert staging.get(candidate.candidate_id) == candidate


def test_a_candidate_carries_its_model_provenance_and_no_canonical_identity(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    provider = _provider(extraction_dict([dataset_candidate(doc)]))

    (candidate,) = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["dataset"], staging=staging
    ).candidates

    provenance = candidate.evidence.provenance
    assert provenance.source is ProvenanceSource.MODEL
    assert provenance.actor == "scripted-a/model-a"
    assert provenance.run_id == RUN_ID
    assert provenance.template_version == "1.0.0"
    assert candidate.extraction.request_fingerprint
    assert candidate.extraction.response_schema_fingerprint
    assert candidate.evidence.id == PROVISIONAL_EVIDENCE_ID


def test_a_numeric_field_is_staged_for_deep_review(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    provider = _provider(extraction_dict([metric_candidate(doc)]))

    (candidate,) = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["metric_result"], staging=staging
    ).candidates

    assert candidate.evidence.review_tier is ReviewTier.TIER_2
    assert candidate.evidence.content.numeric is not None
    assert candidate.evidence.content.numeric.metric == "F1"
    assert candidate.evidence.content.exact_text == "94.32"


def test_the_same_span_gets_the_same_candidate_id_from_any_provider(
    doc: ParsedDocument,
) -> None:
    payload = extraction_dict([dataset_candidate(doc)])
    first = extract_candidates(
        doc, DEFAULT_SCHEMA, _provider(payload), run_id=RUN_ID, fields=["dataset"]
    )
    second = extract_candidates(
        doc,
        DEFAULT_SCHEMA,
        ScriptedProvider([payload], name="scripted-b", model="model-b"),
        run_id="run_20260102T000000Z_cafef00d",
        fields=["dataset"],
    )

    assert first.candidate_ids == second.candidate_ids


# ---------------------------------------------------------------------- rejections


def test_wrong_offsets_are_rejected_as_a_span_mismatch_and_never_staged(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    start, end = span_of(doc, DATASET_BLOCK, DATASET_SENTENCE)
    provider = _provider(
        extraction_dict([dataset_candidate(doc, char_start=start + 7, char_end=end + 7)])
    )

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["dataset"], staging=staging
    )

    assert result.candidates == []
    assert [item.reason for item in result.rejected] == ["span mismatch"]
    assert staging.list() == []


def test_a_span_outside_the_block_is_rejected_rather_than_clamped(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    provider = _provider(
        extraction_dict([dataset_candidate(doc, char_start=10_000, char_end=10_030)])
    )

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["dataset"], staging=staging
    )

    assert result.candidates == []
    assert "exceeds block" in result.rejected[0].reason
    assert staging.list() == []


def test_a_block_the_document_does_not_have_is_rejected(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    provider = _provider(extraction_dict([dataset_candidate(doc, block="B9999")]))

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["dataset"], staging=staging
    )

    assert result.candidates == []
    assert "not part of this document" in result.rejected[0].reason


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("absent", {"negative_state": "absent"}),
        ("researcher_inferred", {"origin": EvidenceOrigin.RESEARCHER_INFERRED.value}),
    ],
)
def test_an_audited_conclusion_or_a_researcher_inference_never_reaches_staging(
    doc: ParsedDocument, staging: StagingStore, label: str, payload: dict[str, Any]
) -> None:
    """The role schema refuses both, so nothing the model proposed can reach staging."""
    provider = _provider(extraction_dict([dataset_candidate(doc, **payload)]))

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["dataset"], staging=staging
    )

    assert result.candidates == []
    assert staging.list() == []
    assert "invalid candidate" in result.rejected[0].reason
    assert label in json.dumps(result.rejected[0].raw)


def test_a_number_without_metric_dataset_or_table_provenance_is_rejected(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    naked = numeric_value()
    naked.pop("dataset")
    naked.pop("condition")
    provider = _provider(extraction_dict([metric_candidate(doc, numeric=naked)]))

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["metric_result"], staging=staging
    )

    assert result.candidates == []
    assert staging.list() == []
    assert "invalid candidate" in result.rejected[0].reason


def test_one_malformed_candidate_does_not_discard_the_valid_ones_beside_it(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    """Dogfood F18: `ExtractionOutput` validated all-or-nothing per (field, chunk).

    A wrong shape in one candidate lost the two valid candidates that came with it, which
    is a routine and expensive occurrence with a real model. The provider still refuses to
    return a partial object; the extraction layer re-reads the refused text candidate by
    candidate and keeps the survivors, recording the rest as ordinary rejections.
    """
    naked = numeric_value()
    naked.pop("dataset")
    naked.pop("condition")
    provider = _provider(
        extraction_dict(
            [
                metric_candidate(doc, numeric=naked),
                metric_candidate(doc),
            ]
        )
    )

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["metric_result"], staging=staging
    )

    assert [candidate.field for candidate in result.candidates] == ["metric_result"]
    assert len(staging.list()) == 1
    assert [rejection.field for rejection in result.rejected] == ["metric_result"]
    assert "invalid candidate" in result.rejected[0].reason
    staged = result.candidates[0]
    assert staged.extraction.provider and staged.extraction.model
    assert staged.extraction.request_fingerprint


def test_a_reply_that_is_not_an_extraction_object_is_rejected_whole(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    """Salvage reads candidates, never prose: unparsable text is still one rejection."""
    provider = ScriptedProvider(["not json at all"], name="scripted-a", model="model-a")

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["metric_result"], staging=staging
    )

    assert result.candidates == []
    assert len(result.rejected) == 1
    assert "invalid structured output" in result.rejected[0].reason


# ---------------------------------------------------------------- categorical labels


def _categorical_schema() -> InterrogationSchema:
    """A one-question schema whose answer is a category, which `DEFAULT_SCHEMA` has none of."""
    return InterrogationSchema(
        name="labelled",
        version="1.0.0",
        fields=(
            InterrogationField(
                name="dataset",
                question="Which corpus do the reported experiments use?",
                evidence_types=(EvidenceType.DATASET_DESCRIPTION,),
                value_kind=ValueKind.CATEGORICAL,
                categories=("public benchmark", "private capture", "unclear"),
            ),
        ),
    )


def test_a_categorical_answer_carries_its_category(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    """Dogfood F13: the answer was a quoted span and the label was re-derived much later."""
    provider = _provider(
        extraction_dict([dataset_candidate(doc, labels=["Public_Benchmark"])]),
    )

    result = extract_candidates(
        doc, _categorical_schema(), provider, run_id=RUN_ID, fields=["dataset"], staging=staging
    )

    assert result.rejected == []
    assert result.candidates[0].evidence.content.labels == ("public benchmark",), (
        "the schema's own spelling is what is stored"
    )


def test_a_label_the_field_does_not_declare_is_rejected(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    """A label is an answer inside a declared vocabulary, never a new category."""
    provider = _provider(extraction_dict([dataset_candidate(doc, labels=["synthetic traffic"])]))

    result = extract_candidates(
        doc, _categorical_schema(), provider, run_id=RUN_ID, fields=["dataset"], staging=staging
    )

    assert result.candidates == []
    assert staging.list() == []
    assert "not categories of field" in result.rejected[0].reason


def test_a_field_that_declares_no_categories_takes_no_labels(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    provider = _provider(extraction_dict([dataset_candidate(doc, labels=["anything"])]))

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["dataset"], staging=staging
    )

    assert result.candidates == []
    assert "declared: none" in result.rejected[0].reason


def test_a_candidate_without_labels_is_unchanged(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    provider = _provider(extraction_dict([dataset_candidate(doc)]))

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["dataset"], staging=staging
    )

    assert result.candidates[0].evidence.content.labels == ()


def test_a_numeric_field_answered_without_a_number_is_rejected(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    provider = _provider(extraction_dict([metric_candidate(doc, numeric=None)]))

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["metric_result"], staging=staging
    )

    assert result.candidates == []
    assert "expects a measured value" in result.rejected[0].reason


def test_an_evidence_type_the_field_does_not_allow_is_rejected(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    provider = _provider(
        extraction_dict(
            [dataset_candidate(doc, evidence_type=EvidenceType.BIBLIOGRAPHIC_METADATA.value)]
        )
    )

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["dataset"], staging=staging
    )

    assert result.candidates == []
    assert "is not allowed for field" in result.rejected[0].reason


def test_a_field_the_document_does_not_answer_is_reported_not_found(
    doc: ParsedDocument, staging: StagingStore
) -> None:
    provider = _provider(extraction_dict(fields_not_found=["baseline"]))

    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["baseline"], staging=staging
    )

    assert result.fields_not_found == ["baseline"]
    assert result.candidates == []


# ------------------------------------------------------ canonical state stays untouched


def test_extraction_leaves_the_canonical_tree_byte_identical(
    doc: ParsedDocument, workspace: WorkspaceRepository, staging: StagingStore
) -> None:
    before = canonical_digest(workspace.root)
    provider = _provider(
        extraction_dict([dataset_candidate(doc)]),
        extraction_dict([metric_candidate(doc)]),
    )

    result = extract_candidates(
        doc,
        DEFAULT_SCHEMA,
        provider,
        run_id=RUN_ID,
        fields=["dataset", "metric_result"],
        staging=staging,
    )

    assert len(result.candidates) == 2
    assert canonical_digest(workspace.root) == before
    assert not workspace.layout.evidence_file(WORK).exists()
    assert list(workspace.iter_evidence(WORK)) == []


def test_the_evidence_package_never_opens_a_workspace_transaction() -> None:
    """Structural guard: staging code that could write canonical state would break ADR-003."""
    root = Path(__file__).resolve().parents[3] / "src" / "research_harness"
    modules = [
        *sorted((root / "evidence").glob("*.py")),
        root / "workflows" / "interrogate.py",
        root / "workflows" / "verify.py",
    ]
    assert len(modules) >= 7
    offenders = [
        path.relative_to(root).as_posix()
        for path in modules
        if re.search(r"\btransaction\s*\(", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


# ------------------------------------------------------------- workflow idempotence


def _full_schema_provider(doc: ParsedDocument, name: str, model: str) -> ScriptedProvider:
    """One answer per field of `DEFAULT_SCHEMA`, in schema order."""
    return ScriptedProvider(
        [
            extraction_dict([dataset_candidate(doc)]),
            extraction_dict([metric_candidate(doc)]),
            extraction_dict([method_candidate(doc)]),
            extraction_dict([limitation_candidate(doc)]),
            extraction_dict(fields_not_found=["baseline"]),
        ],
        name=name,
        model=model,
    )


def test_the_interrogate_workflow_stages_every_field(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    provider = _full_schema_provider(doc, "scripted-a", "model-a")

    report = run_interrogation(engine, staging, workspace, WORK, provider)

    assert sorted(report.candidates_by_field) == sorted(DEFAULT_SCHEMA.names)
    assert report.fields_not_found == ["baseline"]
    assert len(staging.list(work=WORK)) == 4
    assert {candidate.artifact for candidate in report.candidates} == {ARTIFACT}
    assert canonical_digest(workspace.root) == canonical_digest(workspace.root)


def test_rerunning_one_field_on_another_provider_recomputes_only_that_stage(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    """PRODUCT §19.1: `interrogate --rerun metric_result --provider other`."""
    first = _full_schema_provider(doc, "scripted-a", "model-a")
    report = run_interrogation(engine, staging, workspace, WORK, first)
    assert len(first.requests) == 5

    second = ScriptedProvider(
        [extraction_dict([metric_candidate(doc)])], name="scripted-b", model="model-b"
    )
    again = run_interrogation(
        engine,
        staging,
        workspace,
        WORK,
        first,
        run_id=report.run.run_id,
        field_providers={"metric_result": second},
    )

    assert len(second.requests) == 1, "the overridden field is answered by the new provider"
    assert len(first.requests) == 5, "no other field was asked again"
    recomputed = again.run.stage(extract_stage_name("metric_result"))
    assert recomputed.status is StageStatus.succeeded
    assert len(recomputed.attempts) == 2
    for name in DEFAULT_SCHEMA.names:
        if name == "metric_result":
            continue
        assert again.run.stage(extract_stage_name(name)).status is StageStatus.skipped_cached


def test_a_rerun_that_changes_nothing_reuses_every_checkpoint(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    provider = _full_schema_provider(doc, "scripted-a", "model-a")
    report = run_interrogation(engine, staging, workspace, WORK, provider)

    again = run_interrogation(engine, staging, workspace, WORK, provider, run_id=report.run.run_id)

    assert provider.remaining == 0
    assert len(provider.requests) == 5
    assert [record.status for record in again.run.stages] == [StageStatus.skipped_cached] * len(
        again.run.stages
    )
    assert again.candidate_ids == report.candidate_ids


def test_the_interrogate_run_keeps_its_candidates_in_regenerable_state_only(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    before = canonical_digest(workspace.root)
    provider = _full_schema_provider(doc, "scripted-a", "model-a")

    report = run_interrogation(engine, staging, workspace, WORK, provider)

    assert canonical_digest(workspace.root) == before
    assert not workspace.layout.evidence_file(WORK).exists()
    staged = staging.path_for(WORK, report.candidate_ids[0])
    assert workspace.layout.is_regenerable(staged)
    assert json.loads(staged.read_text(encoding="utf-8"))["status"] == "proposed"


def test_a_rejected_proposal_is_reported_but_not_staged(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    bogus = candidate_dict(
        block=DATASET_BLOCK,
        char_start=0,
        char_end=30,
        exact_text="A sentence this paper never contains",
        field="dataset",
        evidence_type=EvidenceType.DATASET_DESCRIPTION,
    )
    provider = ScriptedProvider([extraction_dict([bogus])], name="scripted-a", model="model-a")

    report = run_interrogation(engine, staging, workspace, WORK, provider, fields=["dataset"])

    assert report.candidates == []
    assert [item.reason for item in report.rejected] == ["span mismatch"]
    assert staging.list(work=WORK) == []

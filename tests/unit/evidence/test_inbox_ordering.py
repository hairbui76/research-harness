"""ROADMAP Task 6.3: the Review Inbox orders work the way Product §24.2 says it must.

Conflicts first, then high-risk scientific claims, then stale anchors, then ambiguous
extractions, then routine verified candidates — and inside a category the deeper review and
the older candidate come first. The candidates here are hand-built so each classification
rule is exercised in isolation, and every signal the inbox reads is a fact: a verdict, an
anchor status, a competing value, an accepted object, a recorded rejection.

The last test is the one that matters most: model confidence appears nowhere in the queue.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    NegativeEvidenceState,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    NumericValue,
    SourceAnchor,
    VerificationRecord,
)
from research_harness.domain.ids import ArtifactId, BlockId, EvidenceId, VersionId, WorkId
from research_harness.evidence.review import (
    CATEGORY_ORDER,
    ReviewCategory,
    build_inbox,
)
from research_harness.evidence.staging import (
    PROVISIONAL_EVIDENCE_ID,
    CandidateStatus,
    EvidenceCandidate,
    ExtractionProvenance,
    StagingStore,
    candidate_id_for,
)
from research_harness.parsing.anchors import AnchorValidationStatus
from research_harness.roles.schemas import VerificationOutput
from research_harness.workspace.rejections import RejectionRecord
from research_harness.workspace.repository import WorkspaceRepository

WORK = WorkId("W0001")
VERSION = VersionId("V0001-1")
ARTIFACT = ArtifactId("A0001-1")
FILE_HASH = f"sha256:{hashlib.sha256(b'artifact').hexdigest()}"
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def digest(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"


def anchor(block: str = "B0007", text: str = "the span") -> SourceAnchor:
    return SourceAnchor(
        work=WORK,
        version=VERSION,
        artifact=ARTIFACT,
        file_hash=FILE_HASH,
        block=BlockId(block),
        text_hash=digest(text),
        page=2,
        section_path=("3 Experiments",),
        char_start=0,
        char_end=len(text),
    )


def numeric() -> NumericValue:
    return NumericValue(
        raw="94.32",
        parsed=94.32,
        unit="percent",
        metric="F1",
        dataset="CICIDS2017",
        source_table="Table 1",
    )


def candidate(
    *,
    field: str = "dataset",
    text: str = "the span",
    block: str = "B0007",
    tier: ReviewTier = ReviewTier.TIER_1,
    verdict: VerificationVerdict | None = VerificationVerdict.SUPPORTED,
    origin: EvidenceOrigin = EvidenceOrigin.SOURCE_OBSERVED,
    value: NumericValue | None = None,
    negative_state: NegativeEvidenceState | None = None,
    anchor_status: AnchorValidationStatus = AnchorValidationStatus.VALID,
    minutes: int = 0,
    suffix: str = "",
) -> EvidenceCandidate:
    """One staged candidate; every argument is a signal the inbox is allowed to read."""
    source = anchor(block, text)
    status = EvidenceStatus.PROPOSED if verdict is None else EvidenceStatus.VERIFIED
    evidence = Evidence(
        id=PROVISIONAL_EVIDENCE_ID,
        source=source,
        content=EvidenceContent(
            exact_text=text, numeric=value, negative_state=negative_state, field=field
        ),
        origin=origin,
        evidence_type=EvidenceType.DATASET_DESCRIPTION,
        strength=EvidenceStrength.DIRECT,
        verification=VerificationRecord(
            status=status, verdict=verdict, extractor="vendor-a/model-x"
        ),
        review_tier=tier,
        provenance=Provenance.model("vendor-a/model-x"),
        created_at=EPOCH,
    )
    verification = (
        None
        if verdict is None
        else VerificationOutput(
            verdict=verdict, rationale="an independent reading", quoted_support=text
        )
    )
    return EvidenceCandidate(
        candidate_id=candidate_id_for(field, text, block, tier, suffix),
        work=WORK,
        artifact=ARTIFACT,
        field=field,
        evidence=evidence,
        extraction=ExtractionProvenance(
            run_id="run_1",
            provider="vendor-a",
            model="model-x",
            template_version="1.0.0",
            request_fingerprint=digest("request"),
            response_schema_fingerprint=digest("schema"),
        ),
        verification=verification,
        verifier=None if verdict is None else "vendor-b/model-y",
        anchor_status=anchor_status,
        status=CandidateStatus.PROPOSED if verdict is None else CandidateStatus.VERIFIED,
        created_at=EPOCH.replace(minute=minutes),
    )


@pytest.fixture
def repo(tmp_path: Path) -> WorkspaceRepository:
    """An empty workspace: the inbox reads canonical state, and there is none yet."""
    return WorkspaceRepository.init(tmp_path / "project", "inbox-ordering")


@pytest.fixture
def staging(repo: WorkspaceRepository) -> StagingStore:
    return StagingStore(repo.layout.research_dir)


def categories(items: Any) -> list[str]:
    return [item.category.value for item in items]


# -- the queue order ---------------------------------------------------------


def test_the_queue_is_ordered_conflict_high_risk_stale_ambiguous_routine(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    staging.put_all(
        [
            candidate(field="baseline", text="a routine span", block="B0001"),
            candidate(
                field="limitation",
                text="an ambiguous span",
                block="B0002",
                verdict=VerificationVerdict.PARTIALLY_SUPPORTED,
            ),
            candidate(
                field="venue",
                text="a stale span",
                block="B0003",
                anchor_status=AnchorValidationStatus.STALE,
            ),
            candidate(field="metric", text="94.32", block="B0004", value=numeric()),
            candidate(
                field="dataset",
                text="a contradicted span",
                block="B0005",
                verdict=VerificationVerdict.CONTRADICTED,
            ),
        ]
    )

    queue = build_inbox(staging, repo)

    assert categories(queue) == [category.value for category in CATEGORY_ORDER]
    assert [item.priority for item in queue] == [0, 1, 2, 3, 4]
    assert queue.counts == dict.fromkeys(CATEGORY_ORDER, 1)


def test_within_a_category_the_deeper_review_and_the_older_candidate_come_first(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    staging.put_all(
        [
            candidate(field="a", text="tier one late", block="B0001", minutes=30),
            candidate(field="b", text="tier one early", block="B0002", minutes=10),
            candidate(
                field="c",
                text="tier two",
                block="B0003",
                tier=ReviewTier.TIER_2,
                minutes=50,
            ),
        ]
    )

    queue = build_inbox(staging, repo)

    assert categories(queue) == ["high_risk", "routine", "routine"]
    assert [item.candidate.evidence.content.exact_text for item in queue] == [
        "tier two",
        "tier one early",
        "tier one late",
    ]


def test_an_empty_queue_reports_every_category_as_zero(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    queue = build_inbox(staging, repo)

    assert len(queue) == 0
    assert queue.next() is None
    assert queue.by_id("cand_0000000000000000") is None
    assert queue.counts == dict.fromkeys(CATEGORY_ORDER, 0)


def test_next_and_by_id_reach_the_item_a_reviewer_asked_for(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    routine = candidate(field="baseline", text="a routine span", block="B0001")
    conflict = candidate(
        field="dataset",
        text="a contradicted span",
        block="B0002",
        verdict=VerificationVerdict.CONTRADICTED,
    )
    staging.put_all([routine, conflict])

    queue = build_inbox(staging, repo)

    first = queue.next()
    assert first is not None and first.candidate_id == conflict.candidate_id
    found = queue.by_id(routine.candidate_id)
    assert found is not None and found.category is ReviewCategory.ROUTINE


# -- classification ----------------------------------------------------------


def test_a_contradicted_verdict_outranks_every_other_signal(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    """A conflicted Tier-2 numeric is a conflict, not a high-risk item: §24.2 order."""
    staging.put(
        candidate(
            field="metric",
            text="94.32",
            value=numeric(),
            tier=ReviewTier.TIER_2,
            verdict=VerificationVerdict.CONTRADICTED,
        )
    )

    (item,) = build_inbox(staging, repo).items

    assert item.category is ReviewCategory.CONFLICT
    assert item.reasons == ("the verifier contradicted this candidate",)


def test_competing_candidates_are_a_conflict_only_when_the_values_compete(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    """A single-valued field has one true answer, so two of them is a disagreement."""
    agreeing = [
        candidate(field="encryption_status", text="the same span", block="B0001", suffix="a"),
        candidate(field="encryption_status", text="the same span", block="B0001", suffix="b"),
    ]
    staging.put_all(agreeing)

    queue = build_inbox(staging, repo)
    assert categories(queue) == ["routine", "routine"]
    assert all(item.competing for item in queue)

    staging.put(candidate(field="encryption_status", text="a different span", block="B0002"))
    queue = build_inbox(staging, repo)

    assert categories(queue) == ["conflict", "conflict", "conflict"]
    assert all("propose a different value" in " ".join(item.reasons) for item in queue)


def test_several_answers_to_a_multi_valued_field_are_not_a_conflict(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    """Dogfood F7: two stated limitations of one paper are two answers, not two claims.

    The item keeps naming its peers - a researcher still wants to see them side by side -
    but it sits at the priority its own tier earns instead of at the top of the queue.
    """
    staging.put_all(
        [
            candidate(field="baselines", text="we compare against ET-BERT", block="B0001"),
            candidate(field="baselines", text="and against FS-Net", block="B0002"),
            candidate(field="baselines", text="and against a random forest", block="B0003"),
        ]
    )

    queue = build_inbox(staging, repo)

    assert categories(queue) == ["routine", "routine", "routine"]
    assert all(len(item.competing) == 2 for item in queue)
    reasons = " ".join(reason for item in queue for reason in item.reasons)
    assert "propose a different value" not in reasons
    assert "takes several values" in reasons


def test_a_number_or_an_absence_state_is_never_routine(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    staging.put_all(
        [
            candidate(field="metric", text="94.32", block="B0001", value=numeric()),
            candidate(
                field="threat_model",
                text="the paper does not report it",
                block="B0002",
                negative_state=NegativeEvidenceState.NOT_REPORTED,
            ),
        ]
    )

    queue = build_inbox(staging, repo)

    assert categories(queue) == ["high_risk", "high_risk"]
    reasons = " ".join(reason for item in queue for reason in item.reasons)
    assert "numeric evidence" in reasons
    assert "not_reported" in reasons


def test_an_unverified_candidate_is_ambiguous_rather_than_routine(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    staging.put(candidate(field="baseline", text="unchecked", verdict=None))

    (item,) = build_inbox(staging, repo).items

    assert item.category is ReviewCategory.AMBIGUOUS
    assert item.reasons == ("no independent verification result yet",)
    assert item.verdict is None


def test_an_interpretive_origin_is_high_risk_even_at_tier_one(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    staging.put(
        candidate(field="gap", text="the authors imply a gap", origin=EvidenceOrigin.MODEL_PROPOSED)
    )

    (item,) = build_inbox(staging, repo).items

    assert item.category is ReviewCategory.HIGH_RISK
    assert "is interpretive" in " ".join(item.reasons)


def test_a_reviewed_candidate_leaves_the_queue_but_stays_in_staging(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    from research_harness.domain.enums import ReviewAction

    staged = candidate(field="dataset", text="already answered")
    staging.put(staged)
    staging.mark_reviewed(staged.candidate_id, ReviewAction.REJECT)

    assert len(build_inbox(staging, repo)) == 0
    assert staging.get(staged.candidate_id).review_action is ReviewAction.REJECT


# -- rejections and accepted state -------------------------------------------


def test_a_previously_rejected_span_is_flagged_when_it_is_proposed_again(
    staging: StagingStore, repo: WorkspaceRepository, tmp_path: Path
) -> None:
    staged = candidate(field="dataset", text="the span")
    staging.put(staged)
    _append_rejection(
        repo,
        RejectionRecord(
            candidate_id="cand_ffffffffffffffff",
            anchor=staged.evidence.source,
            field="dataset",
            reason="the sentence names a corpus, not the evaluation set",
            actor="human:tester",
            rejected_at=EPOCH,
            origin=EvidenceOrigin.SOURCE_OBSERVED,
            evidence_type=EvidenceType.DATASET_DESCRIPTION,
        ),
    )

    (item,) = build_inbox(staging, repo).items

    assert item.previously_rejected is True
    assert "previously rejected" in " ".join(item.reasons)


def test_accepted_evidence_at_the_same_span_saying_something_else_is_a_conflict(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    staged = candidate(field="dataset", text="the span")
    staging.put(staged)
    _append_evidence(
        repo,
        staged.evidence.touch(
            id=EvidenceId("E0001"),
            content=EvidenceContent(exact_text="something else entirely", field="dataset"),
            verification=VerificationRecord(
                status=EvidenceStatus.ACCEPTED,
                verdict=VerificationVerdict.SUPPORTED,
                accepted_by="human:tester",
            ),
        ),
    )

    (item,) = build_inbox(staging, repo).items

    assert item.category is ReviewCategory.CONFLICT
    assert item.accepted_conflict == EvidenceId("E0001")


# -- the rule the whole model rests on ---------------------------------------


def test_model_confidence_appears_nowhere_in_the_queue(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    """Confidence is not scope (§5 P6) and never an acceptance signal (§24.4, §43)."""
    import json

    staging.put_all(
        [
            candidate(field="metric", text="94.32", block="B0001", value=numeric()),
            candidate(field="dataset", text="a span", block="B0002"),
        ]
    )

    rendered = json.dumps(build_inbox(staging, repo).as_dict(), default=str).lower()

    assert "confidence" not in rendered
    assert "probability" not in rendered
    assert "score" not in rendered


# -- helpers -----------------------------------------------------------------


def _append_rejection(repo: WorkspaceRepository, record: RejectionRecord) -> None:
    """Write a rejection the way the capability layer does, without a full mutation."""
    from research_harness.workspace.serialization import dump_jsonl_line

    path = repo.layout.rejections_path(record.work)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(dump_jsonl_line(record))


def _append_evidence(repo: WorkspaceRepository, evidence: Evidence) -> None:
    from research_harness.workspace.serialization import dump_jsonl_line

    path = repo.layout.evidence_file(evidence.source.work)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(dump_jsonl_line(evidence))


# -- the peer index answers exactly what scanning every peer answered ----------


def _reference_relations(
    candidates: list[EvidenceCandidate],
) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """The competing/disagreeing relations as the original O(n^2) peer scans computed them."""
    from research_harness.evidence.review import _value_key

    relations: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for candidate in candidates:
        competing = tuple(
            peer.candidate_id
            for peer in candidates
            if peer.candidate_id != candidate.candidate_id
            and peer.work == candidate.work
            and peer.field == candidate.field
        )
        disagreeing = tuple(
            peer.candidate_id
            for peer in candidates
            if peer.candidate_id in set(competing) and _value_key(peer) != _value_key(candidate)
        )
        relations[candidate.candidate_id] = (competing, disagreeing)
    return relations


def test_the_peer_index_reproduces_the_relations_a_full_peer_scan_found(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    """Bucketing by (work, field) must change speed and nothing else."""
    from research_harness.evidence.review import _PeerIndex

    candidates = [
        candidate(field=field, text=text, block=block, suffix=str(index))
        for index, (field, text, block) in enumerate(
            [
                ("dataset", "CICIDS2017", "B0001"),
                ("dataset", "CICIDS2017", "B0002"),
                ("dataset", "UNSW-NB15", "B0003"),
                ("metric", "F1", "B0004"),
                ("metric", "F1", "B0005"),
                ("metric", "AUROC", "B0006"),
                ("venue", "NDSS", "B0007"),
            ]
        )
    ]
    index = _PeerIndex.build(candidates)
    expected = _reference_relations(candidates)
    for position, item in enumerate(candidates):
        key = (str(item.work), item.field)
        assert index.relations(position, key) == expected[item.candidate_id]


def test_competing_and_disagreeing_survive_into_the_queue(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    """The item a researcher sees still names its peers, and only the ones that differ."""
    agreeing = candidate(field="method_summary", text="F1 of 94.32", block="B0001", suffix="a")
    same = candidate(field="method_summary", text="F1 of 94.32", block="B0002", suffix="b")
    differing = candidate(field="method_summary", text="F1 of 91.10", block="B0003", suffix="c")
    elsewhere = candidate(field="dataset", text="CICIDS2017", block="B0004", suffix="d")
    for item in (agreeing, same, differing, elsewhere):
        staging.put(item)

    queue = build_inbox(staging, repo)
    by_id = {item.candidate_id: item for item in queue}

    assert set(by_id[agreeing.candidate_id].competing) == {
        same.candidate_id,
        differing.candidate_id,
    }
    assert by_id[elsewhere.candidate_id].competing == ()
    reasons = " ".join(by_id[agreeing.candidate_id].reasons)
    assert "1 competing candidate(s) propose a different value" in reasons


def test_a_large_inbox_stays_linear_enough_to_open(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    """400 candidates over few fields is where the quadratic version spent minutes."""
    for index in range(400):
        staging.put(
            candidate(
                field=f"field{index % 4}",
                text=f"span {index % 7}",
                block=f"B{index:04d}",
                suffix=str(index),
            )
        )
    queue = build_inbox(staging, repo)
    assert len(queue) == 400

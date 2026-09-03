"""Dogfood F7: "conflict" must mean the two answers cannot both be right.

The 2026-09-03 session staged 39 candidates and the Review Inbox called 18 of them
conflicts. Two were real. The other sixteen fired for one reason: a field had been answered
more than once, and two stated limitations of the same paper, or three sentences naming
three datasets, were reported as `1 competing candidate(s) propose a different value`.
Conflict-first review is the promise of Product 25, and it was wrong 89% of the time.

So the property pinned here is what a conflict *is*
(:func:`research_harness.evidence.conflicts.values_conflict`): a contradicted verdict, an
absence claim against a positive value, two numbers measuring the same thing differently,
two readings of one span - and, on a single-valued field, two different answers. Additional
answers to a multi-valued field are not conflicts, and the item stays at the priority its
own tier earns.

The last two tests are the before/after: the same 39 hand-built candidates, in the field mix
the dogfood recorded, counted the way the queue used to count them and the way it counts
them now.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

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
from research_harness.domain.ids import ArtifactId, BlockId, VersionId, WorkId
from research_harness.evidence.conflicts import (
    inferred_field,
    is_multi_valued,
    values_conflict,
)
from research_harness.evidence.interrogation import (
    InterrogationField,
    InterrogationSchema,
    ValueKind,
)
from research_harness.evidence.review import ReviewCategory, build_inbox
from research_harness.evidence.staging import (
    PROVISIONAL_EVIDENCE_ID,
    CandidateStatus,
    EvidenceCandidate,
    ExtractionProvenance,
    StagingStore,
    candidate_id_for,
)
from research_harness.plugins.spi import InterrogationContribution, merge_interrogation
from research_harness.roles.schemas import VerificationOutput
from research_harness.workspace.repository import WorkspaceRepository

#: The interrogation contract the dogfood ran, reduced to the eight fields it actually
#: answered. The wording matters: `plugins/structured-traffic` declares a field multi-label
#: by asking for "every value that applies", which is the only declaration
#: `InterrogationField` can carry today.
TRAFFIC_SCHEMA = InterrogationSchema(
    name="structured-traffic:paper",
    version="1.0.0",
    fields=(
        InterrogationField(
            name="traffic.traffic_unit",
            question=(
                "Which unit of network traffic does the paper treat as one sample? List "
                "every value that applies and quote the sentence that states it."
            ),
            evidence_types=(EvidenceType.METHOD_DESCRIPTION,),
            value_kind=ValueKind.CATEGORICAL,
            categories=("packet", "flow", "session", "unclear"),
        ),
        InterrogationField(
            name="traffic.representation_family",
            question=(
                "Where does this paper's input representation sit in the project taxonomy? "
                "List every value that applies."
            ),
            evidence_types=(EvidenceType.REPRESENTATION_DESCRIPTION,),
            value_kind=ValueKind.CATEGORICAL,
            risk=ReviewTier.TIER_2,
            categories=("raw sequential", "field-based", "behavior-aware", "unclear"),
        ),
        InterrogationField(
            name="traffic.tokenization",
            question=(
                "How is the serialized traffic split into tokens? List every value that "
                "applies and quote the sentence that states it."
            ),
            evidence_types=(EvidenceType.METHOD_DESCRIPTION,),
            value_kind=ValueKind.CATEGORICAL,
            categories=("byte_level", "bpe", "wordpiece", "unclear"),
        ),
        InterrogationField(
            name="traffic.encryption_status",
            question=(
                "How much of the evaluated traffic is encrypted, and at which layer? Quote "
                "the sentence that states it."
            ),
            evidence_types=(EvidenceType.DATASET_DESCRIPTION,),
            value_kind=ValueKind.CATEGORICAL,
            risk=ReviewTier.TIER_2,
            categories=("plaintext", "encrypted", "mixed", "unclear"),
        ),
        InterrogationField(
            name="traffic.llm_role",
            question=(
                "What does the language model actually do in the pipeline? List every value "
                "that applies."
            ),
            evidence_types=(EvidenceType.METHOD_DESCRIPTION,),
            value_kind=ValueKind.CATEGORICAL,
            categories=("classifier", "feature_extractor", "generator", "unclear"),
        ),
        InterrogationField(
            name="traffic.dataset",
            question=(
                "Which traffic corpus do the reported experiments use, including its "
                "release or version? Quote the sentence that names it."
            ),
            evidence_types=(EvidenceType.DATASET_DESCRIPTION,),
            value_kind=ValueKind.TEXT,
        ),
        InterrogationField(
            name="traffic.metrics",
            question=(
                "Which measured value does the paper report for its own system on this "
                "corpus? Quote the exact value with its metric, unit, dataset, and table."
            ),
            evidence_types=(EvidenceType.EXPERIMENTAL_RESULT,),
            value_kind=ValueKind.NUMERIC,
            risk=ReviewTier.TIER_2,
        ),
        InterrogationField(
            name="traffic.author_stated_limitations",
            question=(
                "Which limitation, threat to validity, or scope restriction do the authors "
                "state themselves? Quote it verbatim."
            ),
            evidence_types=(EvidenceType.LIMITATION,),
            value_kind=ValueKind.TEXT,
            risk=ReviewTier.TIER_2,
        ),
    ),
)

#: The same contract with every "list every value that applies" removed and
#: `multi_label` declared instead. It is what `plugins/structured-traffic` now ships:
#: the prose is guidance for the model, the flag is the machine-readable declaration.
MUTE_SCHEMA = TRAFFIC_SCHEMA.model_copy(
    update={
        "fields": tuple(
            item.model_copy(
                update={
                    "question": f"What does this Work answer for {item.name}?",
                    "multi_label": item.name != "traffic.encryption_status",
                }
            )
            for item in TRAFFIC_SCHEMA.fields
        )
    }
)

_EVIDENCE_TYPES = {
    "traffic.traffic_unit": EvidenceType.METHOD_DESCRIPTION,
    "traffic.representation_family": EvidenceType.REPRESENTATION_DESCRIPTION,
    "traffic.tokenization": EvidenceType.METHOD_DESCRIPTION,
    "traffic.encryption_status": EvidenceType.DATASET_DESCRIPTION,
    "traffic.llm_role": EvidenceType.METHOD_DESCRIPTION,
    "traffic.dataset": EvidenceType.DATASET_DESCRIPTION,
    "traffic.metrics": EvidenceType.EXPERIMENTAL_RESULT,
    "traffic.author_stated_limitations": EvidenceType.LIMITATION,
}


def digest(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"


def candidate(
    work: str,
    field: str,
    text: str,
    *,
    block: str,
    numeric: NumericValue | None = None,
    negative_state: NegativeEvidenceState | None = None,
    verdict: VerificationVerdict | None = VerificationVerdict.SUPPORTED,
    origin: EvidenceOrigin = EvidenceOrigin.SOURCE_OBSERVED,
) -> EvidenceCandidate:
    """One staged answer to one field of one Work, anchored in its own block."""
    identity = WorkId(work)
    number = str(identity)[1:]
    evidence_type = _EVIDENCE_TYPES.get(field, EvidenceType.DATASET_DESCRIPTION)
    tier = TRAFFIC_SCHEMA.field(field).review_tier if field in TRAFFIC_SCHEMA.names else None
    anchor = SourceAnchor(
        work=identity,
        version=VersionId(f"V{number}-1"),
        artifact=ArtifactId(f"A{number}-1"),
        file_hash=digest(f"artifact-{work}"),
        block=BlockId(block),
        text_hash=digest(text),
        page=3,
        section_path=("4 Evaluation",),
        char_start=0,
        char_end=len(text),
    )
    status = EvidenceStatus.PROPOSED if verdict is None else EvidenceStatus.VERIFIED
    evidence = Evidence(
        id=PROVISIONAL_EVIDENCE_ID,
        source=anchor,
        content=EvidenceContent(
            exact_text=text, numeric=numeric, negative_state=negative_state, field=field
        ),
        origin=origin,
        evidence_type=evidence_type,
        strength=EvidenceStrength.DIRECT,
        verification=VerificationRecord(
            status=status, verdict=verdict, extractor="vendor-a/model-x"
        ),
        review_tier=tier if tier is not None else ReviewTier.TIER_1,
        provenance=Provenance.model("vendor-a/model-x"),
    )
    return EvidenceCandidate(
        candidate_id=candidate_id_for(work, field, block, text),
        work=identity,
        artifact=ArtifactId(f"A{number}-1"),
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
        verification=(
            None
            if verdict is None
            else VerificationOutput(
                verdict=verdict, rationale="an independent reading", quoted_support=text
            )
        ),
        verifier=None if verdict is None else "vendor-b/model-y",
        status=CandidateStatus.PROPOSED if verdict is None else CandidateStatus.VERIFIED,
    )


def f1(value: float, *, dataset: str = "CICIDS2017", metric: str = "F1") -> NumericValue:
    return NumericValue(
        raw=str(value),
        parsed=value,
        unit="percent",
        metric=metric,
        dataset=dataset,
        source_table="Table 3",
    )


@pytest.fixture
def repo(tmp_path: Path) -> WorkspaceRepository:
    return WorkspaceRepository.init(tmp_path / "project", "conflict-judgement")


@pytest.fixture
def staging(repo: WorkspaceRepository) -> StagingStore:
    return StagingStore(repo.layout.research_dir)


# -- what a conflict is ------------------------------------------------------


def test_two_answers_to_a_multi_valued_field_are_not_competing() -> None:
    field = TRAFFIC_SCHEMA.field("traffic.author_stated_limitations")
    first = candidate("W0001", field.name, "Generalizability is limited.", block="B0001")
    second = candidate("W0001", field.name, "The capture is from 2017.", block="B0002")

    judged = values_conflict(field, first, second)

    assert judged.conflict is False
    assert "several values" in judged.reason


def test_two_answers_to_a_single_valued_field_are_competing() -> None:
    field = TRAFFIC_SCHEMA.field("traffic.encryption_status")
    first = candidate("W0001", field.name, "All flows are TLS encrypted.", block="B0001")
    second = candidate("W0001", field.name, "The capture is plaintext HTTP.", block="B0002")

    judged = values_conflict(field, first, second)

    assert judged.conflict is True
    assert "one value" in judged.reason


def test_two_numbers_conflict_only_when_they_measure_the_same_thing() -> None:
    field = TRAFFIC_SCHEMA.field("traffic.metrics")
    same_measurement = (
        candidate("W0001", field.name, "94.32", block="B0001", numeric=f1(94.32)),
        candidate("W0001", field.name, "91.10", block="B0002", numeric=f1(91.10)),
    )
    other_measurement = candidate(
        "W0001", field.name, "88.40", block="B0003", numeric=f1(88.40, dataset="USTC-TFC2016")
    )

    disagreement = values_conflict(field, *same_measurement)
    assert disagreement.conflict is True
    assert "94.32" in disagreement.reason and "91.1" in disagreement.reason

    unrelated = values_conflict(field, same_measurement[0], other_measurement)
    assert unrelated.conflict is False
    assert "different measurements" in unrelated.reason


def test_an_absence_state_against_a_positive_value_is_always_a_conflict() -> None:
    """`not_reported` and a quoted answer cannot both be true, multi-valued or not."""
    field = TRAFFIC_SCHEMA.field("traffic.author_stated_limitations")
    assert is_multi_valued(field)
    stated = candidate("W0001", field.name, "The capture is from 2017.", block="B0001")
    absent = candidate(
        "W0001",
        field.name,
        "",
        block="B0002",
        negative_state=NegativeEvidenceState.NOT_REPORTED,
        verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
    )

    judged = values_conflict(field, stated, absent)

    assert judged.conflict is True
    assert "not_reported" in judged.reason


def test_a_contradicted_verdict_beside_a_supported_one_is_a_conflict() -> None:
    field = TRAFFIC_SCHEMA.field("traffic.dataset")
    supported = candidate("W0001", field.name, "We evaluate on CICIDS2017.", block="B0001")
    contradicted = candidate(
        "W0001",
        field.name,
        "The survey runs no experiments.",
        block="B0002",
        verdict=VerificationVerdict.CONTRADICTED,
    )

    judged = values_conflict(field, supported, contradicted)

    assert judged.conflict is True
    assert "contradicted" in judged.reason


def test_two_readings_of_one_span_conflict_whatever_the_field_takes() -> None:
    """F7's other half: overlapping spans with different values is a real disagreement."""
    field = TRAFFIC_SCHEMA.field("traffic.author_stated_limitations")
    first = candidate("W0001", field.name, "the model does not generalise", block="B0001")
    second = candidate("W0001", field.name, "the model generalises well", block="B0001")

    judged = values_conflict(field, first, second)

    assert judged.conflict is True
    assert "same span" in judged.reason


def test_answers_about_different_works_never_compete() -> None:
    field = TRAFFIC_SCHEMA.field("traffic.encryption_status")
    mine = candidate("W0001", field.name, "All flows are TLS encrypted.", block="B0001")
    theirs = candidate("W0002", field.name, "The capture is plaintext.", block="B0001")

    assert values_conflict(field, mine, theirs).conflict is False


def test_a_field_name_alone_carries_the_list_like_ones() -> None:
    """Without a schema the head noun is the only declaration left (`inferred_field`)."""
    plural = candidate("W0001", "traffic.baselines", "we compare against ET-BERT", block="B0001")
    singular = candidate("W0001", "traffic.dataset_age", "captured in 2016", block="B0002")
    status = candidate("W0001", "traffic.encryption_status", "TLS throughout", block="B0003")

    assert is_multi_valued(inferred_field(plural)) is True
    assert is_multi_valued(inferred_field(singular)) is False
    assert is_multi_valued(inferred_field(status)) is False


# -- the queue: six baselines are six answers --------------------------------


def test_six_baselines_for_one_work_are_zero_conflicts(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    """The example F7 names: a paper compared against six systems is not six disagreements."""
    systems = ("ET-BERT", "FS-Net", "DeepPacket", "AppScanner", "a random forest", "BERT-base")
    staging.put_all(
        [
            candidate("W0001", "traffic.baselines", f"we compare against {name}", block=f"B000{i}")
            for i, name in enumerate(systems, start=1)
        ]
    )

    queue = build_inbox(staging, repo)

    assert len(queue) == 6
    assert queue.by_category(ReviewCategory.CONFLICT) == ()
    assert all(len(item.competing) == 5 for item in queue)


# -- the dogfood session, counted both ways ----------------------------------


#: The interrogation questions `plugins/structured-traffic` ships, read from the file
#: itself. `merge_interrogation` is what the plugin loader calls, so the schema here is the
#: one a project loading that plugin gets; nothing is executed and no gateway is involved.
PLUGIN_INTERROGATION = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "structured-traffic"
    / "interrogation"
    / "paper.yaml"
)


def shipped_traffic_schema() -> InterrogationSchema:
    """`structured-traffic:paper` as the loader builds it, from the shipped YAML."""
    contribution = InterrogationContribution.model_validate(
        yaml.safe_load(PLUGIN_INTERROGATION.read_text(encoding="utf-8"))
    )
    return merge_interrogation("structured-traffic", contribution)


def dogfood_candidates() -> list[EvidenceCandidate]:
    """The 39 staged candidates of the 2026-09-03 session, in the field mix it recorded.

    Counts per field are the ones in `docs/plans/dogfood-2026-09-03.md` section 4: four
    `traffic_unit`, six `representation_family`, two `tokenization`, four
    `encryption_status`, one `llm_role`, nine `dataset`, five `metrics`, eight
    `author_stated_limitations`. Only W0001's two `metrics` answers are a real disagreement:
    the same metric on the same dataset, reported as two different numbers.
    """
    made: list[EvidenceCandidate] = []
    block = iter(f"B{index:04d}" for index in range(1, 200))

    def add(work: str, field: str, text: str, numeric: NumericValue | None = None) -> None:
        made.append(candidate(work, field, text, block=next(block), numeric=numeric))

    for work in ("W0001", "W0002", "W0003", "W0004"):
        add(work, "traffic.traffic_unit", f"one {work} sample is a flow")
    for work in ("W0001", "W0002"):
        add(work, "traffic.representation_family", f"{work} serialises raw bytes")
        add(work, "traffic.representation_family", f"{work} also separates header fields")
    add("W0004", "traffic.representation_family", "W0004 builds behaviour vectors")
    add("W0005", "traffic.representation_family", "W0005 uses field-based input")
    for work in ("W0002", "W0003"):
        add(work, "traffic.tokenization", f"{work} tokenizes at byte level")
    for work in ("W0001", "W0002", "W0003", "W0004"):
        add(work, "traffic.encryption_status", f"{work} evaluates encrypted traffic")
    add("W0003", "traffic.llm_role", "the model is used as a classifier")
    for work in ("W0001", "W0002", "W0003"):
        add(work, "traffic.dataset", f"{work} evaluates on CICIDS2017")
        add(work, "traffic.dataset", f"{work} also evaluates on USTC-TFC2016")
    # W0004 names one corpus in two sentences: the same answer twice, never a conflict.
    add("W0004", "traffic.dataset", "W0004 evaluates on ISCXVPN2016")
    add("W0004", "traffic.dataset", "W0004 evaluates on ISCXVPN2016")
    add("W0005", "traffic.dataset", "W0005 surveys other papers' corpora")
    add("W0001", "traffic.metrics", "99.20", numeric=f1(99.20))
    add("W0001", "traffic.metrics", "94.32", numeric=f1(94.32))
    add("W0002", "traffic.metrics", "98.25", numeric=f1(98.25, dataset="ISCXVPN2016"))
    add("W0003", "traffic.metrics", "91.10", numeric=f1(91.10, dataset="USTC-TFC2016"))
    add("W0005", "traffic.metrics", "88.40", numeric=f1(88.40, dataset="UNSW-NB15"))
    for work in ("W0001", "W0002", "W0003"):
        add(work, "traffic.author_stated_limitations", f"{work} states a generalisation limit")
        add(work, "traffic.author_stated_limitations", f"{work} states a capture-age limit")
    add("W0004", "traffic.author_stated_limitations", "W0004 states a latency limit")
    add("W0005", "traffic.author_stated_limitations", "W0005 states a coverage limit")
    return made


def former_conflict_count(candidates: list[EvidenceCandidate]) -> int:
    """How many items the queue used to call conflicts: any peer with a different value.

    Reconstructed from the peer index the classifier still uses, so the "before" number in
    the next test is measured rather than remembered.
    """
    from research_harness.evidence.review import _PeerIndex

    index = _PeerIndex.build(candidates)
    return sum(
        1
        for position, item in enumerate(candidates)
        if index.relations(position, (str(item.work), item.field))[1]
    )


def test_the_dogfood_queue_had_eighteen_conflicts_and_now_has_two(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    """F7, measured: 18 conflicts of 39 items become 2, and the 2 are the real one.

    The two survivors are W0001's `traffic.metrics` pair - one metric, one dataset, two
    numbers - which is exactly the disagreement conflict-first review exists to surface.
    Everything else moves to the category its own tier earns.
    """
    candidates = dogfood_candidates()
    assert len(candidates) == 39
    assert former_conflict_count(candidates) == 18

    staging.put_all(candidates)
    queue = build_inbox(staging, repo, schema=TRAFFIC_SCHEMA)

    conflicts = queue.by_category(ReviewCategory.CONFLICT)
    assert len(queue) == 39
    assert len(conflicts) == 2
    assert {item.candidate.field for item in conflicts} == {"traffic.metrics"}
    assert {str(item.work) for item in conflicts} == {"W0001"}
    assert all("94.32" in " ".join(item.reasons) for item in conflicts)

    routine = queue.by_category(ReviewCategory.ROUTINE)
    assert any("takes several values" in " ".join(item.reasons) for item in routine)
    assert all(item.competing for item in conflicts)


def test_without_the_schema_a_multi_label_categorical_field_still_reads_as_a_conflict(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    """What a candidate alone can and cannot say, now that the flag exists.

    `research inbox` reads staging, and a candidate records its field's *name* but not the
    schema that asked it, so `build_inbox` falls back to `conflicts.inferred_field`, which
    asserts no declaration nobody made. A list-like head noun (`traffic.dataset`,
    `..._limitations`) still carries; a multi-label *categorical* field named in the
    singular (`traffic.representation_family`) does not, and its four answers are still
    reported as competing. Supplying the schema is the fix, and the next test is the proof
    that the declaration - not the question's wording - is what does it.
    """
    staging.put_all(dogfood_candidates())

    without = build_inbox(staging, repo).by_category(ReviewCategory.CONFLICT)
    with_schema = build_inbox(staging, repo, schema=TRAFFIC_SCHEMA).by_category(
        ReviewCategory.CONFLICT
    )

    assert len(with_schema) == 2
    assert len(without) == 6
    assert {item.candidate.field for item in without} == {
        "traffic.metrics",
        "traffic.representation_family",
    }


def test_the_shipped_plugin_schema_leaves_no_false_conflict(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    """The same 39 candidates against the real `plugins/structured-traffic` questions.

    Read straight off the YAML the plugin ships, merged the way the loader merges it, so
    what is asserted is the file a project actually uses rather than a schema written for
    the test. Four of the six `traffic.representation_family` conflicts were false; with
    the shipped declarations there are **none**, and the two real `traffic.metrics`
    disagreements survive.
    """
    staging.put_all(dogfood_candidates())

    conflicts = build_inbox(staging, repo, schema=shipped_traffic_schema()).by_category(
        ReviewCategory.CONFLICT
    )

    assert {item.candidate.field for item in conflicts} == {"traffic.metrics"}
    assert len(conflicts) == 2
    assert len(build_inbox(staging, repo).by_category(ReviewCategory.CONFLICT)) == 6


def test_the_declared_flag_closes_the_four_the_field_name_could_not(
    staging: StagingStore, repo: WorkspaceRepository
) -> None:
    """F7's residual, closed: `InterrogationField.multi_label` decides, wording aside.

    Every question below is rewritten to ask for nothing in particular, so
    `_asks_for_several` fires on none of them and `traffic.representation_family` is still
    named in the singular - the exact shape the inference could not read. The declaration
    alone takes the four false conflicts to zero, and leaves the two real ones: W0001's
    `traffic.metrics` pair, which `_numeric_clash` judges before multi-valuedness is ever
    consulted, so declaring a numeric field multi-label costs no real disagreement.
    """
    declared = MUTE_SCHEMA
    family = declared.field("traffic.representation_family")
    assert is_multi_valued(family) is True, "the declaration carries it"
    assert is_multi_valued(family.model_copy(update={"multi_label": False})) is False, (
        "and nothing else does: neither the question's wording nor the head noun"
    )
    staging.put_all(dogfood_candidates())

    conflicts = build_inbox(staging, repo, schema=declared).by_category(ReviewCategory.CONFLICT)

    assert {item.candidate.field for item in conflicts} == {"traffic.metrics"}
    assert len(conflicts) == 2, "the four representation_family conflicts are gone"
    assert not [item for item in conflicts if item.candidate.field != "traffic.metrics"]
    routine = build_inbox(staging, repo, schema=declared).by_category(ReviewCategory.ROUTINE)
    assert any("takes several values" in " ".join(item.reasons) for item in routine)

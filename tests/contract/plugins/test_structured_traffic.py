"""ROADMAP Task 15.1: the structured-traffic domain, added without touching the core.

The plugin under test is the real one in `plugins/structured-traffic`, not a fixture. These
tests assert the two acceptance requirements of Task 15.1 - the recommended taxonomy terms
are plugin vocabulary rather than core enums, and hybrid/multi-label classification is
permitted - plus the boundary the whole of Phase 14 exists to protect: `DEFAULT_SCHEMA` is
the same object, with the same fingerprint, after the plugin is loaded.
"""

from __future__ import annotations

import enum
import inspect
from pathlib import Path

import pytest

import research_harness.domain.enums as core_enums
from research_harness.domain.enums import EvidenceType, ReviewTier
from research_harness.evidence.conflicts import is_multi_valued
from research_harness.evidence.interrogation import DEFAULT_SCHEMA, ValueKind
from research_harness.plugins import (
    PLUGIN_ALLOWED_CAPABILITIES,
    IssueSeverity,
    PluginBoundaryError,
    PluginRuntime,
    load_plugin,
)
from research_harness.roles.contracts import InputKind, WriteScope
from research_harness.roles.registry import ROLES
from research_harness.roles.schemas import ClaimAuditOutput

from .conftest import RecordingGateway, Request

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugins" / "structured-traffic"
SCHEMA_NAME = "structured-traffic:paper"
ROLE = "traffic.domain_reviewer"

#: The PRODUCT.md 33 field list, with the answer shape and review tier each is staged at.
#: `risk` is what the YAML declares; `tier` is what the field actually stages at, which
#: differs for a numeric field because a number is never Tier 1 (PRODUCT.md 12, 24.1).
EXPECTED_FIELDS: tuple[tuple[str, ValueKind, ReviewTier, bool], ...] = (
    ("traffic.traffic_unit", ValueKind.CATEGORICAL, ReviewTier.TIER_1, True),
    ("traffic.representation_family", ValueKind.CATEGORICAL, ReviewTier.TIER_2, False),
    ("traffic.raw_information_retained", ValueKind.TEXT, ReviewTier.TIER_1, False),
    ("traffic.derived_information", ValueKind.TEXT, ReviewTier.TIER_2, False),
    ("traffic.serialization", ValueKind.CATEGORICAL, ReviewTier.TIER_1, False),
    ("traffic.tokenization", ValueKind.CATEGORICAL, ReviewTier.TIER_1, False),
    ("traffic.llm_architecture", ValueKind.CATEGORICAL, ReviewTier.TIER_1, False),
    ("traffic.llm_role", ValueKind.CATEGORICAL, ReviewTier.TIER_1, False),
    ("traffic.training_strategy", ValueKind.CATEGORICAL, ReviewTier.TIER_1, False),
    ("traffic.detection_target", ValueKind.CATEGORICAL, ReviewTier.TIER_1, False),
    ("traffic.dataset", ValueKind.TEXT, ReviewTier.TIER_1, True),
    ("traffic.dataset_age", ValueKind.TEXT, ReviewTier.TIER_2, False),
    ("traffic.encryption_status", ValueKind.CATEGORICAL, ReviewTier.TIER_2, False),
    ("traffic.train_test_partition", ValueKind.TEXT, ReviewTier.TIER_2, False),
    ("traffic.evaluation_unit", ValueKind.CATEGORICAL, ReviewTier.TIER_1, False),
    ("traffic.baselines", ValueKind.TEXT, ReviewTier.TIER_1, False),
    ("traffic.metrics", ValueKind.NUMERIC, ReviewTier.TIER_2, True),
    ("traffic.ablations", ValueKind.NEGATIVE, ReviewTier.TIER_2, False),
    ("traffic.robustness_evaluation", ValueKind.NEGATIVE, ReviewTier.TIER_2, False),
    ("traffic.deployment_assumptions", ValueKind.TEXT, ReviewTier.TIER_2, False),
    ("traffic.author_stated_limitations", ValueKind.TEXT, ReviewTier.TIER_2, False),
    ("traffic.researcher_observed_limitations", ValueKind.TEXT, ReviewTier.TIER_2, False),
)

#: The three starting terms PRODUCT.md 33 *recommends*, in the form the plugin writes them.
TAXONOMY_SUGGESTIONS: tuple[str, ...] = ("raw sequential", "field-based", "behavior-aware")


@pytest.fixture
def runtime(gateway: RecordingGateway) -> PluginRuntime:
    """The real `plugins/structured-traffic`, loaded against a gateway that reaches nothing."""
    return load_plugin(PLUGIN_DIR, gateway=gateway)


def test_the_plugin_loads_and_identifies_itself(runtime: PluginRuntime) -> None:
    assert runtime.name == "structured-traffic"
    assert runtime.version == "0.1.0"
    assert runtime.manifest.namespaces == frozenset({"structured_traffic", "traffic"})
    assert runtime.manifest.satisfied_by("0.1.0")


# --------------------------------------------------------------------- the field list


def test_every_product_33_field_is_asked(runtime: PluginRuntime) -> None:
    schema = runtime.interrogation_schemas[SCHEMA_NAME]
    plugin_names = tuple(name for name in schema.names if name.startswith("traffic."))
    assert plugin_names == tuple(name for name, _, _, _ in EXPECTED_FIELDS)


@pytest.mark.parametrize(("name", "kind", "tier", "required"), EXPECTED_FIELDS)
def test_each_field_declares_its_shape_and_review_tier(
    runtime: PluginRuntime,
    name: str,
    kind: ValueKind,
    tier: ReviewTier,
    required: bool,
) -> None:
    field = runtime.interrogation_schemas[SCHEMA_NAME].field(name)
    assert field.value_kind is kind
    assert field.review_tier is tier
    assert field.required is required
    assert field.evidence_types, "a field must name the core evidence types that answer it"
    assert all(isinstance(item, EvidenceType) for item in field.evidence_types)


#: Questions one paper answers once. Everything else in the plugin schema is multi-label:
#: a hybrid representation, three datasets, and six baselines are additional answers.
SINGLE_VALUED: frozenset[str] = frozenset(
    {
        "traffic.encryption_status",
        "traffic.dataset_age",
        "traffic.train_test_partition",
    }
)


def test_every_multi_valued_question_declares_the_flag_rather_than_implying_it(
    runtime: PluginRuntime,
) -> None:
    """Dogfood F7: `is_multi_valued` reads a declaration, not the field name's head noun."""
    schema = runtime.interrogation_schemas[SCHEMA_NAME]
    plugin_fields = [item for item in schema.fields if item.name.startswith("traffic.")]

    declared = {item.name for item in plugin_fields if item.multi_label}
    assert declared == {item.name for item in plugin_fields} - SINGLE_VALUED
    assert all(is_multi_valued(schema.field(name)) for name in declared)
    assert not any(is_multi_valued(schema.field(name)) for name in SINGLE_VALUED)


def test_the_interrogation_flag_agrees_with_the_vocabulary_flag(runtime: PluginRuntime) -> None:
    """One fact, stated twice: about the vocabulary field, and about the question filling it."""
    schema = runtime.interrogation_schemas[SCHEMA_NAME]
    for vocabulary_field in runtime.vocabulary.fields:
        if not vocabulary_field.multi_label:
            continue
        assert schema.field(vocabulary_field.name).multi_label is True, (
            f"{vocabulary_field.name} is multi-label vocabulary but a single-valued question"
        )


def test_a_question_permits_the_evidence_type_its_own_wording_invites(
    runtime: PluginRuntime,
) -> None:
    """Dogfood F14: correct enforcement of a wrong declaration is still a lost span.

    "Which unit does the paper treat as one sample" is answered by a definition sentence,
    and "which limitation do the authors state" is routinely written as what a deployment
    must provide. Both were refused at extraction by this schema's own gate.
    """
    schema = runtime.interrogation_schemas[SCHEMA_NAME]
    assert schema.field("traffic.traffic_unit").allows(EvidenceType.DEFINITION)
    assert schema.field("traffic.author_stated_limitations").allows(
        EvidenceType.DEPLOYMENT_ASSUMPTION
    )
    assert not schema.field("traffic.metrics").allows(EvidenceType.DEFINITION), (
        "widening one question does not widen the rest"
    )


def test_a_measured_value_is_never_triaged(runtime: PluginRuntime) -> None:
    """A number carries metric, unit, dataset, and condition a quick pass cannot check."""
    metrics = runtime.interrogation_schemas[SCHEMA_NAME].field("traffic.metrics")
    assert metrics.value_kind is ValueKind.NUMERIC
    assert metrics.review_tier is ReviewTier.TIER_2


def test_limitations_are_deep_review(runtime: PluginRuntime) -> None:
    schema = runtime.interrogation_schemas[SCHEMA_NAME]
    for name in (
        "traffic.author_stated_limitations",
        "traffic.researcher_observed_limitations",
        "traffic.deployment_assumptions",
    ):
        assert schema.field(name).review_tier is ReviewTier.TIER_2


def test_absence_shaped_questions_are_negative_not_categorical(runtime: PluginRuntime) -> None:
    """`negative` marks a question whose useful answer is often an absence *state*.

    It never licenses `absent`, which stays an audited researcher conclusion (Product 11).
    """
    schema = runtime.interrogation_schemas[SCHEMA_NAME]
    for name in ("traffic.ablations", "traffic.robustness_evaluation"):
        assert schema.field(name).value_kind is ValueKind.NEGATIVE


# ------------------------------------------------------------------ the core is untouched


def test_the_merged_schema_keeps_every_core_question(runtime: PluginRuntime) -> None:
    schema = runtime.interrogation_schemas[SCHEMA_NAME]
    assert set(DEFAULT_SCHEMA.names).issubset(schema.names)
    assert schema.names[: len(DEFAULT_SCHEMA.names)] == DEFAULT_SCHEMA.names


def test_the_core_schema_is_the_same_object_after_the_merge(
    gateway: RecordingGateway,
) -> None:
    """Loading the plugin twice leaves `DEFAULT_SCHEMA` byte-identical (Task 14.3)."""
    before = DEFAULT_SCHEMA.fingerprint()
    load_plugin(PLUGIN_DIR, gateway=gateway)
    load_plugin(PLUGIN_DIR, gateway=gateway)
    assert DEFAULT_SCHEMA.fingerprint() == before
    assert DEFAULT_SCHEMA.name == "generic-empirical"
    assert not [name for name in DEFAULT_SCHEMA.names if name.startswith("traffic.")]


def test_no_plugin_label_collides_with_a_core_one(runtime: PluginRuntime) -> None:
    core_labels = {member.value for member in EvidenceType} | set(DEFAULT_SCHEMA.names)
    assert not runtime.vocabulary.labels() & core_labels
    assert all(label.startswith("traffic.") for label in runtime.vocabulary.labels())


def test_a_core_evidence_type_still_resolves_to_the_core_member(runtime: PluginRuntime) -> None:
    """A plugin term and a core evidence type can never be confused for each other."""
    assert runtime.vocabulary.resolve_evidence_type("experimental_result") is (
        EvidenceType.EXPERIMENTAL_RESULT
    )
    term = runtime.vocabulary.resolve_evidence_type("traffic.encryption_statement")
    assert term is not None and not isinstance(term, EvidenceType)


# ------------------------------------------------------------- taxonomy is not an enum


@pytest.mark.parametrize("term", TAXONOMY_SUGGESTIONS)
def test_a_taxonomy_suggestion_is_not_written_into_domain_enums(term: str) -> None:
    """Grep the core vocabulary file: the recommended terms are not in it, in any spelling."""
    source = Path(inspect.getfile(core_enums)).read_text(encoding="utf-8")
    for spelling in (term, term.replace(" ", "_").replace("-", "_"), term.replace(" ", "-")):
        assert spelling not in source, f"{spelling!r} leaked into domain/enums.py"


@pytest.mark.parametrize("term", TAXONOMY_SUGGESTIONS)
def test_a_taxonomy_suggestion_is_not_a_member_of_any_core_enum(term: str) -> None:
    """The same assertion at runtime, over every enum the core declares."""
    spellings = {term, term.replace(" ", "_").replace("-", "_"), term.replace("-", "_")}
    for _, obj in inspect.getmembers(core_enums, inspect.isclass):
        if not issubclass(obj, enum.Enum) or obj.__module__ != core_enums.__name__:
            continue
        values = {str(member.value) for member in obj}
        names = {member.name.casefold() for member in obj}
        assert not values & spellings
        assert not names & spellings


def test_the_taxonomy_suggestions_are_plugin_categories(runtime: PluginRuntime) -> None:
    field = runtime.vocabulary.field("traffic.representation_family")
    assert field is not None
    assert set(TAXONOMY_SUGGESTIONS).issubset(field.categories)
    assert "unclear" in field.categories, "a paper that does not say must have an answer"
    assert field.multi_label is True


# ------------------------------------------------------------------------- validators


def test_the_validator_rejects_a_unit_outside_the_project_taxonomy(
    runtime: PluginRuntime,
) -> None:
    issues = runtime.validators["structured-traffic.traffic_unit"].run(
        {"field": "traffic.traffic_unit", "value": "datagram"}
    )
    assert [issue.severity for issue in issues] == [IssueSeverity.ERROR]
    assert "datagram" in issues[0].message
    assert "Decision" in issues[0].message


def test_the_validator_accepts_a_single_value_and_a_hybrid(runtime: PluginRuntime) -> None:
    """Hybrid/multi-label classification is permitted (ROADMAP Task 15.1)."""
    validator = runtime.validators["structured-traffic.traffic_unit"]
    assert validator.run({"field": "traffic.traffic_unit", "value": "flow"}) == ()
    assert validator.run({"field": "traffic.traffic_unit", "value": ["packet", "flow"]}) == ()
    assert (
        validator.run(
            {
                "field": "traffic.representation_family",
                "value": ["raw sequential", "field-based"],
            }
        )
        == ()
    )


def test_the_validator_rejects_one_bad_member_of_a_hybrid(runtime: PluginRuntime) -> None:
    issues = runtime.validators["structured-traffic.traffic_unit"].run(
        {"field": "traffic.representation_family", "value": ["field-based", "graph-based"]}
    )
    assert len(issues) == 1
    assert "graph-based" in issues[0].message


def test_unclear_is_an_answer_and_a_blank_is_only_a_warning(runtime: PluginRuntime) -> None:
    """Nobody-recorded-this is not this-paper-has-none (Product 11, 42.F)."""
    validator = runtime.validators["structured-traffic.traffic_unit"]
    assert validator.run({"field": "traffic.representation_family", "value": "unclear"}) == ()
    blank = validator.run({"field": "traffic.traffic_unit", "value": None})
    assert [issue.severity for issue in blank] == [IssueSeverity.WARNING]


def test_the_validator_ignores_fields_it_does_not_own(runtime: PluginRuntime) -> None:
    validator = runtime.validators["structured-traffic.traffic_unit"]
    assert validator.run({"field": "dataset", "value": "anything"}) == ()
    assert validator.run({"field": "traffic.metrics", "value": 94.3}) == ()


@pytest.mark.parametrize("value", ["2016", "2015-2017", "2015--2017", "2015 to 2017", "unclear"])
def test_dataset_age_accepts_a_year_or_a_range(runtime: PluginRuntime, value: str) -> None:
    assert (
        runtime.validators["structured-traffic.dataset_age"].run(
            {"field": "traffic.dataset_age", "value": value}
        )
        == ()
    )


@pytest.mark.parametrize(
    "value", ["mid-2010s", "see Table 1", "recent", "2017-2015", "1200", "the 1990s"]
)
def test_dataset_age_rejects_anything_that_is_not_a_capture_year(
    runtime: PluginRuntime, value: str
) -> None:
    issues = runtime.validators["structured-traffic.dataset_age"].run(
        {"field": "traffic.dataset_age", "value": value}
    )
    assert issues and all(issue.severity is IssueSeverity.ERROR for issue in issues)


@pytest.mark.parametrize(
    "value", ["plaintext", "partially_encrypted", "encrypted", "mixed", "unclear"]
)
def test_encryption_status_accepts_the_five_recorded_states(
    runtime: PluginRuntime, value: str
) -> None:
    assert (
        runtime.validators["structured-traffic.dataset_age"].run(
            {"field": "traffic.encryption_status", "value": value}
        )
        == ()
    )


@pytest.mark.parametrize("value", ["tls", "https", "some", "encrypted?", True])
def test_encryption_status_rejects_anything_else(runtime: PluginRuntime, value: object) -> None:
    issues = runtime.validators["structured-traffic.dataset_age"].run(
        {"field": "traffic.encryption_status", "value": value}
    )
    assert [issue.severity for issue in issues] == [IssueSeverity.ERROR]


def test_a_validator_is_handed_data_and_nothing_else(runtime: PluginRuntime) -> None:
    """`LoadedValidator.run` refuses anything that is not JSON-shaped (Product 32.2)."""
    with pytest.raises(PluginBoundaryError):
        runtime.validators["structured-traffic.traffic_unit"].run(
            {"field": "traffic.traffic_unit", "value": object()}
        )


# ------------------------------------------------------------------------ workflow, role


def test_the_workflow_calls_only_declared_read_and_stage_capabilities(
    runtime: PluginRuntime,
) -> None:
    fragment = runtime.workflow_fragments["traffic.interrogate_paper"]
    assert fragment.capability_names() <= runtime.manifest.permissions.capabilities
    assert fragment.capability_names() <= PLUGIN_ALLOWED_CAPABILITIES
    assert [stage.name for stage in fragment.stages][-1] == "queue_for_review"


def test_the_workflow_ends_in_a_researchers_inbox(runtime: PluginRuntime) -> None:
    """There is no acceptance stage, because there is no acceptance capability to call."""
    fragment = runtime.workflow_fragments["traffic.interrogate_paper"]
    assert not any(
        name.endswith((".accept", ".reject", ".promote")) for name in fragment.capability_names()
    )


def test_the_domain_reviewer_reads_accepted_evidence_and_writes_an_audit_result(
    runtime: PluginRuntime,
) -> None:
    contract = runtime.roles[ROLE]
    assert ROLE not in ROLES
    assert InputKind.ACCEPTED_EVIDENCE in contract.allowed_inputs
    assert contract.write_scope is WriteScope.AUDIT_RESULT
    assert contract.output_schema is ClaimAuditOutput
    assert contract.allowed_capabilities <= PLUGIN_ALLOWED_CAPABILITIES


def test_the_plugin_gateway_refuses_an_acceptance_capability(
    runtime: PluginRuntime, gateway: RecordingGateway
) -> None:
    assert runtime.gateway.call("work.get", Request(), actor="plugin:traffic") is not None
    for capability in ("evidence.accept", "decision.accept", "taxonomy.put"):
        with pytest.raises(PluginBoundaryError):
            runtime.gateway.call(capability, Request(), actor="plugin:traffic")
    assert gateway.calls == [("work.get", "plugin:traffic")]


def test_the_plugin_declares_no_egress(runtime: PluginRuntime) -> None:
    assert runtime.manifest.egress == ()
    assert runtime.search_providers == {}

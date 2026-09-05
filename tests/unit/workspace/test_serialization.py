"""Canonical serialization is deterministic, order-stable, and strictly validated."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from research_harness.domain import (
    Artifact,
    Claim,
    Decision,
    DocumentBlock,
    Evidence,
    ManuscriptAnchor,
    ResearchEvent,
    ResearchEventType,
    ResearchNote,
    ResearchQuestion,
    SynthesisMatrix,
    Taxonomy,
    TaxonomyTerm,
    Version,
    Work,
)
from research_harness.domain.errors import WorkspaceError
from research_harness.workspace.serialization import (
    CanonicalDumper,
    WorkspaceSerializationError,
    _libyaml_emits_the_same_bytes,
    canonical_bytes,
    dump_jsonl_line,
    dump_yaml,
    iter_jsonl,
    load_yaml,
    read_yaml,
)
from tests.unit.domain.strategies import (
    HASH_B,
    HUMAN,
    artifacts,
    claims,
    decisions,
    evidence_objects,
    make_artifact,
    make_block,
    make_claim,
    make_evidence,
    make_note,
    make_question,
    make_search_run,
    make_version,
    make_work,
    versions,
    works,
)


def _round_trip[T: BaseModel](model: T) -> T:
    return load_yaml(dump_yaml(model), type(model))


# -- YAML round trips --------------------------------------------------------


@given(works())
def test_work_survives_a_yaml_round_trip(work: Work) -> None:
    assert _round_trip(work) == work


@given(versions())
def test_version_survives_a_yaml_round_trip(version: Version) -> None:
    assert _round_trip(version) == version


@given(artifacts())
def test_artifact_survives_a_yaml_round_trip(artifact: Artifact) -> None:
    assert _round_trip(artifact) == artifact


@given(evidence_objects())
def test_evidence_survives_a_yaml_round_trip(evidence: Evidence) -> None:
    assert _round_trip(evidence) == evidence


@given(claims())
def test_claim_survives_a_yaml_round_trip(claim: Claim) -> None:
    assert _round_trip(claim) == claim


@given(decisions())
def test_decision_survives_a_yaml_round_trip(decision: Decision) -> None:
    assert _round_trip(decision) == decision


def _every_canonical_object() -> list[BaseModel]:
    """One instance of every canonical type, including those with no Hypothesis generator."""
    anchor = ManuscriptAnchor(
        file="main.tex",
        line_start=12,
        line_end=12,
        sentence="Existing systems disagree on tokenization.",
        sentence_fingerprint=HASH_B,
        claim=make_claim().id,
        provenance=HUMAN,
    )
    taxonomy = Taxonomy(
        name="tokenization",
        terms=(TaxonomyTerm(term="byte"), TaxonomyTerm(term="field", parent="byte")),
        provenance=HUMAN,
    )
    matrix = SynthesisMatrix(id="S0002", name="coverage", provenance=HUMAN)
    event = ResearchEvent(
        event=ResearchEventType.CLAIM_CREATED,
        actor="human:alice",
        summary="created C0041",
        subjects=(make_claim().id,),
    )
    return [
        make_work(),
        make_version(),
        make_artifact(),
        make_evidence(),
        make_claim(),
        make_question(),
        make_search_run(),
        make_note(key="note-20260101-120000-abcdef"),
        make_block(),
        anchor,
        taxonomy,
        matrix,
        event,
    ]


def test_every_canonical_type_survives_a_yaml_round_trip() -> None:
    """The remaining canonical types have no generator; cover them from the builders."""
    for model in _every_canonical_object():
        if isinstance(model, ResearchEvent):
            continue
        assert _round_trip(model) == model


# -- JSON Lines round trips --------------------------------------------------


@given(evidence_objects())
def test_evidence_survives_a_jsonl_round_trip(evidence: Evidence) -> None:
    payload = json.loads(dump_jsonl_line(evidence))
    assert Evidence.model_validate(payload) == evidence


def test_jsonl_files_round_trip_every_append_only_type(tmp_path: Path) -> None:
    records: list[tuple[Path, list[BaseModel], type[BaseModel]]] = [
        (tmp_path / "evidence.jsonl", [make_evidence(), make_evidence(id="E0483")], Evidence),
        (tmp_path / "blocks.jsonl", [make_block()], DocumentBlock),
        (
            tmp_path / "events.jsonl",
            [
                ResearchEvent(
                    event=ResearchEventType.CLAIM_CREATED,
                    actor="human:alice",
                    summary="created C0041",
                    subjects=(make_claim().id,),
                )
            ],
            ResearchEvent,
        ),
    ]
    for path, models, model_type in records:
        path.write_text("".join(dump_jsonl_line(model) for model in models), encoding="utf-8")
        assert list(iter_jsonl(path, model_type)) == models


def test_jsonl_lines_sort_keys_and_carry_no_trailing_whitespace() -> None:
    line = dump_jsonl_line(make_claim())
    assert line.endswith("}\n")
    assert not line[:-1].endswith(" ")
    payload = json.loads(line)
    assert list(payload) == sorted(payload)


def test_iter_jsonl_of_a_missing_file_is_empty(tmp_path: Path) -> None:
    assert list(iter_jsonl(tmp_path / "absent.jsonl", Evidence)) == []


# -- byte-level canonical form -----------------------------------------------


@given(st.one_of(works(), claims(), decisions()))
def test_yaml_keys_follow_field_declaration_order_not_alphabetical(model: BaseModel) -> None:
    parsed = yaml.safe_load(dump_yaml(model))
    assert list(parsed) == list(type(model).model_fields)


def test_yaml_is_block_style_utf8_and_ends_in_one_newline() -> None:
    text = dump_yaml(make_work(title="Représentations structurées", authors=("Ana Ö.",)))
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert "Représentations structurées" in text
    assert "{" not in text and "[]" in text  # block style; empty collections stay compact
    work = make_work()
    assert canonical_bytes(work) == dump_yaml(work).encode("utf-8")


def test_long_values_are_never_wrapped_onto_a_second_line() -> None:
    statement = "word " * 60
    text = dump_yaml(make_claim(statement=statement))
    lines = text.splitlines()
    assert any(line.startswith("statement:") and statement.strip() in line for line in lines)


def test_repeated_sub_objects_never_become_yaml_anchors() -> None:
    text = dump_yaml(make_claim())
    assert "&id" not in text and "*id" not in text


def test_serialization_is_stable_across_calls() -> None:
    claim = make_claim()
    assert dump_yaml(claim) == dump_yaml(claim)
    assert dump_jsonl_line(claim) == dump_jsonl_line(claim)


def test_timestamps_load_as_aware_utc_even_when_a_hand_edit_unquoted_them(
    tmp_path: Path,
) -> None:
    """PyYAML would hand back a naive datetime, which the domain rejects."""
    path = tmp_path / "W0017.yaml"
    text = dump_yaml(make_work()).replace("'2", "2").replace("Z'", "Z")
    path.write_text(text, encoding="utf-8")
    work = read_yaml(path, Work)
    assert work.created_at.tzinfo is not None


# -- strict validation names the file ----------------------------------------


def test_an_unknown_key_fails_with_a_workspace_error_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "C0041.yaml"
    path.write_text(dump_yaml(make_claim()) + "unexpected_key: 1\n", encoding="utf-8")
    with pytest.raises(WorkspaceSerializationError) as caught:
        read_yaml(path, Claim)
    assert str(path) in str(caught.value)
    assert "unexpected_key" in str(caught.value)
    assert isinstance(caught.value, WorkspaceError)


def test_a_missing_required_field_fails_with_a_workspace_error(tmp_path: Path) -> None:
    path = tmp_path / "RQ0003.yaml"
    path.write_text("schema_version: 1\nid: RQ0003\n", encoding="utf-8")
    with pytest.raises(WorkspaceSerializationError) as raised:
        read_yaml(path, ResearchQuestion)
    assert str(path) in str(raised.value)


def test_invalid_yaml_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("a: [1,\n", encoding="utf-8")
    with pytest.raises(WorkspaceSerializationError, match="invalid YAML"):
        read_yaml(path, Work)


def test_a_non_mapping_document_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(WorkspaceSerializationError, match="expected a Work mapping"):
        read_yaml(path, Work)


def test_a_broken_jsonl_line_names_the_file_and_the_line(tmp_path: Path) -> None:
    path = tmp_path / "evidence.jsonl"
    path.write_text(dump_jsonl_line(make_evidence()) + "{not json}\n", encoding="utf-8")
    with pytest.raises(WorkspaceSerializationError, match="line 2"):
        list(iter_jsonl(path, Evidence))


def test_a_jsonl_line_that_is_not_the_expected_type_names_the_line(tmp_path: Path) -> None:
    path = tmp_path / "evidence.jsonl"
    path.write_text(dump_jsonl_line(make_note(key="k")) + "\n", encoding="utf-8")
    with pytest.raises(WorkspaceSerializationError, match="not a valid Evidence"):
        list(iter_jsonl(path, Evidence))


def test_reading_a_note_as_yaml_still_validates_strictly(tmp_path: Path) -> None:
    path = tmp_path / "note.yaml"
    path.write_text("text: hi\nprovenance: not-a-mapping\n", encoding="utf-8")
    with pytest.raises(WorkspaceSerializationError, match="not a valid ResearchNote"):
        read_yaml(path, ResearchNote)


# -- the LibYAML fast path never changes a byte --------------------------------


def _pure_yaml(model: BaseModel) -> str:
    """What the pure-Python emitter produces; canonical bytes are defined by this."""
    text: str = yaml.dump(
        model.model_dump(mode="json"),
        Dumper=CanonicalDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=1_000_000,
    )
    return text if text.endswith("\n") else text + "\n"


@given(st.one_of(works(), versions(), artifacts(), evidence_objects(), claims(), decisions()))
def test_dump_yaml_is_the_pure_python_emitter_byte_for_byte(model: BaseModel) -> None:
    """Whichever emitter `dump_yaml` picks, the bytes are the ones PyYAML would write.

    Object digests are the SHA-256 of these bytes and they live in the persisted event log,
    so an emitter that differed by one byte on one machine would fail every workspace
    written on another closed.
    """
    assert dump_yaml(model) == _pure_yaml(model)


def test_every_canonical_type_dumps_identically_through_either_emitter() -> None:
    """The generated types above plus the ones that have no generator."""
    for model in _every_canonical_object():
        assert dump_yaml(model) == _pure_yaml(model)


@given(st.text(max_size=200))
def test_arbitrary_text_dumps_identically_through_either_emitter(text: str) -> None:
    """Any character at all - astral, surrogate, control - still reaches one set of bytes.

    ``text`` is padded so that a field which strips its edges cannot drop the character
    under test; the interesting characters sit in the interior either way.
    """
    note = make_note(key="note-20260101-120000-abcdef", text=f"a{text}z")
    assert dump_yaml(note) == _pure_yaml(note)


@pytest.mark.parametrize(
    "text",
    [
        "plain",
        "a \U0001f600 emoji",  # astral: LibYAML escapes it, PyYAML does not
        "next\x85line",  # U+0085: printable to PyYAML only
        "carriage\rreturn",  # a line break to LibYAML only
        "a" * 300,
        "ligature ﬁeld and é accents",
        "trailing space ",
        "#hash: colon, [bracket] {brace}",
    ],
)
def test_characters_the_two_emitters_disagree_about_still_dump_identically(text: str) -> None:
    note = make_note(key="note-20260101-120000-abcdef", text=f"a{text}z")
    assert dump_yaml(note) == _pure_yaml(note)


def test_a_document_with_an_exotic_mapping_key_falls_back_rather_than_diverging() -> None:
    """`ResearchEvent.objects` can hold keys longer than the two emitters agree about."""
    event = ResearchEvent(
        event=ResearchEventType.CLAIM_CREATED,
        actor="human:alice",
        summary="created C0041",
        subjects=(make_claim().id,),
        objects={f"anchor/{'d' * 90}.tex#{HASH_B}": HASH_B},
    )
    assert not _libyaml_emits_the_same_bytes(event.model_dump(mode="json"))
    assert dump_yaml(event) == _pure_yaml(event)

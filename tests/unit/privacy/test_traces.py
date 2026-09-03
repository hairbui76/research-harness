"""Disposable traces: where they are written, what redaction removes, what purge deletes.

ROADMAP Task 17.4 / Product SS19.3, SS34. A trace may contain source text, so the two
properties that matter are that redaction really removes it and that purging really deletes
it — and that neither ever writes outside `.research/traces/`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from research_harness.domain.errors import WorkspaceError
from research_harness.privacy.policy import EgressPolicy
from research_harness.privacy.traces import TraceWriter, redact_payload

SOURCE_TEXT = "Table 3 reports a mean throughput of 1.4 Gbps on the CIC-IDS2017 corpus."
QUOTE = "94.32% accuracy"
ANSWER = '{"supported": true}'
FINGERPRINT = "0123456789abcdef" * 4
DAY = datetime(2026, 3, 14, 9, 30, tzinfo=UTC)


def payload() -> dict[str, Any]:
    """A completion trace shaped like the one `ModelProvider.complete` writes."""
    return {
        "role": "evidence_verifier",
        "instructions": "Decide whether the source supports the candidate.",
        "inputs": [
            {"object_id": "W0001", "kind": "source_text", "content": SOURCE_TEXT},
            {"object_id": None, "kind": "candidate", "content": QUOTE},
        ],
        "candidate": {"exact_text": QUOTE, "field": "metric_result"},
        "response": {"raw_text": ANSWER, "latency_ms": 12},
    }


@pytest.fixture
def research_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ".research"
    directory.mkdir()
    return directory


def written(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def digest(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


# -- writing -----------------------------------------------------------------


def test_a_trace_lands_under_its_day_named_by_kind_and_fingerprint(research_dir: Path) -> None:
    writer = TraceWriter(research_dir, EgressPolicy())
    path = writer.record(
        "completion",
        provider="openai",
        model="gpt-x",
        request_fingerprint=FINGERPRINT,
        payload=payload(),
        recorded_at=DAY,
    )
    assert path == research_dir / "traces" / "2026-03-14" / "completion-01234567.json"
    document = written(path)
    assert document["provider"] == "openai"
    assert document["model"] == "gpt-x"
    assert document["request_fingerprint"] == FINGERPRINT
    assert document["redacted"] is False
    assert "not scientific state" in document["authority"]


def test_an_unredacted_trace_keeps_the_text_it_recorded(research_dir: Path) -> None:
    writer = TraceWriter(research_dir, EgressPolicy(redact_traces=False))
    path = writer.record(
        "completion",
        provider="openai",
        model="gpt-x",
        request_fingerprint=FINGERPRINT,
        payload=payload(),
    )
    assert SOURCE_TEXT in path.read_text(encoding="utf-8")


def test_the_same_request_recorded_twice_in_a_day_does_not_accumulate(research_dir: Path) -> None:
    writer = TraceWriter(research_dir, EgressPolicy())
    for _ in range(3):
        writer.record(
            "completion",
            provider="openai",
            model="gpt-x",
            request_fingerprint=FINGERPRINT,
            payload=payload(),
            recorded_at=DAY,
        )
    assert len(writer.list_traces()) == 1


@pytest.mark.parametrize("kind", ["../escape", "traces/../../etc", "/absolute", ".hidden", ""])
def test_a_trace_can_never_be_written_outside_the_traces_directory(
    research_dir: Path, kind: str
) -> None:
    writer = TraceWriter(research_dir, EgressPolicy())
    with pytest.raises(WorkspaceError, match="unsafe trace kind"):
        writer.record(
            kind,
            provider="openai",
            model="gpt-x",
            request_fingerprint=FINGERPRINT,
            payload=payload(),
        )
    assert not list(research_dir.rglob("*.json"))


# -- redaction ---------------------------------------------------------------


def test_redaction_replaces_every_source_text_field_with_a_digest_and_a_length(
    research_dir: Path,
) -> None:
    writer = TraceWriter(research_dir, EgressPolicy(redact_traces=True))
    path = writer.record(
        "completion",
        provider="openai",
        model="gpt-x",
        request_fingerprint=FINGERPRINT,
        payload=payload(),
    )
    raw = path.read_text(encoding="utf-8")
    assert SOURCE_TEXT not in raw
    assert QUOTE not in raw
    assert ANSWER not in raw

    document = written(path)
    assert document["redacted"] is True
    body = document["payload"]
    first = body["inputs"][0]
    assert first["content"] == digest(SOURCE_TEXT)
    assert first["content_length"] == len(SOURCE_TEXT)
    assert body["candidate"]["exact_text"] == digest(QUOTE)
    assert body["candidate"]["exact_text_length"] == len(QUOTE)
    assert body["response"]["raw_text"] == digest(ANSWER)
    assert body["response"]["raw_text_length"] == len(ANSWER)


def test_redaction_keeps_everything_that_is_not_source_text(research_dir: Path) -> None:
    writer = TraceWriter(research_dir, EgressPolicy(redact_traces=True))
    document = written(
        writer.record(
            "completion",
            provider="openai",
            model="gpt-x",
            request_fingerprint=FINGERPRINT,
            payload=payload(),
        )
    )
    body = document["payload"]
    assert body["role"] == "evidence_verifier"
    assert body["inputs"][0]["object_id"] == "W0001"
    assert body["inputs"][0]["kind"] == "source_text"
    assert body["response"]["latency_ms"] == 12


def test_the_same_text_always_redacts_to_the_same_digest() -> None:
    once = redact_payload({"content": SOURCE_TEXT})
    twice = redact_payload({"content": SOURCE_TEXT})
    assert once == twice
    assert once["content"] == digest(SOURCE_TEXT)


# -- listing and purging -----------------------------------------------------


def _seed(writer: TraceWriter, days: int) -> None:
    """One trace per day, `days` days back from today."""
    today = datetime.now(UTC)
    for offset in range(days):
        writer.record(
            "completion",
            provider="openai",
            model="gpt-x",
            request_fingerprint=f"{offset:064x}",
            payload=payload(),
            recorded_at=today - timedelta(days=offset),
        )


def test_list_traces_reports_every_trace_oldest_day_first(research_dir: Path) -> None:
    writer = TraceWriter(research_dir, EgressPolicy())
    _seed(writer, 3)
    records = writer.list_traces()
    assert len(records) == 3
    assert [record.day for record in records] == sorted(record.day for record in records)
    assert all(record.kind == "completion" for record in records)
    assert all(record.size_bytes > 0 for record in records)


def test_purging_everything_leaves_no_trace_behind(research_dir: Path) -> None:
    writer = TraceWriter(research_dir, EgressPolicy())
    _seed(writer, 4)
    result = writer.purge(all_traces=True)
    assert result.files == 4
    assert result.freed_bytes > 0
    assert writer.list_traces() == []


def test_purging_by_age_keeps_the_days_inside_the_window(research_dir: Path) -> None:
    writer = TraceWriter(research_dir, EgressPolicy())
    _seed(writer, 6)
    result = writer.purge(older_than_days=3)
    assert result.files == 3
    assert len(writer.list_traces()) == 3


def test_purging_without_arguments_uses_the_policy_retention(research_dir: Path) -> None:
    writer = TraceWriter(research_dir, EgressPolicy(trace_retention_days=2))
    _seed(writer, 5)
    assert writer.purge().files == 3
    assert len(writer.list_traces()) == 2


def test_a_project_that_keeps_traces_forever_purges_nothing_by_default(research_dir: Path) -> None:
    writer = TraceWriter(research_dir, EgressPolicy(trace_retention_days=None))
    _seed(writer, 4)
    result = writer.purge()
    assert not result.removed_anything
    assert len(writer.list_traces()) == 4
    assert writer.purge(all_traces=True).files == 4


def test_purging_a_workspace_without_traces_is_harmless(research_dir: Path) -> None:
    writer = TraceWriter(research_dir, EgressPolicy())
    assert writer.purge(all_traces=True).files == 0
    assert writer.list_traces() == []

"""Fingerprints must be canonical, order-independent, and identical in any process."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

import research_harness
from research_harness.workflows.fingerprints import (
    FingerprintError,
    canonical_bytes,
    fingerprint,
    fingerprint_file,
)
from research_harness.workflows.models import RunStatus

KNOWN_VALUE: dict[str, object] = {"b": [1, 2], "a": "x", "c": None, "d": {"z": True, "y": 1.5}}
KNOWN_FINGERPRINT = "sha256:093483e8c00804c5c9694753069ea557b8445888287d42f4324c4937f465e3ec"

_SRC = str(Path(research_harness.__file__).resolve().parents[1])
_OTHER_PROCESS = (
    "from research_harness.workflows.fingerprints import fingerprint\n"
    'print(fingerprint({"b": [1, 2], "a": "x", "c": None, "d": {"z": True, "y": 1.5}}))\n'
)


class Point(BaseModel):
    x: int
    y: str


@dataclass
class Boxed:
    label: str
    values: list[int]


def test_fingerprint_of_a_known_value_never_changes() -> None:
    assert fingerprint(KNOWN_VALUE) == KNOWN_FINGERPRINT


def test_canonical_encoding_is_sorted_utf8_json_without_whitespace() -> None:
    assert canonical_bytes(KNOWN_VALUE) == (b'{"a":"x","b":[1,2],"c":null,"d":{"y":1.5,"z":true}}')
    assert canonical_bytes({"k": "é"}) == '{"k":"é"}'.encode()


def test_mapping_key_order_does_not_change_the_fingerprint() -> None:
    left = {"a": 1, "b": {"x": [1, 2], "y": 2}}
    right = {"b": {"y": 2, "x": [1, 2]}, "a": 1}
    assert fingerprint(left) == fingerprint(right)


@given(
    st.dictionaries(
        st.text(max_size=5),
        st.recursive(
            st.none() | st.booleans() | st.integers() | st.text(max_size=5),
            lambda children: (
                st.lists(children, max_size=3)
                | st.dictionaries(st.text(max_size=5), children, max_size=3)
            ),
            max_leaves=6,
        ),
        max_size=6,
    )
)
def test_fingerprint_is_independent_of_mapping_insertion_order(mapping: dict[str, object]) -> None:
    assert fingerprint(mapping) == fingerprint(dict(reversed(list(mapping.items()))))


def test_sequence_order_does_change_the_fingerprint() -> None:
    assert fingerprint([1, 2]) != fingerprint([2, 1])


def test_set_order_does_not_change_the_fingerprint() -> None:
    assert fingerprint({"a", "b", "c"}) == fingerprint({"c", "a", "b"})


def test_pydantic_models_and_dataclasses_fingerprint_as_their_plain_data() -> None:
    assert fingerprint(Point(x=1, y="a")) == fingerprint({"x": 1, "y": "a"})
    assert fingerprint(Boxed("l", [1, 2])) == fingerprint({"label": "l", "values": [1, 2]})
    assert fingerprint(Point(x=1, y="a")) != fingerprint(Point(x=2, y="a"))


def test_paths_bytes_enums_and_decimals_have_stable_encodings() -> None:
    assert fingerprint(Path("/a/b")) == fingerprint("/a/b")
    assert fingerprint(b"\x00\xff") == fingerprint("00ff")
    assert fingerprint(RunStatus.succeeded) == fingerprint("succeeded")
    assert fingerprint(Decimal("1.50")) == fingerprint("1.50")


def test_values_without_a_canonical_encoding_are_rejected() -> None:
    with pytest.raises(FingerprintError):
        fingerprint(object())


def test_fingerprint_file_hashes_the_file_bytes(tmp_path: Path) -> None:
    path = tmp_path / "artifact.bin"
    payload = b"hello world\n" * 200_000  # larger than one read chunk
    path.write_bytes(payload)
    assert fingerprint_file(path) == f"sha256:{hashlib.sha256(payload).hexdigest()}"
    path.write_bytes(payload + b"!")
    assert fingerprint_file(path) != f"sha256:{hashlib.sha256(payload).hexdigest()}"


def test_fingerprint_is_identical_in_another_process() -> None:
    for seed in ("0", "1", "424242"):
        result = subprocess.run(
            [sys.executable, "-c", _OTHER_PROCESS],
            env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": _SRC},
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == KNOWN_FINGERPRINT

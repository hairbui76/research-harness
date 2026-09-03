"""Fixtures shared by the plugin boundary and example-plugin contract tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import BaseModel

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plugins"


@dataclass
class RecordingGateway:
    """An inner gateway that records what reached it, and never reaches the harness."""

    calls: list[tuple[str, str]] = field(default_factory=list)

    def call(self, name: str, request: BaseModel, *, actor: str) -> object:
        """Record the call and answer with a marker the test can assert on."""
        self.calls.append((name, actor))
        return {"capability": name, "actor": actor}


class Request(BaseModel):
    """A trivial capability request DTO, so tests do not depend on a real one."""

    work_id: str = "W0001"


@pytest.fixture
def fixtures_dir() -> Path:
    """Root of the fixture plugin directories."""
    return FIXTURES


@pytest.fixture
def minimal_dir() -> Path:
    """The example plugin of ROADMAP Task 14.3."""
    return FIXTURES / "minimal"


@pytest.fixture
def gateway() -> RecordingGateway:
    """A fresh recording gateway per test."""
    return RecordingGateway()

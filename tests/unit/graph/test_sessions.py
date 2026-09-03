"""Pure session-projection rules: authority, inherited visibility, and the registry entry."""

from __future__ import annotations

import pytest

from research_harness.domain.base import Provenance
from research_harness.domain.conversation import ConversationSession, Visibility
from research_harness.domain.graph import GraphVisibility
from research_harness.domain.ids import ConversationSessionId
from research_harness.graph.projectors import default_projectors
from research_harness.graph.sessions import (
    SessionProjector,
    message_visibility,
    session_visibility,
)

HUMAN = Provenance.human("human:alice")


def make_session(visibility: Visibility) -> ConversationSession:
    """A session record with nothing in it but the field under test."""
    return ConversationSession(
        id=ConversationSessionId("CS0001"),
        title="Notes on tokenization",
        visibility=visibility,
        provenance=HUMAN,
    )


@pytest.mark.parametrize(
    ("visibility", "expected"),
    [
        (Visibility.PRIVATE, GraphVisibility.PRIVATE),
        (Visibility.PROJECT, GraphVisibility.PROJECT),
    ],
)
def test_a_session_node_carries_the_egress_class_of_its_record(
    visibility: Visibility, expected: GraphVisibility
) -> None:
    assert session_visibility(make_session(visibility)) == expected


@pytest.mark.parametrize(
    ("session", "member", "expected"),
    [
        (Visibility.PRIVATE, Visibility.PRIVATE, GraphVisibility.PRIVATE),
        (Visibility.PRIVATE, Visibility.PROJECT, GraphVisibility.PRIVATE),
        (Visibility.PRIVATE, None, GraphVisibility.PRIVATE),
        (Visibility.PROJECT, Visibility.PRIVATE, GraphVisibility.PRIVATE),
        (Visibility.PROJECT, Visibility.PROJECT, GraphVisibility.PROJECT),
        (Visibility.PROJECT, None, GraphVisibility.PROJECT),
    ],
)
def test_a_member_never_becomes_more_visible_than_the_session_holding_it(
    session: Visibility, member: Visibility | None, expected: GraphVisibility
) -> None:
    """A `project` message inside a `private` session is still private (graph spec §8).

    If the member's own field could win, marking one message `project` would publish it
    out of a private session — the "route around the restriction" the spec forbids, one
    field wide.
    """
    assert message_visibility(make_session(session), member) == expected


def test_the_session_projector_is_registered_once_in_the_default_registry() -> None:
    """A namespace joins by being in `default_projectors`; nothing else changes."""
    names = [projector.name for projector in default_projectors()]

    assert names.count("session") == 1
    assert isinstance(
        next(item for item in default_projectors() if item.name == "session"), SessionProjector
    )

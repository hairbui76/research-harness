"""A workspace, a session, and a way to put accepted state in front of the assembler."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.domain.base import Provenance
from research_harness.domain.claim import Claim, ClaimAssessment, ClaimScopeSpec, ClaimSemantics
from research_harness.domain.conversation import (
    AuthorityLabel,
    ConversationSession,
    Message,
    MessageRole,
    ReferenceBlock,
    TextBlock,
    Visibility,
)
from research_harness.domain.enums import (
    ClaimScope,
    ClaimStatus,
    ClaimType,
    DecisionStatus,
    DecisionType,
    StaleState,
)
from research_harness.domain.ids import ClaimId, ConversationSessionId, DecisionId, MessageId
from research_harness.domain.research import Decision
from research_harness.workspace.conversations import ConversationStore
from research_harness.workspace.repository import WorkspaceRepository

HUMAN = Provenance.human()


@pytest.fixture
def repo(tmp_path: Path) -> WorkspaceRepository:
    return WorkspaceRepository.init(tmp_path / "project", "conversation-unit")


@pytest.fixture
def ctx(repo: WorkspaceRepository) -> CapabilityContext:
    return CapabilityContext(repo=repo)


@pytest.fixture
def store(repo: WorkspaceRepository) -> ConversationStore:
    return ConversationStore(repo.layout)


@pytest.fixture
def session(store: ConversationStore) -> ConversationSession:
    return store.create_session(title="Latency study", provenance=HUMAN)


def say(
    session: ConversationSessionId,
    text: str,
    *,
    role: MessageRole = MessageRole.USER,
    references: tuple[str, ...] = (),
    visibility: Visibility = Visibility.PRIVATE,
) -> Callable[[MessageId], Message]:
    """Builder for one transcript entry; the store supplies the allocated id."""

    def build(message_id: MessageId) -> Message:
        blocks: list[TextBlock | ReferenceBlock] = [TextBlock(text=text)]
        blocks.extend(
            ReferenceBlock(target=ClaimId(reference), authority=AuthorityLabel.ACCEPTED)
            for reference in references
        )
        return Message(
            id=message_id,
            session=session,
            role=role,
            blocks=tuple(blocks),
            visibility=visibility,
            provenance=HUMAN,
        )

    return build


def write_claim(
    repo: WorkspaceRepository,
    claim_id: str,
    statement: str,
    *,
    status: ClaimStatus = ClaimStatus.SUPPORTED,
    stale: StaleState = StaleState.FRESH,
) -> Claim:
    """One Claim on disk, written straight through the repository for a unit fixture."""
    claim = Claim(
        id=ClaimId(claim_id),
        statement=statement,
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(subject="latency", predicate="drops under", object="batching"),
        scope=ClaimScopeSpec(level=ClaimScope.CORPUS_PATTERN),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.CORPUS_PATTERN,
            allowed_strength=ClaimScope.CORPUS_PATTERN,
            status=status,
        ),
        stale=stale,
        provenance=HUMAN,
    )
    path = repo.layout.claim_file(claim.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    from research_harness.workspace.serialization import canonical_bytes

    path.write_bytes(canonical_bytes(claim))
    return claim


def write_decision(
    repo: WorkspaceRepository,
    decision_id: str,
    rationale: str,
    *,
    claim: str | None = None,
    status: DecisionStatus = DecisionStatus.ACCEPTED,
) -> Decision:
    """One accepted Decision on disk, for the conflict rule to find."""
    decision = Decision(
        id=DecisionId(decision_id),
        type=DecisionType.OTHER,
        status=status,
        title="latency ceiling",
        rationale=rationale,
        claim=None if claim is None else ClaimId(claim),
        provenance=HUMAN,
    )
    path = repo.layout.decision_file(decision.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    from research_harness.workspace.serialization import canonical_bytes

    path.write_bytes(canonical_bytes(decision))
    return decision

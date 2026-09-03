"""What the assembler packs, what it refuses, and why the receipt can prove it.

The invariants under test are the ones Phase 18 is measured against: the order of
`CONTEXT_ORDER`, a token budget per class, privacy applied before packing, accepted state
winning a conflict with remembered chat, and one deterministic token estimator.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from research_harness.conversation.context import (
    CONTRADICTION_CUES,
    ContextAssembler,
    ContextBudget,
    ProviderProfile,
    estimate_tokens,
    reference_tokens,
)
from research_harness.conversation.retrieval import Excerpt, GraphExcerpts, TranscriptScan
from research_harness.domain.conversation import (
    CONTEXT_ORDER,
    AuthorityLabel,
    ContextClass,
    ConversationSession,
    EgressClass,
    MessageRole,
    OmissionReason,
    Visibility,
)
from research_harness.domain.enums import ClaimStatus, StaleState
from research_harness.privacy.policy import EgressPolicy
from research_harness.workspace.conversations import ConversationStore
from research_harness.workspace.repository import WorkspaceRepository
from tests.unit.conversation.conftest import HUMAN, say, write_claim, write_decision

EXTERNAL = ProviderProfile(
    provider="vendor-a", model="model-x", egress=EgressClass.EXTERNAL, vision=False
)
LOCAL = ProviderProfile(provider="local", model="model-y", egress=EgressClass.LOCAL)


def assembler(
    repo: WorkspaceRepository, store: ConversationStore, **kwargs: object
) -> ContextAssembler:
    return ContextAssembler(repo, store, **kwargs)  # type: ignore[arg-type]


# -- the estimator -----------------------------------------------------------


def test_the_token_estimator_is_deterministic_and_floors_by_class() -> None:
    text = "latency dropped by nine percent"
    first = estimate_tokens(text, ContextClass.CURRENT_SESSION)
    assert first == estimate_tokens(text, ContextClass.CURRENT_SESSION)
    assert first == len(text) // 4 + (1 if len(text) % 4 else 0)
    assert estimate_tokens("hi", ContextClass.ACCEPTED_STATE) == 16
    assert estimate_tokens("", ContextClass.POLICY) == 0


def test_a_class_budget_never_exceeds_the_total() -> None:
    budget = ContextBudget(total=1000)
    allocations = budget.allocations()
    assert [item.context_class for item in allocations] == list(CONTEXT_ORDER)
    assert sum(item.tokens for item in allocations) == 1000


def test_stable_ids_are_recognised_with_or_without_an_at_sign() -> None:
    found = reference_tokens("compare @E0482 with C0041 and the older E0482")
    assert found == ("E0482", "C0041")


# -- order and budgets -------------------------------------------------------


def test_the_pack_follows_the_context_order(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    write_claim(repo, "C0001", "Batching reduces tail latency across the corpus.")
    store.append_message(session.id, say(session.id, "What do we know about latency?"))

    assembled = assembler(repo, store).assemble(
        session.id, "latency and batching", model=LOCAL, policy=EgressPolicy()
    )
    order = {context_class: index for index, context_class in enumerate(CONTEXT_ORDER)}
    positions = [order[item.context_class] for item in assembled.receipt.included]
    assert positions == sorted(positions)
    assert assembled.receipt.included[0].context_class is ContextClass.POLICY


def test_an_item_that_does_not_fit_is_omitted_with_the_tokens_it_would_have_cost(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    store.append_message(session.id, say(session.id, "latency " * 400))

    assembled = assembler(repo, store).assemble(
        session.id, "latency", model=LOCAL, budget=ContextBudget(total=200)
    )
    dropped = [
        item for item in assembled.receipt.omitted if item.reason is OmissionReason.TOKEN_BUDGET
    ]
    assert dropped, "a message far larger than its class budget must be reported, not hidden"
    assert dropped[0].tokens > 0
    assert "budget" in (dropped[0].detail or "")


def test_the_pack_never_spends_more_than_it_was_allocated(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    for index in range(12):
        store.append_message(session.id, say(session.id, f"message {index} about latency " * 20))

    assembled = assembler(repo, store).assemble(
        session.id, "latency", model=LOCAL, budget=ContextBudget(total=600)
    )
    spent = assembled.receipt.tokens_by_class()
    for budget in assembled.budgets:
        assert spent.get(budget.context_class, 0) <= budget.tokens
    assert assembled.receipt.total_tokens() <= 600


def test_the_current_session_is_packed_newest_first_but_reads_oldest_first(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    for index in range(6):
        store.append_message(session.id, say(session.id, f"turn {index} about latency " * 12))

    assembled = assembler(repo, store).assemble(
        session.id, "latency", model=LOCAL, budget=ContextBudget(total=700)
    )
    included = [
        item
        for item in assembled.receipt.included
        if item.context_class is ContextClass.CURRENT_SESSION
    ]
    kept = [str(item.id) for item in included]
    assert kept == sorted(kept), "what is packed is rendered oldest first"
    assert "M0006" in kept, "the newest turn is the one a budget must never drop"
    dropped = {
        str(item.id)
        for item in assembled.receipt.omitted
        if item.reason is OmissionReason.TOKEN_BUDGET
    }
    assert "M0001" in dropped, "the oldest turn is the one the budget drops first"


# -- privacy -----------------------------------------------------------------


def test_a_private_message_never_reaches_an_external_provider(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    store.append_message(session.id, say(session.id, "unpublished latency numbers"))

    assembled = assembler(repo, store).assemble(session.id, "latency", model=EXTERNAL)
    blocked = [
        item for item in assembled.receipt.omitted if item.reason is OmissionReason.EGRESS_BLOCKED
    ]
    assert blocked, "a private transcript may not be packed for an external provider"
    assert not [
        item
        for item in assembled.receipt.included
        if item.context_class is ContextClass.CURRENT_SESSION
    ]


def test_the_same_private_message_reaches_a_local_provider(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    store.append_message(session.id, say(session.id, "unpublished latency numbers"))

    assembled = assembler(repo, store).assemble(session.id, "latency", model=LOCAL)
    assert [
        item
        for item in assembled.receipt.included
        if item.context_class is ContextClass.CURRENT_SESSION
    ]
    assert not [
        item for item in assembled.receipt.omitted if item.reason is OmissionReason.EGRESS_BLOCKED
    ]


def test_a_private_prior_session_excerpt_is_blocked_and_the_reason_is_recorded(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    earlier = store.create_session(title="Earlier latency work", provenance=HUMAN)
    store.append_message(
        earlier.id, say(earlier.id, "we measured latency at nine percent on the pilot corpus")
    )

    assembled = assembler(repo, store, sources=[TranscriptScan(store)]).assemble(
        session.id, "what did we measure about latency", model=EXTERNAL
    )
    blocked = [
        item
        for item in assembled.receipt.omitted
        if item.context_class is ContextClass.PRIOR_SESSIONS
        and item.reason is OmissionReason.EGRESS_BLOCKED
    ]
    assert blocked, "the receipt must say a private excerpt was withheld, not stay silent"
    assert "external provider" in (blocked[0].detail or "")


def test_a_project_visible_excerpt_reaches_an_external_provider(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    earlier = store.create_session(
        title="Shared latency work", provenance=HUMAN, visibility=Visibility.PROJECT
    )
    store.append_message(
        earlier.id,
        say(
            earlier.id,
            "we measured latency at nine percent on the pilot corpus",
            visibility=Visibility.PROJECT,
        ),
    )

    assembled = assembler(repo, store, sources=[TranscriptScan(store)]).assemble(
        session.id, "what did we measure about latency", model=EXTERNAL
    )
    assert [
        item
        for item in assembled.receipt.included
        if item.context_class is ContextClass.PRIOR_SESSIONS
    ]


def test_source_text_egress_can_be_refused_by_the_project_policy(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    write_claim(repo, "C0001", "Batching reduces tail latency across the corpus.")

    assembled = assembler(repo, store).assemble(
        session.id,
        "batching and latency",
        model=EXTERNAL,
        policy=EgressPolicy(allow_source_text=False),
    )
    refused = [
        item for item in assembled.receipt.omitted if item.reason is OmissionReason.PRIVACY_POLICY
    ]
    assert refused
    assert "allow_source_text" in (refused[0].detail or "")


# -- accepted state outranks chat --------------------------------------------


def test_accepted_state_wins_when_a_message_contradicts_it(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    write_claim(repo, "C0001", "Batching reduces tail latency across the corpus.")
    store.append_message(
        session.id,
        say(
            session.id,
            "Actually C0001 is wrong, batching made latency worse in our run.",
            references=("C0001",),
        ),
    )

    assembled = assembler(repo, store).assemble(
        session.id, "what does C0001 say about batching latency", model=LOCAL
    )
    included = {str(item.id) for item in assembled.receipt.included if item.id is not None}
    conflicted = [
        item
        for item in assembled.receipt.omitted
        if item.reason is OmissionReason.CONFLICTS_WITH_ACCEPTED
    ]
    assert "C0001" in included, "the accepted claim is what the model is shown"
    assert conflicted, "the contradicting message is left out, and the receipt says so"
    assert assembled.discrepancies, "the disagreement is surfaced for the inspector"
    assert assembled.discrepancies[0].accepted == "C0001"
    assert any(cue in (conflicted[0].detail or "") for cue in CONTRADICTION_CUES)


def test_an_accepted_decision_about_the_same_claim_outranks_a_remembered_message(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    write_claim(repo, "C0001", "Batching reduces tail latency across the corpus.")
    write_decision(repo, "D0001", "the corpus-level ceiling stands", claim="C0001")
    store.append_message(
        session.id, say(session.id, "we can state C0001 universally", references=("C0001",))
    )

    assembled = assembler(repo, store).assemble(
        session.id, "can we state C0001 universally", model=LOCAL
    )
    conflicted = [
        item
        for item in assembled.receipt.omitted
        if item.reason is OmissionReason.CONFLICTS_WITH_ACCEPTED
    ]
    assert conflicted
    assert assembled.discrepancies[0].accepted == "D0001"


def test_a_message_that_merely_mentions_accepted_state_is_still_packed(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    write_claim(repo, "C0001", "Batching reduces tail latency across the corpus.")
    store.append_message(
        session.id, say(session.id, "C0001 is the one I was thinking of", references=("C0001",))
    )

    assembled = assembler(repo, store).assemble(session.id, "C0001 batching", model=LOCAL)
    assert not assembled.discrepancies
    assert [
        item
        for item in assembled.receipt.included
        if item.context_class is ContextClass.CURRENT_SESSION
    ]


# -- references --------------------------------------------------------------


def test_an_unresolved_reference_is_reported_and_not_invented(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    assembled = assembler(repo, store).assemble(
        session.id, "what about @C9999?", ("C9999",), model=LOCAL
    )
    assert assembled.unresolved == ("C9999",)
    assert [
        item
        for item in assembled.receipt.omitted
        if item.reason is OmissionReason.UNRESOLVED_REFERENCE
    ]


def test_a_referenced_claim_is_packed_with_its_authority_label(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    write_claim(repo, "C0001", "Batching reduces tail latency.", status=ClaimStatus.QUALIFIED)

    assembled = assembler(repo, store).assemble(session.id, "", ("@C0001",), model=LOCAL)
    packed = [item for item in assembled.receipt.included if str(item.id) == "C0001"]
    assert packed and packed[0].authority is AuthorityLabel.QUALIFIED


def test_a_stale_object_is_omitted_as_stale_unless_it_was_asked_for(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    write_claim(repo, "C0001", "Batching reduces tail latency.", stale=StaleState.STALE)

    by_relevance = assembler(repo, store).assemble(session.id, "batching tail latency", model=LOCAL)
    assert [item for item in by_relevance.receipt.omitted if item.reason is OmissionReason.STALE]

    by_reference = assembler(repo, store).assemble(session.id, "", ("C0001",), model=LOCAL)
    packed = [item for item in by_reference.receipt.included if str(item.id) == "C0001"]
    assert packed and packed[0].authority is AuthorityLabel.STALE


def test_an_object_the_draft_is_not_about_is_reported_as_low_relevance(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    write_claim(repo, "C0001", "Batching reduces tail latency across the corpus.")

    assembled = assembler(repo, store).assemble(
        session.id,
        "does batching improve throughput for encrypted flows in production",
        model=LOCAL,
    )
    reasons = {item.reason for item in assembled.receipt.omitted}
    assert OmissionReason.LOW_RELEVANCE in reasons


# -- retrieval sources -------------------------------------------------------


class FakeGraph:
    """A `GraphContext` that answers with one fragment, as the projection would."""

    def __init__(self, *, visibility: str = "private") -> None:
        self.calls: list[dict[str, object]] = []
        self._visibility = visibility

    def context_fragments(
        self,
        *,
        session: str | None = None,
        query: str = "",
        references: Sequence[str] = (),
        visibility: str = "private",
        limit: int = 12,
    ) -> tuple[object, ...]:
        self.calls.append({"session": session, "query": query, "limit": limit})

        class Fragment:
            id = "M0009"
            context_class = "prior_sessions"
            source_pointer = "rh://session/CS0009?message=M0009"
            text = "the pilot corpus showed a nine percent latency drop"
            tokens = 12
            score = 0.9
            authority = "private"
            visibility = self._visibility

        return (Fragment(),)


def test_the_graph_is_preferred_and_its_fragments_are_packed(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    graph = FakeGraph(visibility="project")

    assembled = assembler(
        repo, store, sources=[GraphExcerpts(graph), TranscriptScan(store)]
    ).assemble(session.id, "latency on the pilot corpus", model=EXTERNAL)

    assert graph.calls, "the graph source is asked when it is configured"
    packed = [
        item
        for item in assembled.receipt.included
        if item.context_class is ContextClass.PRIOR_SESSIONS
    ]
    assert packed and packed[0].source == "rh://session/CS0009?message=M0009"


def test_a_private_graph_fragment_is_blocked_for_an_external_provider(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    assembled = assembler(repo, store, sources=[GraphExcerpts(FakeGraph())]).assemble(
        session.id, "latency on the pilot corpus", model=EXTERNAL
    )
    assert [
        item for item in assembled.receipt.omitted if item.reason is OmissionReason.EGRESS_BLOCKED
    ]


def test_a_source_that_raises_does_not_fail_the_assembly(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    class Broken:
        name = "broken"

        def excerpts(self, **kwargs: object) -> Sequence[Excerpt]:
            raise RuntimeError("the projection is mid-rebuild")

    assembled = assembler(repo, store, sources=[Broken(), TranscriptScan(store)]).assemble(
        session.id, "latency", model=LOCAL
    )
    assert assembled.receipt.included, "a broken index degrades retrieval, it does not fail a send"


# -- the pack ----------------------------------------------------------------


def test_a_preview_records_that_nothing_was_sent(
    repo: WorkspaceRepository, store: ConversationStore, session: ConversationSession
) -> None:
    from research_harness.domain.ids import ContextPackId

    assembled = assembler(repo, store).assemble(session.id, "latency", model=EXTERNAL)
    pack = assembled.pack(ContextPackId.make(1), session.id, HUMAN, egress=EgressClass.NONE)
    assert pack.egress is EgressClass.NONE
    assert pack.model is not None and pack.model.provider == "vendor-a"


@pytest.mark.parametrize("role", [MessageRole.SYSTEM])
def test_a_system_message_is_not_conversational_memory(
    repo: WorkspaceRepository,
    store: ConversationStore,
    session: ConversationSession,
    role: MessageRole,
) -> None:
    store.append_message(session.id, say(session.id, "latency policy", role=role))

    assembled = assembler(repo, store).assemble(session.id, "latency", model=LOCAL)
    assert not [
        item
        for item in assembled.receipt.included
        if item.context_class is ContextClass.CURRENT_SESSION
    ]

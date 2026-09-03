"""Cross-session retrieval: deterministic scoring, a direct scan, and the graph adapter."""

from __future__ import annotations

from typing import Any

from research_harness.conversation.retrieval import (
    Excerpt,
    GraphExcerpts,
    TranscriptScan,
    graph_is_available,
    relevance,
    terms,
)
from research_harness.domain.conversation import ConversationSession, Visibility
from research_harness.domain.ids import MessageId
from research_harness.workspace.conversations import ConversationStore
from tests.unit.conversation.conftest import HUMAN, say

# -- scoring -----------------------------------------------------------------


def test_terms_drops_stopwords_and_keeps_ids() -> None:
    assert terms("What about the latency in E0482?") == ["latency", "e0482"]


def test_relevance_is_deterministic_and_bounded() -> None:
    query = terms("tail latency under batching")
    text = "batching reduced tail latency by nine percent"
    first = relevance(query, text)
    assert first == relevance(query, text)
    assert 0.0 < first <= 1.0
    assert relevance(query, "an unrelated note about funding") == 0.0
    assert relevance([], text) == 0.0


def test_a_passage_covering_more_of_the_query_scores_higher() -> None:
    query = terms("tail latency under batching")
    both = relevance(query, "batching reduced tail latency")
    one = relevance(query, "batching was enabled")
    assert both > one


# -- the direct scan ---------------------------------------------------------


def test_the_transcript_scan_skips_the_session_being_written(
    store: ConversationStore, session: ConversationSession
) -> None:
    store.append_message(session.id, say(session.id, "latency on the pilot corpus"))
    other = store.create_session(title="Earlier", provenance=HUMAN)
    store.append_message(other.id, say(other.id, "latency on the pilot corpus was nine percent"))

    found = TranscriptScan(store).excerpts(query="latency pilot corpus", session=str(session.id))
    assert [item.session for item in found] == [str(other.id)]
    assert found[0].identity == MessageId("M0002")


def test_the_scan_labels_visibility_rather_than_filtering_it(
    store: ConversationStore, session: ConversationSession
) -> None:
    """The receipt has to be able to say a private excerpt was withheld, and why."""
    private = store.create_session(title="Private", provenance=HUMAN)
    store.append_message(private.id, say(private.id, "unreleased latency numbers"))
    shared = store.create_session(title="Shared", provenance=HUMAN, visibility=Visibility.PROJECT)
    store.append_message(
        shared.id,
        say(shared.id, "published latency numbers", visibility=Visibility.PROJECT),
    )

    found = TranscriptScan(store).excerpts(query="latency numbers", session=str(session.id))
    labels = {item.visibility for item in found}
    assert labels == {Visibility.PRIVATE, Visibility.PROJECT}


def test_the_scan_answers_when_the_projection_is_gone(
    store: ConversationStore, session: ConversationSession
) -> None:
    other = store.create_session(title="Earlier", provenance=HUMAN)
    store.append_message(other.id, say(other.id, "latency on the pilot corpus"))
    research = store.layout.research_dir
    if research.is_dir():
        import shutil

        shutil.rmtree(research)

    found = TranscriptScan(store).excerpts(query="latency pilot", session=str(session.id))
    assert found, "a deleted index may cost ranking, never access to a transcript"


def test_a_summary_is_offered_when_it_matches(
    store: ConversationStore, session: ConversationSession
) -> None:
    other = store.create_session(title="Earlier", provenance=HUMAN)
    store.append_message(other.id, say(other.id, "latency on the pilot corpus"))
    store.regenerate_summary(other.id)

    found = TranscriptScan(store).excerpts(query="latency pilot corpus", session=str(session.id))
    assert {item.kind for item in found} == {"message", "summary"}


# -- the graph adapter -------------------------------------------------------


class Fragment:
    """Shaped like `domain.graph.ContextFragment`, without importing the graph."""

    id = "E0482"
    context_class = "prior_sessions"
    source_pointer = "rh://evidence/E0482"
    text = "the pilot corpus showed a nine percent drop"
    tokens = 11
    score = 0.75
    authority = "accepted"
    visibility = "project"


class Graph:
    def __init__(self, fragments: tuple[Any, ...] = (Fragment(),)) -> None:
        self._fragments = fragments
        self.asked: list[dict[str, Any]] = []

    def context_fragments(self, **kwargs: Any) -> tuple[Any, ...]:
        self.asked.append(kwargs)
        return self._fragments


def test_the_request_focus_is_passed_to_the_graph_as_its_own_session() -> None:
    """`session=` is the graph's focus, not a filter: it is how it tells current from prior."""
    graph = Graph()
    GraphExcerpts(graph).excerpts(query="pilot corpus", session="CS0002")
    assert graph.asked[0]["session"] == "CS0002"


def test_two_fragments_from_one_transcript_get_distinct_pointers() -> None:
    """The graph points at a file; one file holds a whole transcript (graph spec 7)."""

    class First(Fragment):
        id = "M0001"
        source_pointer = "conversations/CS0001/messages.jsonl"
        text = "the pilot corpus showed a nine percent drop"

    class Second(Fragment):
        id = "M0002"
        source_pointer = "conversations/CS0001/messages.jsonl"
        text = "and the tail flattened after batching"

    found = GraphExcerpts(Graph((First(), Second()))).excerpts(query="pilot")
    assert len({item.source for item in found}) == 2
    assert found[0].source == "conversations/CS0001/messages.jsonl#M0001"


def test_a_pointer_that_already_names_the_fragment_is_left_alone() -> None:
    class Linked(Fragment):
        id = "M0001"
        source_pointer = "rh://session/CS0001?message=M0001"

    found = GraphExcerpts(Graph((Linked(),))).excerpts(query="pilot")
    assert found[0].source == "rh://session/CS0001?message=M0001"


def test_a_graph_fragment_becomes_an_excerpt_with_its_pointer_and_labels() -> None:
    found = GraphExcerpts(Graph()).excerpts(query="pilot corpus")
    assert len(found) == 1
    excerpt = found[0]
    assert excerpt.source == "rh://evidence/E0482"
    assert excerpt.visibility is Visibility.PROJECT
    assert str(excerpt.identity) == "E0482"
    assert excerpt.score == 0.75


def test_the_adapter_keeps_only_the_classes_it_was_asked_for() -> None:
    class Other(Fragment):
        context_class = "accepted_state"

    assert GraphExcerpts(Graph((Other(),))).excerpts(query="x") == ()


def test_a_fragment_with_no_text_is_dropped_rather_than_guessed_at() -> None:
    class Empty(Fragment):
        text = "   "

    assert GraphExcerpts(Graph((Empty(),))).excerpts(query="x") == ()


def test_a_graph_that_raises_answers_emptily() -> None:
    class Broken:
        def context_fragments(self, **kwargs: Any) -> tuple[Any, ...]:
            raise RuntimeError("mid-rebuild")

    assert GraphExcerpts(Broken()).excerpts(query="x") == ()


def test_an_excerpt_is_passed_through_unchanged() -> None:
    excerpt = Excerpt(text="already an excerpt", source="rh://x", score=0.5, kind="prior_sessions")
    assert GraphExcerpts(Graph((excerpt,))).excerpts(query="x") == (excerpt,)


# -- availability ------------------------------------------------------------


def test_graph_availability_reads_the_status_it_finds() -> None:
    class Status:
        def __init__(self, current: bool) -> None:
            self.current = current
            self.exists = current

    class Projection:
        def __init__(self, current: bool) -> None:
            self._current = current

        def status(self) -> Status:
            return Status(self._current)

    assert graph_is_available(Projection(True)) is True
    assert graph_is_available(Projection(False)) is False
    assert graph_is_available(object()) is False


def test_a_status_that_raises_means_unavailable() -> None:
    class Broken:
        def status(self) -> Any:
            raise RuntimeError("no database")

    assert graph_is_available(Broken()) is False

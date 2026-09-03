"""Conversation schemas: authority, attempts, attachment transitions, and receipts."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from research_harness.domain import (
    ArtifactId,
    ClaimId,
    ContextPackId,
    ConversationSessionId,
    EvidenceId,
    MessageId,
    QuestionId,
    SessionAttachmentId,
    VersionId,
    WorkId,
)
from research_harness.domain.conversation import (
    ATTACHMENT_TRANSITIONS,
    CONTEXT_ORDER,
    STORED_ATTACHMENT_STATES,
    AttachmentBlock,
    AttachmentState,
    AttemptStatus,
    AuthorityLabel,
    ClassBudget,
    ContextClass,
    ContextItem,
    ContextPack,
    ContextReceipt,
    ConversationSession,
    EgressClass,
    Message,
    MessageAttempt,
    MessageRole,
    ModelIdentity,
    OmissionReason,
    OmittedContextItem,
    PromotionRequest,
    PromotionTarget,
    ReferenceBlock,
    SessionAttachment,
    SessionDefaults,
    TextBlock,
    Visibility,
    allowed_attachment_transitions,
    transition_attachment,
)
from research_harness.domain.errors import TransitionError
from tests.unit.domain import strategies as sty

ROUNDTRIP = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

SESSION = ConversationSessionId("CS0001")
HASH = sty.HASH_A


def assert_roundtrips[ModelT: BaseModel](model: ModelT) -> None:
    """A model must survive json-mode dumping and json serialization unchanged."""
    same_class = type(model)
    assert same_class.model_validate(model.model_dump(mode="json")) == model
    assert same_class.model_validate_json(model.model_dump_json()) == model
    assert same_class.model_validate(model.model_dump()) == model


# --- deterministic builders -------------------------------------------------


def make_session(**overrides: Any) -> ConversationSession:
    fields: dict[str, Any] = {
        "id": SESSION,
        "title": "Tokenization terminology",
        "provenance": sty.HUMAN,
    }
    return ConversationSession(**{**fields, **overrides})


def make_message(**overrides: Any) -> Message:
    fields: dict[str, Any] = {
        "id": MessageId("M0042"),
        "session": SESSION,
        "role": MessageRole.USER,
        "blocks": (TextBlock(text="Which systems keep protocol field semantics?"),),
        "provenance": sty.HUMAN,
    }
    return Message(**{**fields, **overrides})


def state_fields(state: AttachmentState) -> dict[str, Any]:
    """The fields an attachment must carry to be valid in ``state``."""
    fields: dict[str, Any] = {}
    if state in STORED_ATTACHMENT_STATES:
        fields["content_hash"] = HASH
    if state is AttachmentState.FAILED:
        fields["failure_reason"] = "the file could not be read"
    if state is AttachmentState.IN_CORPUS:
        fields |= {
            "work": WorkId("W0017"),
            "version": VersionId("V0017-1"),
            "artifact": ArtifactId("A0017-1"),
        }
    return fields


def make_attachment(
    state: AttachmentState = AttachmentState.SELECTED, **overrides: Any
) -> SessionAttachment:
    fields: dict[str, Any] = {
        "id": SessionAttachmentId("SA0003"),
        "session": SESSION,
        "state": state,
        "filename": "paper.pdf",
        "media_type": "application/pdf",
        "size_bytes": 1024,
        "page_count": 12,
        "provenance": sty.HUMAN,
        **state_fields(state),
    }
    return SessionAttachment(**{**fields, **overrides})


def make_pack(**overrides: Any) -> ContextPack:
    receipt = ContextReceipt(
        included=(
            ContextItem(
                context_class=ContextClass.ACCEPTED_STATE,
                source="rh://claim/C0041",
                id=ClaimId("C0041"),
                authority=AuthorityLabel.ACCEPTED,
                tokens=120,
            ),
        ),
        omitted=(
            OmittedContextItem(
                context_class=ContextClass.PRIOR_SESSIONS,
                source="rh://session/CS0002?message=M0009",
                id=MessageId("M0009"),
                reason=OmissionReason.PRIVACY_POLICY,
                tokens=80,
            ),
        ),
    )
    fields: dict[str, Any] = {
        "id": ContextPackId("CP0001"),
        "session": SESSION,
        "receipt": receipt,
        "model": ModelIdentity(provider="vendor-a", model="model-x"),
        "egress": EgressClass.EXTERNAL,
        "provenance": sty.SYSTEM,
    }
    return ContextPack(**{**fields, **overrides})


# --- hypothesis strategies --------------------------------------------------


def text_blocks() -> st.SearchStrategy[TextBlock]:
    return st.builds(TextBlock, text=st.text(alphabet=sty.TEXT_ALPHABET, max_size=40))


def reference_blocks() -> st.SearchStrategy[ReferenceBlock]:
    return st.builds(
        ReferenceBlock,
        target=st.sampled_from(
            [WorkId.make, EvidenceId.make, ClaimId.make, MessageId.make]
        ).flatmap(lambda make: sty.numbers().map(make)),
        label=st.none() | sty.texts(),
        locator=st.none() | sty.texts(),
        authority=st.none() | st.sampled_from(list(AuthorityLabel)),
    )


@st.composite
def messages(draw: st.DrawFn) -> Message:
    """Valid messages across roles, attempts, and block kinds."""
    attachments = tuple(
        dict.fromkeys(draw(st.lists(sty.numbers().map(SessionAttachmentId.make), max_size=2)))
    )
    blocks: list[Any] = draw(st.lists(text_blocks() | reference_blocks(), min_size=1, max_size=3))
    blocks.extend(AttachmentBlock(attachment=attachment) for attachment in attachments)
    role = draw(st.sampled_from(list(MessageRole)))
    attempt = MessageAttempt()
    if role is not MessageRole.USER and draw(st.booleans()):
        attempt = MessageAttempt(
            number=2,
            status=AttemptStatus.INTERRUPTED,
            retry_of=MessageId.make(draw(sty.numbers())),
        )
    return Message(
        id=MessageId.make(draw(sty.numbers())),
        session=ConversationSessionId.make(draw(sty.numbers())),
        role=role,
        blocks=tuple(blocks),
        authority=draw(
            st.sampled_from(
                [label for label in AuthorityLabel if label is not AuthorityLabel.ACCEPTED]
            )
        ),
        visibility=draw(st.sampled_from(list(Visibility))),
        attachments=attachments,
        context_pack=draw(st.none() | sty.numbers().map(ContextPackId.make)),
        model=draw(st.none() | st.builds(ModelIdentity, provider=sty.texts(), model=sty.texts())),
        attempt=attempt,
        created_at=draw(sty.timestamps()),
        updated_at=draw(sty.timestamps()),
        provenance=draw(sty.provenances()),
    )


@st.composite
def attachments(draw: st.DrawFn) -> SessionAttachment:
    """Valid attachments in every state, with the fields each state requires."""
    state = draw(st.sampled_from(list(AttachmentState)))
    return make_attachment(
        state,
        id=SessionAttachmentId.make(draw(sty.numbers())),
        session=ConversationSessionId.make(draw(sty.numbers())),
        filename=draw(sty.texts()),
        media_type=draw(st.sampled_from(["application/pdf", "image/png"])),
        size_bytes=draw(st.integers(min_value=0, max_value=10**9)),
        page_count=draw(st.none() | st.integers(min_value=1, max_value=400)),
        description=draw(st.none() | sty.texts()),
        visibility=draw(st.sampled_from(list(Visibility))),
        created_at=draw(sty.timestamps()),
        updated_at=draw(sty.timestamps()),
        provenance=draw(sty.provenances()),
    )


@st.composite
def context_items(draw: st.DrawFn, index: int) -> ContextItem:
    return ContextItem(
        context_class=draw(st.sampled_from(list(ContextClass))),
        source=f"rh://item/{index}",
        id=draw(st.none() | sty.numbers().map(ClaimId.make)),
        authority=draw(st.sampled_from(list(AuthorityLabel))),
        label=draw(st.none() | sty.texts()),
        tokens=draw(st.integers(min_value=0, max_value=500)),
    )


@st.composite
def context_packs(draw: st.DrawFn) -> ContextPack:
    """Packs whose budgets always cover what the receipt says was spent."""
    included = [draw(context_items(index)) for index in range(draw(st.integers(0, 3)))]
    omitted = [
        OmittedContextItem(
            context_class=draw(st.sampled_from(list(ContextClass))),
            source=f"rh://omitted/{index}",
            reason=draw(st.sampled_from(list(OmissionReason))),
            detail=draw(st.none() | sty.texts()),
            tokens=draw(st.integers(min_value=0, max_value=500)),
        )
        for index in range(draw(st.integers(0, 2)))
    ]
    receipt = ContextReceipt(included=tuple(included), omitted=tuple(omitted))
    spent = receipt.tokens_by_class()
    return ContextPack(
        id=ContextPackId.make(draw(sty.numbers())),
        session=ConversationSessionId.make(draw(sty.numbers())),
        receipt=receipt,
        message=draw(st.none() | sty.numbers().map(MessageId.make)),
        model=draw(st.none() | st.builds(ModelIdentity, provider=sty.texts(), model=sty.texts())),
        egress=draw(st.sampled_from(list(EgressClass))),
        token_budget=receipt.total_tokens() + draw(st.integers(min_value=0, max_value=100)),
        budgets=tuple(
            ClassBudget(context_class=name, tokens=tokens) for name, tokens in spent.items()
        ),
        created_at=draw(sty.timestamps()),
        updated_at=draw(sty.timestamps()),
        provenance=draw(sty.provenances()),
    )


@st.composite
def promotion_requests(draw: st.DrawFn) -> PromotionRequest:
    target = draw(st.sampled_from(list(PromotionTarget)))
    candidate = target in {PromotionTarget.CLAIM_CANDIDATE, PromotionTarget.DECISION_CANDIDATE}
    return PromotionRequest(
        session=ConversationSessionId.make(draw(sty.numbers())),
        message=MessageId.make(draw(sty.numbers())),
        target=target,
        excerpt=draw(sty.texts()),
        rationale=draw(st.none() | sty.texts()),
        question=draw(st.none() | sty.numbers().map(QuestionId.make)),
        claim=(
            draw(st.none() | sty.numbers().map(ClaimId.make))
            if target is PromotionTarget.DECISION_CANDIDATE
            else None
        ),
        supporting_evidence=(
            tuple(dict.fromkeys(draw(st.lists(sty.numbers().map(EvidenceId.make), max_size=2))))
            if candidate
            else ()
        ),
        created_at=draw(sty.timestamps()),
        updated_at=draw(sty.timestamps()),
        provenance=draw(sty.provenances()),
    )


# --- round-trips ------------------------------------------------------------


@ROUNDTRIP
@given(
    st.builds(
        ConversationSession,
        id=sty.numbers().map(ConversationSessionId.make),
        title=sty.texts(),
        visibility=st.sampled_from(list(Visibility)),
        defaults=st.builds(
            SessionDefaults,
            model=st.none() | st.builds(ModelIdentity, provider=sty.texts(), model=sty.texts()),
            mode=st.none() | sty.texts(),
            token_budget=st.none() | st.integers(min_value=0, max_value=10**6),
        ),
        created_at=sty.timestamps(),
        updated_at=sty.timestamps(),
        provenance=sty.provenances(),
    )
)
def test_session_roundtrips(session: ConversationSession) -> None:
    assert_roundtrips(session)


@ROUNDTRIP
@given(messages())
def test_message_roundtrips(message: Message) -> None:
    assert_roundtrips(message)


@ROUNDTRIP
@given(attachments())
def test_attachment_roundtrips(attachment: SessionAttachment) -> None:
    assert_roundtrips(attachment)


@ROUNDTRIP
@given(context_packs())
def test_context_pack_roundtrips(pack: ContextPack) -> None:
    assert_roundtrips(pack)


@ROUNDTRIP
@given(promotion_requests())
def test_promotion_request_roundtrips(request: PromotionRequest) -> None:
    assert_roundtrips(request)


@ROUNDTRIP
@given(messages())
def test_message_ids_serialize_as_plain_strings(message: Message) -> None:
    dumped = message.model_dump(mode="json")
    assert type(dumped["id"]) is str
    assert type(dumped["session"]) is str
    for block in dumped["blocks"]:
        assert isinstance(block["kind"], str)


def test_content_blocks_keep_their_kind_through_a_round_trip() -> None:
    message = make_message(
        attachments=(SessionAttachmentId("SA0003"),),
        blocks=(
            TextBlock(text=r"The bound is $O(n \log n)$ for \[ x^2 \]."),
            ReferenceBlock(target=EvidenceId("E0482"), label="E0482"),
            AttachmentBlock(attachment=SessionAttachmentId("SA0003")),
        ),
    )
    restored = Message.model_validate(message.model_dump(mode="json"))
    assert restored == message
    assert isinstance(restored.blocks[0], TextBlock)
    assert isinstance(restored.blocks[1], ReferenceBlock)
    assert isinstance(restored.blocks[2], AttachmentBlock)
    assert r"$O(n \log n)$" in restored.text()


# --- authority --------------------------------------------------------------


def test_message_cannot_label_its_own_content_accepted() -> None:
    """Chat is working context; accepted state is only reached through review."""
    with pytest.raises(ValidationError, match="cannot be labelled accepted"):
        make_message(authority=AuthorityLabel.ACCEPTED)


@pytest.mark.parametrize(
    "label",
    [label for label in AuthorityLabel if label is not AuthorityLabel.ACCEPTED],
)
def test_message_may_carry_every_other_authority_label(label: AuthorityLabel) -> None:
    assert make_message(authority=label).authority is label


def test_a_completed_message_must_have_content() -> None:
    with pytest.raises(ValidationError, match="at least one content block"):
        make_message(blocks=())


def test_an_interrupted_stream_keeps_partial_content_and_is_flagged_incomplete() -> None:
    message = make_message(
        role=MessageRole.ASSISTANT,
        blocks=(TextBlock(text="The first half of the answer"),),
        attempt=MessageAttempt(status=AttemptStatus.INTERRUPTED),
    )
    assert message.incomplete
    assert message.text() == "The first half of the answer"
    empty = make_message(
        role=MessageRole.ASSISTANT,
        blocks=(),
        attempt=MessageAttempt(status=AttemptStatus.INTERRUPTED),
    )
    assert empty.incomplete


def test_a_retry_keeps_the_failed_attempt_it_replaces() -> None:
    failed = make_message(
        id=MessageId("M0043"),
        role=MessageRole.ASSISTANT,
        blocks=(),
        attempt=MessageAttempt(status=AttemptStatus.FAILED, error="provider unavailable"),
    )
    retry = make_message(
        id=MessageId("M0044"),
        role=MessageRole.ASSISTANT,
        blocks=(TextBlock(text="the answer"),),
        attempt=MessageAttempt(number=2, retry_of=failed.id),
    )
    assert failed.incomplete and failed.attempt.error == "provider unavailable"
    assert retry.attempt.retry_of == failed.id
    assert not retry.incomplete


def test_a_failed_attempt_must_say_why() -> None:
    with pytest.raises(ValidationError, match="record why it failed"):
        MessageAttempt(status=AttemptStatus.FAILED)


def test_a_retry_names_the_attempt_it_retries() -> None:
    with pytest.raises(ValidationError, match="must name the attempt it retries"):
        MessageAttempt(number=2)
    with pytest.raises(ValidationError, match="must name the attempt it retries"):
        MessageAttempt(retry_of=MessageId("M0001"))


def test_an_attempt_cannot_finish_before_it_started() -> None:
    with pytest.raises(ValidationError, match="cannot finish before it started"):
        MessageAttempt(
            started_at=sty.make_evidence().created_at,
            finished_at=sty.make_evidence().created_at.replace(year=2000),
        )


def test_a_user_message_is_not_a_model_attempt() -> None:
    with pytest.raises(ValidationError, match="not a model attempt"):
        make_message(
            role=MessageRole.USER,
            attempt=MessageAttempt(status=AttemptStatus.FAILED, error="nope"),
        )


def test_attachment_blocks_must_be_listed_in_the_message_index() -> None:
    with pytest.raises(ValidationError, match="unlisted attachments"):
        make_message(blocks=(AttachmentBlock(attachment=SessionAttachmentId("SA0003")),))
    with pytest.raises(ValidationError, match="same attachment twice"):
        make_message(attachments=(SessionAttachmentId("SA0003"), SessionAttachmentId("SA0003")))


def test_session_counters_and_summary_state_stay_consistent() -> None:
    with pytest.raises(ValidationError, match="both be set or both be empty"):
        make_session(message_count=3)
    with pytest.raises(ValidationError, match="recorded together"):
        make_session(message_count=1, last_message=MessageId("M0001"))
    with pytest.raises(ValidationError, match="when it was written"):
        make_session(summarized_through=MessageId("M0001"))


# --- attachment state machine -----------------------------------------------


def test_the_transition_table_covers_every_state() -> None:
    assert set(ATTACHMENT_TRANSITIONS) == set(AttachmentState)
    assert allowed_attachment_transitions()["ready"] == {
        "sending",
        "session_only",
        "promoting",
        "failed",
    }


@given(
    st.sampled_from(list(AttachmentState)),
    st.sampled_from(list(AttachmentState)),
)
def test_only_tabled_attachment_transitions_are_allowed(
    source: AttachmentState, target: AttachmentState
) -> None:
    attachment = make_attachment(source)
    if target in ATTACHMENT_TRANSITIONS[source]:
        moved = transition_attachment(attachment, target, **state_fields(target))
        assert moved.state is target
        assert moved.id == attachment.id
    else:
        with pytest.raises(TransitionError, match="is not allowed"):
            transition_attachment(attachment, target, **state_fields(target))


def test_the_documented_happy_path_walks_from_selection_to_the_corpus() -> None:
    attachment = make_attachment(AttachmentState.SELECTED)
    for state in (
        AttachmentState.VALIDATING,
        AttachmentState.READY,
        AttachmentState.SENDING,
        AttachmentState.SESSION_ONLY,
        AttachmentState.PROMOTING,
        AttachmentState.IN_CORPUS,
    ):
        attachment = transition_attachment(attachment, state, **state_fields(state))
    assert attachment.state is AttachmentState.IN_CORPUS
    assert attachment.work == WorkId("W0017")
    with pytest.raises(TransitionError):
        transition_attachment(attachment, AttachmentState.PROMOTING)


def test_a_failed_promotion_leaves_a_retryable_attachment() -> None:
    attachment = make_attachment(AttachmentState.SESSION_ONLY)
    promoting = transition_attachment(attachment, AttachmentState.PROMOTING)
    failed = transition_attachment(
        promoting, AttachmentState.FAILED, failure_reason="identity was ambiguous"
    )
    assert failed.content_hash == HASH
    retried = transition_attachment(failed, AttachmentState.PROMOTING)
    assert retried.state is AttachmentState.PROMOTING
    assert retried.failure_reason == "identity was ambiguous"


def test_a_stored_attachment_must_record_its_content_hash() -> None:
    with pytest.raises(ValidationError, match="content hash"):
        make_attachment(AttachmentState.READY, content_hash=None)


def test_only_an_attachment_in_the_corpus_carries_corpus_links() -> None:
    with pytest.raises(ValidationError, match="must link its Work"):
        make_attachment(AttachmentState.IN_CORPUS, artifact=None)
    with pytest.raises(ValidationError, match="corpus links belong"):
        make_attachment(AttachmentState.READY, work=WorkId("W0017"))


def test_a_failed_attachment_must_say_why() -> None:
    with pytest.raises(ValidationError, match="record why it failed"):
        make_attachment(AttachmentState.FAILED, failure_reason=None)


# --- context packs ----------------------------------------------------------


def test_context_order_is_the_documented_selection_order() -> None:
    assert set(CONTEXT_ORDER) == set(ContextClass)
    assert CONTEXT_ORDER[0] is ContextClass.POLICY
    assert CONTEXT_ORDER.index(ContextClass.ACCEPTED_STATE) < CONTEXT_ORDER.index(
        ContextClass.CURRENT_SESSION
    )


def test_a_receipt_reports_tokens_by_class_and_omissions_by_reason() -> None:
    pack = make_pack()
    assert pack.receipt.tokens_by_class() == {ContextClass.ACCEPTED_STATE: 120}
    assert pack.receipt.total_tokens() == 120
    grouped = pack.receipt.omissions_by_reason()
    assert list(grouped) == [OmissionReason.PRIVACY_POLICY]
    assert grouped[OmissionReason.PRIVACY_POLICY][0].id == MessageId("M0009")


def test_a_receipt_cannot_include_and_omit_the_same_source() -> None:
    with pytest.raises(ValidationError, match="both included and omitted"):
        ContextReceipt(
            included=(ContextItem(context_class=ContextClass.POLICY, source="rh://claim/C0041"),),
            omitted=(
                OmittedContextItem(
                    context_class=ContextClass.POLICY,
                    source="rh://claim/C0041",
                    reason=OmissionReason.STALE,
                ),
            ),
        )


def test_a_receipt_cannot_repeat_a_source() -> None:
    item = ContextItem(context_class=ContextClass.POLICY, source="policy://project")
    with pytest.raises(ValidationError, match="repeats a source pointer"):
        ContextReceipt(included=(item, item))


def test_a_pack_cannot_spend_more_than_it_was_allocated() -> None:
    with pytest.raises(ValidationError, match="used 120 tokens of the 50"):
        make_pack(budgets=(ClassBudget(context_class=ContextClass.ACCEPTED_STATE, tokens=50),))
    with pytest.raises(ValidationError, match="the pack used 120 tokens"):
        make_pack(token_budget=10)


def test_a_pack_budgets_each_class_once() -> None:
    with pytest.raises(ValidationError, match="budgeted at most once"):
        make_pack(
            budgets=(
                ClassBudget(context_class=ContextClass.ACCEPTED_STATE, tokens=200),
                ClassBudget(context_class=ContextClass.ACCEPTED_STATE, tokens=300),
            )
        )


def test_a_preview_pack_records_that_nothing_was_sent() -> None:
    pack = make_pack(egress=EgressClass.NONE, model=None, message=None)
    assert pack.egress is EgressClass.NONE
    assert pack.budget_for(ContextClass.POLICY) is None


# --- promotion --------------------------------------------------------------


def test_promotion_targets_do_not_include_evidence() -> None:
    """Evidence needs an artifact and an exact anchor, so prose cannot become one."""
    assert {target.value for target in PromotionTarget} == {
        "note",
        "question",
        "claim_candidate",
        "decision_candidate",
    }


def test_only_a_decision_candidate_is_promoted_about_a_claim() -> None:
    with pytest.raises(ValidationError, match="only a decision candidate"):
        PromotionRequest(
            session=SESSION,
            message=MessageId("M0042"),
            target=PromotionTarget.NOTE,
            excerpt="worth keeping",
            claim=ClaimId("C0041"),
            provenance=sty.HUMAN,
        )


def test_a_note_promotion_carries_no_supporting_evidence() -> None:
    with pytest.raises(ValidationError, match="belongs to a claim or decision candidate"):
        PromotionRequest(
            session=SESSION,
            message=MessageId("M0042"),
            target=PromotionTarget.QUESTION,
            excerpt="an open question",
            supporting_evidence=(EvidenceId("E0482"),),
            provenance=sty.HUMAN,
        )


def test_a_promotion_keeps_provenance_back_to_the_session_and_message() -> None:
    request = PromotionRequest(
        session=SESSION,
        message=MessageId("M0042"),
        target=PromotionTarget.DECISION_CANDIDATE,
        excerpt="the scope should stay at corpus level",
        claim=ClaimId("C0041"),
        supporting_evidence=(EvidenceId("E0482"),),
        provenance=sty.HUMAN,
    )
    assert request.session == SESSION
    assert request.message == MessageId("M0042")
    assert request.excerpt == "the scope should stay at corpus level"
    assert_roundtrips(request)

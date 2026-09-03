"""Research capture: notes that may be promoted, and questions that stay open.

Both objects exist so that thinking done in a conversation survives it without being
mistaken for a conclusion (Product 31). A `ResearchNote` has no authority and can never be
cited; a `ResearchQuestion` records what is still unresolved and everything currently
bearing on it. Every mutation here runs through `capabilities/`.

    from research_harness.research import NoteService, QuestionLinks, QuestionService

    note, _ = NoteService(ctx).capture("byte-level tokenization keeps recurring", source="cli")
    question, _ = QuestionService(ctx).create("Does field-based framing survive encryption?")
"""

from __future__ import annotations

from research_harness.research.notes import (
    DISCARD_CAPABILITY,
    NotePromotion,
    NoteService,
    PromotionTarget,
    next_claim_id,
)
from research_harness.research.questions import QuestionLinks, QuestionService, next_question_id

__all__ = [
    "DISCARD_CAPABILITY",
    "NotePromotion",
    "NoteService",
    "PromotionTarget",
    "QuestionLinks",
    "QuestionService",
    "next_claim_id",
    "next_question_id",
]

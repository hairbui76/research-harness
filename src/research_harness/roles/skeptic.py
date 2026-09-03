"""Skeptic / Counter-evidence Finder: tries to falsify, qualify, or bound a claim.

READ accepted claims and evidence, retrieval results, search runs, and the source spans
needed to anchor a counter candidate. WRITE an audit result (Product 23, ROADMAP 7.4).
"""

from __future__ import annotations

from research_harness.providers.models.base import ModelRequirements
from research_harness.roles.contracts import (
    HUMAN_ONLY_CAPABILITIES,
    InputKind,
    RoleContract,
    WriteScope,
)
from research_harness.roles.schemas import SkepticOutput

__all__ = ["SKEPTIC"]

SYSTEM_PROMPT = """\
You look for what would make the given claims wrong, narrower, or not comparable. You are
not asked to support them, and finding nothing against a claim is a real result.

Rules:
- Anchor every counter candidate the way an extractor would: the block, the exact
  character span, the verbatim text. An unanchored objection is not evidence.
- Results measured on different datasets, metrics, splits, populations, or deployment
  conditions are incomparable, not contradictory. Put them in `incomparability_notes`
  rather than calling a difference a contradiction.
- A qualifier narrows a claim: population, setting, method, comparison condition, time
  window, or measurement definition. Attach the evidence ids it rests on.
- Report only what the corpus you were given contains. Do not invent studies, numbers,
  authors, or citations, and do not reach for what you remember about a paper.
- Not finding a result is `not_found` or `not_reported`, never `absent`.
- `rationale` is short and states what you searched and what you did not find. Do not
  include private deliberation.

Your output is a proposal for a researcher to review; it changes no accepted claim.
"""

SKEPTIC = RoleContract(
    name="skeptic",
    objective=(
        "Find anchored counter-evidence, qualifiers, and incomparability that would "
        "weaken or bound the claims under review."
    ),
    allowed_inputs=frozenset(
        {
            InputKind.SOURCE_DOCUMENT,
            InputKind.DOCUMENT_BLOCKS,
            InputKind.ACCEPTED_EVIDENCE,
            InputKind.ACCEPTED_CLAIMS,
            InputKind.RETRIEVAL_RESULTS,
            InputKind.SEARCH_RUN,
        }
    ),
    allowed_capabilities=frozenset(
        {
            "claim.find_counterevidence",
            "retrieval.resolve_source",
            "retrieval.search",
            "work.get",
        }
    ),
    forbidden=HUMAN_ONLY_CAPABILITIES | frozenset({"claim.create", "manuscript.*"}),
    output_schema=SkepticOutput,
    write_scope=WriteScope.AUDIT_RESULT,
    requirements=ModelRequirements(
        structured_output=True,
        context_tokens=150_000,
        reasoning="high",
        vision=False,
        max_output_tokens=8000,
    ),
    template_version="1.0.0",
    system_prompt=SYSTEM_PROMPT,
)

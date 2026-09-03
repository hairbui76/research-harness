"""Evidence Verifier: independently checks one candidate against the source spans.

READ candidate evidence, source document, document blocks. WRITE a verification result.
FORBIDDEN every mutation of accepted state (Product 23, ADR-003).

The contract deliberately omits every input that would carry the extractor's reasoning or
the accepted record: the verifier sees the candidate and the source, so agreement between
extraction and verification carries information instead of echoing it (Product 43).
"""

from __future__ import annotations

from research_harness.providers.models.base import ModelRequirements
from research_harness.roles.contracts import (
    HUMAN_ONLY_CAPABILITIES,
    InputKind,
    RoleContract,
    WriteScope,
)
from research_harness.roles.schemas import VerificationOutput

__all__ = ["VERIFIER"]

SYSTEM_PROMPT = """\
You independently check one candidate evidence object against the source spans supplied
with it. You did not produce the candidate and you are not told how it was produced.

Rules:
- Judge only from the supplied source spans. Outside knowledge of the paper, its authors,
  the dataset, the benchmark, or the system named in the text is not evidence: a familiar
  name establishes no property the span does not state.
- `supported`: the span states the candidate, including its number, unit, metric,
  dataset, and condition.
- `partially_supported`: the span states part of the candidate, or states it only under a
  narrower condition than the candidate claims.
- `contradicted`: the span states something incompatible with the candidate.
- `insufficient_evidence`: the span does not establish the candidate either way. Answer
  this whenever deciding would need an assumption, a definition the source does not give,
  or anything you know from outside the span. It is the right answer far more often than
  a guess is.
- Quote the span you relied on, verbatim, in `quoted_support` for every verdict except
  `insufficient_evidence`.
- List each mismatch in `discrepancies`: a different metric, dataset, split, unit,
  rounding, denominator, condition, hedge, or scope. A candidate carrying a mismatch is
  not `supported`.
- `rationale` is one or two sentences saying what the span does and does not establish.
  Do not restate the candidate and do not include private deliberation.

You never accept, reject, edit, or rewrite anything. Your verdict is metadata for a
researcher's review.
"""

VERIFIER = RoleContract(
    name="evidence_verifier",
    objective=(
        "Decide from the supplied source spans alone whether they support, partially "
        "support, contradict, or fail to establish one candidate."
    ),
    allowed_inputs=frozenset(
        {
            InputKind.CANDIDATE_EVIDENCE,
            InputKind.DOCUMENT_BLOCKS,
            InputKind.SOURCE_DOCUMENT,
        }
    ),
    allowed_capabilities=frozenset({"work.get", "retrieval.resolve_source"}),
    forbidden=HUMAN_ONLY_CAPABILITIES
    | frozenset({"evidence.extract", "claim.*", "manuscript.*", "synthesis.*"}),
    output_schema=VerificationOutput,
    write_scope=WriteScope.VERIFICATION_RESULT,
    requirements=ModelRequirements(
        structured_output=True,
        context_tokens=100_000,
        reasoning="high",
        vision=False,
        max_output_tokens=2048,
    ),
    template_version="1.0.0",
    system_prompt=SYSTEM_PROMPT,
)

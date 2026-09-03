"""Evidence Extractor: proposes source-anchored candidates, and nothing else.

READ source document, document blocks, interrogation schema. WRITE staging evidence.
FORBIDDEN accepting or rejecting evidence and every claim capability (Product 23).
"""

from __future__ import annotations

from research_harness.providers.models.base import ModelRequirements
from research_harness.roles.contracts import (
    HUMAN_ONLY_CAPABILITIES,
    InputKind,
    RoleContract,
    WriteScope,
)
from research_harness.roles.schemas import ExtractionOutput

__all__ = ["EXTRACTOR"]

SYSTEM_PROMPT = """\
You extract candidate evidence from one source document. You do nothing else.

Rules:
- Quote only text that appears verbatim in the supplied blocks. Copy the characters
  exactly, numbers and units included; never paraphrase, correct, complete, or convert.
- Every candidate names the block it came from and the character span inside that block.
  If you cannot point at an exact span, do not emit the candidate.
- Classify epistemic origin by what the source does, not by what you believe:
  `source_observed` for something measured or reported, `author_claimed` for what the
  authors assert, `author_interpreted` for the authors' reading of their own results.
  You may not emit `researcher_inferred`; inference is a researcher's act, not yours.
- Do not use outside knowledge of a paper, dataset, benchmark, model, or author to fill a
  field. A familiar name in the text establishes nothing the text does not state.
- A number travels with its metric, its dataset or experimental condition, and the table
  it came from. If any of those is missing from the source, leave `numeric` empty and
  quote the sentence instead of assembling a number yourself.
- If the document does not answer an interrogation field, list it in `fields_not_found`.
  Where the source explicitly says nothing was measured or reported, record
  `not_reported`, `not_found`, `not_applicable`, or `unclear`. You may never report
  `absent`: absence is an audited conclusion a researcher reaches, not an extraction.
- `rationale` is at most one short sentence naming the span you used. Do not include
  private deliberation, planning, or step-by-step reasoning anywhere in your output.

Your output is a proposal with no scientific authority. It is verified independently and
accepted only by a researcher.
"""

EXTRACTOR = RoleContract(
    name="evidence_extractor",
    objective=(
        "Propose candidate evidence for the requested interrogation fields, each quoted "
        "verbatim and anchored to an exact span of one source block."
    ),
    allowed_inputs=frozenset(
        {
            InputKind.SOURCE_DOCUMENT,
            InputKind.DOCUMENT_BLOCKS,
            InputKind.INTERROGATION_SCHEMA,
        }
    ),
    allowed_capabilities=frozenset({"work.get", "retrieval.resolve_source"}),
    forbidden=HUMAN_ONLY_CAPABILITIES
    | frozenset({"claim.*", "manuscript.*", "synthesis.*", "corpus.ingest"}),
    output_schema=ExtractionOutput,
    write_scope=WriteScope.STAGING_EVIDENCE,
    requirements=ModelRequirements(
        structured_output=True,
        context_tokens=100_000,
        reasoning="medium",
        vision=False,
        max_output_tokens=8000,
    ),
    template_version="1.0.0",
    system_prompt=SYSTEM_PROMPT,
)

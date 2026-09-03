"""Writer: drafts manuscript candidates from accepted state, and flags what it cannot support.

READ accepted claims, evidence, decisions, taxonomy, and current manuscript text. WRITE a
manuscript candidate. FORBIDDEN creating accepted scientific facts (Product 23, 30).
"""

from __future__ import annotations

from research_harness.providers.models.base import ModelRequirements
from research_harness.roles.contracts import (
    HUMAN_ONLY_CAPABILITIES,
    InputKind,
    RoleContract,
    WriteScope,
)
from research_harness.roles.schemas import WriterOutput

__all__ = ["WRITER"]

SYSTEM_PROMPT = """\
You draft manuscript text from accepted claims, evidence, and decisions. You never create
scientific facts to improve prose.

Rules:
- Every substantive sentence traces to an accepted claim you were given; list the claim
  and evidence ids you used. Use no id that is not in your inputs.
- Never exceed the maximum defensible wording of the claim you are drafting from. Do not
  add "significantly", "always", "all", "the first", or "state of the art" unless the
  accepted claim itself says so.
- Copy numbers, units, metrics, datasets, conditions, and quotations exactly from the
  evidence. Never round, convert, re-derive, or rephrase them.
- Preserve epistemic qualifiers, scope, comparison conditions, and negative-evidence
  wording: "we identified no work reporting X" is not "X does not exist".
- If a sentence the section needs has no accepted support, write it plainly and list it
  in `unsupported_statements` and `needs_source`. Flag the gap; never invent a citation,
  a number, a dataset, or a study to fill it.
- Do not cite a work you were not given, and do not treat a citation you remember as
  support for the sentence you are writing.

Your draft is a candidate. It replaces accepted manuscript text only after manuscript
audit and researcher acceptance.
"""

WRITER = RoleContract(
    name="writer",
    objective=(
        "Draft manuscript candidate text that stays inside the accepted claim graph and "
        "flags every statement it cannot support."
    ),
    allowed_inputs=frozenset(
        {
            InputKind.ACCEPTED_CLAIMS,
            InputKind.ACCEPTED_EVIDENCE,
            InputKind.ACCEPTED_DECISIONS,
            InputKind.TAXONOMY,
            InputKind.MANUSCRIPT_TEXT,
        }
    ),
    allowed_capabilities=frozenset({"citation.verify", "claim.find_support", "work.get"}),
    forbidden=HUMAN_ONLY_CAPABILITIES
    | frozenset({"evidence.*", "claim.create", "decision.*", "manuscript.attach_claim"}),
    output_schema=WriterOutput,
    write_scope=WriteScope.MANUSCRIPT_CANDIDATE,
    requirements=ModelRequirements(
        structured_output=True,
        context_tokens=150_000,
        reasoning="medium",
        vision=False,
        max_output_tokens=8000,
    ),
    template_version="1.0.0",
    system_prompt=SYSTEM_PROMPT,
)

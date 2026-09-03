"""Synthesizer: places accepted evidence into the project taxonomy, cell by cell.

READ accepted evidence and taxonomy. WRITE a synthesis candidate (Product 23, 8.2).
"""

from __future__ import annotations

from research_harness.providers.models.base import ModelRequirements
from research_harness.roles.contracts import (
    HUMAN_ONLY_CAPABILITIES,
    InputKind,
    RoleContract,
    WriteScope,
)
from research_harness.roles.schemas import SynthesisOutput

__all__ = ["SYNTHESIZER"]

SYSTEM_PROMPT = """\
You place accepted evidence into the project's taxonomy, one matrix cell at a time.

Rules:
- Use only the taxonomy labels you were given. If a work does not fit any of them, say so
  in `notes` instead of inventing a label or stretching an existing one.
- A cell may carry several labels. Never force exclusivity to make a table tidy.
- Every cell lists the accepted evidence ids that justify it, using only ids from your
  inputs. If nothing accepted supports a cell, return it with an empty evidence list; an
  unsupported cell is information, a fabricated one is damage.
- Do not compare numbers measured under different metrics, datasets, splits, or
  conditions, and do not normalize, convert, or round them to make them comparable.
- Missing information is `not_reported` or `not_found` for that work, never `absent`.
- `notes` is short and records what did not fit; it holds no private deliberation.

The matrix is derived state. It becomes stale when the taxonomy or the evidence behind it
changes, and it is accepted by a researcher, not by you.
"""

SYNTHESIZER = RoleContract(
    name="synthesizer",
    objective=(
        "Propose synthesis-matrix cells that classify accepted evidence under the "
        "project taxonomy, with multi-label cells and evidence ids attached."
    ),
    allowed_inputs=frozenset({InputKind.ACCEPTED_EVIDENCE, InputKind.TAXONOMY}),
    allowed_capabilities=frozenset({"retrieval.search", "work.get"}),
    forbidden=HUMAN_ONLY_CAPABILITIES
    | frozenset({"claim.create", "evidence.extract", "manuscript.*"}),
    output_schema=SynthesisOutput,
    write_scope=WriteScope.SYNTHESIS_CANDIDATE,
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

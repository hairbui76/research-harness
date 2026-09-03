"""Claim Auditor: reports the strongest wording the accepted evidence actually defends.

READ accepted claims, evidence, decisions, retrieval results, and search runs. WRITE an
audit result. FORBIDDEN creating claims or accepting anything (Product 23, ROADMAP 7.4).
"""

from __future__ import annotations

from research_harness.providers.models.base import ModelRequirements
from research_harness.roles.contracts import (
    HUMAN_ONLY_CAPABILITIES,
    InputKind,
    RoleContract,
    WriteScope,
)
from research_harness.roles.schemas import ClaimAuditOutput

__all__ = ["CLAIM_AUDITOR"]

SYSTEM_PROMPT = """\
You audit one claim against the accepted evidence you are given and report the strongest
wording that evidence defends. You try to falsify and bound the claim, not to maximize
support for it.

Rules:
- Resolve support, counter-evidence, and qualifiers by evidence id, using only ids that
  appear in your inputs. Never cite an id, a paper, or a number that was not given to you.
- Warn when the support is not independent: the same authors, the same dataset, the same
  system reused across papers, or one measurement reported in several places.
- State coverage honestly in `coverage_state`: how many relevant works were examined, how
  many are unresolved, and what the search did not cover. Incomplete coverage caps scope.
- Recommend the highest scope the evidence defends and no higher, on the ladder
  `individual`, `observed_subset`, `corpus_pattern`, `field_generalization`,
  `universal_or_absence`. Confidence is not scope: a strong result in a few papers is
  still `observed_subset`.
- Universal or absence wording requires an audited search with stated coverage, never the
  mere absence of hits.
- Results that differ under different metrics, datasets, or conditions are incomparable,
  not contradictory; say so rather than counting them as counter-evidence.
- `maximum_defensible_wording` is a single sentence the researcher could publish as is.
- `rationale` is short and does not contain private deliberation.

Your audit is advice. Only a researcher changes an accepted claim, and an override of
your audit is recorded as a Decision.
"""

CLAIM_AUDITOR = RoleContract(
    name="claim_auditor",
    objective=(
        "Resolve support, counter-evidence, qualifiers, independence, and coverage for a "
        "claim, and recommend the maximum defensible scope and wording."
    ),
    allowed_inputs=frozenset(
        {
            InputKind.ACCEPTED_CLAIMS,
            InputKind.ACCEPTED_EVIDENCE,
            InputKind.ACCEPTED_DECISIONS,
            InputKind.RETRIEVAL_RESULTS,
            InputKind.SEARCH_RUN,
        }
    ),
    allowed_capabilities=frozenset(
        {
            "claim.find_counterevidence",
            "claim.find_support",
            "retrieval.search",
            "work.get",
        }
    ),
    forbidden=HUMAN_ONLY_CAPABILITIES
    | frozenset({"claim.create", "manuscript.*", "evidence.extract"}),
    output_schema=ClaimAuditOutput,
    write_scope=WriteScope.AUDIT_RESULT,
    requirements=ModelRequirements(
        structured_output=True,
        context_tokens=150_000,
        reasoning="high",
        vision=False,
        max_output_tokens=4096,
    ),
    template_version="1.0.0",
    system_prompt=SYSTEM_PROMPT,
)

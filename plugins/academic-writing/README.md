# `academic-writing`

Writing policies for an academic manuscript. Four YAML files and nothing else: no code, no
capability, no role, no host contacted. A policy constrains **wording**; it cannot upgrade
scientific authority, add a citation, or change what a sentence claims (ROADMAP Task 15.2,
PRODUCT.md §32.2).

```bash
uv run pytest tests/contract/plugins/test_academic_writing.py tests/e2e/test_style_pass.py -q
```

| Policy | File | What it bounds |
|---|---|---|
| `writing.claim_language` | `writing/claim-language.yaml` | Escalation phrases, keyed to the rung of the claim scope ladder they overshoot (§10.2, §10.5) |
| `writing.citation_discipline` | `writing/citation-discipline.yaml` | Hand-typed citations, anonymous authority, uncited measurements, invented placeholders |
| `writing.project_style` | `writing/project-style.yaml` | Tense, the project's hedging vocabulary, banned filler |
| `writing.humanizer` | `writing/humanizer.yaml` | The adapted `skills/humanizer` style pass |

Every one of them declares `authority: candidate_only` and lists all eight core
`ProtectedSpanKind`s. `validation.check_writing_policy` refuses a policy that drops one.

## How a policy runs

`research_harness.manuscript.style` loads a policy and applies it:

```python
policy = StylePolicy.from_contribution(runtime.writing_policies["writing.humanizer"])
candidate = run_style_pass(text, policy, rewriter=some_rewriter)
accepted = accept_style_pass(candidate, human_approved=True, audit_ok=True)
```

Three properties make this a style pass rather than an edit:

- **The rewriter is external and untrusted.** It proposes `after`; the core measures the
  distance from `before` and returns a `StylePassCandidate`. With no rewriter the pass is a
  read-only report.
- **Nothing here writes.** `accept_style_pass` returns a *string*. Persisting it is still a
  capability call, after manuscript audit and human acceptance.
- **A finding never gates acceptance.** `severity: error` on a style rule means "look at
  this", not "stop". Style preferences never outrank scientific meaning or venue
  requirements (§30.4); the `SemanticDiff` is what gates.

A match that overlaps a protected span is dropped before it is reported, which is humanizer
§14 — *"do not change a protected span merely to remove it"* — enforced rather than asked
for. A stock phrase inside a quotation raises nothing.

## Two conventions the SPI does not have a field for

- **Suggestions.** `WordingConstraint` carries `name`, `pattern`, `message`, and `severity`,
  but no suggestion. So a `style_rules:` entry written `"<constraint name>: <suggestion>"`
  becomes that rule's suggestion when the key matches a constraint in the same file. Every
  other entry is kept verbatim as a policy *note*.
- **The scope ladder.** `WordingConstraint` has no `ClaimScope` field, so
  `claim-language.yaml` names each constraint for the rung it guards
  (`l4_universal_without_coverage`, `l3_field_generalization`, …) and records the §10.5
  rung-to-phrase table verbatim in `style_rules:`.

Both conventions live beside the YAML on purpose. If the SPI gains `suggestion` and a
scope-keyed wording table, these files shorten and `StylePolicy.from_contribution` loses a
branch.

The notes are also where the rules a regex cannot express live — "every substantive sentence
carries a Claim anchor or `[NEEDS SOURCE]`", "a citation must resolve *and* support" — and
they are not repeated as patterns because the core already enforces them:
`manuscript.audit` raises `UNREGISTERED_CLAIM`, `CITATION_MISMATCH`, and
`UNSUPPORTED_NUMERIC`, and `manuscript.support` decides support from the Claim-Evidence
graph rather than from the bibliography (§30.3, §42 J).

## What was adapted from `skills/humanizer`

`docs/plans/skill-audit.md` classifies `humanizer` (v2.12.0-rh1) `adapt-to-plugin`, target
`academic-writing`, authority *manuscript candidate only*. The skill is a **design input,
not a runtime component** (§32.5): nothing loads it, imports it, or calls it, and no file of
it was copied into the core.

**Adapted, as data:**

- the seven pattern families this task names — inflated claims (§§1, 2, 6), sales language
  (§4), vague attribution (§5), stock AI phrases (§7, §8, §27), filler and qualifier pileup
  (§23, §24, §25), chatbot artifacts (§20, §21, §22, §28, §33, and emoji from §18), and
  repetitive structure (§3, §9, §10, §12, §11, §16) — as 22 wording constraints with a
  suggestion each;
- the skill's own **Research Harness manuscript mode**: the protected-span list, the
  semantic-change report, and *"return a revised manuscript candidate, never accepted
  scientific state"*. That section is why this adaptation is short — the skill had already
  been adapted once;
- §14's rule that a protected span is never changed merely to remove a flagged pattern,
  which became the overlap suppression in `apply_style_rules` rather than a sentence;
- the "check for false positives" and "human details to keep" lists, as notes. They bind a
  person and no regex can apply them.

**Excluded:**

- **File mode** — *"when the user names a file, run the full rewrite process but write only
  the final text to the file"*. This is the one clause the audit says must not travel: a
  plugin does not write files (§32.2), and manuscript writes go through
  `manuscript.*` capabilities after audit and acceptance.
- **`agents/openai.yaml`** — classified `exclude`. An agent-host interface descriptor
  (`display_name`, `default_prompt`, `$humanizer` invocation syntax) is host-specific state
  by definition (§32.2, ADR-009).
- **Pasted-text, embedded, and voice-matching modes** — output formats for a chat host.
  `manuscript.style` has one output: a candidate plus a semantic diff.
- **§14's dash preference as a ban, and §15–§19 (bold, title case, emojis in headings, curly
  quotes) as content rules** — presentation for Markdown chat output. Only the parts with a
  LaTeX manuscript meaning survive: `bold_mini_heading_list` (`\item \textbf{...}:`),
  `title_case_heading` in `project-style.yaml`, and `emoji_decoration`. Punctuation
  preference never outranks a venue requirement (§30.4).
- **§30 "writing about the previous version"** — a documentation rule; a manuscript's
  relationship to prior work is a Claim with citations, not a style choice.
- **"Add personality when it fits"** — the skill scopes it to blog posts and essays and
  excludes reference, technical, and factual text. A manuscript is the excluded case.

Also adapted here, per `docs/plans/skill-audit.md` §8: `slr-writer`'s anti-hallucination
rule (`[NEEDS SOURCE]` instead of an invented reference) and its assembler's `UNVERIFIED`
reporting, both in `citation-discipline.yaml` as constraints plus manuscript-audit notes.
`slr-writer`'s IEEE survey structure is *not* here — venue structure rules need a venue
this project has chosen, and inventing one would be a rule nobody asked for.

## What this plugin cannot do

- It declares no capabilities, so `PermissionedGateway` refuses every call it could make.
- `authority: candidate_only` is a one-valued field on `WritingPolicyContribution`.
- It cannot raise a Claim's scope: `claim-language.yaml` flags escalation *downward* only,
  and the maximum defensible wording stays a property of the accepted Claim graph.
- It cannot add a citation. An unsupported statement becomes `[NEEDS SOURCE]` and an audit
  warning; that is the whole of the repair it is allowed to propose (§30.2).

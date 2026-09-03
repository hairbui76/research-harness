# `structured-traffic`

The domain vocabulary of PRODUCT.md §33 — representation, detection, and evaluation of
structured network traffic — as a plugin. It adds questions and controlled values to the
invariant core; it adds no authority (§32.2, ADR-010).

```bash
uv run pytest tests/contract/plugins/test_structured_traffic.py -q
```

## What it contributes

| Extension point | File | What it adds |
|---|---|---|
| Schema | `schemas/traffic.yaml` | 6 evidence-type labels, 2 claim-type labels, 10 controlled fields, all namespaced `traffic.` |
| Interrogation | `interrogation/paper.yaml` | The 22 questions of §33, merged *beside* `DEFAULT_SCHEMA` as `structured-traffic:paper` |
| Validators | `validators/traffic_unit.py`, `validators/dataset_age.py` | Taxonomy membership; capture year vs. publication year; encryption status |
| Workflow | `workflows/traffic_interrogate.yaml` | Read → retrieve → stage → verify → audit → **researcher inbox** |
| Role | `roles/domain_reviewer.yaml` | `traffic.domain_reviewer`: reads accepted evidence, writes an `audit_result` |

It contributes no search providers, so its `egress:` block is empty by construction and
nothing it contributes leaves the workstation (§34).

## Taxonomy is a Decision, not a plugin fact

`raw sequential`, `field-based`, and `behavior-aware` are the three starting terms
PRODUCT.md §33 **recommends**. They appear here as `categories` of
`traffic.representation_family` and as a table in `validators/traffic_unit.py`, and they are
suggestions in both places:

- they are **not** members of any core enum — `domain/enums.py` does not contain them, and
  a contract test greps it to keep that true;
- they are **not** an accepted taxonomy — the accepted taxonomy is a researcher `Decision`
  (§33, §38), and revising it marks dependent classifications stale (ADR-008);
- widening the list is therefore a `Decision`, not a plugin edit. The validator's error
  message says so.

`unclear` is a first-class value everywhere. A paper that does not say is an answer to
record, and forcing a choice is how a blank cell becomes a fact (§32.5).

## Multi-label

A hybrid representation is normal: a system that serializes header fields *and* keeps a raw
byte prefix is both `field-based` and `raw sequential`, and collapsing it to one bucket
loses the distinction the review is about. So:

- `schemas/traffic.yaml` declares `multi_label: true` on every field that admits several
  values at once — `VocabularyField` has the flag;
- `interrogation/paper.yaml` declares it too, on the question that fills each of those
  fields and on the text and numeric questions a paper answers repeatedly (`traffic.dataset`,
  `traffic.baselines`, `traffic.metrics`, `traffic.ablations`, both limitation questions).
  `InterrogationField.multi_label` now exists, and
  `evidence.conflicts.is_multi_valued` reads it instead of guessing from the field name —
  which is what stopped six baselines being reported as five disagreements (dogfood F7).
  The two files must agree: the vocabulary field and the question that fills it are one
  fact stated twice;
- a categorical answer is still **a single category or a list of categories**, and the
  multi-label questions still say "list every value that applies" in their `question:`
  text — that prose is now guidance for the model rather than the machine-readable
  declaration;
- `validators/traffic_unit.py` accepts both shapes and checks each element, and it flags a
  list on a single-valued field (`traffic.encryption_status` is single-valued: a corpus
  with both carries `mixed`).

Three questions are deliberately **not** multi-label — `traffic.encryption_status`,
`traffic.dataset_age`, and `traffic.train_test_partition`. One paper has one answer to each,
so a second, different answer is a disagreement a reviewer should see.

## Review tiers

`risk:` is the tier an answer is staged at (§24.1). Tier 2 — deep review — is used wherever
the answer is an *interpretation* rather than a sentence that can be quoted:

- taxonomy placement (`representation_family`) and derived information;
- corpus provenance: `dataset_age`, `encryption_status`, `train_test_partition`;
- absence-shaped questions: `ablations`, `robustness_evaluation`;
- everything about limits: `deployment_assumptions`, `author_stated_limitations`,
  `researcher_observed_limitations`.

`traffic.metrics` is `numeric`, and `InterrogationField.review_tier` makes a number Tier 2
whatever this file says: a measured value carries metric, unit, dataset, split, and
condition that a triage pass cannot check (§12).

`traffic.researcher_observed_limitations` is deliberately a question a *person* answers. It
is in the schema so that the observation has a home with the rest of the record, not so a
model can fill it.

## Where the questions came from

Per `docs/plans/skill-audit.md` §8, this plugin is the destination for the reading framework
and information matrix of `my-literature-review`, `deep-research`'s omit-on-degradation
protocol, and `slr-writer`'s evidence-card field set. What is implemented here is the
PRODUCT.md §33 field list and the ROADMAP Task 15.1 acceptance requirements. Three carried
adaptations are worth naming:

- **Epistemic origin is core, not local.** The audit's one blocking edit against
  `reading_framework.md` was its four-value origin list, which collapses `author_claimed`
  and `author_interpreted`. Nothing here declares origins at all: `evidence_types:` names
  core `EvidenceType` members and `EvidenceOrigin` stays where it is (§9.1, §42 E).
- **A failed search is not an empty result.** The `locate_passages` stage resolves each hit
  back to its artifact before anything is extracted, so a retrieval failure is a
  `SourceFailure` and never a zero-result answer (§42 F).
- **Identity is a Work/Version/Artifact triple.** `traffic.dataset` records the corpus *and
  its release*, because "CIC-IDS2017" names several files that are not the same evidence.

## Boundaries this plugin lives inside

- `permissions.capabilities` is six read-and-stage names, all inside
  `PLUGIN_ALLOWED_CAPABILITIES`. It cannot accept, reject, promote, or override anything.
- `traffic.domain_reviewer` names the core `claim_audit` output schema and writes
  `audit_result`. It reports; a researcher decides.
- The merged interrogation schema is a new object: `DEFAULT_SCHEMA` keeps the fingerprint it
  had before this plugin was loaded.
- Every validator is a pure function over a plain dict, with no harness import at all.

# Strict review

> Models may propose; evidence must justify; the researcher decides.

Nothing a model produces becomes part of the project until a person accepts it. This page
is the whole gate: where proposals live, in what order you are asked about them, what you
can answer, and what is refused whatever the caller claims to be.

Strict review is the default (`research init --policy strict`) and is recorded in
`research.yaml` as `review_policy`. See ADR-007 and ADR-003.

## Where a proposal lives

```text
raw source → model proposal → verification → review queue → researcher acceptance → canonical state
```

`research interrogate` asks a Work the interrogation schema's questions and writes every
answer to `.research/staging/`, which carries no authority at all:

```console
$ research interrogate W0001 --provider scripted --script extract.json \
    --field dataset --field metric_result --field method_summary
run run_20260902T215622Z_cee46fa4: staged 3 candidate(s) across 3 field(s)
  cand_4590b9b1f474d343  dataset            All experiments use CICIDS2017
  cand_44c1f007fc0db0b2  metric_result      94.32
  cand_b09aa84fc5dee7c0  method_summary     The encoder is a twelve layer transformer
```

No canonical file changed. `research verify` then re-reads each candidate's span with an
independent reader that sees the span and the assertion but **not** the extractor's
reasoning — agreement only carries information when the second reader did not read the
first:

```console
$ research verify W0001 --provider scripted --script verify.json
run run_20260902T215623Z_eb1feb3c: verified 3 candidate(s)
  cand_44c1f007fc0db0b2  supported
  cand_4590b9b1f474d343  supported
  cand_b09aa84fc5dee7c0  partially_supported
```

The verifier must quote its support out of the span it was given. When the quote is not
found there, the verdict is downgraded to `insufficient_evidence` with the reason
recorded — a verifier cannot certify a span it did not read.

## Review tiers

Every candidate is staged at a tier, which is a property of the *question*, not of the
answer or of any model's confidence:

| tier | meaning | examples |
|---|---|---|
| 0 | automatic — deterministic, mechanical facts | hashes, page counts, resolved DOIs |
| 1 | quick triage — directly evidenced extraction | dataset name, a reported metric, traffic unit |
| 2 | deep review — interpretation | taxonomy placement, methodological limitations, gap and absence claims, claim strength, counter-evidence |

A numeric answer is Tier 2 whatever the interrogation schema says, because a number
carries a metric, a unit, a dataset, and a condition that all have to be right together.

## The inbox

`research inbox` is the queue, in a fixed priority order: **conflicts, high-risk, stale,
ambiguous, routine**. The order comes from what is most likely to change a conclusion, not
from a score.

```console
$ research inbox
3 item(s) to review  [high_risk 1, ambiguous 1, routine 1]
  cand_44c1f007fc0db0b2  high_risk  tier 2  metric_result  supported
      94.32
      - tier 2: an interpretive judgement needs deep review
      - numeric evidence: F1 carries unit, dataset, and condition
  cand_b09aa84fc5dee7c0  ambiguous  tier 1  method_summary  partially_supported
      The encoder is a twelve layer transformer
      - the verifier reported partially_supported
  cand_4590b9b1f474d343  routine    tier 1  dataset  supported
      All experiments use CICIDS2017
      - verified supported, tier 1, anchor valid
```

What puts an item in each category, tested in that order:

| category | any of |
|---|---|
| `conflict` | the verifier contradicted the candidate; accepted evidence reads the same span differently; two providers disagree on a field; another candidate proposes a *competing* value for the same field (see below); an open conflict record |
| `high_risk` | Tier 2; the candidate carries a numeric value; it records an absence; its origin is interpretive |
| `stale` | the anchor no longer replays against the stored parse |
| `ambiguous` | no verification yet, or a `partially_supported` / `insufficient_evidence` verdict |
| `routine` | verified `supported`, Tier 0 or 1, anchor valid |

Model confidence appears nowhere: not as a field, not as a tie-break, not as a reason.

### When two answers compete

Answering a field twice is not a disagreement. A paper compares against six baselines,
evaluates on three corpora, and states four limitations; those are additional answers, and
a queue that calls each of them a conflict spends the researcher's attention on nothing —
in the 2026-09-03 dogfood session, 18 of 39 items were conflicts and 2 were real.

Two candidates for the same field of the same Work compete when:

* the verifier contradicted one of them and supported the other;
* one records an absence (`not_reported`, `not_found`, ...) where the other reports a
  value, or the two record different absences;
* both carry numbers for the same metric, dataset, and condition, and the numbers differ;
* both read the same span and say different things;
* or the field takes a single value and their values differ.

A field takes several values when the interrogation schema says so:
`InterrogationField.multi_label` is the declaration, and a domain plugin sets it on the
question the way it sets it on the vocabulary field
(`plugins/structured-traffic/interrogation/paper.yaml`). Without a declaration to read the
queue falls back to what a field name and a question wording still say — a name that is a
list (`baselines`, `traffic.dataset`, `..._limitations`), or a question asking for every
value that applies. That fallback is what a *staged candidate* gets: it records its field's
name and not the contract that asked it, so a multi-label categorical field named in the
singular (`traffic.representation_family`) is only recognised when the caller passes the
schema — `build_inbox(..., schema=...)` takes it, and `research inbox` reads staging.

Either way those items keep listing their peers — `competing` is on every item, and the
reason line says how many other candidates answered the field — but they sit at the
priority their own tier earns rather than at the top of the queue.

Narrow the queue with `--work W0001`, `--category conflict`, or `--limit N`, and take the
whole thing as JSON with `--json`. Only the first `--limit` items print; when there are
more, the header says `showing 20 of 39 item(s) — use --limit 0 for all`, and `--limit 0`
prints the queue entire. `--json` carries `shown` and `limit` beside `count` for the same
reason.

`research conflicts` shows the same disagreements on their own, and `research stale`
lists anchors that no longer replay plus accepted objects an upstream change has marked
stale. Neither repairs anything: a stale anchor is reported and left alone, because
silently re-anchoring would move the source an accepted conclusion rests on (ADR-008).

## Review actions

One candidate, exactly one action, taken by the researcher. Each flag is a named
capability, so the Web cockpit, the editor, and a script all take the same action:

| flag | capability | action recorded | effect |
|---|---|---|---|
| `--accept` | `review.accept` | `accept` | creates accepted Evidence and marks the candidate reviewed |
| `--qualify "<text>"` | `review.qualify` | `accept_with_qualification` | accepted Evidence carrying that qualification; the text is required |
| `--edit <file.json>` | `review.edit` | `edit` | accepts a corrected Evidence object read from JSON; the source anchor may never move |
| `--reject "<reason>"` | `review.reject` | `reject` | no Evidence; the refusal is appended to the Work's `rejections.jsonl` so the same proposal is recognised next time |
| `--defer "<note>"` | `review.defer` | `defer` | leaves it in staging with a note |
| `--request-more "<note>"` | `review.request_more` | `request_more_evidence` | captures the ask as a low-authority note |

`review.candidate` reads one staged proposal verbatim, which is how a client gets the
object a review action posts back.

**With no flag at all, `research review candidate <id>` shows the item and changes
nothing**: the verdict, the verifier's discrepancies, the competing answers, and the quoted
span with the block it came from and its neighbours — everything Product §25 asks to be on
one screen when a rejection has to be honest. `research review next` shows the top of the
queue in the same detail and says how many are left, so working the queue is `next`, act,
`next` rather than reading an id out of `research inbox` each time.

```console
$ research review next
12 item(s) left; next in Product 24.2 order:

cand_44c1f007fc0db0b2  high_risk  tier 2  metric_result
  work               W0001  (A0001-1)
  verdict            supported
  anchor             valid
  measured           94.32, percent, F1, CICIDS2017
  reason             tier 2: an interpretive judgement needs deep review

  quoted             94.32
  at                 page 4, 4 Evaluation > Table 3
```

This command is the human gate: taken in person, it accepts any tier, an interpretive
candidate included. The conditions live on `research review batch`.

```console
$ research review cand_44c1f007fc0db0b2 --accept
cand_44c1f007fc0db0b2: accept -> E0001
  event              evidence.accepted

$ research review cand_4590b9b1f474d343 --qualify "holds for the CICIDS2017 capture only"
cand_4590b9b1f474d343: accept_with_qualification -> E0002
  event              evidence.accepted

$ research review cand_b09aa84fc5dee7c0 --reject "the span describes the encoder, not the method"
cand_b09aa84fc5dee7c0: reject
  event              evidence.rejected
```

Two flags at once is an error, not a merge:

```console
$ research review cand_4590b9b1f474d343 --accept --defer later
error: give exactly one review action (--accept, --qualify, --edit, --reject, --defer, --request-more)
```

The reviewed candidate stays in staging as history; the accepted Evidence is what
canonical state gains.

### Partial acceptance

A candidate that mixes what the source says with what it is taken to mean can be split:
the source fact is accepted with the candidate's own anchor, and the interpretation is
either staged as its own Tier-2 candidate under a distinct field or rejected with a
reason. Exactly one accepted Evidence results, and the accepted half must carry a source
origin (`source_observed` or `author_claimed`) and a valid anchor.

```console
$ research review cand_44c1f007fc0db0b2 --split \
    --interpretation "The corpus is therefore representative of enterprise traffic."
cand_44c1f007fc0db0b2: accept -> E0001
  interpretation     staged as cand_9d21b0f4c8ea6117
  event              evidence.accepted
```

The reading is staged under `<field>:interpretation` at Tier 2, keeping the fact's anchor,
so it comes back in the queue as its own question and never as a competing answer to the
fact just accepted. To refuse it instead, give the reason:

```console
$ research review cand_44c1f007fc0db0b2 --split \
    --reject-interpretation "the sentence names the corpus and claims no more than that"
cand_44c1f007fc0db0b2: accept -> E0001
  interpretation     rejected and recorded
```

Exactly one of the two is required — a split that decides neither half is refused, and so
is one that tries to do both:

```console
$ research review cand_44c1f007fc0db0b2 --split
error: --split needs --interpretation TEXT (stage the reading for its own review) or --reject-interpretation REASON (refuse it)
```

This is `EvidenceReviewService.split_accept` in `evidence/service.py`, reached through the
`review.split` capability, so HTTP and MCP hosts see the same operation (and are refused it
for the same reason as every other acceptance: it is `mutate` and human-only). The
capability request also accepts a full `fact` Evidence object for a split that corrects the
fact on the way through; the CLI accepts the candidate's own evidence, which is the common
case.

## Batch acceptance

`research review batch` accepts every candidate that satisfies a fixed list of
deterministic conditions. Under the default policy it is refused outright:

```console
$ research review batch
error: batch acceptance under review policy 'strict' needs the Product 24.4 conditions stated explicitly; strict review is the default and a batch is an exception a researcher declares
```

A workspace created with `research init --policy policy_batch` permits it. A candidate is
accepted only when **all** of these hold; each failure is named in the output so a skip is
auditable:

* the verifier's verdict is `supported`;
* the anchor still replays as valid;
* no competing candidate proposes a different value for the same field (the batch is
  stricter than the queue here: *any* other answer, competing or not, stops it);
* the tier is 0 or 1;
* the candidate carries no numeric value (a number is never low risk);
* it records no absence state;
* it does not conflict with accepted evidence;
* an identical span was not previously rejected.

`--dry-run` reports what would be accepted and changes nothing. Model confidence is not on
the list, is not read, and is not stored anywhere the batch can reach.

## Conflicts

A conflict is a question for a person. `review.resolve_conflict` records the researcher's
choice — `accept`, `reject`, or `defer` — with a mandatory reason, closes any open
conflict record with the same choice and reason, and only closes it after the action
succeeded, so a refused acceptance leaves the conflict where you can still see it.
Nothing prefers a provider, a verdict, or the newer proposal.

## What a model or an agent host cannot do

Permissions are enforced in the capability layer, so every transport gets the same answer
(ADR-004). Four permissions exist: `read`, `stage`, `mutate`, `admin`.

| principal | granted | so it can | and cannot |
|---|---|---|---|
| `human` | `read`, `stage`, `mutate`, `admin` | everything | — |
| `agent_host` (Claude, ChatGPT, any MCP host, an HTTP caller with no token) | `read`, `stage` | read the project, including `review.inbox` and `review.candidate`; call `work.interrogate`, `evidence.extract`, `evidence.verify`, `manuscript.draft`; leave proposals in the queue | every `review.*` action that accepts, qualifies, edits, rejects, splits, defers, or resolves a conflict; `evidence.accept`, `evidence.reject`, `claim.audit`, `claim.override_strength`, `decision.accept`, `note.promote`, `manuscript.attach_claim`, `taxonomy.put`, `state.rebuild`, and every other `mutate`/`admin` capability |
| `model` | `read`, `stage` | propose into staging | the same list |

`mutate` and `admin` additionally require a human principal whatever else was granted, and
the capability layer refuses when the principal and the workspace actor disagree — so a
host cannot put a researcher's name on its own mutation. An agent host that tries:

```json
{"capability": "evidence.accept", "ok": false, "result": null,
 "error": {"code": "permission_denied",
           "message": "evidence.accept: a agent_host principal does not hold the 'mutate' permission (holds: read, stage)",
           "capability": "evidence.accept"}}
```

Below that, the domain refuses acceptance for a non-human actor under the default policy
whatever the transport allowed, and refuses auto-acceptance for any interpretive or
Tier-2 candidate under **every** policy. Tier 0 candidates are the one exception that may
be accepted without a review action, because they are mechanical facts.

A plugin is bounded further still: its manifest may only request read and staging
capabilities, and the accepted-state mutations are refused however the manifest is
written. See [Plugins](plugins.md).

## The full capability list

[Capabilities](capabilities.md) is generated from the registry: every name, its
permission, whether it needs the researcher, and what it changes in scientific terms.

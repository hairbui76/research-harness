# Grouping the project rail: a proposal

**Roadmap item 3L, 2026-09-07.**

## The question

The rail lists eleven destinations as one flat column in a fixed order, Conversation down
to Manuscript, with a number beside the four the daemon reports waiting work against. The
critique of 2026-09-06 asked one thing: should those eleven become three groups?

## What the eleven are for

What a person goes there to do, in the page's words. **†** carries a count from
`overview.attention`; **‡** is an authority page.

- **Conversation** — where you talk to the project, and promote every candidate.
- **Overview** — what needs a researcher next, and what the project holds.
- **Review inbox †** — the daemon's queue; decide a candidate beside its source page.
- **Conflicts †** — where two readings of the same subject disagree.
- **Stale †** — objects whose ground has moved, and may want redoing.
- **Corpus ‡** — the sources this project reads from: works, files, parses.
- **Claims ‡** — what the project asserts, held against what its evidence allows.
- **Questions** — what is still open, and what remains uncertain.
- **Synthesis** — a matrix reading one property across every work; it proposes nothing.
- **Taxonomy ‡** — how this project classifies its works, each term with its Decision.
- **Manuscript †‡** — the writing, and the audit of sentences no claim supports.

The fourth count is Manuscript's — "unsupported manuscript claims" — so waiting work is
not only the queues.

## Options

### Option A — the flow of the work

    Conversation
    Overview
    Waiting
        Review inbox      12
        Conflicts          3
        Stale              5
    The record
        Corpus
        Claims
        Questions
        Taxonomy
    Outputs
        Synthesis
        Manuscript         2

Three visible headings, sentence case and muted at label size — the palette's "Go to"
pattern, never an uppercase micro-label, which the craft floor bans. Conversation and
Overview stay unheaded — the ways in, not a category. It names the eight pages a newcomer
cannot tell apart, in the order a session runs. Cost: three coined nouns;
"Outputs" is contestable, since Synthesis reads rather than produces; and Manuscript's count
sits outside "Waiting", which therefore means the queues, not PRODUCT §26's Attention block.
Each heading is its group's accessible name, announced on entry — text, not a tab stop; no
option here adds one.

### Option B — separation only, the order untouched

    Conversation
    Overview
    ─────────────
    Review inbox      12
    Conflicts          3
    Stale              5
    ─────────────
    Corpus
    Claims
    Questions
    Synthesis
    Taxonomy
    Manuscript         2

Two hairlines and a little more space: no word changes, no item moves. Each block is a
group with an `aria-label` — "Entry points", "Waiting", "The record" — announced but never
shown. The order was learned long ago and the counts already structure the column, so
separation alone stops it reading as one list. Cost: it answers the critique with "no", and
screen-reader users get three names sighted users cannot see.

(PRODUCT §26's list runs Overview, Corpus, Evidence, Claims … Conflicts, Stale; the
shipped rail already differs, and every option keeps what shipped.)

### Option C — one name, for the only real cluster

    Conversation
    Overview
    Waiting
        Review inbox      12
        Conflicts          3
        Stale              5
    ─────────────
    Corpus
    Claims
    Questions
    Synthesis
    Taxonomy
    Manuscript         2

One visible heading over the three queues; a hairline above six pages that keep none.
Waiting work is the one grouping the product already has a concept and a feed for; the
rest share no word a researcher says. Cost: asymmetry, and the vague pages stay vague.

## Recommendation

**Option A.** Eleven is not too many to see; the trouble is that eight are proper nouns
with no stated relation, so the rail teaches nothing and only the numbered items are fast
targets. A names them in the order the work runs, and a heading is renamed in one line. If
the coined vocabulary is the objection, C is the honest half-measure and B the null result.
Under all three the destinations are untouched: the same pages, labels, routes, counts,
shortcuts and palette names.

## What building it touches

- **One additive prop.** `RailItem` takes an optional group name; `ProjectRail` renders one
  group per run of items sharing it, under a visible heading (B and C: an `aria-label`).
  Ungrouped items render as today, so nothing existing changes.
- **`NAVIGATION`** (`web/src/app/routes.tsx`) gains that name per entry,
  `navigationForProject` passes it through, `Layout.tsx` copies it onto the `RailItem`.
- **The palette** files every destination under one "Go to" heading in `CommandsProvider`;
  it should take the rail's group, so both read the same. Keys unchanged.
- **Two tests change.** `ProjectRail.test.tsx` gains a case that a grouped rail names each
  group, keeps every link's name and count, and passes axe; its theme×density snapshot
  moves only if the specimen groups its items. `web/src/app/routes.test.tsx`
  asserts labels, ids, icons and `end` survive `navigationForProject`; the group must join
  them, or a project-scoped rail loses its headings.
- **Must keep passing:** `browser-tests/research-pages.spec.ts` runs axe over eight pages
  with the rail mounted, so a heading with no programmatic name fails there; `app.spec.ts`
  reaches the rail through a drawer named "Project navigation" and expects the switcher
  next, so no group may add a focusable element there.
- **Size:** 4–6 hours for one implementer with tests; Option B, 2–3.

## Decision needed

    Grouping:  A  /  B  /  C  /  none
    If A or C, keep these names? Waiting · The record · Outputs
    Build it in wave 3, or later?

# Shape: an Evidence index under The record

**Date:** 2026-09-08
**Wave:** six, item 6A
**Critique:** `web/.impeccable/critique/2026-09-08T02-18-57Z__src-app-layout-tsx.md`, P1 —
"Accepted evidence has no page." `routes.tsx` defines `evidence/:evidenceId` and no index;
PRODUCT §26 lists Evidence between Corpus and Claims; the rail's eleven destinations hold
no Evidence entry.
**Playbook:** shape → build inside the incumbent world, following the ten-rule page pattern
the Overview proved and the Corpus rolled out (`web/src/views/Corpus.tsx`).

No researcher was available to answer a discovery round, so the questions below are read
off the recorded product (PRODUCT §9, §24, §26, §37, §42), off what the daemon already
knows how to answer, and off the critique's own persona flags. They are marked as the
assumptions they are.

## Job and audience

Everyone who reaches this page is looking *back* at accepted state, not forward at a
decision — the review inbox is where a decision is made, and this is where its output
lands. Three arrivals, from the critique's personas:

- **Alex, the power user, sweeping.** "No Evidence index to sweep" is a named red flag. He
  arrives after a review session with the corpus in his head and wants the whole body of
  accepted evidence in one list he can narrow and search.
- **A researcher returning after a week.** She wants what came in while she was away, and
  what has decayed under her: a source re-parsed under an accepted span leaves it stale
  (§37), and nothing on the Corpus page says which *evidence* that hit.
- **Jordan, writing.** He is about to cite something and needs to know whether a claim
  already rests on it, and at what strength the product will let him say it (§9.3).

## The questions this page answers

Six, and the page is built around these and nothing else:

1. **What have I accepted from this corpus?** — the whole list, with its size stated in a
   sentence rather than in a figure.
2. **Which evidence rests on which work?** — the row leads with the field and the work's
   *title*, not `E0007 · W0001`; the find covers title, id, field and the quoted span.
3. **Which evidence is cited by no claim?** — accepted work that landed nowhere. The
   daemon already inverts this edge for the corpus (`evidence_citations`).
4. **What is stale?** — the span whose source moved under it, and the object a later
   version superseded.
5. **What came in since I last looked?** — accepted in the last seven days, the same
   stated window the corpus uses for arrivals.
6. **What did a verifier disagree with, and what is not direct?** — a contradicted or
   insufficient verdict standing on accepted state, and derived strength, which §9.3 says
   must never be silently displayed as direct.

## What stays, and what may not appear

- **No confidence number.** The daemon reports none (§43) and there is nowhere on this page
  for one to come from. Nothing here ranks evidence.
- **Six scientific status families and no seventh** (DESIGN.md): accepted, candidate,
  qualified, contested, stale, private. Status colour is used on scientific state only —
  the type, the origin and the strength are text, not tinted chips, because a colour that
  said "derived" would be the page grading the evidence.
- **The daemon's order.** The list is `evidence.list`'s order; a find only ever hides, and
  no column sorts. Which evidence needs a researcher is composed server-side (§5 P10) —
  a cockpit that decided for itself that a stale span needs attention would be a second,
  disagreeing copy of §37 living in React.
- **Every row already carries a decision.** There is no Accept, Reject or Defer here.
  Acceptance happened in the review queue and there is no undo capability; this page is the
  record of it, and its one action is to open the evidence at its source.

## Shape

The Corpus page, in its own vocabulary — the same pattern, so the two record pages cannot
teach two different reading orders:

1. The page frame (`h1`, description, find) is mounted before the read resolves and
   survives loading, refusal and empty.
2. **Lead:** "Evidence that needs a researcher" — the daemon's `attention` groups, in the
   daemon's order, each one whole sentence with its count inside it, naming the first few
   pieces of evidence it counts, each a link to that evidence's own page.
3. **Then the list, under its own heading**, with the questions as the controls that narrow
   it, a status line saying what is on screen, and the rows.
4. **The row is read across shared columns**: what it is (field · work title, id, the quoted
   span) · Type · Strength · Origin · Cited by · Accepted. Six columns, so it never becomes
   a card. Below the width they need, the row becomes labelled pairs, as the corpus's does.
5. **The list is windowed** (`VirtualList`) with a find of its own over the whole list, and
   says how much of it is showing — the corpus's trade-off, made the same way, because this
   list is longer than the corpus by construction (§26's example: 42 works, 186 evidence).
6. **A row opens the evidence page** (`/evidence/:evidenceId`), which already exists and
   shows the exact span.
7. Every empty state names the object, says why it might be absent, and offers one next
   action: no evidence at all → the review inbox; no evidence answers this question → show
   everything; no evidence matches this find → clear the find.

## Server, and why

`evidence.list` gains, additively, exactly what those six questions need and nothing more:
the work's title, the claims citing each piece, when it was accepted, the `attention`
groups, the `questions` the list can be narrowed by, and the `total` a narrowed list is
read against. This is the shape `work.list` took in wave five, for the same reason — the
judgement and the words for it are one decision and both are the daemon's.

## Also in scope

The critique's minor observation on the same file: an unknown URL silently renders the
Overview, so a stale bookmark shows a plausible wrong page. `/*` becomes a not-found state
inside the frame — "There is no page at this address" — with one link to the Overview.

## Anti-goals

No batch action, no sort, no saved view, no export, no evidence editor, no second copy of
the review queue. The evidence detail page is not redesigned.

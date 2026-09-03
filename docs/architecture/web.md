# The Web research cockpit

The cockpit is a React client of the local daemon. It owns no research logic: every
mutation is one `POST /capabilities/<name>` call, and every judgement it displays — which
items need review, in what order, what a claim may say, whether an acceptance is allowed —
was made server-side and is rendered, not recomputed (PRODUCT §5 P10, §26; ADR-004).

It is a cockpit rather than a chat window: navigation is Overview, Review inbox, Conflicts,
Stale, Corpus, Claims, Questions, Synthesis, Taxonomy, Manuscript, and the screen a
researcher spends their day on puts the source page beside the decision.

## Running it

Two ways, and they use the same daemon.

**Built, served by the daemon** (what a researcher uses):

```bash
cd web && pnpm install && pnpm build      # writes web/dist
research serve                            # binds 127.0.0.1:8765
open "http://127.0.0.1:8765/?token=$(cat .research/daemon-token)"
```

The daemon mounts `web/dist` at `/` when it exists, with a single-page fallback so
`/review/cand_…` and `/claims/C0001` render the shell. Without a build it serves the JSON
API alone. Set `RESEARCH_HARNESS_WEB_DIST=/path/to/dist` to serve a bundle from elsewhere.

**Dev server** (what you change code against):

```bash
RESEARCH_HARNESS_DEV=1 research serve      # allows the Vite origin, dev only
cd web && pnpm dev                         # http://127.0.0.1:5173
```

`RESEARCH_HARNESS_DEV=1` is the only thing that opens CORS, and it opens it to
`http://localhost:5173` and `http://127.0.0.1:5173` and nothing else. In dev the client
talks to `http://127.0.0.1:8765` by default; `VITE_API_BASE` overrides it. In a build the
base URL is the empty string, so the cockpit calls the origin that served it.

## The token

The daemon's authority is `.research/daemon-token`, a file only a local process can read
(PRODUCT §34). The cockpit picks it up in one of two ways:

* `?token=…` on the first load — the token is stored for the origin and stripped from the
  address bar, so it does not survive into a bookmark or a screenshot;
* pasted into the bar the cockpit shows when it is not holding one.

Without a token the daemon resolves the caller as an `agent_host`. That is a *correct*
state, not an error: the cockpit reads everything, and every mutation control is disabled
with the reason on screen — an agent host reads and proposes, and the researcher accepts
(PRODUCT §29, ADR-007). `GET /overview` reports `principal`, which is what the UI keys on;
it never infers its own permissions.

## Routes the daemon adds for the cockpit

All five are reads. The write surface is still `POST /capabilities/<name>` alone, and
`tests/contract/protocol/test_http.py` asserts the whole route set so a new one cannot
appear by accident.

| Route | What it is for |
|---|---|
| `GET /artifacts/{artifact_id}/bytes` | The immutable file an anchor was accepted against, streamed inline (§42 D). |
| `GET /blocks/{artifact_id}` | The stored parse: page, order, and bbox per block, so the source pane can draw the span without re-parsing. |
| `GET /candidates/{candidate_id}` | One staged candidate verbatim. `evidence.accept` takes the `Evidence` object, so the cockpit reads it and posts it back unchanged. |
| `GET /overview` | Attention first: review items, conflicts, stale objects, unsupported manuscript claims, then claim health and open questions. Composed server-side. |
| `GET /index` | Summaries of everything the navigation lists: works, claims, questions, decisions, matrices, taxonomies, manuscript anchors. The cockpit reads this through `state.index` instead — same answer, and a name every host shares — but the route stays for anything that wants one round trip. |

`GET /overview` also reports `principal`, `actor`, and `next_decision_id` — the id the next
`decision.accept` will write, which the Override control needs because an override is a
Decision before it is a claim edit (§38).

## Regenerating the types and the fixtures

The cockpit is typed against snapshots exported from the daemon, so a drift between the two
shows up as a diff rather than as a runtime surprise.

```bash
uv run python web/scripts/export_backend_json.py   # web/openapi.json, web/capabilities.json,
                                                   # web/src/test/fixtures/*.json
cd web && pnpm gen:types                           # src/api/types.gen.ts, src/api/capabilities.gen.ts
```

The export builds two workspaces. The first is the Gate P11 one (the synthetic paper,
ingested and parsed through capabilities, with three verified candidates staged by a
scripted extractor and verifier); the second is the fixture manuscript
`vscode/scripts/export_fixtures.py` builds, because the Manuscript view needs a manuscript
and the Gate P11 corpus has none — pinning both clients to the same manuscript is what makes
"the cockpit and the editor agree" mean anything. It drives the real routes and
capabilities against them and writes what came back. It starts no server and touches no
network. `pnpm gen:types` reads only those snapshots: `openapi-typescript` produces the
route and DTO types, and a small emitter produces the capability-name union, each
capability's permission, and the `review.edit` request schema that the Edit action's JSON
editor validates a hand edit against.

The capability responses no HTTP route returns (`ClaimList`, `ReviewOutcome`,
`ManuscriptAnchors`, `RevalidationView`, `TraceView`, `FindingLocation`, …) are not in the
OpenAPI document, so `src/api/dto.ts` declares them by hand.
`tests/contract/protocol/test_web_routes.py` checks every field name in those declarations
against the response schema the daemon publishes, which is what stops them drifting.

Run both after changing a route, a DTO, or a capability request model.

## Layout

```
web/
  openapi.json          daemon OpenAPI snapshot          (checked in)
  capabilities.json     GET /capabilities snapshot       (checked in)
  scripts/              export_backend_json.py, gen-types.mjs
  src/api/              client.ts (mirrors HarnessHttpClient), dto.ts, schema.ts,
                        session.ts, *.gen.ts
  src/app/              session context, layout, routes, useAsync
  src/components/       SourcePane (pdf.js), ReviewActions, JsonEditor, Feedback
  src/views/            one per navigation entry, plus the detail screens
  src/test/             harness.tsx and the exported fixtures
```

`src/api/client.ts` is the TypeScript twin of
`research_harness.protocol.http.HarnessHttpClient`: it knows the routes and the envelopes
and nothing else. A capability refusal comes back as `ok: false` with a stable `code`; the
typed helpers raise `CapabilityError` carrying it, and the views render the daemon's own
message.

## The review screen

`/review/:candidateId` is the screen PRODUCT §25 asks for.

* **Left** — the page the span was read off, rendered from the artifact's own bytes with
  pdf.js, with the block's stored geometry drawn over it. pdf.js is imported lazily, and
  when it cannot run the pane falls back to the exact block text with the span marked
  inside it and a link to the unchanged file. The source is never absent.
* **Right** — the quoted text, the field, origin, evidence type and strength, the numeric
  value with the metric/unit/dataset/table a number must carry (§12), the verifier's verdict
  and rationale, competing candidates, and each side of any conflict with the diff of what
  accepting it would change.
* **Actions** — Accept, Accept with qualification, Edit, Reject, Defer, Request more
  evidence (§24.3). Each is a capability call and a refresh.

Which capability each action uses. Every one of them takes the staging id and whatever the
researcher typed, and nothing else — the cockpit never posts back the `Evidence` object the
daemon just handed it. That is what settles the queue: the handler allocates the evidence
id and marks the candidate reviewed in the same transaction.

| Action | Call |
|---|---|
| Accept | `review.accept` `{candidate_id}` |
| Accept with qualification | `review.qualify` `{candidate_id, qualification}` |
| Edit | `review.edit` `{candidate_id, edited}`. The editor checks the object against the daemon's own `review.edit` schema first; the daemon validates it again, and an edit that moves the source anchor is refused there. |
| Reject | `review.reject` `{candidate_id, reason}` |
| Defer | `review.defer` `{candidate_id, note}` |
| Request more evidence | `review.request_more` `{candidate_id, note}`, which records the request on the candidate *and* captures it as a note, so the question outlives the next `.research/` deletion (§31). |

**One exception, and it is the daemon's rule rather than the screen's.** When the queue item
carries an open *conflict record*, Accept, Reject, and Defer go through
`review.resolve_conflict` instead. It reaches the same three `EvidenceReviewService`
methods and additionally closes the record with the researcher's reason, which nothing else
does — accepting a conflicted proposal through `review.accept` would write the Evidence
correctly and leave the disagreement on the Conflicts screen for ever. Accept therefore asks
for a reason when, and only when, there is a conflict to close.

## Gate P11 walkthrough

The gate: *a researcher completes the Evidence review loop and the Claim audit loop from
Web without direct file edits or CLI mutation commands.*

```bash
research init ./project --name demo
research ingest paper.pdf -w ./project
research parse W0001 -w ./project
research interrogate W0001 -w ./project --provider <configured>   # stages proposals
research verify W0001 -w ./project --provider <configured>        # records verdicts
cd web && pnpm build
research serve -w ./project
open "http://127.0.0.1:8765/?token=$(cat ./project/.research/daemon-token)"
```

Then, entirely in the browser:

1. **Overview** shows what needs attention, review items first.
2. **Review inbox** groups the queue: conflicts, high-risk, stale, ambiguous, routine.
3. Open an item: the page and the highlighted span are on the left, the proposal and the
   verifier's verdict on the right. **Accept** one, **Reject** another with a reason.
4. **Claims** → the accepted evidence is now relatable. Create the claim, **Relate
   evidence**, **Audit** it (status, allowed strength, maximum defensible wording), and
   **Override** the auditor if you disagree — which writes an accepted `epistemic_override`
   Decision and then applies it. The Decision is posted without an id and applied under the
   one the daemon returns.
5. **Overview** again: accepted evidence counted, claim health updated, queue drained.

Steps 3–5 are exactly the HTTP calls `tests/e2e/test_web_gate.py` drives, and it asserts the
canonical result on disk afterwards: the Evidence in `evidence.jsonl`, the refusal in
`rejections.jsonl`, the audited Claim, the accepted Decision, and a workspace that still
passes its consistency check. Step 4's Decision is the one blocked by the id-allocation
defect below; that part of the gate is reported as an expected failure rather than hidden,
and it will pass with nothing to un-mark once the lock is fixed.

## Verification

```bash
cd web && pnpm install && pnpm typecheck && pnpm test && pnpm build && pnpm lint
uv run pytest tests/contract/protocol tests/e2e/test_web_gate.py -q
```

## What the cockpit calls (v0.4)

The v0.4 capability additions are taken up. Nothing was removed from the daemon, so this
section is a record of which call each screen makes, not a list of things to do.

**The review screen** posts the candidate-keyed actions above. `review.candidate` is the
capability twin of `GET /candidates/{id}`; the screen keeps the route, because it reads the
blocks from a route on the same screen anyway, and a host with no routes has the capability.

**The navigation reads one list at a time.** Claims uses `claim.list`, Corpus `work.list`,
Questions `question.list`, the claim detail `decision.list` (filtered by claim) and
`anchor.list`, and a Work's page `evidence.list` — so the accepted evidence is a list of
links rather than a count. Synthesis and Taxonomy use `state.index`, because no capability
lists matrices or taxonomies on their own. `HarnessClient.index()` is `state.index`; the
cockpit no longer calls `GET /index`.

**No id is guessed.** `claim.create`, `question.create`, and `decision.accept` are posted
without one and the daemon's `objects[0]` is the id used afterwards, so the Override control
no longer reads `next_decision_id` before writing. `GET /overview` still reports it, for
display.

**Manuscript** is three reads and one mutation. `manuscript.anchors` lists every stored
anchor beside the verdict it currently earns; `manuscript.audit` reports findings, each
rendered at its own `location`; `manuscript.trace` walks one sentence down to its Claim and
source spans. **Revalidate anchors** calls `manuscript.revalidate`, which records the
verdicts — a mutation, and human-only, because a reworded sentence going stale is a change
to accepted state (ADR-008); the control is disabled with the reason for an agent host.

**Claim coverage** is rendered from the `Coverage` the Claim records — examined of relevant,
unresolved, overturn risk, and the `SearchRun`s it rests on. `claim.update_coverage` writes
it; nothing in the cockpit recomputes it.

### What the cockpit still cannot do

**Discovery's metadata proposals — the read now exists; the view does not.**
`work.update_metadata` fills a Work's empty or undecodable bibliographic fields, and a
discovery run turns up exactly those proposals as `MetadataEnrichment` records. The
capability gap is closed: `search_run.list` returns every recorded run with its funnel
counts, and `search_run.get` returns one run with its candidates and the enrichments its
candidates carry, naming `work.update_metadata` as what applies one. Both are `read`, so an
agent host may show a proposal and only the researcher may write it. Nothing is recomputed
client-side, which is what §5 P10 forbids. *Wanted now: the Corpus view that fetches
`search_run.get` and offers the proposal.*

**Server-side id allocation, over HTTP.** `claim.create`, `question.create`, `decision.accept`, and `search_run.record` allocate ids under the workspace lock on every transport. `server/app.py::_invoke` takes `ctx.repo.lock()` around every `mutate`/`admin` capability and the allocating handlers take it again; `WorkspaceRepository.lock()` nests within one repository (only the outermost context releases the OS lock), so the cockpit posts no id anywhere and the Override control writes its Decision over HTTP. `tests/e2e/test_web_gate.py` asserts the same id sequence over HTTP and in process.

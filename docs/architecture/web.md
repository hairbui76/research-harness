# The Web research cockpit

The cockpit is a React client of the local daemon. It owns no research logic: every
mutation is one `POST /capabilities/<name>` call, and every judgement it displays — which
items need review, in what order, what a claim may say, whether an acceptance is allowed —
was made server-side and is rendered, not recomputed (PRODUCT §5 P10, §26; ADR-004).

The default screen is a conversation, and it is still a cockpit rather than a chat window:
`/` is the conversation workspace, and Overview, Review inbox, Conflicts, Stale, Corpus,
Claims, Questions, Synthesis, Taxonomy and Manuscript are all one click away in the rail.
Nothing a researcher says in the conversation becomes accepted scientific state; the screen
they spend their day on still puts the source page beside the decision.

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

Every one of them is a read. The write surface is still `POST /capabilities/<name>` alone —
watching a streamed answer arrive is not authority to have asked for it — and
`tests/contract/protocol/test_http.py` asserts the whole route set so a new one cannot
appear by accident.

| Route | What it is for |
|---|---|
| `GET /artifacts/{artifact_id}/bytes` | The immutable file an anchor was accepted against, streamed inline (§42 D). |
| `GET /blocks/{artifact_id}` | The stored parse: page, order, and bbox per block, so the source pane can draw the span without re-parsing. |
| `GET /candidates/{candidate_id}` | One staged candidate verbatim. `evidence.accept` takes the `Evidence` object, so the cockpit reads it and posts it back unchanged. |
| `GET /overview` | Attention first: review items, conflicts, stale objects, unsupported manuscript claims, then claim health and open questions. Composed server-side. |
| `GET /index` | Summaries of everything the navigation lists: works, claims, questions, decisions, matrices, taxonomies, manuscript anchors. The cockpit reads this through `state.index` instead — same answer, and a name every host shares — but the route stays for anything that wants one round trip. |
| `GET /runs/{run_id}/events` | The server-sent events of one model call: `delta`, `status`, `error`, ending after the terminal status. The daemon persists every delta into the message *before* emitting it, so a client that reconnects reads the same content from `session.get` (plan §0.4). |
| `GET /sessions/{id}/attachments/{sa}/bytes` and `/preview` | The bytes of a file a session already holds, and a rendered page preview of it. Read with the token header and turned into object URLs, exactly as artifact bytes are. |

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
`ManuscriptAnchors`, `RevalidationView`, `TraceView`, `FindingLocation`, and the whole
`// manuscript workspace (P21)` block — `ManuscriptTree`, `FileSnapshot`, `BuildView`,
`SynctexView`, `SuggestionCandidate`, `AppliedSuggestion` and their nested models) are not in
the OpenAPI document, so `src/api/dto.ts` declares them by hand.
`tests/contract/protocol/test_web_routes.py` checks every field name in those declarations
against the response schema the daemon publishes, which is what stops them drifting. Until
the snapshots are re-exported, the eight `manuscript.*` workspace names are also absent from
the generated `CapabilityName` union; `HarnessClient` narrows them to
`ManuscriptWorkspaceCapability` and casts once, in `manuscriptCall`, so a typo is still a
compile error and the seam disappears with the next regeneration.

Run both after changing a route, a DTO, or a capability request model.

## Layout

```
web/
  openapi.json          daemon OpenAPI snapshot          (checked in)
  capabilities.json     GET /capabilities snapshot       (checked in)
  scripts/              export_backend_json.py, gen-types.mjs
  src/api/              client.ts (mirrors HarnessHttpClient), dto.ts, schema.ts,
                        session.ts, sse.ts, *.gen.ts
  src/app/              session context, Layout (the shell), routes.tsx, TokenBar,
                        SettingsDialog, useAsync
  src/components/       SourcePane, ReviewActions, JsonEditor, ObjectRef, Feedback
  src/views/            one per navigation entry, plus the detail screens
  src/views/manuscript/ the LaTeX workspace: the route, its four hooks, its three panes
  src/views/conversation/ the conversation workspace: the `/` route, its state, its hooks,
                        the transcript, the composer, the receipt, promotion, the inspector
  src/views/conversation/attachments/
                        intake, the tray, previews, the send check, `Save to corpus`
  src/pdf/              pdf.js adapter: worker, usePdfDocument, PdfPage
  src/render/           Markdown + KaTeX renderer
  src/editor/           CodeMirror LaTeX editor
  src/styles.css        application layout only; everything else is the Design System
  src/test/             harness.tsx, the axe helper, and the exported fixtures
```

`src/api/client.ts` is the TypeScript twin of
`research_harness.protocol.http.HarnessHttpClient`: it knows the routes and the envelopes
and nothing else. A capability refusal comes back as `ok: false` with a stable `code`; the
typed helpers raise `CapabilityError` carrying it, and the views render the daemon's own
message.

## The shell and the Design System

Every pixel the cockpit draws comes from `@research-harness/design`
(`docs/architecture/design-system.md`). The client itself owns no palette, no typography, no
button and no badge.

**`src/main.tsx`** imports `@research-harness/design/styles.css` *before* `./styles.css`, so
the package's token layer and base rules are in force and the application stylesheet only
adds what is genuinely layout. It then wraps the client in `ThemeProvider` (dark default,
comfortable density) and `ToastProvider`.

**`src/app/Layout.tsx`** is an `AppShell`: a skip link, a `ProjectRail`, and the main
surface. The rail carries the project name from `GET /overview`, the PRODUCT §26 navigation
with the counts the daemon reported in `overview.attention[].route`, `aria-current="page"` on
the active route, the principal in the footer (researcher, or the agent host that may only
read and propose), and a Settings dialog holding the theme and density toggles. Below the
shell's width breakpoint the rail becomes a drawer and the main surface stays mounted, so
nothing a researcher has typed is lost.

`ProjectRail` renders real `<a href>` links and the Design System has no router, so the
shell turns a plain left click into a client-side navigation and leaves modified clicks
(new tab, new window) to the browser — the rule react-router's own `<Link>` applies.

Two slots in the shell belong to the conversation workspace: `sessionList` on the rail, and
`inspector` on the shell. The session history is in the rail on *every* route, so a
researcher reading a claim can still see and reopen the conversation they were in; the
inspector is mounted for `/` alone, because a full research page carries its own side panel.
`Layout` therefore wraps the whole shell in `ConversationProvider`
(`src/views/conversation/state.tsx`), which is the state the rail, the route and the
inspector share.

**`src/app/routes.tsx`** is the one route table, and the navigation is derived from it, so a
screen cannot appear in one and not the other. `/` renders the conversation workspace and
`/overview` renders the Overview; an unknown path renders the Overview too, because a
mistyped URL names no session.

**Every view** is a `FullPageWorkspace` — a sticky header with the page's `h1`, its
description and its toolbar — composing package components: `Card`/`Badge`/`AuthorityBadge`
through the shared helpers in `src/components/Feedback.tsx`, `EntityRef` through
`src/components/ObjectRef.tsx` (which gives a reference the cockpit route as its `href`),
`Button`/`Input`/`Select`/`Textarea`/`Dialog` directly, `AsyncState`/`ErrorNotice`/`Toast`
for loading, empty and failure states, and `EvidenceCard`/`ClaimCard`/`SourceAnchor`/
`ProvenancePath`/`ReviewDecisionBar` for the research objects themselves. Tables set
`data-density="compact"` and scroll inside a named `ScrollArea` rather than widening the page.

**Status is never colour alone.** `StatusBadge` sends the six `AuthorityLabel` words to
`AuthorityBadge` and everything else — review categories, verifier verdicts, screening and
anchor states — to a toned `Badge`, and both always render the daemon's own word beside the
glyph. `authorityOf()` is the single place a v1.0 assessment status is mapped onto the v1.1
authority vocabulary; it disappears when the ResearchGraph carries `authority` on every node.

**The lint.** `design/scripts/check-tokens.mjs` scans `web/src` as well as `design/src` and
**fails** on any `#hex`, `rgb()`, `hsl()`, `oklab()`, `oklch()` or a `color-mix()` over
literals; a genuine visualisation case annotates the line with `/* raw-colour-ok: … */`. It
runs inside `pnpm --filter @research-harness/design lint`. `web/src/styles.css` reads
`--rh-*` tokens only.

## The conversation workspace

`/` is the screen a researcher starts on (`src/views/conversation/`). It is the
conversation-first workspace of `docs/superpowers/specs/2026-09-03-conversation-workspace-design.md`,
and its one rule is the same as the rest of the cockpit's: conversation is durable *private
working context*, never accepted scientific state. Nothing on this screen writes research
state except an explicit promotion, and every answer carries a receipt saying exactly what
the model was shown.

**The URL carries the session.** `/?session=CS0001`, optionally `&message=M0042`. One route,
so the rail's session list is a query change rather than a remount, a conversation is
linkable and bookmarkable, and the deep link `rh://session/CS0001?message=M0042` (plan §0.1)
resolves to exactly that address. Reopening the project with no session in the URL restores
the one this workspace was last in — remembered per workspace path in `localStorage` — and
otherwise the most recently updated one.

**Three panes, from two places.** The rail and the inspector are `AppShell`'s, because the
shell owns the narrow-screen behaviour the spec asks for: below 960px both side panes become
drawers and `main` is never unmounted, so opening the session list cannot lose an unsent
draft. The centre is `ConversationWorkspace`: a toolbar, the scrolling transcript, and a
composer pinned below it. The inspector starts open on a wide screen and closed on a narrow
one — a research pane that covers the draft on load is the thing §9 forbids.

### What each part calls

| Part | Capability |
|---|---|
| Session history, search, create, rename | `session.list`, `session.search`, `session.create`, `session.rename` |
| Transcript, and every reconciliation | `session.get` |
| Send, stop, retry | `session.send`, `session.stop`, `session.retry` |
| The answer as it arrives | `GET /runs/{run_id}/events` (a read) |
| `Context used` on an answer | `context.get` |
| `Preview context` on a draft | `context.preview` with `persist: false` |
| Promotion | `session.promote` |
| The model selector | `provider.list` |
| Inspector tabs | `evidence.list`, `claim.list`, `review.inbox`, `state.stale`, `GET /overview` |
| Attachments | the byte route and the four `attachment.*` capabilities — see **Attachments** below |

Every write is `MUTATE` and therefore researcher-only. An agent host reads the transcript,
opens receipts and browses the inspector; Send, New session, Rename and Promote are absent or
disabled with the daemon's own reason (PRODUCT §29, ADR-007).

### Streaming, and why the client never owns the answer

`session.send` returns as soon as the user's message, the `ContextPack` and the run are
durable, and hands back ids that can already be read. The deltas are then a *read* of what
the run has persisted — the daemon writes each one into the message before it emits it — so
`useSend` shows them for immediacy and throws its buffer away the moment the run reaches a
terminal state, a stream drops, or the researcher stops it. What is on screen afterwards is
whatever `session.get` returned. Three consequences fall out of that and are tested:

* **A reload mid-stream recovers.** The run id is stored beside the draft, so a remount
  resubscribes; the daemon replays from delta zero and the buffer is rebuilt rather than
  appended to, so nothing is doubled.
* **An interruption keeps what arrived.** The `incomplete` marker and the retry come from
  the attempt the daemon wrote, never from a status the client invented. A stream that ends
  without a terminal status means the connection dropped, and the client says so by
  reconciling.
* **A refusal leaves the draft alone.** `useDraft` writes every keystroke to `localStorage`
  keyed by session and clears it in exactly one place: after a send that produced a durable
  message. A refusal, an outage, a navigation and a remount all leave the words where they
  were.

A retry is a new message naming the attempt it retries, so `groupAttempts` folds a retry
chain into one turn with its attempts navigable inside it. Nothing is hidden: every attempt
is still on screen, one click away, with its own `attempt n of m`.

### `Context used`

Per answer, from the `CP####` the message records; per draft, from `context.preview` with
`persist: false`, so inspecting a draft leaves no pack behind. The Design System's
`ContextReceipt` lists what was included and omitted by class with the daemon's own reason
for each omission, the provider, model and egress class, and the token allocation. Where
remembered conversation contradicted an accepted Claim or Decision, the pack's
`discrepancies` are rendered as `ConflictNotice`: the assembler already resolved it —
accepted state was sent — and the notice exists so the researcher sees the disagreement and
not only its outcome.

### References and promotion

`@` completion runs through `useReferenceQuery`, whose `ReferenceProvider` is a parameter
with two implementations by design. The one in place completes over `state.index` and
`evidence.list` — the same listings the research pages read, so it works with no projection
at all. Task W3 passes a `graph.autocomplete` provider instead, and nothing else changes: the
picker, the composer and the token round-trip only ever see `EntityRefModel`s. Selected
references travel as `references` (the stable ids) with `session.send`, and
`SendStarted.unresolved` marks the ones the assembler could not resolve on the message that
used them.

Promotion offers four targets and only four — note, question, Claim candidate, Decision
candidate — and says on screen why Evidence is not among them: evidence needs an artifact and
an exact resolvable anchor, and prose has neither. The dialog shows the provenance it is
about to record, the claim form asks for subject, predicate and object, and the result is a
toast naming what was created with a link to it. Nothing is accepted; a candidate enters the
existing review workflow.

### Two-way navigation

A reference in a message opens its object in the inspector, and the inspector's header offers
the way out to the object's own page. The other direction is the point: the inspector lists
**every message that referenced the selected object**, and each one selects that message back
in the transcript. It reads the loaded transcript rather than the graph, so it keeps working
while the projection is being rebuilt.

### References and the graph

`src/views/conversation/references/` is the Web half of Phase 20. Everything the workspace
asks the ResearchGraph goes through it, and its rule is the one the projection itself is
built on: the graph is a **disposable index with no authority of its own** (ADR-006), so
this directory renders what the daemon returns and infers nothing from it.

**Completion swaps providers, and the daemon chooses.** `useReferenceQuery`'s
`ReferenceProvider` is a one-method seam with two implementations. `graph.autocomplete`
completes over every namespace the projection holds — sessions, messages, attachments and
manuscript files as well as the corpus and the scientific state — and each row arrives with
its own `authority` and `visibility`, so a stale reference is offered *and marked* rather
than hidden. `indexReferenceProvider` (task W1, over `state.index` and `evidence.list`)
stays mounted behind it. `graph.status` picks: `available: false`, `rebuilding: true`, or a
status read that fails at all, and the fallback answers instead. That is graph spec §8's
*direct canonical reads remain possible if the graph is unavailable or rebuilding*, and the
composer says so once, in the Design System's own `index-rebuilding` wording, with a *Check
again* that re-reads the status when a rebuild finishes. A `graph.autocomplete` call that
fails after the check falls back for that query rather than emptying the picker.

**Every token is resolved before it is sent.** `graph.resolve` is the one `graph.*` read
that does not answer from the index: existence, authority, privacy and anchor freshness come
from the canonical file, or for a session from its durable record. `useResolveReferences`
puts each answer back onto the draft's own token, so the composer needs no change, and lists
the ones that did not come back clean above the box with the resolver's own sentence — the
`Composer`'s `Tag` cannot carry a resolution state and `EntityRef` renders one as an icon
*and* a word. A flagged token stays sendable: conversation spec §7 asks for *marked before
sending*, not for the researcher to be stopped from writing about a reference they know is
broken. `SendStarted.unresolved` is reconciled in afterwards and wins where it disagrees,
because it describes the send that actually happened. Which of the five words a `ResolvedView`
is shown as is the one presentational judgement in `references/mappers.ts`, and it is stated
there: a missing deep link is `broken` (it named a target this project has not got), a
missing `@` id is `unresolved` (the index may be rebuilding), `fresh: false` is `stale`, and
`visibility: private` is `private`.

**A deep link is a question, not a URL.** `rh://` in a message is handed to `deepLinks.ts`,
which resolves it and only then navigates — plan §0.1 requires the project, existence,
authority, privacy and anchor freshness to be checked *before* anything opens. A link that
fails explains itself above the transcript in the daemon's words, and offers *Open anyway*
only when the object exists.

| link | route |
|---|---|
| `rh://artifact/A0017-3?page=6&block=B0081` | `/source/A0017-3?page=6&block=B0081` |
| `rh://artifact/A0017-3` | `/corpus/W0017`, where the file is listed |
| `rh://evidence/E0482`, `claim`, `work`, `version`, `question`, `decision` | their own pages |
| `rh://session/CS0001?message=M0042` | `/?session=CS0001&message=M0042` |
| `rh://attachment/SA0003` | the session the graph says holds it, attachment selected |
| `rh://manuscript/main.tex?line=120` | `/manuscript?file=main.tex&line=120` |

`/source/:artifactId` is new and is not on the navigation: an artifact is reached through a
reference, never by browsing to "source". It is thin on purpose — `GET /blocks/{artifact}`
for the stored parse, then the review screen's own `SourcePane`, so the page, the highlight
and the geometry have one implementation. `ManuscriptWorkspace` reads `?file=` and `?line=`
once per address and opens that position through its existing `openAt`.

**The inspector traverses in both directions.** The Context tab's graph pane asks
`graph.provenance` for the path to the exact artifact anchor — `C0001 → supports → E0482 →
anchored_at → B0081 → contains → A0017-3`, ending in a `SourceAnchor` that opens the page
and block — and `graph.neighbors` for one hop in both directions, grouped by relation. Two
things it is careful about:

* **The edge's authority is not the node's.** Accepted Evidence can be joined to a Claim by
  an unreviewed proposal, so every scientific row carries both badges with "this relation
  is" between them, and a `model_proposed` edge also says *proposed by a model, not
  reviewed*. A candidate relation is never drawn as an accepted one (ADR-003).
* **Privacy is the graph's answer.** The traversal is asked for under the session's egress
  class — a `project` session passes `visibility: ['project']`, a `private` session asks for
  everything on this machine, because private context never leaves it — and the result is
  rendered exactly as it comes back. A private prior-session message missing from a
  project-visible object's neighbourhood is missing because the daemon pruned the walk, and
  nothing on this side filters, re-ranks or re-adds a neighbour (graph spec §8).

This is the *second* half of the two-way navigation, not a replacement for the first: task
W1's "where was this used?" reads the loaded transcript and keeps working while the
projection rebuilds, and the graph pane adds what only the graph can see — the messages in
*other* sessions that mentioned the same object, under the same egress class. Following a
neighbour inside the pane changes what is followed and never which tab is open, so the walk
out to the evidence and back to the claim is one movement.

| Part | Capability |
|---|---|
| `@` completion | `graph.autocomplete`, or `state.index` + `evidence.list` when the graph cannot answer |
| Which one answers, and the composer's notice | `graph.status` |
| Every composer token, and every `rh://` link | `graph.resolve` |
| The inspector's neighbourhood | `graph.neighbors` (one hop, both directions) |
| The path to the exact artifact anchor | `graph.provenance` |

`graph.query` is declared on the client and not yet called by a surface: nothing on these
screens asks a structured kind/authority/link question that a neighbourhood or a listing
does not already answer.

### Attachments

`src/views/conversation/attachments/` fills the composer's `onAttach` and `attachmentTray`.
Its one rule follows from the rest of the screen's: an attachment is **session working
material**, and only an explicit `Save to corpus` gives it a corpus identity.

**Intake.** Files dropped anywhere on the composer, or chosen through its paperclip, reach
one handler. `POST /sessions/{id}/attachments` is the single documented write that is not a
capability call (plan §0.4): the raw file is the body, its media type is the `Content-Type`,
and `?filename=` is display metadata the daemon reduces to a basename. It writes session-only
bytes through the same service `attachment.add` uses, under the same researcher-only
`mutate` authorisation, and can create no Work, Version, Artifact or Evidence.

The lifecycle on screen is the daemon's, mirrored: a dropped file is a local row in
`validating` until the route answers with the record it wrote — `ready`, or `failed`
carrying the daemon's reason. Files upload one at a time and each result is recorded on its
own, so **a batch with one refusal leaves the others ready**; a failed row keeps its `File`,
so `Retry` re-uploads what was chosen rather than asking for it again. Nothing in the client
decides that a PNG is too large or a PDF too long: it asks, and renders the answer.

**The tray is the draft's files, not the session's.** `session.get` lists every attachment a
session holds, including the ones past turns carry; those belong to their turn. The tray
therefore shows the records no message references yet, plus the ones still arriving, and it
is those ids that ride in `SendMessageRequest.attachments`. A tray that re-offered a sent
file would silently attach it to every later message.

**Previews.** Images get a thumbnail, a gallery with arrow keys, zoom and the original bytes
to download; PDFs get a file card, a page viewer and page navigation, rendered by pdf.js
through `src/pdf` over the attachment's *own bytes* (the card's thumbnail is still the
daemon's PNG, which is what makes a tray of ten PDFs cheap). Every byte route carries the
token in a header, so each file is drawn from an object URL and nothing is fetched from the
network. The viewer says in words that previewing a file — or sending it to a model — adds
nothing to the corpus. An unsupported type is never dropped and never given a preview it
cannot honour: it keeps the generic card, its state and the daemon's reason.

**Model compatibility.** `attachment.check_send` runs whenever the selected model or the set
of attachments changes, and again immediately before a send, because those are two controls
a researcher can change between one and the other. A blocked verdict fills the composer's
`blockedReasons` with **every** blocked item — its own reason, its own suggested model —
disables Send, and leaves the draft and the attachments exactly as they were. Size, page,
count, media, egress and privacy are all decided in `conversation/attachments.py`; the
client renames the answer and adds no rule. A check that could not run at all is reported as
a note and blocks nothing: `session.send` runs the same check inside the mutation and
refuses there, in the same words.

`Context used` already lists attachments — `receipt_items` packs each one under the
`attachments` context class as sent, converted or omitted, with the omission reason and the
model that would have taken it — so the receipt needed no change.

**`Save to corpus`.** Two capabilities, in order and never merged: `attachment.resolve_identity`
is a read that answers what the bytes would become, and `attachment.save_to_corpus` acts on
the researcher's confirmation. Nothing is preselected; an identity the resolver could not
decide is offered as the two answers the capability accepts (`attach_to` a Work, or
`as_new`), and a decided one sends no answer at all, because the save resolves again under
the workspace lock. The result says what was created — `created: "nothing"` is the same bytes
resolving to the existing Artifact — and states that **no evidence was created**, which is a
field the daemon sets rather than a caveat the client adds. A failed promotion leaves the
session copy intact, previewable and retryable, and the retry is the same save again.

The flow is mounted in four places, all sharing one state, so a save started in one is
reported in all: the composer's tray, the transcript's action row, the viewer, and the
inspector's Context tab when the selected reference is an `SA####`.

| Part | Capability or route |
|---|---|
| Intake | `POST /sessions/{id}/attachments` (session-only bytes) |
| Remove | `attachment.remove` |
| Compatibility before send | `attachment.check_send` |
| Identity resolution | `attachment.resolve_identity` (a read) |
| Promotion | `attachment.save_to_corpus` |
| Bytes and page previews | `GET …/{sa}/bytes`, `GET …/{sa}/preview?page=N` |

An agent host may read a transcript's attachments and may not attach: the intake is closed
and says so in the daemon's own sentence, no attach control is offered, and a drop writes
nothing.

### Slots left open on purpose

* **Graph references (task W3).** Filled: the provider is `graph.autocomplete` with
  the index provider behind it — see *References and the graph* above.

## The review screen

`/review/:candidateId` is the screen PRODUCT §25 asks for.

The two halves are a `PaneGroup`, so the split is draggable and keyboard-resizable and
neither half can push the other off the screen. Below 1100px they stack, source first.

* **Left** — the page the span was read off, rendered from the artifact's own bytes through
  the `src/pdf` adapter (`usePdfDocument` + `PdfPage`), with the block's stored geometry
  drawn over it. pdf.js is imported lazily and its worker is configured in exactly one
  place, `src/pdf/worker.ts`, which is what keeps the no-CDN rule true at runtime. When it
  cannot run the pane falls back to the exact block text with the span marked inside it and
  a link to the unchanged file. The source is never absent.
* **Right** — an `EvidenceCard` for the proposal (quote, field, origin, evidence type,
  strength, and the `candidate` authority it holds until someone decides), the anchor and
  the reasons it is in the queue, the numeric value with the metric/unit/dataset/table a
  number must carry (§12), the verifier's verdict and rationale, competing candidates, and
  each side of any conflict with the diff of what accepting it would change.
* **Actions** — a `ReviewDecisionBar` offering Accept, Qualify, Edit, Reject, Defer and
  Request more evidence (§24.3). Each is a capability call and a refresh. The Design System
  owns the wording of the six decisions (`REVIEW_DECISION_META`), which is why the second
  button reads *Qualify* and the form it opens still submits *Accept with qualification*.
  Without the local token the bar disables every button and prints the reason on screen.

Which capability each action uses. Every one of them takes the staging id and whatever the
researcher typed, and nothing else — the cockpit never posts back the `Evidence` object the
daemon just handed it. That is what settles the queue: the handler allocates the evidence
id and marks the candidate reviewed in the same transaction.

| Action | Call |
|---|---|
| Accept | `review.accept` `{candidate_id}` |
| Qualify | `review.qualify` `{candidate_id, qualification}` |
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

## The manuscript workspace

`/manuscript` is the screen the LaTeX workspace specification asks for
(`docs/superpowers/specs/2026-09-03-latex-manuscript-workspace-design.md`): owned LaTeX
source, a real local compile, the actual PDF, and the scientific audit, in one view. It is
the Design System's `ManuscriptWorkspace` — a file tree, the source frame, the PDF frame,
and a collapsible inspector — wrapped around this client's CodeMirror (`src/editor`) and
pdf.js (`src/pdf`) adapters. Pane sizes and the inspector's open state are remembered in
`localStorage` under `rh.manuscript.*`, every access guarded, and below the package's width
breakpoint the editor and preview become tabs with *both panels still mounted*, so neither
the cursor nor the page being read is lost.

```
src/views/manuscript/
  ManuscriptWorkspace.tsx   the route (`ManuscriptPage`): layout, and nothing else
  useManuscriptFiles.ts     the tree, one buffer per open path, save and conflict
  useBuild.ts               manuscript.build / manuscript.compile, and the PDF's bytes
  useSynctex.ts             both directions, or the daemon's reason there are none
  useSuggestion.ts          stage a candidate; apply it only on an explicit click
  EditorPane.tsx            SourceEditorFrame + LatexEditor
  PreviewPane.tsx           PdfPreview + PdfPage, the coordinate flip, the text search
  AuditPane.tsx             DiagnosticsPanel, and the v1.0 anchors/trace/revalidate screen
  SuggestDialog.tsx         what `manuscript.suggest` needs, and nothing else
  mappers.ts                DTOs -> FileNode / BuildModel / DiagnosticModel / …
```

**Which capability each part calls.** All eight are `POST /capabilities/manuscript.*`; the
PDF is the one thing that cannot be assembled from JSON.

| Part | Call |
|---|---|
| File tree | `manuscript.files` — a *flat* list; `mappers.ts` grows the directories out of the path segments |
| Opening a file | `manuscript.read_file` `{path}` |
| Save (`Mod-S` or the button) | `manuscript.write_file` `{path, content, expected_hash}` |
| Compile | `manuscript.compile`, which answers with the same `BuildView` a read does |
| The inspector | `manuscript.build` `{audit: true}` — a *read*, so it answers for an agent host and for a workspace with no engine |
| Jump to PDF / back | `manuscript.synctex` `{file, line}` / `{page, x, y}` |
| Suggest… | `manuscript.suggest` `{file, line_start, line_end, provider, style?, instruction?}` |
| Apply | `manuscript.apply_suggestion` `{candidate_id, expected_hash}` |
| The pages | `GET /manuscript/builds/{build_id}/pdf`, fetched with the bearer token and handed to `usePdfDocument` as an `ArrayBuffer`, exactly as the review screen fetches artifact bytes |

**A save is an act, and a conflict is a refusal.** Edits stay in the buffer until the
researcher saves. A save presents the `content_hash` of the snapshot it was read from; when
the bytes on disk are no longer those, the daemon refuses and the frame shows a banner with
two answers. *Reload from disk* re-reads and discards the local text. *Keep mine* re-reads
only to learn the new hash — the text stays, and the next save is checked against what is on
disk now, which the banner says before the researcher has to choose. `ErrorBody` carries no
structured hashes, so the conflict is recognised by the daemon's own sentence and answered
by re-reading; the hashes in the message are never parsed.

**A failure keeps the last good PDF.** `BuildView.pdf` is set only when *this* build
produced one. When it did not and `last_good` exists, the model carries only `lastGood`,
which is what makes `PdfPreview` keep the older document on screen under a timestamped stale
banner while the diagnostics describe the source as it is now. A missing toolchain is read
off `toolchain.selected`, not off a refused compile, so the pane shows the setup guidance
without anything having been started and without a source file being touched.

**The two lists never merge.** `DiagnosticsPanel` puts compiler diagnostics and scientific
findings under separate headings with separate severity words (`Error`/`Warning` against
`Must fix`/`Review`/`Note`) and separate counts, and the inspector's tab label carries both
counts side by side — `2 compiler · 1 audit` — because summing them would answer a question
nobody asked. Either list opens the exact source position: the file is opened if it is not
already, then `LatexEditor.goTo(line)`.

**Coordinates.** `PdfLocation` is in PDF points from the page's *top* left; `PdfPage` draws
and reports in PDF *user* space, whose origin is the *bottom* left. `PreviewPane` flips
between them about the page's real height, read back from pdf.js, so the highlight is right
on A4 and on US Letter. When the build reports no SyncTeX map, both directions are disabled
and the daemon's reason is printed; nothing is guessed.

**A model never writes the manuscript.** `manuscript.suggest` stages a candidate and leaves
the file byte-identical; the diff is reviewed in a dialog with the protected spans marked in
words, the semantic summary in the reviewer's terms, and the audit status. Apply is a click
and is disabled with the reason whenever the daemon blocked it, whenever this window is an
agent host, and whenever the target file has unsaved edits that applying would overwrite.
Applying takes the snapshot `AppliedSuggestion` returns — the file the daemon wrote, read
back under the same lock — and refreshes the audit.

**Referencing.** *Copy reference* yields `rh://manuscript/<file>?line=<n>` for use in a
conversation; `manuscriptReference()` in `mappers.ts` is the one place that format is
written, and `useBuild`/`useSynctex` are reusable by the conversation routes.

**Permissions.** `files`/`read_file`/`build`/`synctex` are reads and `suggest` stages, so an
agent host sees everything and may propose. `write_file`, `compile` and `apply_suggestion`
are human-only: without the local token the editor is read-only with the reason on the chip,
Save and Compile are disabled, and Apply is disabled with the same sentence.

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
pnpm --filter research-harness-web typecheck
pnpm --filter research-harness-web lint
pnpm --filter research-harness-web test      # includes axe-core on the migrated views
pnpm --filter research-harness-web build
pnpm --filter @research-harness/design lint  # eslint + check-tokens (web/src too) + contrast
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

**Manuscript** is now the workspace above; the v1.0 anchor-and-audit screen lives on as the
inspector's second tab. `manuscript.anchors` lists every stored anchor beside the verdict it
currently earns and `manuscript.trace` walks one sentence down to its Claim and source
spans; the audit findings come from `manuscript.build`, which runs the same audit beside the
compiler's own output rather than as a second call. **Revalidate anchors** calls
`manuscript.revalidate`, which records the verdicts — a mutation, and human-only, because a
reworded sentence going stale is a change to accepted state (ADR-008); the control is
disabled with the reason for an agent host.

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

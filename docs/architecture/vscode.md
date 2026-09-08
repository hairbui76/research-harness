# VS Code manuscript client

The fourth surface of Product 1, and deliberately the narrowest. Product 28 asks VS Code to
focus on manuscript work rather than replicating the Web cockpit, so the extension answers one
question well — *may I write this sentence?* — and hands everything else to the CLI, the
cockpit, or an agent host.

It is a transport (ADR-004). It writes no canonical file, keeps no research state of its own,
and reaches the workspace only through named capabilities on the local daemon (ADR-009).
Everything it shows is an answer some capability gave.

Source: `vscode/`. Contract test: `tests/contract/protocol/test_vscode_contract.py`.

## Setup

```bash
research serve                       # the local daemon, loopback only, in the workspace
cd vscode && pnpm install            # zero runtime dependencies; dev tooling only
pnpm run compile                     # tsc --noEmit, then esbuild -> dist/extension.js
```

Then press **F5** in VS Code with `vscode/` open: the Extension Development Host starts with
the extension loaded. Open the workspace containing `.research/` in that window.

To install it into a normal VS Code instead:

```bash
cd vscode && pnpm run package        # runs `npx @vscode/vsce package`; needs network
code --install-extension research-harness-0.1.0.vsix
```

`vsce` is not a dependency of this package — packaging is a release step, not a build step, and
Phase 16 keeps the extension's dependency surface at zero runtime packages.

### Settings

| setting | default | meaning |
|---|---|---|
| `researchHarness.daemonUrl` | `http://127.0.0.1:8765` | where `research serve` is listening |
| `researchHarness.tokenPath` | `.research/daemon-token` | the local token, relative to the workspace root or absolute |
| `researchHarness.webUrl` | `http://127.0.0.1:8765` | the Web cockpit, for `[Open Claim]` and `[Open Evidence]`; set to `http://127.0.0.1:5173` while running its Vite dev server |
| `researchHarness.manuscriptRoot` | *(empty)* | manuscript project root; empty means the workspace's canonical `manuscript/` |
| `researchHarness.mainTex` | `main.tex` | entry point inside that root |
| `researchHarness.auditOnSave` | `true` | re-audit after a save |
| `researchHarness.auditDebounceMs` | `750` | how long to coalesce saves |

**Authority.** The token file is what makes the extension the researcher rather than an agent
host. Without it every read still works and every mutation comes back `permission_denied`,
which the extension reports with the fix rather than as a crash (Product 29, 34). Print the
path with `research token`.

## What it does

### Commands

| command | capability | notes |
|---|---|---|
| `Research: Audit Selection` | `manuscript.audit` | the selection's `file`, `line_start`, `line_end` go to the daemon, which narrows the report *and* re-parses only the artifacts those lines rest on; results as a quick pick, and the diagnostics refresh |
| `Research: Attach Claim` | `claim.list`, `manuscript.attach_claim` | quick pick over the whole workspace, this manuscript's own Claims first; a typed id is still accepted and validated with `GET /objects/{id}` |
| `Research: Create Claim from Selection` | `claim.create`, then `manuscript.attach_claim` | no id is sent: the daemon allocates one and the extension attaches `objects[0]`. Created `unverified` at L0 whatever scope is asked for (Product 42.G) |
| `Research: Add Research Note` | `note.add` | low-authority capture; `source` records the editor and the line as provenance |
| `Research: Open Evidence` | `manuscript.trace`, `retrieval.resolve_source` | one sentence rather than a whole-project audit; resolves the exact artifact, page, and bbox, then offers the Web cockpit |
| `Research: Revalidate Anchors` | `manuscript.revalidate` | records every anchor's verdict. A mutation, and human-only: without the token it comes back `permission_denied` |
| `Research: Show Claim Under Cursor` | `manuscript.trace`, `claim.find_support` | the Product 28 one-liner, with its three links |

`manuscript.anchors` is the read behind the same verdicts when nothing is being recorded.

`claim.audit` is also declared and contract-tested; no command drives it yet, because deciding
what evidence allows is not an editor gesture.

### Hover (Task 16.2)

Hovering a sentence in a `.tex` file shows the Claim it is anchored to:

```
C0041 — QUALIFIED · stale
Byte-level tokenization improves recall in the reviewed corpus
7 supporting works · 1 qualifying work · 0 contradicting
scope requested `field_generalization` → allowed `corpus_pattern`
cites `traffic2024`
[Open Claim] [Open Evidence] [Audit]
```

Over a sentence with no Claim it says so and offers `Attach Claim…`, because unlinked
substantive prose being visible is the point of Product 28.

### Diagnostics (Task 16.4)

`manuscript.audit` findings become editor diagnostics, placed by the finding's own
`location` (file, line range, and character span) and refreshed on save (debounced) and by
every command that mutates:

| finding | shown as |
|---|---|
| `unregistered_claim` | Information |
| `over_strong_wording` | Warning |
| `citation_mismatch` | Error |
| `unsupported_numeric` | Error |
| `stale_claim` | Warning |
| `invalid_evidence_anchor` | Error |

One rule bends the table, upward only: a finding the auditor itself marked `error` is always
an Error, so an anchor naming a Claim the graph does not hold (reported as
`unregistered_claim` at error severity) is not filed as a hint. Nothing is ever demoted — the
auditor is the authority on severity and the editor is a display.

Code actions on those diagnostics: **Attach Claim…**, and **Add NEEDS SOURCE note**, which
inserts the harness's own `% NEEDS SOURCE:` marker so the gap is visible in the manuscript
rather than only in the problem list (Product 30.2).

## Design notes

### The sentence port

`vscode/src/manuscript/latex.ts` is a port of `research_harness/manuscript/latex.py`:
normalization, the fingerprint, the abbreviation list, and the boundary rules. It exists
because a hover must answer without a round trip, and because `manuscript.attach_claim` takes
a whole `ManuscriptAnchor` — fingerprint included — so an HTTP client has to compute one.

Two safeguards keep the copy honest:

- `vscode/scripts/export_fixtures.py` builds a workspace through the real capability layer and
  writes `vscode/src/test/fixtures/manuscript.json` (every sentence Python found, with its
  fingerprint) and `audit-report.json` (a real `manuscript.audit` response, `location` on
  every finding). `vscode/src/test/latex.test.ts` asserts the TypeScript reproduces them
  exactly, and `web/scripts/export_backend_json.py` builds the same manuscript for the Web
  cockpit's fixtures, so the two clients are tested against one manuscript.
- After attaching, `Research: Attach Claim` re-audits and checks the new anchor comes back
  `valid`. If the editor and the harness disagreed about where the sentence ends, the
  researcher is told at once and pointed at `research manuscript attach <file>:<line> <claim>`,
  rather than being left with an anchor that silently matches nothing.

The port is narrower than Python in two documented ways: it reads one buffer at a time (an
`\input` ends a sentence, as a segment boundary does in Python) and its offsets are UTF-16
code units rather than code points.

Re-run the exporter whenever the manuscript modules change:

```bash
uv run python vscode/scripts/export_fixtures.py
cd vscode && pnpm test
```

`test_the_typescript_fixtures_match_what_the_daemon_returns` fails when you forget.

### Testing

`pnpm test` runs vitest against a hand-written `vscode` mock
(`vscode/src/test/vscode-mock.ts`, aliased in `vitest.config.ts`): client request shaping,
sentence-at-cursor, diagnostics mapping, hover formatting, anchor building. No editor is
downloaded and no daemon is needed.

Integration tests with `@vscode/test-electron` are optional and are not wired in, because they
download a VS Code build; if they are added they must stay behind
`RESEARCH_HARNESS_VSCODE_E2E=1` so the default suite remains hermetic (conventions.md).

The Python side of the contract is `tests/contract/protocol/test_vscode_contract.py`: it calls
the daemon with the exact bodies from `vscode/src/client/requests.ts` and asserts that every
field name declared in `vscode/src/client/types.ts` appears in the response.

## Gate P16 walkthrough

One Claim, four surfaces, no duplication (Product 42 B).

1. **Edit a section.** Open `manuscript/main.tex`. A substantive sentence with no Claim is
   flagged Information — *the sentence states a result; anchor it to a Claim so the
   manuscript stays downstream of accepted state*.
2. **Create and attach a Claim.** Select the sentence, run
   `Research: Create Claim from Selection`, give it a statement, a type, and a requested scope.
   The extension calls `claim.create` with no id, attaches the `C####` the daemon allocated
   with `manuscript.attach_claim` for the sentence at the cursor, and re-audits to confirm the
   anchor is `valid`. The Information diagnostic disappears. (Blocked over HTTP today; see
   *Still open*.)
3. **Audit it.** Run `Research: Audit Selection`. The selection's line range goes to
   `manuscript.audit`, and its findings appear in a quick pick and in the problem list —
   over-strong wording, a citation that resolves but supports nothing, a number with no
   source-observed evidence.
4. **Open the exact Evidence.** Hover the sentence, read the Claim's status and counts, and
   click `[Open Evidence]` (or run `Research: Open Evidence`). The extension walks the chain
   with `manuscript.trace`, resolves the supporting Evidence with `retrieval.resolve_source`,
   prints the artifact, page, bbox, and span into the *Research Harness* output channel, and
   opens the Web cockpit at `<webUrl>/evidence/<E####>`.
5. **See the same state from the CLI.**

   ```bash
   research claim show C0003
   research manuscript anchors
   research manuscript trace main.tex:23
   research manuscript audit
   ```

   The same Claim, the same anchor, the same findings — one canonical object, not a copy.
6. **See it from an agent host.**

   ```bash
   research mcp --stdio
   ```

   The host calls `claim.list`, `claim.find_support`, `manuscript.audit`, and
   `manuscript.trace` by the same names the extension used and gets the same answers
   (ADR-009). It cannot accept anything, and it cannot revalidate: without the local token it
   is an agent host.

## The backend gaps, closed (v0.4)

Six things the capability surface did not carry were listed here for the PM, each with a
mitigation in the extension. All six are now capabilities, every mitigation has been
deleted, and the assertions that pinned the old behaviour are gone from
`tests/contract/protocol/test_vscode_contract.py` with them.

| was wanted | now | what came out of the extension |
|---|---|---|
| a `claim.list` read | `claim.list` `{status?, stale?, type?}` | `HarnessClient.claims()` and its `GET /index` 404 fallback. The picker lists the whole workspace again, and an MCP host gets the same answer from the same name. |
| server-side id allocation | `claim.create` with no `claim.id` | all of `client/claimIds.ts` — the doubling-and-bisecting `GET /objects/C####` probe, `nextClaimIdFrom`, and the "confirm the id" input box. The id comes back in `objects[0]`. `isClaimId` survives, in `manuscriptCommands.ts`, to check an id typed by hand. |
| a line range on the audit | `manuscript.audit` `{file, line_start, line_end}` | client-side filtering in `Research: Audit Selection`. The daemon narrows the report and re-parses only what those lines rest on. |
| structured finding locations | `ManuscriptAuditFinding.location` | the message-prefix parse in `report.ts::findingLocation` — kept only as a fallback for a daemon built before the field, never as the first answer. |
| `manuscript.revalidate` and `manuscript.anchors` | both | the "Record with CLI" button and the terminal it opened. `Research: Revalidate Anchors` records the verdicts itself, and is human-only for it. |
| a trace read | `manuscript.trace` `{file, line}` | the whole-project audit `Open Evidence` and `Show Claim Under Cursor` used to pay for one cursor. |

Closed during Phase 16, and still true: `note.add` has a `source` field, so the editor
records where a note was captured as provenance (`Provenance.note`) instead of writing it
into the note text.

### Still open

**`manuscript.attach_claim` takes a whole `ManuscriptAnchor`.** There is no request that
takes `file` and `line` the way `ManuscriptService.attach` does, and no read that returns the
project's sentence stream, so the extension still reproduces the segmentation and the
fingerprint (`latex.ts`, and the two safeguards above). This is the reason the port exists.
*Wanted: `manuscript.attach_claim` by location, or a sentence-stream read.*

**Server-side id allocation works over HTTP.** `claim.create` with no id allocates under the workspace lock on every transport: `server/app.py::_invoke` holds `ctx.repo.lock()` around every `mutate` capability and the handler takes it again to allocate, which `WorkspaceRepository.lock()` now nests within one repository (the OS-level lock stays non-reentrant). `Research: Create Claim from Selection` therefore never sends an id. `tests/contract/protocol/test_vscode_contract.py` asserts the allocation over the daemon.

Two more capabilities are worth knowing about even though no command drives them.
`question.create`, `decision.accept`, and `search_run.record` allocate their ids the way
`claim.create` does; and every review action has a candidate-keyed capability
(`review.accept`, `review.qualify`, `review.edit`, `review.reject`, `review.defer`,
`review.request_more`, plus the `review.candidate` read) — the surface to use if the
extension ever grows a review command. `work.list`, `evidence.list`, `question.list`,
`decision.list`, `anchor.list`, and `state.index` complete the read surface.

Re-run `uv run python vscode/scripts/export_fixtures.py` before `pnpm test`:
`audit-report.json` carries `location` on every finding.

## Verification

```bash
cd vscode && pnpm install && pnpm test && pnpm run compile
uv run pytest tests/contract/protocol/test_vscode_contract.py -q
```

# The Web cockpit

A React client of the local daemon: the corpus, the review inbox with the source page
beside each decision, conflicts, stale objects, claims, questions, synthesis, taxonomy, and
the manuscript. It owns no research logic — every mutation is one
`POST /capabilities/<name>` and every judgement it shows was made server-side and is
rendered, not recomputed.

Full detail, including the review screen, the routes the daemon adds for it, how the
TypeScript types are generated from the daemon, and the known gaps, is in
**[docs/architecture/web.md](../architecture/web.md)**.

## Starting it

Needs Node and pnpm (`research doctor` reports whether you have them). The three JavaScript
packages — the Design System, the cockpit, and the VS Code extension — are **one pnpm
workspace rooted at the repository**, so install once at the top rather than inside `web/`:

```bash
pnpm install                                    # at the repository root, once
pnpm --filter research-harness-web build        # writes web/dist
research serve                                  # binds 127.0.0.1:8765
open "http://127.0.0.1:8765/?token=$(cat .research/daemon-token)"
```

`pnpm -r build`, `pnpm -r test`, `pnpm -r lint`, and `pnpm -r typecheck` run every package.

The daemon mounts `web/dist` at `/` when it exists, with a single-page fallback so
`/review/cand_…` and `/claims/C0001` render the shell. Without a build it serves the JSON
API alone. `RESEARCH_HARNESS_WEB_DIST=/path/to/dist` serves a bundle from elsewhere.

To develop the cockpit itself:

```bash
RESEARCH_HARNESS_DEV=1 research serve             # allows the Vite origin, dev only
pnpm --filter research-harness-web dev            # http://127.0.0.1:5173
```

`RESEARCH_HARNESS_DEV=1` is the only thing that opens CORS, and only to
`http://localhost:5173` and `http://127.0.0.1:5173`.

## The token

`?token=…` on the first load stores the token for the origin and strips it from the
address bar, so it does not survive into a bookmark or a screenshot; you can also paste it
into the bar the cockpit shows when it has none. Print the path with `research token`.

Without a token the daemon resolves the caller as an `agent_host`. That is a correct state,
not an error: the cockpit reads everything and disables every mutation control with the
reason on screen. See [Review](review.md#what-a-model-or-an-agent-host-cannot-do).

## Themes, density, and the Design System

Every surface of the cockpit composes one local package, `@research-harness/design`: the
semantic tokens, both themes, the accessible primitives, and the research, conversation and
manuscript components. The package owns presentation and nothing else — it makes no daemon
call and holds no research rule — so a status chip, a focus ring and a review action look
and behave the same on every route (ADR-029).

**Dark is the default.** It is declared on a bare `:root`, so the first paint is correct
before any preference has been read; light is opt-in. Density is `comfortable` (36px rows,
for conversation and manuscript reading) or `compact` (28px rows, for corpus tables, graph
results and review queues). Both are attributes, and the settings dialog in the shell
writes them:

```html
<html data-theme="light" data-density="compact">
```

The preference is stored on this machine and has no effect on canonical state, on
`.research/`, or on anything a model is sent. `prefers-reduced-motion: reduce` is honoured
by every transition.

Runtime rendering makes **no CDN request** — not for a font, an icon, a stylesheet, or
component code. Fonts are system stacks until licensed files are self-hosted, icons are
bundled, and KaTeX ships from the package.

To see the components on their own, the package has a specimen gallery:

```bash
pnpm --filter @research-harness/design specimens     # http://127.0.0.1:5173
```

and its own gates, which the cockpit shares:

```bash
pnpm --filter @research-harness/design lint   # eslint + raw-palette lint + WCAG contrast gate
pnpm --filter @research-harness/design test   # vitest, axe-core, per theme x density snapshots
```

The raw-palette lint fails on a `#hex` or `rgb()` outside the token and theme files — in
`web/src` as well as in the package — because a literal in a route forks the theme: it
looks right in dark and wrong in light. The contrast check resolves every `var()` chain and
gates each declared text/surface pair at WCAG 2.2 AA. The token contract, the component
map, and the known gaps are in
[docs/architecture/design-system.md](../architecture/design-system.md).

## The conversation and manuscript surfaces

Two v1.1 surfaces sit beside the v1.0 research pages:

* the **conversation workspace** — session rail, transcript with Markdown and KaTeX
  rendering, composer with `@` completion, attachment tray, the `Context used` receipt, and
  promotion actions. Every write it makes is one of the `session.*` capabilities, which
  means everything it can do is also on the [conversation guide](conversation.md) page.
* the **manuscript workspace** — file tree, source editor, PDF preview, and a collapsible
  audit inspector that keeps compiler diagnostics and scientific findings apart. See
  [the manuscript workspace](manuscript.md).

Which routes a given build mounts, and what each one is still missing, is recorded per
route in [docs/architecture/web.md](../architecture/web.md).

## Before there is anything to review

The quickest way is the bundled demo, which needs no API key:

```bash
research demo ./demo-review
research serve -w ./demo-review
```

Otherwise, stage proposals from a real workspace:

The cockpit does not run models. Stage some proposals first — from the CLI, an MCP host, or
anything else that can call `work.interrogate` and `evidence.verify`:

```bash
research ingest paper.pdf
research parse W0001
research interrogate W0001 --provider <configured>
research verify W0001 --provider <configured>
```

Then the review inbox has items, and the loop from there — accept, reject with a reason,
relate evidence to a claim, audit it, override the auditor — happens entirely in the
browser.

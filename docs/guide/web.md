# The Web cockpit

A React client of the local daemon: the corpus, the review inbox with the source page
beside each decision, conflicts, stale objects, claims, questions, synthesis, taxonomy, and
the manuscript. It owns no research logic — every mutation is one
`POST /capabilities/<name>` and every judgement it shows was made server-side and is
rendered, not recomputed.

Full detail, including the review screen, the routes the daemon adds for it, how the
TypeScript types are generated from the daemon, and the known gaps, is in
**[docs/architecture/web.md](../architecture/web.md)**.

There are two ways to serve it, and the cockpit itself is the same either way:

* `research app` — the **multi-project application**. One loopback process holds every
  project you have opened, and you switch between them in the browser.
* `research serve -w <workspace>` — the **one-workspace daemon**, unchanged. One workspace,
  one port, one `.research/daemon-token`.

## The multi-project app

```bash
uv sync
uv run research app          # binds 127.0.0.1:8765 and opens your browser
```

Installed on your `PATH` that is just `research app`; `uv run` is the repository-development
form. The command is independent of the current directory — it reads no `research.yaml` and
takes no `-w`, because the application resolves projects through its own registry. `--port`
moves it; `--no-open` prints the URL instead of launching a browser. If a compatible app is
already listening on the port, the command opens *that* one rather than starting a second
server; if something unrelated holds the port — a `research serve` daemon, for instance —
it says so and names `--port` instead of driving it.

The app serves the same `web/dist` bundle the daemon does, so build it once
([below](#starting-it-over-one-workspace)); without a build there is a JSON API and no
screen to open.

### Project Home

The first screen is **Your research projects**: every workspace the application has been
shown, most recently opened first. Each row carries the display name, the folder path, when
it was last opened, its availability (`Unavailable`, `Invalid`, `Incompatible`, `Busy`, or
nothing at all when it is fine), and how many workflows are still running in it. With no
projects registered, Project Home is where you start; with projects, the app opens the most
recent available one and Project Home stays one click away.

| action | what it does |
|---|---|
| **New project** | asks for a name and a parent folder, creates a filesystem-safe child of it, and initializes it exactly as `research init` does. It never writes into an existing folder — if the child name is taken, choose another name or use **Open folder**. |
| **Open folder** | validates a folder you choose and registers it. A folder already registered opens its existing project instead of a duplicate. |
| **Initialize research project** | offered when the folder you chose is readable but holds no `research.yaml`. It lists the files it is about to create and waits for you; nothing is initialized automatically. |
| **Locate** | for a project whose folder moved or is not mounted. It keeps the project's identity — its id, its history, its remembered conversation state — and replaces the recorded path only after the new folder validates as the same kind of workspace. |
| **Rename** | changes the display name in this application only. `research.yaml` is scientific state and is not touched. |
| **Forget project** | removes the registry entry. It **does not delete** anything: the folder and every file in it stay exactly as they are, and **Open folder** adds it back. A project with a workflow still running refuses to be forgotten until it finishes or is cancelled. |

### The project rail

Inside a project the left rail becomes the switcher. It shows the open project, every other
registered project with its availability and background-run count, **Add project**, and
**All projects** back to Project Home. Switching projects never cancels work: the workflow
keeps running, the rail says so, and returning to that project reconnects to its durable run
status. The per-project **Project actions** menu is **Show in file manager**, **Locate
folder**, **Rename**, and **Forget project** — the same four operations as on Project Home,
with the same confirmations.

### Choosing a folder

Every path that reaches the application comes from a dialog a human answered, run by the
local process rather than the browser:

* **Windows** — the native `FolderBrowserDialog`, shown from a short-lived PowerShell
  process.
* **Linux** — `zenity`, then `kdialog`.
* **Neither installed** — the dialog reports that no picker is available and the UI offers
  an authenticated field for an absolute path instead. Cancelling a dialog is a normal
  result, not an error, and changes nothing.

### The app token

The application binds `127.0.0.1` only; that is a boundary, not a default, and there is no
setting that widens it. Its authority is one random token in `app-token`, beside
`projects.json` in the application data directory
([where that is](install.md#where-the-app-keeps-its-data)).

The token never travels in a URL. What `research app` puts in the launch URL is a
single-use `bootstrap` nonce valid for a minute; the page exchanges it once, same-origin,
for a token it keeps in `sessionStorage` and removes from the address bar. So the tab is
signed in, the token dies with the tab, and a bookmarked URL without the nonce shows *"This
tab is not signed in to the local application. Start Research Harness with `research app`"*
rather than a broken screen — start the app again and you get a fresh authenticated window.

Without that token the application refuses everything on its control plane, and refuses it
without disclosing anything: an unauthenticated caller cannot list projects, learn a local
path, open a folder picker, register, rename, locate, or forget. Research authority is
unchanged by any of it — registering a folder grants access to that workspace, not the right
to accept anything in it. See [Review](review.md#what-a-model-or-an-agent-host-cannot-do).

### What it deliberately is not

* not a desktop application — no Electron, no Tauri; it is a browser page on loopback;
* not a scan of your disk — a project appears in the list because you opened it;
* no cloud sync of the registry, and no copy of project contents into application data;
* no arbitrary file or shell authority: workspace content is still reached through
  capabilities, repositories, and the manuscript and attachment services.

### When to keep using `research serve`

The one-workspace daemon is unchanged and is still the right answer when a single workspace
is the whole story: `research serve -w <workspace>`, `research mcp -w <workspace>`, `-w` on
any command, `RESEARCH_WORKSPACE`, `.research/daemon-token`, the VS Code extension, and any
script or MCP host already pointed at a fixed port. The multi-project app adds a mode; it
removes nothing.

## Starting it over one workspace

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

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

Needs Node and pnpm (`research doctor` reports whether you have them).

```bash
cd web && pnpm install && pnpm build      # writes web/dist
research serve                            # binds 127.0.0.1:8765
open "http://127.0.0.1:8765/?token=$(cat .research/daemon-token)"
```

The daemon mounts `web/dist` at `/` when it exists, with a single-page fallback so
`/review/cand_…` and `/claims/C0001` render the shell. Without a build it serves the JSON
API alone. `RESEARCH_HARNESS_WEB_DIST=/path/to/dist` serves a bundle from elsewhere.

To develop the cockpit itself:

```bash
RESEARCH_HARNESS_DEV=1 research serve     # allows the Vite origin, dev only
cd web && pnpm dev                        # http://127.0.0.1:5173
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

## Before there is anything to review

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

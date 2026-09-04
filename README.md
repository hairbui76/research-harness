# Research Harness

A local-first, provider-neutral research workstation. It converts scholarly sources into
durable evidence, auditable claims, explicit research decisions, and traceable manuscript
prose — and keeps the whole chain from **source → evidence → interpretation → claim →
synthesis → manuscript** inspectable months later. Canonical research state lives in
readable, Git-versionable files; the SQLite, FTS, and vector projections under `.research/`
are always regenerable. Models act as bounded semantic workers behind provider-neutral
contracts, and one workspace serves four surfaces — CLI, Web cockpit, VS Code, and agent
hosts over MCP — without any of them holding research logic of its own.

Conversation is the fastest way into a project and carries no authority of its own: a
session is durable, private working context, `Context used` says exactly what each model
call was shown and what it was not, and an excerpt or an attached PDF reaches accepted
state only through the same review path as everything else.

It is not a PDF chatbot, not a RAG application, and not an autonomous agent swarm.

> **Models may propose; evidence must justify; the researcher decides.**

## Install

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and SQLite with FTS5.

```bash
git clone <this repository> research-harness
cd research-harness
uv sync
uv run research doctor
```

Node and pnpm are needed only to build the Web cockpit, the Design System package, and the
VS Code extension; they are one pnpm workspace, so `pnpm install` runs once at the
repository root. Full detail: [docs/guide/install.md](docs/guide/install.md).

## Open the app

```bash
uv sync
uv run research app          # binds 127.0.0.1:8765 and opens your browser
```

`research app` is the multi-project entry point. It starts once, independently of the
current directory — it reads no `research.yaml` and takes no `-w` — and opens **Your
research projects**: every workspace you have shown it, most recently opened first. **New
project** creates and initializes a folder you choose; **Open folder** registers one that
already holds a `research.yaml`. Installed on your `PATH` the command is `research app`;
`uv run research app` is the repository-development form of the same thing.

The app remembers paths, never contents: a small `projects.json` under your platform's
application data directory. **Forget project** removes that entry and nothing else — the
folder and every file in it stay where they are. Full detail, including the folder picker,
the app token, and what the app deliberately does not do:
[the Web cockpit](docs/guide/web.md#the-multi-project-app).

`research serve -w <workspace>`, `research mcp -w <workspace>`, `-w` on every command, and
`.research/daemon-token` are unchanged. One workspace, one port, one token is still the
right shape for a script, an editor, or an MCP host.

## Try it in one command

```bash
uv run research demo ./demo-review        # bundled synthetic paper, offline, no API key
uv run research serve -w ./demo-review    # then open http://127.0.0.1:8765/?token=<.research/daemon-token>
```

The demo ingests and parses a synthetic paper, stages three proposals with the scripted
provider, verifies them, and rebuilds the projection — and accepts nothing, because that is
the researcher's step: the Review inbox in the cockpit (or `research inbox` / `research
review`) is where the loop continues.

## Run the Web cockpit over one workspace

Both `research app` and `research serve` serve the same cockpit from `web/dist`, so build
it once first (Node 20+ and pnpm 11; `research doctor` says whether you have them). Without
a build either command still runs, but serves the JSON API alone. `research serve` is the
one-workspace daemon: it takes `-w`, uses the workspace's own `.research/daemon-token`, and
is what the VS Code extension and a shell script talk to.

```bash
pnpm install                                     # once, at the repository root
pnpm --filter research-harness-web build         # writes web/dist

uv run research serve -w ./demo-review           # binds 127.0.0.1:8765, loopback only
open "http://127.0.0.1:8765/?token=$(cat ./demo-review/.research/daemon-token)"
```

The token is a file only a local process can read (`research token -w ./demo-review` prints
its path); the cockpit stores it for the origin on first load and strips it from the address
bar. Without a token the cockpit still opens, read-only, as an agent host. The default route
is the three-pane conversation workspace; Overview, Review inbox, Corpus, Claims, Manuscript
and the other research pages are in the left rail. Dark is the default theme; light and
compact density are in the rail's settings.

To work on the cockpit's source instead, run the Vite dev server against a daemon started in
development mode:

```bash
RESEARCH_HARNESS_DEV=1 uv run research serve -w ./demo-review   # opens CORS to the Vite origin only
pnpm --filter research-harness-web dev                          # http://127.0.0.1:5173, hot reload
```

Full detail, including themes, the Design System specimen gallery and the VS Code
extension: [docs/guide/web.md](docs/guide/web.md).

## Ten-minute walkthrough

Every block below was produced by running the command shown, against
`tests/fixtures/synthetic_research_paper.pdf` and the scripted provider — so the whole loop
runs offline, with no API key and no network.

**1. Create a workspace.**

```console
$ uv run research init ./demo --name demo
initialized demo at /home/you/demo
  review policy      strict
  next               research ingest <pdf>

$ cd demo
```

**2. Ingest a paper and parse it.** The file is registered by content hash as an immutable
Artifact of a Work; the parse is stored so every later anchor resolves without re-parsing.

```console
$ research ingest ../tests/fixtures/synthetic_research_paper.pdf
W0001 / V0001-1 / A0001-1: registered a new work
  identity           distinct_work
  reason             no existing work matched by identifier, title, or artifact hash
  event              work.ingested

$ research parse W0001
W0001 / A0001-1: parsed 30 blocks across 5 pages
  parser             pymupdf@1.1
  event              work.parsed
```

**3. Interrogate it.** Every answer lands in `.research/staging/`, which carries no
authority. No canonical file changed.

`--provider scripted --script <file>` is the offline adapter: it sends nothing anywhere and
answers from a JSON file, one reply per stage. With a real model, add a `providers:` block
to `research.yaml` and pass `--provider <name>` instead — see
[providers](docs/guide/providers.md). The two files used here are the ones
`tests/e2e/test_evidence_cli_loop.py` builds from a real parse of the fixture; their exact
shape is in
[providers.md](docs/guide/providers.md#the-scripted-provider).

```console
$ research interrogate W0001 --provider scripted --script extract.json \
    --field dataset --field metric_result --field method_summary
run run_20260903T000649Z_f803a690: staged 3 candidate(s) across 3 field(s)
  cand_4590b9b1f474d343  dataset            All experiments use CICIDS2017
  cand_44c1f007fc0db0b2  metric_result      94.32
  cand_b09aa84fc5dee7c0  method_summary     The encoder is a twelve layer transformer
```

**4. Verify.** A second reader re-opens each span. It sees the span and the assertion but
not the extractor's reasoning — agreement only carries information when the second reader
did not read the first.

```console
$ research verify W0001 --provider scripted --script verify.json
run run_20260903T000650Z_8fef6d4d: verified 3 candidate(s)
  cand_44c1f007fc0db0b2  supported
  cand_4590b9b1f474d343  supported
  cand_b09aa84fc5dee7c0  partially_supported
```

**5. Read the queue.** Conflicts first, routine last. Model confidence appears nowhere.

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

**6. Decide.** One candidate, one action, taken by you. This is the only step that creates
canonical Evidence.

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

**7. Make a claim, and let the evidence decide what it may say.** A claim is created at L0
whatever scope you ask for; the audit is what earns a wider one, and it can only lower the
ceiling.

```console
$ research claim create "TrafficLM reaches an F1 of 94.32 on CICIDS2017" \
    --scope L1 --supports E0001 --supports E0002
created C0001 (descriptive, unverified)
  requested L1 observed_subset; allowed L0 individual until audited
  relations: 2

$ research claim audit C0001
audited C0001: supported
  maximum defensible wording: among the papers examined
  allowed L1 observed_subset; requested L1 observed_subset
  support:
    - E0001
    - E0002
  coverage: 0 of 0 relevant works examined, 0 unresolved; estimated overturn risk unknown; 0 recorded search run(s)
```

**8. Write the sentence, and bind it.** Put the claim into `manuscript/main.tex`, then
attach it — the manuscript audit is what tells you whether the prose is supported.

```console
$ research manuscript attach main.tex:6 C0001
main.tex:6-6 -> C0001
  sentence           TrafficLM reaches an F1 of 94.32 on CICIDS2017.
  fingerprint        sha256:9e0af736e9a29f383fe34cfee69b395108bd0e03db013b2118d50d4358f5c571
  citations          -
  event              manuscript.claim_attached

$ research manuscript audit
1 substantive sentences: 1 anchored, 0 unregistered
0 findings (0 errors)
  the manuscript raised nothing

$ research manuscript trace main.tex:6
main.tex:6  TrafficLM reaches an F1 of 94.32 on CICIDS2017.
  claim              C0001
  evidence           E0001, E0002
  span               page 4  [94.0, 156.3, 474.0, 224.3]  '94.32'
  span               page 3  [54.0, 136.0, 551.4, 189.3]  'All experiments use CICIDS2017'
```

That is the chain, in one command: a sentence, the claim behind it, the evidence behind
that, and the exact bytes on the page.

**9. Throw the machine state away.** `.research/` holds nothing that carries scientific
authority. Delete it and rebuild — the canonical digest is identical.

```console
$ research rebuild
rebuilt 46 objects, 34 indexed rows, 0 stale marks in 70 ms
  ...
  canonical digest   sha256:ab427db61a79d7f5b8b20ebe11ac025c7ddf69b975fd60d36a7d255b2a23aa69

$ rm -rf .research && research rebuild
rebuilt 46 objects, 34 indexed rows, 0 stale marks in 92 ms
  ...
  canonical digest   sha256:ab427db61a79d7f5b8b20ebe11ac025c7ddf69b975fd60d36a7d255b2a23aa69
```

**10. Commit it.** `init` already wrote a `.gitignore` for `.research/`. Everything else —
the works, the parses, the evidence, the refusals, the claim, the anchors, the event log —
is a readable file meant to be committed.

```bash
git init && git add . && git commit -m "first evidence"
```

`tests/e2e/test_evidence_cli_loop.py` runs this whole loop and asserts it, step 9 included.

## Documentation

Start at **[docs/index.md](docs/index.md)**.

| | |
|---|---|
| [Install and first run](docs/guide/install.md) | requirements, `uv sync`, `research doctor`, creating a workspace |
| [The workspace](docs/guide/workspace.md) | the layout, canonical vs `.research/`, Git advice, identifiers |
| [The conversation workspace](docs/guide/conversation.md) | `research chat`, sessions, `@` references, `Context used`, promotion |
| [Attachments](docs/guide/attachments.md) | session-only files, what blocks a send, `Save to corpus` |
| [The ResearchGraph](docs/guide/graph.md) | stable references, `rh://` deep links, traversal, rebuild, budgets |
| [The manuscript workspace](docs/guide/manuscript.md) | files, real local LaTeX compilation, SyncTeX, candidate diffs |
| [Strict review](docs/guide/review.md) | tiers, inbox order, actions, batch conditions, what a model may not do |
| [Providers](docs/guide/providers.md) | OpenAI/Anthropic/local/scripted, subscription-backed local CLIs, env vars, egress policy, traces, cost |
| [Agent hosts over MCP](docs/guide/mcp.md) | `research mcp`, Claude Desktop and Claude Code config, tool names, resources |
| [The local HTTP daemon](docs/guide/http.md) | `research serve`, the token, routes, error codes |
| [The Web cockpit](docs/guide/web.md) · [VS Code](docs/guide/vscode.md) | building and starting the two GUI surfaces, themes and density |
| [Rebuild and recovery](docs/guide/rebuild-and-recovery.md) | rebuild, journal recovery, inconsistency, schema versions |
| [Plugins](docs/guide/plugins.md) | authoring boundaries, the manifest, allowed capabilities |
| [Troubleshooting](docs/guide/troubleshooting.md) | real error messages and what they mean |
| [CLI reference](docs/guide/cli-reference.md) · [Capabilities](docs/guide/capabilities.md) | generated from the code |

Design: [PRODUCT.md](PRODUCT.md) is the specification, [ROADMAP.md](ROADMAP.md) the plan,
[docs/decisions/](docs/decisions/README.md) the binding architecture decisions, and
[docs/architecture/conventions.md](docs/architecture/conventions.md) the engineering rules.

## Status

Version 0.1.0. The v1.0 core is built: the evidence loop, claims and epistemic audit,
synthesis, manuscript traceability, discovery and coverage, cross-model verification, the
capability layer with its HTTP daemon and MCP server, the Web cockpit, the VS Code
extension, the plugin SPI, and Phase 17 hardening.

The **v1.1 conversation-first track** (ROADMAP Phases 18–21 and the Design System
foundation) is built on top of it: durable private sessions with token- and privacy-bounded
context packs and visible `Context used` receipts; session-only attachments with an explicit
`Save to corpus`; the rebuildable ResearchGraph behind `@` references and `rh://` deep
links; a manuscript workspace that compiles owned LaTeX source with a real local engine and
takes model edits only as reviewed candidate diffs; and one Design System package that every
Web surface composes. See [ROADMAP.md](ROADMAP.md) for the dated gate status of each phase.

**Subscription-backed local CLI providers** (2026-09-04): a researcher logged in to Codex
CLI or Claude Code can route research work through that CLI with no API key, under the same
privacy policy, traces, and review gates. Only a subscription login counts; the CLI runs
with its tools off, read-only or restricted according to what that CLI offers; research
content travels on stdin and never argv; and the provider is still *external* egress —
the process starts here, the model is the vendor's. Five runtimes are detected but not
routable in this release: Cursor Agent, Amp, DeepSeek Harness, and Pi document no bounded
mode, and OpenCode's is injected through the environment rather than proved by a flag, so
it stays unproven until a version with recorded fixtures is verified. A single
conversation can also name a runtime without an entry — `research chat configure`, or the
cockpit's composer, binds one session to a runtime, model, and effort level that the daemon
stores and refuses through exactly the gates a configured entry passes, except that a
private session may not be bound to one at all, because a CLI runtime is external egress.
See [providers](docs/guide/providers.md#subscription-backed-local-clis) and
[ADR-030](docs/decisions/ADR-030-cli-backed-providers-are-bounded-external-workers.md).

**The multi-project local app** (2026-09-04): `research app` serves several local projects
from one loopback process, so opening a second project no longer means stopping the first
one's workflows or choosing another port. The registry stores approved folder paths only;
project-scoped requests carry an opaque `project_id` and never a filesystem path; and the
release is deliberately not a desktop shell, not a project scan of your disk, not a cloud
sync, and not a general-purpose file agent. See
[the Web cockpit](docs/guide/web.md#the-multi-project-app).

Known gaps are recorded where they matter rather than hidden: see
[docs/plans/acceptance-matrix.md](docs/plans/acceptance-matrix.md) for what each acceptance
behaviour rests on today, and the "known gaps" sections of
[docs/architecture/web.md](docs/architecture/web.md) and
[docs/architecture/vscode.md](docs/architecture/vscode.md).

## Development

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src

pnpm install            # once, at the repository root: design + web + vscode
pnpm -r typecheck && pnpm -r lint && pnpm -r test && pnpm -r build
```

Read [docs/architecture/conventions.md](docs/architecture/conventions.md) before touching
code.

## License

MIT.

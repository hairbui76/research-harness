# Research Harness

A local-first, provider-neutral research workstation. It converts scholarly sources into
durable evidence, auditable claims, explicit research decisions, and traceable manuscript
prose — and keeps the whole chain from **source → evidence → interpretation → claim →
synthesis → manuscript** inspectable months later. Canonical research state lives in
readable, Git-versionable files; the SQLite, FTS, and vector projections under `.research/`
are always regenerable. Models act as bounded semantic workers behind provider-neutral
contracts, and one workspace serves four surfaces — CLI, Web cockpit, VS Code, and agent
hosts over MCP — without any of them holding research logic of its own.

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

Node and pnpm are needed only to build the Web cockpit and the VS Code extension.
Full detail: [docs/guide/install.md](docs/guide/install.md).

## Try it in one command

```bash
uv run research demo ./demo-review        # bundled synthetic paper, offline, no API key
uv run research serve -w ./demo-review    # then open http://127.0.0.1:8765/?token=<.research/daemon-token>
```

The demo ingests and parses a synthetic paper, stages three proposals with the scripted
provider, verifies them, and rebuilds the projection — and accepts nothing, because that is
the researcher's step: the Review inbox in the cockpit (or `research inbox` / `research
review`) is where the loop continues.

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
| [Strict review](docs/guide/review.md) | tiers, inbox order, actions, batch conditions, what a model may not do |
| [Providers](docs/guide/providers.md) | OpenAI/Anthropic/local/scripted, env vars, egress policy, traces, cost |
| [Agent hosts over MCP](docs/guide/mcp.md) | `research mcp`, Claude Desktop and Claude Code config, tool names, resources |
| [The local HTTP daemon](docs/guide/http.md) | `research serve`, the token, routes, error codes |
| [The Web cockpit](docs/guide/web.md) · [VS Code](docs/guide/vscode.md) | building and starting the two GUI surfaces |
| [Rebuild and recovery](docs/guide/rebuild-and-recovery.md) | rebuild, journal recovery, inconsistency, schema versions |
| [Plugins](docs/guide/plugins.md) | authoring boundaries, the manifest, allowed capabilities |
| [Troubleshooting](docs/guide/troubleshooting.md) | real error messages and what they mean |
| [CLI reference](docs/guide/cli-reference.md) · [Capabilities](docs/guide/capabilities.md) | generated from the code |

Design: [PRODUCT.md](PRODUCT.md) is the specification, [ROADMAP.md](ROADMAP.md) the plan,
[docs/decisions/](docs/decisions/README.md) the binding architecture decisions, and
[docs/architecture/conventions.md](docs/architecture/conventions.md) the engineering rules.

## Status

Version 0.1.0, working toward v1.0. The evidence loop, claims and epistemic audit,
synthesis, manuscript traceability, discovery and coverage, cross-model verification, the
capability layer with its HTTP daemon and MCP server, the Web cockpit, the VS Code
extension, and the plugin SPI are all built; ROADMAP Phase 17 is v1.0 hardening. The gate
for v1.0 is that a real project is usable for a full research session without direct
database editing or dependence on conversation memory.

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
```

Read [docs/architecture/conventions.md](docs/architecture/conventions.md) before touching
code.

## License

MIT.

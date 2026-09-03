# Benchmarks

Personal-scale performance measurement for the Research Harness (ROADMAP Task 17.3,
"measure rather than prematurely optimize"). Nothing here ships with the package and nothing
here changes core code: the modules build a synthetic workspace and time the paths a
researcher waits on, so the project manager can schedule optimization against numbers.

Results, proposed budgets, and the ranked hotspot list live in
[`docs/plans/performance-budgets.md`](../docs/plans/performance-budgets.md).

## The two modules

| Module | What it does |
| --- | --- |
| `generate_corpus.py` | Builds a deterministic synthetic workspace through `WorkspaceRepository` transactions. |
| `run_benchmarks.py` | Times project open, rebuild, FTS, the Review Inbox, the claim graph, the vector index, and retrieval against it. |

## Running

```bash
# quick run: 50 works, 5,000 blocks, 2,500 evidence, 250 claims (well under a minute)
uv run python -m benchmarks.run_benchmarks --root /tmp/bench --scale 0.05 \
    --json /tmp/bench.json --markdown /tmp/bench.md

# the ROADMAP target corpus: 1,000 works, 100,000 blocks, 50,000 evidence, 5,000 claims
uv run python -m benchmarks.run_benchmarks --root /tmp/bench --scale 1.0 \
    --json /tmp/bench.json --markdown /tmp/bench.md

# corpus only, no measurement
uv run python -m benchmarks.generate_corpus --root /tmp/bench --scale 0.05 --verbose
```

Useful flags: `--quick` is the iteration profile (scale 0.05, 500 inbox candidates), and
any explicit `--scale`/`--candidates` still wins over it; `--profile` adds a `cProfile`
top-15-by-cumulative-time listing for rebuild, the inbox, and open; `--reuse` measures an
existing workspace instead of regenerating it; `--candidates` sets how many Review Inbox
candidates are staged (default 5,000); `--dimension` sets the embedding width (default 256).

`open` is measured twice, because a researcher gets two different opens: **full
verification**, which re-derives every digest the event log names, and **verification
cached**, which is what `open` costs when `.research/consistency-check.json` proves nothing
under the workspace has moved since the last successful full check. Neither is projected —
the old `--force-open` flag and the `open` scaling study existed only while verification was
quadratic, and both are gone.

```bash
# the iteration loop: build, measure, and read the table in a few minutes
uv run python -m benchmarks.run_benchmarks --root /tmp/bench --quick --markdown /tmp/quick.md
```

## What the corpus contains

At `--scale 1.0`, per the ROADMAP targets: 1,000 Works, each with one Version, one Artifact
(tiny placeholder bytes, never a real PDF), 100 parsed `DocumentBlock`s in a
paragraph/table/caption/reference mix under real section paths, and 50 accepted `Evidence`
records anchored into those blocks (every fifth one numeric, with table provenance). On top
of that: 5,000 Claims with three cross-work evidence relations each, 10 taxonomy Decisions,
one Taxonomy, synthesis matrices whose cells cite evidence, research questions, search runs,
and manuscript anchors — so the dependency graph has depth
(`decision → taxonomy → matrix → claim → manuscript anchor`) rather than being a forest.

Block text is drawn from a fixed pseudo-scientific vocabulary that always names a dataset
(`CICIDS2017`, `UNSW-NB15`, `ImageNet`, …) and a metric (`F1`, `AUROC`, `nDCG`, …), so the
FTS and retrieval queries hit real rows instead of measuring an empty index.

**Determinism.** A seed fixes the text, the structure, the ids, and every timestamp, so two
runs of one seed produce byte-identical canonical files (`research.yaml` excepted: `init`
stamps it with the wall clock). `tests/perf/test_budgets.py` asserts this.

**Transaction batching.** Works are committed 25 per journalled transaction and claims 250.
The ceiling is `workspace.events.MAX_EVENT_OBJECTS` (10,000 object digests per semantic
event): at 54 digests per work — work, version, artifact, block file, 50 evidence — a
transaction cannot hold more than 185 works. 25 amortizes the journal's fixed cost (stage
every file, fsync the staging tree, land the record, apply, fsync, commit) over ~150 files
while keeping the staged payload around 10 MB in memory.

## What is measured

1. **Generation** — informational; it is the canonical *write* path under load.
2. **`WorkspaceRepository.open`** — project open including journal recovery and consistency
   verification. Guarded above 3,000 evidence records because verification is quadratic
   (see the budgets document); above the guard the run performs a small scaling study
   instead and reports a fitted projection, clearly labelled as one.
3. **`rebuild_workspace`** — once over an existing projection, then again after
   `rm -rf .research/`.
4. **FTS** — 20 queries (exact dataset and metric terms, quoted phrases, prefix searches,
   boolean combinations) through `search_fts`, reported as p50/p95.
5. **Review Inbox** — stage 5,000 `EvidenceCandidate`s in `StagingStore`, then time
   `StagingStore.list` and `build_inbox`.
6. **Claim graph** — `DependencyGraph.from_objects`, `mark_changed` from a hub Decision,
   `assess_strength` over 1,000 claims, and `independent_support` for 100 claims against a
   synthetic citation graph.
7. **Vector index** — `SemanticIndex.rebuild` over every block and evidence unit with
   `HashingEmbeddingProvider` at dimension 256, then 20 queries as p50/p95.
8. **Retrieval** — `RetrievalService.search` for 10 mixed queries through the full authority
   ladder.

Also recorded: wall time via `time.perf_counter`, peak RSS via `resource.getrusage`,
`research.db` / index / staging / canonical tree sizes, and machine info (platform, CPU
count, Python version).

**Web interaction latency is not measured.** The Web surface (ROADMAP Phase 16) does not
exist yet; a placeholder number would be worse than an absent one. Add it here when Phase 16
lands.

## Caveats

- The page cache is warm. Dropping it needs root, so "cold open" means "cold process", not
  "cold disk"; a first open after a reboot will be slower.
- `HashingEmbeddingProvider` is a lexical approximation, not a semantic model. It is the
  right thing to benchmark (it is what a workstation with no embedding budget gets) but a
  hosted embedding provider would be dominated by network latency, not by this code.
- `run_benchmarks.open_unverified` builds a repository handle without recovery, migration,
  or consistency verification. `open` is itself one of the measurements; making every other
  benchmark pay for verification again would time the same thing many times over.

## The opt-in regression suite

`tests/perf/` runs the same benchmark at `--scale 0.05` and asserts loose ceilings:

```bash
uv run pytest tests/perf -q                          # skipped
RESEARCH_HARNESS_PERF=1 uv run pytest tests/perf -q  # ~20 s
```

Set `RESEARCH_HARNESS_PERF_SCALE` to change the corpus size. The budgets there are several
times looser than the measured numbers so a slow CI machine does not fail the build; the
budgets a researcher should actually get are in the plan document.

## The ResearchGraph benchmark (`benchmarks/graph/`)

A separate corpus and a separate measurement, because the graph's budgets (graph spec §9)
are about how long a lookup and a two-hop walk take once the index exists, not about how
long it took to write the corpus:

```bash
# the agreed personal-scale graph corpus: 200 works, 20,000 blocks, 10,000 evidence,
# 1,000 claims, 40 sessions (14 private), 1,200 messages, 200 attachments
uv run python -m benchmarks.graph.run_graph_benchmarks --root /tmp/graph --scale 1.0 \
    --json /tmp/graph.json --markdown /tmp/graph.md

# measure the corpus already there, without regenerating it
uv run python -m benchmarks.graph.run_graph_benchmarks --root /tmp/graph --reuse

# corpus only
uv run python -m benchmarks.graph.generate_graph_corpus --root /tmp/graph --scale 1.0
```

The canonical half comes from `generate_corpus.generate_workspace` at the fraction that
yields 200 works, so the two benchmarks share one generator; the conversation half is
written through `ConversationStore`. The measurement itself is
`research_harness.graph.bench`, which ships with the package so
`tests/perf/test_graph_budgets.py` and the Phase 20 gate test can run the same workload
against much smaller graphs. The exit code is non-zero when any mode misses its budget.

# The ResearchGraph

The ResearchGraph is the index behind `@` references, autocomplete, two-hop traversal, and
provenance paths. It is a **projection**: it lives at `.research/graph/research-graph.db`,
it is rebuilt by `research rebuild`, and it decides nothing. Every node and edge carries the
authority and the visibility it was projected with, and the final answer to "what is this
reference?" is read from the canonical file, never from a row (ADR-027).

```console
$ research graph status
graph index current: 50 nodes, 56 edges from 16 source(s)
  database /home/you/demo/.research/graph/research-graph.db
  built    2026-09-03T11:34:01+00:00
  schema   1
  canonical sha256:ac75569c…
```

Without a build it says so and every read answers emptily — navigation degrades, nothing
breaks:

```console
$ research graph status
no graph index at /home/you/demo/.research/graph/research-graph.db; run `research rebuild`
```

## Stable references

A reference is `@` plus an id, and it addresses a canonical object rather than a database
row — which is why it survives deleting and rebuilding the projection.

| prefix | object | prefix | object |
|---|---|---|---|
| `W` | Work | `E` | Evidence |
| `V` | Version | `C` | Claim |
| `A` | Artifact | `RQ` | ResearchQuestion |
| `S` | SynthesisMatrix | `D` | Decision |
| `CS` | conversation session | `M` | message |
| `SA` | session attachment | `CP` | context pack (receipt) |

Three kinds of identity are addressed differently, because they have no counter id of their
own: a document block is `block:<artifact>#<block>` (a `B####` is unique inside its
artifact, not across the project), a manuscript file is `file:<relative path>`, a manuscript
sentence is `anchor:<file>#<fingerprint>`, a bibliography key is `cite:<key>`, and a staged
proposal is `candidate:<candidate id>` — which never borrows an `EvidenceId`.

Some ids parse as references and resolve to nothing, on purpose. The graph does not project
taxonomies, SearchRuns, matrix *cells*, notes, or interpretations; `projection.dependencies`
remains the authority for those and for staleness. `@SR0001` therefore answers
"nothing named '@SR0001' is projected", which is the honest answer rather than an error.

```console
$ research graph resolve @E0001
@E0001 resolved in demo: accepted/project
  link   rh://evidence/E0001
  node   E0001  [evidence/accepted/project]  All experiments use CICIDS2017
  source corpus/works/W0001/evidence.jsonl

$ research graph complete E00
1 completion(s) for 'E00'
  E0001  [evidence/accepted/project]  All experiments use CICIDS2017
```

`complete` is what a composer's `@` menu calls. It matches identities first and labels
second, and it takes `--kind`, `--visibility`, and `--limit`.

## `rh://` deep links

A deep link addresses an exact location inside an object:

```text
rh://artifact/A0017-3?page=6&block=B0081
rh://evidence/E0482
rh://claim/C0041
rh://session/CS0001?message=M0042
rh://attachment/SA0003
rh://manuscript/main.tex?line=120
```

The query keys are `page`, `block`, `line`, and `message`. `research graph resolve` takes a
link as readily as a reference, and before anything opens or includes the target it checks
four things against the canonical object: does it exist **in this project**, what authority
does it carry, may it leave the machine, and **is its anchor still fresh** — both the
artifact's `file_hash` and the anchored text's `text_hash`, so a re-parse that moved a block
is reported stale rather than opened and hoped for.

Session and attachment links resolve through the conversation store rather than through the
canonical resolver, which reads corpus and scientific objects only.

## Traversal

```console
$ research graph neighbors C0041 --hops 2 --direction both
$ research graph neighbors E0001 --edge supports --edge contradicts --direction in
$ research graph query --kind claim --authority contested
$ research graph query --linked-to W0001 --text tokenisation
$ research graph provenance C0041 --to artifact
```

| flag | what it restricts |
|---|---|
| `--hops 1\|2` | how far to walk (default 1) |
| `--direction out\|in\|both` | which way to follow edges |
| `--kind` | node kind: `work`, `evidence`, `claim`, `session`, `message`, `manuscript_file`, … |
| `--edge` | edge kind: deterministic (`contains`, `version_of`, `artifact_of`, `cites`, `attached_to`, `anchored_at`, `mentioned_in`) or scientific (`supports`, `contradicts`, `qualifies`, `derived_from`, `depends_on`) |
| `--authority` | `accepted`, `candidate`, `qualified`, `contested`, `stale`, `private` |
| `--visibility` | `private`, `project` — **excluded nodes are never traversed through** |
| `--linked-to`, `--text`, `--limit` | structured and lexical filters on `query` |

`provenance` is the one that answers "why does this sentence say that": it walks a node back
to its source and prints the path, ending at the exact anchor.

```console
$ research graph provenance E0001
E0001 -> A0001-1
  from E0001  [evidence/accepted/project]  All experiments use CICIDS2017
  anchored_at (out)
      A0001-1  [artifact/accepted/project]  synthetic_research_paper.pdf
  anchor block=B0017, page=3, char_start=0, char_end=30,
         section_path=3 Experiments / 3.1 Dataset
```

## Authority and privacy are on the data

Every row is labelled, and two labels are refused at write time: a **model-proposed edge
can never be `accepted`**, and an edge read off an accepted relation can never be
`candidate`. So a model's proposed `supports` shows up in the same traversal as the
accepted ones and is visibly not one of them.

Sessions, messages, and attachments project with `private` authority — a transcript is not
reviewed state — and a message or attachment inherits **the stricter** of its own and its
session's visibility. `--visibility project` therefore cannot reach a private session even
through a public neighbour, because the filter prunes the walk rather than the result:

```console
$ research graph query --visibility private
7 node(s)
  CS0001  [session/private/private]  v1.1 dogfood: reading the demo corpus
  M0001   [message/private/private]  What does this corpus actually contain…
  SA0003  [attachment/private/private]  tiny.png
```

That is the same filter the conversation's context assembler runs under, which is why a
private prior-session excerpt cannot enter a pack bound for an external provider
([the conversation workspace](conversation.md#context-used)).

## Rebuild

`research rebuild` rebuilds the graph together with the relational projection, and reports
both:

```console
$ research rebuild
rebuilt 38 objects, 32 indexed rows, 0 stale marks, graph 50 nodes / 56 edges in 54 ms
```

The unit of projection is one durable file — a work's `evidence.jsonl`, a session's
`messages.jsonl`, one `attachments/SA0003.yaml` — each carrying its digest as a fingerprint,
so an incremental update re-projects only what changed and a full rebuild and an incremental
update produce identical output.

Deleting `.research/` and rebuilding resolves every stable reference to the same object.
The node *count* can legitimately change: staged candidates live in `.research/staging/`,
so their nodes go with them. Accepted relations, corpus identity, transcripts, and
attachments are all projected from durable files and come back unchanged.

## Speed

The budgets are measured, not asserted. On the personal-scale benchmark corpus
(200 works, 20,000 blocks, 10,000 Evidence, 1,000 Claims, 40 sessions, 1,200 messages —
33,180 nodes and 74,617 edges from 2,307 files):

| query mode | budget | measured (median) |
|---|---|---|
| exact reference resolution | < 100 ms | 0.07 ms |
| one-hop neighbourhood | < 250 ms | 0.9 ms |
| two-hop neighbourhood | < 250 ms | 8–12 ms |
| autocomplete | < 100 ms | 0.4 ms |
| provenance path to an artifact anchor | < 250 ms | 2.5–3.1 ms |
| full rebuild from durable sources | informational | ≈ 5 s |

Reproduce them with:

```bash
uv run python -m benchmarks.graph.run_graph_benchmarks --root /tmp/graph --scale 1.0 \
    --json /tmp/graph.json --markdown /tmp/graph.md
RESEARCH_HARNESS_PERF=1 uv run pytest tests/perf/test_graph_budgets.py -q
```

The full write-up, including what the corpus contains and why privacy filtering is free,
is in [docs/plans/performance-budgets.md](../plans/performance-budgets.md) and
[benchmarks/README.md](../../benchmarks/README.md).

## See also

* [Rebuild and recovery](rebuild-and-recovery.md) — what `research rebuild` does, and when.
* [The conversation workspace](conversation.md) — where `@` references are typed.
* [The workspace](workspace.md) — what is canonical, what is durable, and what is disposable.

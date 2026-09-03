# Performance budgets for personal-scale research

**Task:** ROADMAP 17.3 — "measure rather than prematurely optimize".
**Status:** measured. No core module was changed for this document; the hotspots below are
reported for the project manager to schedule.

Reproduce with:

```bash
uv run python -m benchmarks.run_benchmarks --root /tmp/bench --scale 1.0 \
    --json /tmp/bench.json --markdown /tmp/bench.md
uv run python -m benchmarks.run_benchmarks --root /tmp/prof --scale 0.05 --profile
```

See [`benchmarks/README.md`](../../benchmarks/README.md) for what the corpus contains and
what each measurement covers.

## The corpus and the machine

The ROADMAP target corpus, generated in full: **1,000 Works, 100,000 DocumentBlocks,
50,000 Evidence records, 5,000 Claims with 15,000 evidence relations**, plus 12 synthesis
matrices (1,200 cells), 10 taxonomy Decisions, one Taxonomy, 40 questions, 20 search runs,
500 manuscript anchors, and 66 semantic events across 65 journalled transactions. A rebuild
projects 158,649 objects and indexes 156,000 FTS rows.

Measured on Linux 5.14 (x86-64), 28 CPUs, Python 3.12.13, local SSD, warm page cache.
Peak RSS for the whole benchmark process: **2.6 GB**.

| On disk | Size |
| --- | ---: |
| canonical tree (`corpus/`, `claims/`, `events/`, …) | 186 MB |
| `events/research.jsonl` | 5.1 MB |
| `.research/research.db` | 225 MB |
| `.research/index/` (vector index, d=256) | 194 MB |
| `.research/` total | 430 MB |

## Measured results, and the budgets they should meet

Budgets are what a researcher should get on a workstation at this corpus size. "Today" is
the measurement above.

| Path | Budget | Today (scale 1.0) | Verdict |
| --- | --- | ---: | --- |
| Project open (`WorkspaceRepository.open`, cold process) | < 2 s | **~6.4 h (projected)** | **fail, ~10⁴×** |
| Full rebuild after `rm -rf .research/` | < 60 s | **335 s** | **fail, 5.6×** |
| Rebuild over an existing projection | < 60 s | **360 s** | **fail, 6.0×** |
| FTS query (`search_fts`, 20 queries) | p95 < 50 ms | p50 44 ms / **p95 71 ms** | **fail, 1.4×** |
| Review Inbox (`build_inbox`, 5,000 staged candidates) | < 1 s | **18.0 s** | **fail, 18×** |
| `StagingStore.list` (5,000 candidates) | < 1 s | 353 ms | pass |
| `DependencyGraph.from_objects` (56,563 objects, 86,572 edges) | < 1 s | 134 ms | pass |
| `mark_changed` from a hub Decision (2,903 marked) | < 100 ms | 6.7 ms | pass |
| `assess_strength`, per claim | < 1 ms | 0.04 ms | pass |
| `independent_support`, per claim | < 5 ms | 0.02 ms | pass |
| `load_stale_marks` | < 100 ms | 1.3 ms | pass |
| Vector index rebuild (136,000 units, d=256) | < 120 s | 70 s | pass |
| Vector query (`SemanticIndex.query`, k=10) | p95 < 100 ms | p50 58 ms / p95 99.5 ms | pass, no margin |
| `RetrievalService.search` (full ladder walk, k=10) | p95 < 250 ms | p50 74 ms / p95 141 ms | pass |
| Peak RSS for a full-corpus operation | < 4 GB | 2.6 GB | pass |
| Corpus generation (canonical write path, informational) | — | 155 s | — |

**Web interaction latency is not measured.** The Web surface (ROADMAP Phase 16) does not
exist yet. Add a row here — and a benchmark in `benchmarks/run_benchmarks.py` — when it
lands; a placeholder number now would be worse than an absent one.

### Why project open is projected rather than measured

Consistency verification grows with the square of the corpus, so a full-scale `open` would
take hours. Measured directly on smaller corpora of the same shape:

| Works | Evidence | `open` |
| ---: | ---: | ---: |
| 10 | 500 | 4.7 s |
| 20 | 1,000 | 16.4 s |
| 40 | 2,000 | 61.2 s |
| 50 | 2,500 | 87.3 s |
| 100 | 5,000 | 329.9 s |

A log-log fit over these gives `t ≈ 0.068 · works^1.84`, projecting **23,100 s (6.4 h)** at
1,000 works; extrapolating the 100-work point as a clean quadratic gives 33,000 s (9.2 h).
Either way the answer is "hours", and `benchmarks/run_benchmarks.py` therefore skips the
measurement above 3,000 evidence records and reports the fitted projection, labelled as one.

Everything else in the table scales close to linearly with corpus size: rebuild went 3.3 s →
6.8 s → 17.0 s → 33.3 s → 335 s for 10 → 20 → 50 → 100 → 1,000 works.

## Ranked hotspots

Profiles are `cProfile`, sorted by cumulative time, taken at scale 0.05 (50 works, 5,000
blocks, 2,500 evidence, 250 claims). Profiler overhead inflates wall time ~2.6×; the
*proportions* are what matter. Nothing below was changed.

### 1. `workspace/events.py::_evidence_digest` — project open is quadratic

`verify_consistency` is **99.99 %** of `open` (170.236 s of 170.241 s profiled), and
`_evidence_digest` is **98 %** of that (166.6 s over 2,500 calls, 67 ms each).

The cause is in the function itself: for *each* evidence id the event log names, it globs
`works_dir/*/evidence.jsonl` and validates every record of every file until it finds a
match. For a corpus holding 2,500 evidence records the profile shows **3,188,554
`Evidence.model_validate` calls** — every record re-parsed roughly 1,275 times.

```
     2500    3.117    0.001  166.646    0.067  workspace/events.py:363(_evidence_digest)
  3251910    3.442    0.000  151.851    0.000  workspace/serialization.py:132(iter_jsonl)
  3188554   36.913    0.000  107.503    0.000  {SchemaValidator.validate_python}
```

**Likely fix:** build the `{evidence id → digest}` map in one pass over all
`evidence.jsonl` files (O(E)) and look ids up in it. The same shape of bug sits in
`_canonical_object_digest`, which does `works_dir.glob(f"*/versions/{key}.yaml")` and
`glob(f"*/artifacts/{key}.yaml")` — a full corpus walk per Version and per Artifact id — and
in `_blocks_digest`. One index built once fixes all four.

### 2. `workspace/serialization.py::dump_yaml`, reached through `events.py::object_digest`

Digesting a canonical object serializes it to YAML with PyYAML first. This is on three hot
paths:

- **Rebuild scan:** `object_digest` is 20.7 s of a 43.6 s profiled rebuild (**47 %**), almost
  all of it `_collection_digest` (19.5 s) YAML-dumping the JSONL records — 100,000 blocks and
  50,000 evidence at full scale.
- **Canonical write:** `WorkspaceTransaction._record` → `object_digest` is 10.3 s of a
  profiled scale-0.05 generation, i.e. every Evidence record is serialized to YAML for its
  digest *in addition to* the JSON Lines record actually written. The journal, `fsync`, and
  atomic replace together are only ~2.2 s — I/O is not the write path's problem, PyYAML is.
- **Consistency verification**, again, for every object it checks.

```
     7953    0.006    0.000   20.672    0.003  workspace/events.py:120(object_digest)
   526964    3.607    0.000    4.966    0.000  yaml/emitter.py:626(analyze_scalar)
   503806    2.485    0.000    3.826    0.000  yaml/emitter.py:1080(write_plain)
```

**Likely fix:** digest the JSON form (`model_dump_json`) instead of the YAML form, or cache
the digest with the object. Note this changes the digest value, so it needs a projection /
event-log version bump — a decision for the PM, not a local optimization. A cheaper interim
step is to digest a JSONL record's own bytes (which are already produced) instead of
re-serializing it.

### 3. `projection/rows.py::upsert_rows` — one round trip and one compile per row

`upsert_rows` is **19.1 s of a 43.6 s profiled rebuild (44 %)** for 15,848 rows, while
`rows_for` — the code that actually builds them — costs 0.48 s. The time is SQLAlchemy
statement construction and compilation, not SQLite: 237,774 `Column.__init__` calls and
1.3 M `coercions.expect` calls for 15,848 statements, because each row builds a fresh
`sqlite_insert(table).values(dict(...))` and compiles its own
`INSERT … ON CONFLICT DO UPDATE`.

**Likely fix:** group rows by table and `executemany` one prepared statement per table per
batch. At scale 1.0 this is ~147 s of the 335 s rebuild.

### 4. `evidence/review.py::_build_item` — the Review Inbox is quadratic in staged candidates

`_build_item` is 55.9 s of a 56.8 s profiled `build_inbox` over 5,000 candidates. Two
comprehensions inside it scan *all* peers for *every* candidate:

```
     5000    0.158    0.000   55.897    0.011  evidence/review.py:400(_build_item)
   255000   34.553    0.000   51.657    0.000  evidence/review.py:418(<genexpr>)   # disagreeing
   990000    1.989    0.000   16.746    0.000  parsing/text.py:58(normalize_text)
   500000    3.763    0.000    3.763    0.000  evidence/review.py:411(<genexpr>)   # competing
```

Two independent problems. First, `competing` and `disagreeing` are both O(peers) per
candidate, so the whole build is O(n²). Second, `disagreeing` evaluates `set(competing)`
*inside* the comprehension, rebuilding the set once per peer, and calls `_value_key` — which
runs `normalize_text` with four regex substitutions — 990,000 times on 5,000 candidates
instead of 5,000 times.

This also explains why the inbox is *slower* on a smaller corpus: 5,000 candidates spread
over 50 works take **50.2 s**, over 201 works **18.0 s**, because the cost scales with how
many candidates share a `(work, field)` key.

**Likely fix:** bucket candidates by `(work, field)` once, and compute `_value_key` once per
candidate. Both are local to `_build_item` and change no behaviour.

### 5. `domain/ids.py::ResearchId.__new__` / `_regex` — recompiled on every id construction

In the `open` profile, id construction is **15,943,376 calls costing 57.5 s of 170 s (34 %)**,
and 35.6 s of that is `_regex()`, which rebuilds the pattern string with `re.escape` and
looks it up in `re`'s cache on *every* construction:

```
 15943376   13.932    0.000   57.494    0.000  domain/ids.py:61(__new__)
 15943376    7.143    0.000   35.620    0.000  domain/ids.py:79(_regex)
```

Most of those calls disappear once hotspot 1 is fixed, but the per-call cost is paid by every
YAML/JSONL read in the system.

**Likely fix:** compile the pattern once per subclass (a class-level cached property or a
`__init_subclass__` hook). It is a small change with no behavioural effect.

### Watch list (measured, not yet over budget)

- **`projection/fts.py::search_fts` — p95 71 ms, over the 50 ms budget.** Each call queries
  every FTS index in `INDEXES` with `bm25()` and `snippet()` and merges the results, so the
  cost grows with the number of indexes as much as with the corpus. Restricting `kinds` at
  the call site, or short-circuiting indexes that cannot match, is the cheap first move.
- **`SemanticIndex.query` — p95 99.5 ms, exactly at budget.** The index is a dense
  136,000 × 256 float32 matrix scanned per query; it will exceed the budget as the corpus
  grows.
- **`WorkspaceTransaction.allocate_id`** globs the whole flat collection directory
  (`claims/*.yaml`, `decisions/*.yaml`, …) on every allocation, which is O(n) per id and
  O(n²) over a bulk import. It did not surface in the generation profile at this scale, but
  it will on a workspace with tens of thousands of claims.
- **`projection/rebuild.py::_recompute_stale` and `projection/fts.py::build_fts` are *not*
  hotspots** — 0.14 s and 0.06 s of a 43.6 s rebuild. Do not spend time there.

## Transaction batching

The generator commits **25 Works** and **250 Claims** per journalled transaction. Two
ceilings set that. A transaction records one object digest per written object in its semantic
event and `workspace/events.py::MAX_EVENT_OBJECTS` caps that at 10,000, so at 54 digests per
Work (work, version, artifact, block file, 50 evidence) no transaction can hold more than 185
Works. Below that the journal's fixed cost — stage every file, fsync the staging tree, land
the record, apply, fsync, commit — is what batching amortizes; at 25 Works it is spread over
~150 files with roughly 10 MB of staged payload held in memory. Generating the full corpus
this way takes 65 transactions and 155 s, and journal I/O is a small share of that (see
hotspot 2).

## Regression suite

`tests/perf/` re-runs the same benchmark at scale 0.05 and asserts ceilings several times
looser than the numbers above, so a slow CI machine does not fail the build while an
order-of-magnitude regression does:

```bash
uv run pytest tests/perf -q                          # skipped
RESEARCH_HARNESS_PERF=1 uv run pytest tests/perf -q  # ~20 s since the fixes below
```

The `WorkspaceRepository.open` ceiling there was deliberately enormous (600 s at scale
0.05) while verification was quadratic. It is 20 s now; see "The regression suite" at the
end of this document.

## Results after optimization

The five hotspots above were fixed (ROADMAP 17.3, "optimize only paths that fail actual
workstation usability"). Re-measured on the same machine, at the same scale, against a
freshly generated corpus of the same shape:

```bash
uv run python -m benchmarks.run_benchmarks --root /tmp/bench --scale 1.0 --force-open \
    --json /tmp/after.json --markdown /tmp/after.md
```

`--force-open` is needed because `run_benchmarks.OPEN_EVIDENCE_LIMIT` still guards `open`
above 3,000 evidence records and reports the fitted projection instead. **That guard and its
projection are now obsolete** — `open` is linear and measurable at full scale, and a curve
fitted on 10/20/40 works is now dominated by fixed cost and projects nonsense (0.68 as an
exponent). Raising the limit is a one-line change in `benchmarks/run_benchmarks.py`.

| Path | Budget | Before | After | Verdict |
| --- | --- | ---: | ---: | --- |
| Project open (`WorkspaceRepository.open`, cold process) | < 2 s | ~6.4 h (projected) | **28.4 s** (measured) | fail, 14× — but 815× faster |
| Full rebuild after `rm -rf .research/` | < 60 s | 334.7 s | **67.2 s** | fail, 1.12× — 5.0× faster |
| Rebuild over an existing projection | < 60 s | 359.8 s | **66.8 s** | fail, 1.11× — 5.4× faster |
| FTS query (`search_fts`, 20 queries) | p95 < 50 ms | p95 70.5 ms | p95 71.3 ms | fail, 1.43× — untouched |
| Review Inbox (`build_inbox`, 5,000 staged candidates) | < 1 s | 18.0 s | **0.93 s** | **pass** — 19.3× faster |
| `StagingStore.list` (5,000 candidates) | < 1 s | 353 ms | 284 ms | pass |
| `DependencyGraph.from_objects` (56,563 objects) | < 1 s | 134 ms | 136 ms | pass |
| `mark_changed` from a hub Decision | < 100 ms | 6.7 ms | 6.0 ms | pass |
| `assess_strength`, per claim | < 1 ms | 0.04 ms | 0.04 ms | pass |
| `independent_support`, per claim | < 5 ms | 0.02 ms | 0.02 ms | pass |
| `load_stale_marks` | < 100 ms | 1.3 ms | 1.2 ms | pass |
| Vector index rebuild (136,000 units) | < 120 s | 70.1 s | 68.6 s | pass |
| Vector query (`SemanticIndex.query`, k=10) | p95 < 100 ms | p95 99.5 ms | p95 129.4 ms | fail — see below |
| `RetrievalService.search` (k=10) | p95 < 250 ms | p95 140.9 ms | p95 112.3 ms | pass |
| Peak RSS for a full-corpus operation | < 4 GB | 2.50 GB | 2.50 GB | pass |
| Corpus generation (canonical write path) | — | 155.1 s | 92.7 s | 1.67× faster |

`research.db` and the vector index come out byte-identical in size, and the canonical tree
differs only by the `screening_reason` field a concurrent change added to `Work`.

**`SemanticIndex.query` is not a regression from this work.** Nothing here touches
`retrieval/`; the index is a dense 136,000 × 256 float32 matrix scanned per query, and the
watch list above already called it "exactly at budget". Two runs of the same corpus on the
same machine gave p95 112 ms and 129 ms, so the honest reading is that it was never inside
the budget with margin. It needs its own task (an approximate index, or a narrower scan).

### What changed

1. **`workspace/events.py` — `verify_consistency` builds one index per canonical file.**
   Resolving a key used to walk the corpus: a Version or Artifact id globbed every work
   directory, and each Evidence id re-read and re-validated *every* `evidence.jsonl`, so E
   evidence records cost O(E) file reads each. `_CanonicalIndex` now builds `id → path` for
   versions, artifacts and block files, and `id → record` for evidence, rejections and
   anchors, on first use, reading each file at most once. The indexes resolve exactly what
   the per-key scans resolved — the first file in sorted order holding an id, and the last
   record for it within that file — so no verdict changes.
2. **`workspace/serialization.py` — `dump_yaml` emits through LibYAML where the bytes are
   identical.** PyYAML's pure-Python emitter was ~99 % of a digest and 47 % of a rebuild.
   LibYAML is 4-5× faster but *not* byte-compatible: it escapes `\r`, `\x85`, surrogates
   and everything above the BMP, which PyYAML emits literally, and it measures a mapping
   key against YAML's 128-character simple-key limit in bytes where PyYAML measures
   characters plus its tag. `_libyaml_emits_the_same_bytes` refuses a document that holds
   any of those characters or a mapping key that is empty, non-ASCII, or longer than 64
   characters, and the pure emitter handles it instead. On the benchmark corpus the fast
   path takes 15,885 of 15,886 objects; the one exception is a `ResearchEvent` whose
   `objects` map carries a long anchor key.
3. **`projection/rows.py` + `projection/rebuild.py` — one statement per shape, one execute
   per run.** `upsert_rows` built and compiled a fresh `INSERT … ON CONFLICT` for every
   row; it now caches one statement per `(table, columns)` and sends consecutive rows of
   one shape as a single `executemany`, and the rebuild streams every record's rows through
   one call instead of one call per record. SQLite still applies rows one at a time in the
   order given. A refused write is re-run one record at a time so the researcher still gets
   the file name — free on the path that succeeds.
4. **`evidence/review.py` — the Review Inbox indexes its peers once.** `_build_item`
   scanned every peer twice per candidate, rebuilt `set(competing)` inside a comprehension,
   and normalized each candidate's text once per peer. `_PeerIndex` buckets candidates by
   `(work, field)` and keys each one's normalized value once, answering both relations in
   the same order the scan produced.
5. **`domain/ids.py` — one compiled pattern per class.** `_regex()` rebuilt the pattern
   string with `re.escape` and looked it up in `re`'s cache on every construction — 15.9 M
   calls in one `open`. `__init_subclass__` compiles it once; construction went 0.95 µs to
   0.42 µs.

### Digests and file formats are unchanged

This was the hard constraint: object digests live in the persisted event log, so a changed
digest fails every existing workspace closed.

- `tests/unit/workspace/test_serialization.py` asserts, over Hypothesis-generated instances
  of every canonical type and over arbitrary text, that `dump_yaml` returns exactly what the
  pure-Python `CanonicalDumper` returns — including the characters the two emitters disagree
  about, which take the fallback.
- A workspace generated *before* the change was re-read after it: its object digests, its
  per-file digests, its `canonical_digest` and its event-log digests came back identical,
  and `verify_consistency` still passed. Some of its `Work` and `Evidence` digests have
  since moved because concurrent work added fields to those models; re-deriving every one of
  its objects through the pure emitter still matches what `object_digest` returns, so none of
  that drift comes from this change.
- The existing rebuild determinism and idempotence tests pass unchanged, and `research.db`
  comes out the same size.

### What is still over budget, and what it would take

**Rebuild, 67 s against 60 s.** Measured components, scaled from a 0.1 corpus:

| Phase | Scale 1.0 |
| --- | ---: |
| read and validate 150,000 JSONL records + 9,000 YAML files | ~20 s |
| digest every scanned object (`object_digest` / `_collection_digest`) | ~27 s |
| `_canonical_digest` walk | ~2 s |
| `rows_for` + batched upserts + FTS + graph + stale | ~18 s |

The single biggest remaining lever is the 27 s: `_collection_digest` digests an append-only
collection by hashing the canonical YAML of every record in it, while `verify_consistency`
already digests a blocks file by its raw bytes. Hashing the file's bytes instead would
remove ~27 s and bring a rebuild to roughly 40 s — but it changes `canonical_digest`, which
is a projection-format decision for the PM, not a local optimization. Failing that, the
remaining fat is batch fragmentation in the projection write (~230,000 rows arrive in runs
averaging nine, because `rows_for` alternates parent and child tables); grouping by table
would need the write path to respect foreign-key order explicitly.

**Project open, 28 s against 2 s.** `open` is now linear — 59,583 objects verified, each
canonical file read once — and the cost is what is left: parsing 50,000 evidence records and
re-deriving a digest for every object the event log names. No index can remove that while
`verify_consistency` re-derives every digest on every open. Reaching 2 s needs an
architectural decision rather than an optimization, and the two obvious shapes both live in
`workspace/repository.py`:

- **Skip verification when nothing changed.** `open` already has a cheap witness of "the
  canonical tree is as it was": `projection_meta.canonical_digest`. Recomputing it costs the
  same full walk, so the cheaper form is to stamp the event log's byte length and mtime
  alongside the last successful verification and re-verify only what the log gained since.
- **Verify incrementally or in the background**, returning the repository immediately and
  raising `WorkspaceInconsistentError` on the first mutation if verification fails.

Either changes when the workspace fails closed, so neither belongs in a performance task.

**FTS p95, 71 ms against 50 ms.** Untouched and unchanged: `search_fts` queries every index
in `INDEXES` per call. The watch list above still describes the fix.

### The regression suite

`tests/perf/test_budgets.py` ceilings were tightened with these numbers:
`WorkspaceRepository.open` from 600 s to 20 s, `rebuild_workspace` from 180 s to 60 s, and
`build_inbox` from 30 s to 10 s — still several times looser than what this machine measures
at scale 0.05, so a slow CI machine passes and an order-of-magnitude regression does not.

## Results after decision 1 and decision 2

The two shapes the section above left to the project manager were decided and implemented
(ROADMAP 17.3). Same machine, same corpus shape, a **freshly generated** corpus — the one
measured above no longer verifies, because concurrent work added fields to `Evidence` and
moved 50,000 object digests, which is exactly the fail-closed behaviour ADR-014 asks for.

```bash
uv run python -m benchmarks.run_benchmarks --root /tmp/bench --scale 1.0 \
    --json /tmp/after.json --markdown /tmp/after.md
```

`--force-open`, `OPEN_EVIDENCE_LIMIT`, and the `open` scaling study are **gone**. They
existed only while verification was quadratic; `open` is linear and is now measured directly
at full scale, twice — once with the check forced, once with it cached.

### Decision 1 — a verification cache for `open`

After a successful full `verify_consistency`, `WorkspaceRepository.open` writes
`.research/consistency-check.json`: a schema version, `checked_at`, the event log's size and
sha256, and `(size_bytes, mtime_ns)` for every canonical file the digest covers (artifact
binaries included, by stat rather than by content). The next `open` skips the full check only
when all of that still holds — no file added, removed, resized, or restamped, and the event
log byte-identical — and says so through `ConsistencyReport.skipped_reason`. A successful
`transaction()` commit carries the marker across its own mutation by re-stat'ing the files it
wrote and re-hashing the log; a repository that holds no marker deletes it instead, so a
verdict is never inherited by something that did not earn it. `open(..., verify="full")`
forces the whole check, and so does `repo.verify()`.

One detail is load-bearing and is not visible in the budget table. Two writes inside one
filesystem clock tick share an `mtime_ns`, so a same-size edit made in the tick a file was
written in would be invisible to `(size, mtime_ns)`. A marker is therefore only written once
the filesystem's own clock — read by stamping a throwaway file, not by `time.time_ns()`,
because the granularity varies by kernel and filesystem — has moved past every recorded
mtime, and a marker whose entries do not satisfy that is refused on read. On this machine
(xfs, 1 ms granularity) settling costs one 2 ms wait after a commit and nothing after a full
verification of a real corpus.

### Decision 2 — `canonical_digest` over file bytes

`projection/rebuild.py::canonical_digest` is now sha256 over the sorted
`(relative path, sha256 of the file's bytes)` pairs, with no per-record YAML re-dump. The
value in `projection_meta.canonical_digest` changes; `PROJECTION_SCHEMA_VERSION` is
deliberately not bumped, because the projection is dropped and rebuilt anyway and
`verify_rebuild` never compares the digest. The per-object digests the event log records, and
which `verify_consistency` re-derives, are untouched — a hand-reformatted YAML file still
does not fail a workspace closed; it just no longer keeps the same *projection* digest, which
`tests/integration/projection/test_rebuild.py` now asserts from both sides.

### Measured

| Path | Budget | Before 17.3 | After the first fixes | Now | Verdict |
| --- | --- | ---: | ---: | ---: | --- |
| Project open, nothing changed since the last check | < 2 s | ~6.4 h (projected) | 28.4 s | **0.16 s** | **pass**, 12× under |
| Project open, full verification (cold, or after any change) | < 2 s | ~6.4 h (projected) | 28.4 s | 28.9 s | fail, 14× — unchanged by design |
| Full rebuild after `rm -rf .research/` | < 60 s | 334.7 s | 67.2 s | **37.5 s** | **pass**, 1.8× faster |
| Rebuild over an existing projection | < 60 s | 359.8 s | 66.8 s | **39.4 s** | **pass**, 1.7× faster |
| FTS query (`search_fts`, 20 queries) | p95 < 50 ms | p95 70.5 ms | p95 71.3 ms | p95 71.9 ms | fail, 1.44× — untouched |
| Review Inbox (`build_inbox`, 5,000 candidates) | < 1 s | 18.0 s | 0.93 s | 4.36 s | fail — see below, not from this work |
| `StagingStore.list` (5,000 candidates) | < 1 s | 353 ms | 284 ms | 293 ms | pass |
| `DependencyGraph.from_objects` (56,563 objects) | < 1 s | 134 ms | 136 ms | 477 ms | pass |
| `mark_changed` from a hub Decision | < 100 ms | 6.7 ms | 6.0 ms | 5.7 ms | pass |
| `assess_strength`, per claim | < 1 ms | 0.04 ms | 0.04 ms | 0.04 ms | pass |
| `independent_support`, per claim | < 5 ms | 0.02 ms | 0.02 ms | 0.02 ms | pass |
| `load_stale_marks` | < 100 ms | 1.3 ms | 1.2 ms | 1.3 ms | pass |
| Vector index rebuild (136,000 units) | < 120 s | 70.1 s | 68.6 s | 71.7 s | pass |
| Vector query (`SemanticIndex.query`, k=10) | p95 < 100 ms | p95 99.5 ms | p95 129.4 ms | p95 104.1 ms | fail, no margin |
| `RetrievalService.search` (k=10) | p95 < 250 ms | p95 140.9 ms | p95 112.3 ms | p95 113.9 ms | pass |
| Peak RSS for a full-corpus operation | < 4 GB | 2.50 GB | 2.50 GB | 2.44 GB | pass |
| Corpus generation (canonical write path) | — | 155.1 s | 92.7 s | 91.6 s | — |

The three cached opens measured 162, 159 and 160 ms — the cost is one `stat` per canonical
file, one sha256 of the 5.1 MB event log, and reading a 663 KB marker. The 28.9 s full check
is the same number as before, which is the point: nothing was made faster by being skipped,
and any change at all still pays for it.

**This run shared the machine.** Load average was ~15 across the run (other work on the same
28-core box), so every number above is pessimistic and the two that moved without being
touched — `build_inbox` 0.93 s → 4.36 s and `DependencyGraph.from_objects` 136 ms → 477 ms —
are not attributable here. Nothing in this change reaches `evidence/review.py` or
`projection/dependencies.py`, and `evidence/review.py` was rewritten by concurrent work
between the two measurements. Both want a re-run on a quiet machine before anyone reads them
as a regression.

### What is still over budget

**A cold open is still 29 s.** That is the price of the guarantee, and the decision above
does not reduce it — it stops charging it when there is nothing to check. The remaining cost
is what the earlier analysis named: parsing 50,000 evidence records and re-deriving a digest
for every object the event log names. Reaching 2 s on that path needs the digests to stop
being re-derived (caching a digest with the object, or a per-file digest index that is itself
part of canonical state), which is an ADR-014 question, not an optimization.

**FTS p95, 72 ms against 50 ms.** Untouched. The watch list above still describes the fix.

**Vector query p95, 104 ms against 100 ms.** Untouched, and inside noise of the budget; it
still needs its own task (an approximate index, or a narrower scan).

### The regression suite

`tests/perf/test_budgets.py` follows the two open measurements:
`WorkspaceRepository.open (full verification)` 20 s → 10 s,
`WorkspaceRepository.open (verification cached)` 5 s (new), and `rebuild_workspace` 60 s →
30 s. `test_the_cached_open_is_the_one_that_skipped_verification` asserts the cached budget
was met by an open that actually skipped, so it cannot be satisfied by a full check that
happened to be fast. At scale 0.05 on this machine the suite runs in 17 s.

## The ResearchGraph index (Phase 20)

**Task:** ROADMAP Phase 20, Gate P20 — "meet warm targets of under 100 ms for exact refs and
under 250 ms for one- or two-hop queries on the agreed benchmark". The graph spec (§9) also
asks for autocomplete "fast enough to update interactively while typing"; that is taken here
as the usual 100 ms keystroke-response ceiling.

Reproduce with:

```bash
uv run python -m benchmarks.graph.run_graph_benchmarks --root /tmp/graph --scale 1.0 \
    --json /tmp/graph.json --markdown /tmp/graph.md
uv run python -m benchmarks.graph.run_graph_benchmarks --root /tmp/graph --reuse   # measure again
RESEARCH_HARNESS_PERF=1 uv run pytest tests/perf/test_graph_budgets.py -q          # the ceilings
```

### The agreed corpus, and why it is not the one above

The Task 17.3 corpus sizes the canonical write path and the SQLite projection rebuild at
1,000 works. The graph's budgets are about a *lookup* and a *walk* once the index exists, and
those scale with nodes and adjacency rather than with how many evidence records were parsed —
so the graph benchmark has its own shape, generated by
[`benchmarks/graph/generate_graph_corpus.py`](../../benchmarks/graph/generate_graph_corpus.py).
At `--scale 1.0`:

| Namespace | Count |
| --- | ---: |
| Works / Versions / Artifacts | 200 each |
| parsed document blocks | 20,000 |
| accepted Evidence | 10,000 |
| Claims (3 evidence relations each) | 1,000 |
| synthesis matrices / cells | 3 / 300 |
| taxonomy Decisions, questions, search runs | 10 / 12 / 7 |
| manuscript anchors | 100 |
| conversation sessions (14 of them `private`) | 40 |
| messages (120 carrying an `@` reference) | 1,200 |
| session attachments | 200 |

That is a researcher two or three years into a project: a few hundred read papers, a thousand
claims, and a chat history to match. The canonical half is the *same* generator Task 17.3
uses, called at the fraction that yields 200 works (`scale 0.2`), so the two benchmarks cannot
drift apart; the conversation half is written through `ConversationStore`, so every durable
file the session projector reads is a real one. Every third session is `private` and
references the same accepted Evidence a project-visible request may carry, so the
privacy-filtered walk has something to actually refuse.

**It projects 33,180 nodes and 74,617 edges from 2,307 durable source files**, into an 89 MB
`.research/graph/research-graph.db`.

### Measured

Same machine as the rest of this document (Linux 5.14 x86-64, 28 CPUs, Python 3.12.13, local
SSD, warm page cache) — **and it was shared**: three other engineers were running test suites
across the run. Every query mode is warmed once and discarded, then run nine times; the
*Median* column is the **median of the medians of three separate benchmark runs**, so a single
noisy moment on a loaded box cannot set the number, and the *p95* column is the **worst p95 of
the three**. The two interactive modes — exact resolution and autocomplete — agreed across the
three runs to within 0.1 ms; the two-hop walk had the widest spread, 7.84–9.58 ms.

| Query mode | Budget | Median | p95 | Verdict |
| --- | ---: | ---: | ---: | --- |
| exact stable-reference resolution (`@E0482`) | < 100 ms | **0.07 ms** | 0.08 ms | pass, 1,400× under |
| one-hop neighbourhood | < 250 ms | **0.89 ms** | 1.17 ms | pass, 280× under |
| two-hop neighbourhood | < 250 ms | **7.89 ms** | 11.2 ms | pass, 32× under |
| two-hop neighbourhood, project-visible only | < 250 ms | **8.37 ms** | 9.5 ms | pass, 30× under |
| autocomplete (3-character prefix) | < 100 ms | **0.35 ms** | 0.46 ms | pass, 285× under |
| provenance path, Claim → Evidence → Artifact anchor | < 250 ms | 2.51 ms | 4.9 ms | pass |
| `context_fragments`, project-visible, limit 40 | < 250 ms | 26.2 ms | 29.4 ms | pass |
| full graph rebuild from durable sources | — | 5.2 s | — | informational |
| incremental update, nothing changed | — | 3.5 s | — | informational |
| peak RSS for the whole benchmark process | < 4 GB | 486 MB | — | pass |

Latencies are **per query**: each run resolves 42 identities, walks 42 neighbourhoods, and
completes 7 prefixes, and the figure is the run divided by that count.

Two notes on numbers that are not budgeted but are worth having on record:

- **Privacy filtering is free.** The project-visible two-hop walk measures the same as the
  unfiltered one (8.4 ms against 7.9 ms, inside the run-to-run spread). The filter prunes the
  frontier rather than post-filtering a result, so restricting a walk can only reduce the work
  it does; `tests/perf/test_graph_budgets.py` asserts it stays within 4× of the unfiltered
  walk so a future rewrite cannot make privacy the expensive path.
- **The 3.5 s no-op update is dominated by re-projection, not by writing.** `update_graph`
  re-projects every source to compare fingerprints, so a workspace where nothing changed still
  pays for reading 2,307 files. That is the same shape as the projection rebuild and is
  outside this task; it does not touch any budgeted query mode.

### The regression suite

`tests/perf/test_graph_budgets.py` runs the same workload at the session scale
(`RESEARCH_HARNESS_PERF_SCALE`, default 0.05 → 5× the graph scale, ~1,700 nodes) and asserts
**the product budgets themselves**, not a loosened version of them. That is deliberate and it
is not the convention the rest of this suite follows: the margin here is two to three orders
of magnitude, so a slow or loaded CI machine passes comfortably while anything that turns an
indexed lookup back into a scan fails immediately. Median *and* p95 are both asserted, because
a researcher feels the slow keystroke rather than the median one. At scale 0.05 the suite runs
in about 13 s.

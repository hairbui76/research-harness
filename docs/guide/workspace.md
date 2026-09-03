# The workspace

A workspace is a directory, and every file in it belongs to one of three tiers:
**canonical** state, which carries scientific authority and is meant to be committed
(ADR-001); `.research/`, which is machine state you can delete at any time; and
`conversations/`, which is durable but private — the transcripts and their attachments that
deleting `.research/` must never lose, and that are not published by default (ADR-025).

```text
traffic-survey/
├── research.yaml                     project identity, schema version, review policy,
│                                     id counters, providers:, privacy:
├── .gitignore                        written by `init`; ignores .research/ and
│                                     conversations/
├── corpus/
│   └── works/
│       └── W0001/
│           ├── work.yaml             the scholarly work: title, authors, year,
│           │                         identifiers, screening state
│           ├── versions/V0001-1.yaml a specific version of that work (preprint,
│           │                         camera-ready, ...)
│           ├── artifacts/A0001-1.yaml  file metadata: hash, mime type, size
│           ├── artifacts/A0001-1.pdf   the immutable original bytes
│           ├── parsed/A0001-1.blocks.jsonl  the stored parse: one block per line, with
│           │                         page, section path, character offsets, geometry
│           ├── evidence.jsonl        accepted Evidence for this work, one per line
│           └── rejections.jsonl      candidates the researcher refused, and why
├── claims/C0001.yaml                 structured claims and their audits
├── questions/RQ0001.yaml             open research questions
├── taxonomy/<name>.yaml              classification vocabularies
├── decisions/D0001.yaml              researcher decisions (a taxonomy revision, an
│                                     epistemic override) with their rationale
├── matrices/S0001.yaml               cross-paper synthesis matrices
├── notes/<key>.yaml                  low-authority captures; never citable as support
├── searches/SR0001.yaml              SearchRuns: what was searched, where, when
├── manuscript/
│   ├── main.tex, references.bib      yours; the harness does not write them
│   ├── figures/
│   └── anchors.jsonl                 written by the harness: sentence → Claim bindings
├── events/research.jsonl             the semantic event log, one event per line
├── conversations/CS0001/             durable but private; see below
│   ├── session.yaml                  title, timestamps, visibility, model defaults
│   ├── messages.jsonl                the append-only transcript, one Message per line
│   ├── attachments/SA0001.yaml       session attachment metadata
│   ├── attachments/SA0001.pdf        its bytes, immutable once ready
│   ├── context/CP0001.json           one model call's ContextPack and `Context used` receipt
│   └── summary.md                    derived; regenerable, and never authoritative
└── .research/                        regenerable; see below
```

`init` creates every directory above except the per-work ones, which appear on first
ingest.

## What is canonical

Everything outside `.research/` and `conversations/`. Canonical objects are YAML (single
objects) or JSON Lines (append-heavy collections), keys in a stable order, UTF-8, with a
trailing newline —
so a `git diff` reads as a change to the science rather than to a serialization. Every
canonical object carries `schema_version`, `id`, `created_at`, `updated_at`, and
`provenance`:

```yaml
schema_version: 1
id: W0001
created_at: '2026-09-02T21:56:20.478142Z'
updated_at: '2026-09-02T21:56:20.478144Z'
provenance:
  source: human
  actor: human
  workflow: ingest
  run_id: null
  template_version: null
  note: null
title: Deep Representations for Encrypted Network Traffic
authors:
- A. Researcher
- B. Collaborator
- C. Advisor
year: 2024
```

Two canonical files deserve special mention:

* `corpus/works/*/parsed/*.blocks.jsonl` is *derived* from the PDF but stored canonically
  anyway, because every evidence anchor resolves against it. Reparsing with a different
  parser version would move the spans an accepted conclusion rests on, so the parse is
  kept rather than recomputed.
* `events/research.jsonl` is an audit companion, not a second authority. Each event
  records the digest of the object it changed. If an event and the canonical file
  disagree, the workspace fails closed — see
  [Rebuild and recovery](rebuild-and-recovery.md).

## What is regenerable

Everything under `.research/`:

| path | what it holds |
|---|---|
| `research.db` | the SQLite projection: joins, graph edges, FTS5 lexical index, stale marks |
| `index/` | disposable retrieval indexes, including the semantic vector index |
| `cache/` | caches |
| `staging/` | model proposals waiting for review, one directory per run |
| `traces/` | provider prompts, latency, retrieval traces |
| `runs/` | durable records and checkpoints of long-running workflows |
| `journal/` | the transaction journal that makes a multi-file mutation atomic |
| `graph/` | the [ResearchGraph](graph.md) projection: nodes, edges, adjacency, FTS |
| `build/manuscript/<id>/` | one LaTeX build: the PDF, the log, the SyncTeX map, `build.json` |
| `cache/attachments/` | attachment thumbnails and page previews |
| `lock` | the workspace lock |
| `daemon-token` | the local HTTP daemon's authority token |

Delete the whole tree and run `research rebuild`: the projection comes back and no
accepted conclusion changes. That is the property the design rests on, and it is asserted
end to end in `tests/e2e/test_evidence_cli_loop.py`.

Staging is part of it. A model proposal has no authority until a researcher accepts it,
so losing `.research/staging/` loses proposals, never conclusions — re-run
`research interrogate`.

## What is durable but private

`conversations/` is the third tier, and it is neither of the other two. A transcript, its
attachments, and the `Context used` receipt of every model call are **durable source
records**: deleting `.research/` may not lose one, and the session ids keep counting from
the files themselves rather than from the projection. They are also **not scientific
state**: a message cannot carry accepted authority, `conversations/` is excluded from the
canonical digest — so chat can never make a workspace inconsistent — and `init`'s
`.gitignore` keeps it out of Git, because a private thinking log is not published by
accident. Sharing one is an explicit export.

What a conversation *can* do is be promoted: an excerpt becomes a Note, a Question, a Claim
candidate, or a Decision candidate through the same capabilities and the same review gate
as anything else, and an attachment becomes corpus identity only through
`research attachment save`. See [the conversation workspace](conversation.md) and
[attachments](attachments.md).

## Git

The workspace is meant to be a Git repository. `init` writes a `.gitignore` for you:

```text
# Regenerable machine state: SQLite projection, indexes, caches, staging, traces.
# Canonical scientific state lives outside it and is meant to be committed.
.research/

# Durable but private: conversation transcripts, their attachments, and the context
# receipts of model calls. Sharing them is a separate, explicit export.
conversations/
```

```bash
cd traffic-survey
git init
git add .
git commit -m "initialise research project"
```

Practical advice:

* **Commit the PDFs.** `corpus/works/*/artifacts/*.pdf` are the bytes every anchor was
  accepted against; the artifact's `file_hash` is checked against them. If licensing or
  size makes that impossible, keep them somewhere restorable and know that
  `research manuscript audit` cannot check source spans without them.
* **Commit after review, not during it.** An acceptance touches the Work's
  `evidence.jsonl`, `events/research.jsonl`, and possibly a Claim, as one transaction. A
  commit per review session gives a history that reads like research.
* **Never resolve a merge conflict inside `.research/`.** It is not tracked; if a stray
  copy appears, delete it and rebuild.
* **Do not hand-edit canonical files.** It is technically possible — that is the point of
  a readable format — but the event log records a digest for each object, and an edit
  behind the harness's back makes the workspace inconsistent on the next open. The
  recovery path is in [Rebuild and recovery](rebuild-and-recovery.md#a-hand-edited-canonical-file).
* **`research.yaml` holds no secrets.** Provider entries name an environment variable
  (`api_key_env:`); a key written into the file is refused when the workspace opens. See
  [Providers](providers.md).

## The LaTeX toolchain (`manuscript:`)

`research.yaml` carries three optional sections: `providers:` ([Providers](providers.md)),
`privacy:`, and `manuscript:` — the local LaTeX toolchain the Manuscript workspace drives.
Every key has a default, so a project that never writes the section still compiles
`manuscript/main.tex` with the best engine on `PATH`:

```yaml
manuscript:
  engine: tectonic          # latexmk | tectonic | pdflatex | xelatex | lualatex
  entry_file: main.tex      # relative to manuscript/, must be a .tex file
  timeout_seconds: 120      # the process group is killed at this point
  extra_args: [-file-line-error, -halt-on-error]
  synctex: true             # ask the engine for the source ↔ PDF map
```

| key | default | meaning |
|---|---|---|
| `engine` | the first installed of `latexmk`, `tectonic`, `pdflatex`, `xelatex`, `lualatex` | pin one engine; a pinned engine that is not on `PATH` is a setup message, never a fallback |
| `entry_file` | `main.tex` | the file a compile runs, relative to `manuscript/`; `..`, absolute paths, and non-`.tex` names are refused |
| `timeout_seconds` | `120` | wall clock for the whole run; on expiry the process *group* is killed and the log written so far is still parsed |
| `extra_args` | `[]` | extra compiler flags, from a fixed allowlist |
| `synctex` | `true` | request SyncTeX data; without it source ↔ PDF navigation reports itself unavailable rather than guessing |

`extra_args` is an allowlist, not a passthrough: a compiler flag is an execution
capability, so anything not on the list is refused when `research.yaml` is read, before any
process starts. The accepted flags are `-bibtex`, `-bibtex-cond`, `-file-line-error`,
`-halt-on-error`, `-interaction=batchmode`, `-interaction=nonstopmode`, `-pdf`, `-pdflua`,
`-pdfxe`, `--keep-intermediates`, and `--keep-logs`. The harness owns the output directory,
the working directory, and the SyncTeX flag, so nothing may name a file or a program.

What the compile does *not* get is as fixed as what it does. The working directory is
`manuscript/`, `shell=False`, and the environment is rebuilt from a small allowlist with
`TEXINPUTS`/`BIBINPUTS` pinned to the project and `shell_escape=f`. `tectonic` runs
`--untrusted`. **`latexmk` runs with `-norc`**, because a project `latexmkrc` is unsandboxed
Perl that would execute on every compile, while a `.tex` file without shell escape is not.

Output goes to `.research/build/manuscript/<build id>/` — disposable, like everything else
under `.research/`. Deleting it loses build outputs and never a manuscript file: the last
good PDF simply stops being available until the next successful compile.

## Identifiers

Ids are stable, typed, and allocated from counters in `research.yaml`:

| prefix | object | example |
|---|---|---|
| `W` | Work | `W0001` |
| `V` | Version | `V0001-1` |
| `A` | Artifact | `A0001-1` |
| `B` | DocumentBlock | `B0022`, or `B0022@A0001-1` when the artifact matters |
| `E` | Evidence | `E0001` |
| `C` | Claim | `C0001` |
| `RQ` | ResearchQuestion | `RQ0001` |
| `D` | Decision | `D0001` |
| `S` | SynthesisMatrix | `S0001` |
| `SR` | SearchRun | `SR0001` |
| `CS` | conversation session (durable, private) | `CS0001` |
| `M` | message in a session | `M0042` |
| `SA` | session attachment | `SA0003` |
| `CP` | context pack / `Context used` receipt | `CP0007` |
| `cand_<16 hex>` | staged candidate (in `.research/`, never canonical) | `cand_44c1f007fc0db0b2` |

A Work is the scholarly work, a Version is one revision of it, and an Artifact is one file
of one version. Evidence anchors to an Artifact, a block, and a character range; citations
are about the Work (ADR-002).

Most of these ids are also stable `@` references in a composer, resolved through
`research graph resolve` against the canonical object rather than a database row — which is
why a reference survives deleting the projection. Blocks are addressed as
`block:<artifact>#<block>`, manuscript objects have no counter id at all, and a few
namespaces (taxonomies, SearchRuns, matrix cells, notes) are deliberately not projected.
See [the ResearchGraph](graph.md#stable-references).

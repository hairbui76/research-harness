# Troubleshooting

Every message below was produced by running the command shown. A command that fails prints
one `error:` line on stderr and exits 1; a workflow that fails inside a model stage prints
a traceback whose **last paragraph** is the useful part.

Start with `research doctor` — from inside the workspace it checks the interpreter, SQLite
FTS5, the workspace schema, consistency with the event log, the projection, providers and
their key variables, the egress policy, the daemon token, and the plugin directories. See
[Rebuild and recovery](rebuild-and-recovery.md#research-doctor).

## Finding the workspace

```text
error: no research workspace at or above /tmp: run `research init <dir>`, pass --workspace, or set RESEARCH_WORKSPACE
```

You are not inside a workspace. Pass `-w <dir>`, export `RESEARCH_WORKSPACE`, or `cd` into
the project. `init` and `doctor` are the only commands that do not need one.

```text
error: a research workspace already exists at /home/you/projects/traffic-survey
```

`init` never overwrites. To start over, remove the directory yourself.

## Providers and keys

```text
error: no model providers configured: add a `providers:` list to research.yaml, or run offline with `--provider scripted --script <file>`
```

A model command with no `providers:` block. Add one ([Providers](providers.md)) or run the
loop offline with the scripted adapter.

```text
error: no provider named 'nope' in research.yaml (have: fast, local)
```

`--provider` matches an entry's `name` or one of its `tags`. The message lists what is
there.

```text
error: --provider scripted needs --script <file>
```

```text
error: --script runs the 'scripted' provider; --provider 'fast' asks for a configured one
```

`--script` and a configured `--provider` are mutually exclusive.

```text
error: .../research.yaml: not a valid WorkspaceConfig: 1 validation error for WorkspaceConfig
providers
  Value error, providers[0] in research.yaml must not contain api_key: API keys are read from
  environment variables or the OS keychain, never from research.yaml (Product SS34). Name the
  variable with `api_key_env: <VARIABLE>` and export the key in your shell instead.
```

A credential was written into a canonical file, so **nothing** in the workspace opens until
it is removed. Replace `api_key: <value>` with `api_key_env: OPENAI_API_KEY` and export the
key in your shell. If the file was already committed, rotate the key.

An unset key does not stop a command from starting — the provider call fails at the
endpoint instead. `research doctor` reports which variables are set without printing any
value:

```text
[ok  ]   fast            openai/gpt-4o-mini, OPENAI_API_KEY set
[note]   local           local_openai_compatible/qwen2.5:14b, LOCAL_MODEL_API_KEY unset
```

## Egress policy refusals

```text
WorkflowFailed: run run_20260902T215854Z_4c2b30d3 failed in stage 'extract.dataset': privacy
policy refuses the model provider 'openai/gpt-4o-mini' at api.openai.com: external model egress
is disabled for this project, and api.openai.com is not local (set privacy.external_models in
research.yaml, or run `research privacy set`, to change this)
```

The project's policy refused the provider during *selection*, before any request existed —
nothing was sent. `research egress --denied` lists every refusal with its reason;
`research privacy set --external-models allowed` lifts this one. This arrives as a Rich
traceback; only the final paragraph matters.

## Scripted runs

```text
WorkflowFailed: run run_20260902T215933Z_7392ed92 failed in stage 'extract.author_limitation':
script extract.json has no reply left for role 'evidence_extractor'; it lists evidence_extractor
```

The script ran out of replies. One reply is consumed per stage: one per interrogation field
for `interrogate`, one per staged candidate for `verify`. Either add replies or narrow the
run with `--field`. Watch for this when adding `--schema plugin:<name>`, which adds the
plugin's fields to the core ones.

```text
run run_20260902T215546Z_9e1f927d: verified 3 candidate(s)
  cand_44c1f007fc0db0b2  insufficient_evidence
```

A verifier reply whose `quoted_support` does not occur in the span it was given is
downgraded to `insufficient_evidence` with the reason recorded — a verifier cannot certify
a span it did not read. In a scripted run this usually means the replies are in the wrong
order: `verify` consumes them in **candidate-id sorted order**, which is not the order
`interrogate` printed.

## Ingest and parse

```text
error: corpus.ingest: no file at /tmp/nope.pdf
```

```console
$ research ingest tests/fixtures/synthetic_research_paper.pdf
W0001 / V0001-1 / A0001-1: already registered; nothing was written
  identity           same_artifact
  reason             file hash matches artifact A0001-1
```

Not an error. Artifacts are identified by content hash, so re-ingesting the same bytes is a
no-op. `--as-new` registers a new Work anyway; `--attach-to W0001` attaches the file to an
existing Work as another artifact.

```text
error: work.parse: no Work W9999 in /home/you/projects/traffic-survey
```

## Review

```text
error: give exactly one review action (--accept, --qualify, --edit, --reject, --defer, --request-more)
```

```text
error: no staged candidate cand_0000000000000000 under /home/you/projects/traffic-survey/.research/staging/evidence
```

Candidate ids come from `research inbox`. They live under `.research/`, so deleting that
tree loses them — re-run `research interrogate`.

```text
error: unknown category 'nope'; known: conflict, high_risk, stale, ambiguous, routine
```

```text
error: batch acceptance under review policy 'strict' needs the Product 24.4 conditions stated
explicitly; strict review is the default and a batch is an exception a researcher declares
```

Expected under the default policy. See [Review](review.md#batch-acceptance).

```console
$ research interrogate W0001 --provider scripted --script badblock.json --field dataset
run run_20260902T221150Z_47561ada: staged 0 candidate(s) across 1 field(s)
  rejected           dataset: block 'B9999' is not part of this document
```

A proposal whose anchor does not resolve against the stored parse is dropped before
staging. Nothing reached the queue and nothing was written.

## Objects and the projection

```text
error: no Claim C9999 in /home/you/projects/traffic-survey
error: no Work W9999 in /home/you/projects/traffic-survey
```

```text
error: no projection at /home/you/projects/traffic-survey/.research/research.db; run `research rebuild` to build it from canonical state
```

Search, `resolve`, and `compare` read the projection. A fresh workspace has none until the
first mutation builds it, and deleting `.research/` removes it.

```text
error: no evidence E9999 in the projection; rebuild it or check the id
```

The id is wrong, or the projection is behind. `research rebuild`, then retry.

```text
error: no synthesis matrix compares 'representation' in /home/you/projects/traffic-survey; run `research matrix build` first
```

## Consistency

```text
error: workspace /home/you/projects/traffic-survey is inconsistent: 1 of 9 objects disagree with
the event log: C0001: canonical content does not match the digest recorded with the event (event
claim.audited recorded sha256:3c1cfa31..., found sha256:87740e4a...). Canonical files are
authoritative and are never rewritten automatically; open with repair=True to inspect the
report, then reconcile the difference.
```

A canonical file was edited outside the harness. `research doctor` and `research rebuild`
both open with `repair=True` and still work, so you can diagnose. The fix is in
[Rebuild and recovery](rebuild-and-recovery.md#a-hand-edited-canonical-file): revert the
edit, or redo it through a command so it gets its own event.

```text
workspace schema version 2 was written by a newer Research Harness; this build supports up to
version 1. Upgrade the harness rather than editing research.yaml: opening it here could drop
fields this version does not know about.
```

## Manuscript

```text
error: main.tex:2 carries no manuscript sentence
```

The line is blank, a comment, or LaTeX structure rather than prose. `research manuscript
attach-text "<the sentence>"` finds it by content instead. Line numbers are 1-based and
relative to the file inside the manuscript root.

## The daemon

```text
ERROR:    [Errno 98] error while attempting to bind on address ('127.0.0.1', 8793):
          [errno 98] address already in use
```

Another `research serve` is running. Use `--port`, or stop the other one.

```json
{"capability":"evidence.accept","ok":false,"result":null,
 "error":{"code":"permission_denied",
          "message":"evidence.accept: a agent_host principal does not hold the 'mutate' permission (holds: read, stage)",
          "capability":"evidence.accept"}}
```

The caller presented no valid token, so the daemon resolved it as an agent host. That is
correct behaviour for a host; if you meant to act as the researcher, send
`authorization: Bearer $(cat .research/daemon-token)`. See [HTTP daemon](http.md).

```json
{"error":{"code":"invalid_request","message":"claim.create: claim: Field required"}}
```

The body must be the capability's own request object. Read its schema from
`GET /capabilities` or `research capabilities --schemas` — or use the CLI, which composes
the full object for you.

If a workspace lock is held by a process that no longer exists, delete `.research/lock`.

## MCP hosts

A host that reports the server exited immediately is hiding a one-line `error:`. Run the
exact command from a terminal to see it:

```bash
uv run --project /path/to/research-harness research mcp --workspace /path/to/project
```

Use absolute paths for both the executable and the workspace: a host does not reliably
inherit your shell's `PATH` or working directory. See [MCP hosts](mcp.md).

## Plugins

```text
error: no plugin named 'mine' under /home/you/research-harness/plugins (found: academic-writing, structured-traffic)
```

```text
error: plugin 'bad_accept_permission' could not be loaded: .../plugin.yaml is not a valid plugin
manifest: 1 validation error for PluginManifest
permissions.capabilities
  Value error, a plugin may never call accepted-state capabilities: evidence.accept
```

Load-time boundary checks; the message names the rule. See [Plugins](plugins.md).

```text
error: plugin 'x' contributes several interrogation schemas; name one: paper, dataset
```

Use `--schema plugin:x:paper`.

## Nothing is wrong

Some output reads like a problem and is not:

| output | meaning |
|---|---|
| `no traces on disk` | expected: no command writes traces in this build |
| `nothing stale` | no anchor or accepted object needs attention |
| `no conflicts` | nothing disagrees |
| `0 item(s) to review` | the queue is drained |
| `[note] projection  not built yet` | a fresh workspace; run `research rebuild` |
| `[note] daemon token  not created yet` | `serve` was never started |
| `already registered; nothing was written` | the same bytes were already ingested |

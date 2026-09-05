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

```text
error: No LaTeX engine was found on PATH. Install one of: tectonic (a single binary that
fetches what a document needs, https://tectonic-typesetting.github.io), or a TeX
distribution providing latexmk/pdflatex/xelatex/lualatex (TeX Live, MacTeX, MiKTeX). Then
reopen the manuscript workspace; the harness only ever reads engines from PATH and installs
nothing itself. No manuscript source was read or modified.
```

The harness never installs a TeX distribution. If one *is* installed but `research.yaml`
pins a different engine, the message names what is installed instead
([the manuscript workspace](manuscript.md#the-toolchain)).

```text
error: sections/intro.tex changed outside the harness: expected sha256:dead…, found
sha256:2613e526…; re-read the file before saving again
```

Someone else — an editor, a `git checkout`, a co-author — changed the file since you read
it. `research manuscript read <path>` prints the current hash; a save that silently won
over an outside edit would be data loss.

```text
error: no manuscript build last-good
```

`research manuscript build` takes a real build id and, unlike
`GET /manuscript/builds/{id}/pdf`, does not accept the `latest` / `last-good` aliases. With
no argument it reads the latest build, whose output names the last good PDF when the latest
one failed.

## Conversation and attachments

```text
error: session CS0001 is private and openai/gpt-4o-mini is an external provider, so nothing
in this conversation may be sent to it (Product 34; workspace design SS7). Send it to a
local provider, or make the session shareable with `research chat new --visibility project`
on a new conversation.
```

A private session is private: the send is refused rather than trimmed to whatever happened
to be shareable. A session's visibility is fixed at creation, so the fix is either a local
provider or a new session — new sessions are `project` unless `--visibility private` says
otherwise ([conversation workspace](conversation.md#sessions)).

```text
error: no conversation session CS9999 in /home/you/projects/traffic-survey
```

`research chat list` shows what exists. Sessions live in `conversations/`, which is *not*
under `.research/` — a rebuild neither creates nor removes one.

```text
M0002  failed  (context CP0001)
error: model output was not valid JSON: Expecting value: line 1 column 1 (char 0)
```

Usually a `--script` file in the wrong shape: a chat reply is `{"text": "…"}`, not a bare
string ([Providers](providers.md#the-scripted-provider)). The message and its failed
attempt are kept — `research chat retry M0002 --script <fixed file>` answers again as a new
attempt.

```text
error: session.promote: evidence cannot be created from prose: it needs an Artifact and an
exact resolvable anchor … Promote the passage to a note, question, or claim candidate
instead.
```

Working as designed. Evidence anchors to bytes; a model's sentence about a paper is not the
paper ([conversation workspace](conversation.md#promotion)).

```text
error: attachment.check_send: no model providers configured; add a `providers:` list to
research.yaml so the workspace knows what the attachments would be sent to
```

The sendability check compares an attachment against a *model*, so it needs at least one
configured entry — including in a `research demo` workspace, which ships `providers: []`.

```text
2 attachment(s) cannot be sent to local/qwen2.5-7b-instruct: SA0002 paper.pdf: the selected
model does not accept application/pdf input; SA0003 figure.png: …
```

Not an error to work around: the send is blocked so the attachment is not silently dropped.
Pick a model that accepts the media (the refusal names one when a configured entry
qualifies and the attachment may leave the machine), or remove the item
([attachments](attachments.md#what-blocks-a-send)).

## The ResearchGraph

```text
no graph index at /home/you/projects/traffic-survey/.research/graph/research-graph.db; run
`research rebuild`
```

Information, not a failure. The graph is disposable; navigation degrades and nothing else
does — `research chat show`, `chat search`, and every canonical read keep working.

```text
@E9999 unavailable in demo: candidate/project, not fresh
  problem no evidence E9999 in this project
```

The reference resolved as a *reference* and then failed the canonical check. `problem` says
which of the four checks failed: existence in this project, authority, privacy, or anchor
freshness ([the ResearchGraph](graph.md#rh-deep-links)).

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

## The multi-project app

```text
error: port 8765 is in use by something that is not a Research Harness app (HTTP 404 from
/api/app/health); stop it, or run `research app --port <other port>`. A one-workspace
`research serve` daemon answers like this.
```

`research app` joins an app that is already running and refuses to fight anything else for
the port. A `research serve` daemon on `8765` is the usual cause: stop it, or give the app
another `--port`.

```text
error: the app already running on port 8765 does not accept this app token: it was started
from a different app data directory.
```

Two app data directories on one machine — usually a shell with a different
`XDG_DATA_HOME`. Use the instance that is already running, stop it, or pick another
`--port`.

```text
This launch link has already been used or has expired. Start Research Harness again with
`research app` to open a fresh window.
```

The URL `research app` opens carries a one-time nonce good for a minute; a bookmark or a
reload after it was spent has nothing to exchange. Run `research app` again — it opens a new
authenticated window. A tab that never had a token at all says so instead, with the same
remedy. Nothing is wrong with your projects.

```text
This machine has no folder dialog available, so type the absolute path instead.
```

No `zenity` and no `kdialog` on this Linux desktop. Install either one, or type an absolute
path into the field the dialog offers instead — it is authenticated the same way, and it is
the only other route a path may reach the app by.

```json
{"detail":{"code":"picker_unavailable","message":"the zenity folder dialog timed out after 600s"}}
```

The dialog started and never came back — a window behind another one, or a desktop session
the daemon cannot draw on. Nothing was registered. Try again, or use the manual path field.

```text
Unavailable
```

The folder moved, was renamed, or is not mounted. The project keeps its identity and its
history; use **Locate folder** to point it at the folder's new place. **Forget project**
would remove the entry and still delete nothing.

```json
{"detail":{"code":"project_active_runs","message":"Traffic survey has 1 active run(s); wait for them or cancel them first"}}
```

Forgetting or relocating a project with a workflow still running is refused. Let it finish,
or cancel it, then try again. Switching to another project is always allowed — the workflow
keeps running.

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

## `ModuleNotFoundError: No module named 'fcntl'` on Windows

Versions before the cross-platform lock imported `fcntl` unconditionally. Update to a
build that includes `workspace/locking.py` with the `msvcrt` branch (`git pull`, then
`uv sync`). `research doctor` must run without a traceback afterwards.

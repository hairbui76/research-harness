# Providers

A model provider is configuration, never code. Workflows say what they need — structured
output, a context size, a reasoning level — and the router picks the highest-priority
configured entry that satisfies it. Changing which model does a job is an edit to
`research.yaml` (ADR-005).

Credentials are never in `research.yaml`. An entry names an environment variable; the key
is read from the process environment. A key written into the file is refused when the
workspace opens.

## Configuring `providers:`

```yaml
providers:
  - name: fast                    # what `--provider fast` selects
    kind: openai                  # openai | anthropic | local_openai_compatible
    model: gpt-4o-mini
    api_key_env: OPENAI_API_KEY   # the variable to read; never the key itself
    priority: 10                  # lower wins; ties resolve to declaration order
  - name: careful
    kind: anthropic
    model: claude-sonnet-4-5
    api_key_env: ANTHROPIC_API_KEY
    priority: 20
    roles: [claim_auditor, evidence_verifier]   # restrict to these roles
  - name: local
    kind: local_openai_compatible
    model: qwen2.5:14b
    base_url: http://127.0.0.1:11434/v1
    priority: 200
```

Every field of an entry:

| field | default | meaning |
|---|---|---|
| `name` | required | the label `--provider` selects, and a routing tag |
| `kind` | required | `openai`, `anthropic`, `local_openai_compatible`, or `local_cli` |
| `runtime` | required for `local_cli` | `kind: local_cli` only: the runtime id (`codex`, `claude`, …); forbidden for every other kind |
| `model` | required | the model id sent to the endpoint; `default` on a `local_cli` entry means the CLI's own configured model |
| `base_url` | the adapter default | endpoint override, e.g. a local server; refused for `local_cli` |
| `priority` | `100` | lower is preferred |
| `roles` | any role | restrict the entry to named roles |
| `tags` | `[]` | extra labels `--provider` can also select by |
| `api_key_env` | the adapter default | the environment variable holding the key; refused for `local_cli`, which uses the CLI's own login |
| `timeout_seconds` | adapter default | request timeout |
| `capabilities` | adapter defaults | per-model overrides: `structured_output`, `max_context_tokens`, `reasoning_levels`, `vision` |
| `reasoning` | the runtime's own default | `kind: local_cli` only: one of the runtime definition's own effort names, listed under `reasoning_choices` by `providers scan --json` |
| `enabled` | `true` | `false` leaves the entry configured but unrouted |

Adapter defaults:

| kind | default `base_url` | default `api_key_env` | declared egress |
|---|---|---|---|
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` | source text + identifiers to `api.openai.com`; the call asks the provider not to store the response |
| `anthropic` | `https://api.anthropic.com` | `ANTHROPIC_API_KEY` | source text + identifiers to `api.anthropic.com` |
| `local_openai_compatible` | `http://localhost:11434/v1` | `LOCAL_MODEL_API_KEY` | nothing leaves the workstation |
| `local_cli` | — | — | source text + identifiers to the CLI vendor (declared per runtime; `unknown.external` when undisclosed) |

The roles a workflow asks for are `evidence_extractor`, `evidence_verifier`,
`claim_auditor`, `skeptic`, `synthesizer`, and `writer`.

Set the key in your shell, not in a file the project commits:

```bash
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
```

A key in `research.yaml` stops the workspace from opening at all:

```console
$ research inbox
error: .../research.yaml: not a valid WorkspaceConfig: 1 validation error for WorkspaceConfig
providers
  Value error, providers[0] in research.yaml must not contain api_key: API keys are read from
  environment variables or the OS keychain, never from research.yaml (Product SS34). Name the
  variable with `api_key_env: <VARIABLE>` and export the key in your shell instead.
```

## Selecting one

Commands that call a model (`interrogate`, `verify`, `claim audit`, `draft`) take
`--provider`:

* omitted — the whole `providers:` table, routed by capability and priority;
* `--provider <name-or-tag>` — narrow the table to entries with that name or tag;
* `--provider scripted --script <file>` — the in-process scripted adapter.

A failing call is not retried on the next provider. Which model produced a result is
reproducibility metadata, so a silent switch would misreport it; failover and
cross-model verification are explicit policies, not a fallback.

```console
$ research interrogate W0001
error: no model providers configured: add a `providers:` list to research.yaml, or run offline with `--provider scripted --script <file>`

$ research interrogate W0001 --provider nope
error: no provider named 'nope' in research.yaml (have: fast, local)
```

## Subscription-backed local CLIs

If you are already logged in to Codex CLI or Claude Code, the harness can route research
work through that CLI. Cursor Agent, Amp, DeepSeek Harness, OpenCode, and Pi are detected
and reported alongside them, but are not routable in this release (*Bounded mode*, below).
No API key enters Research Harness; the CLI's own login is used — and only a *subscription*
login counts. Codex must report a ChatGPT login and Claude Code an `authMethod` of
`claude.ai`; an API-key login is metered and talks to a different host, so it is reported as
not logged in, with the command that fixes it.

A CLI provider is **not local**. The process starts here; the model is the vendor's.
Research content and object IDs leave the workstation exactly as they do for an HTTP
provider, and `privacy.external_models: disabled` refuses a CLI provider before it is
started (ADR-030).

```console
$ research providers scan
A local CLI starts on this workstation, but the model it talks to is the vendor's: research content and object IDs leave the machine when a CLI provider is used.

codex              0.150.1        logged in          bounded mode ok        verified
    models (live): default, gpt-5.5, gpt-5.4, gpt-5.4-mini
claude             2.1.259        logged in          bounded mode ok        verified
    models (fallback): default, sonnet, opus, haiku, claude-opus-5, claude-sonnet-5 …
cursor-agent       1.4.0          logged in          no bounded mode        warning — cursor-agent 1.4.0 has no tested bounded (no-tools, read-only) mode
    cursor-agent: headless Cursor Agent runs only with --force (approval bypass); no deny-tools flag is documented
    models (live): default, auto, sonnet-4, gpt-5
amp                not installed
    amp is not installed: no 'amp' on PATH
deepseek-harness   not installed
    deepseek-harness is not installed: no 'dsh' on PATH
opencode           not installed
    opencode is not installed: no 'opencode-cli' on PATH
pi                 not installed
    pi is not installed: no 'pi' on PATH

$ research providers add codex --name codex-sub --model gpt-5.5 --priority 10
added codex-sub (codex/gpt-5.5, priority 10) in research.yaml
select it with --provider codex-sub

$ research providers test codex-sub
egress: codex-sub sends research content to chatgpt.com through Codex CLI
codex-sub (codex/gpt-5.5, 0.150.1): ok
  Codex CLI answered through the subscription login in 2140 ms

$ research interrogate W0001 --provider codex-sub
```

Once an entry exists, every later scan repeats it under a `configured in research.yaml`
block with its priority and whether it is routable right now. `research providers remove
codex-sub` deletes that one entry from `research.yaml`, and leaves every other provider —
and the CLI's own login — untouched.

The entry `add` writes:

```yaml
providers:
  - name: codex-sub
    kind: local_cli
    runtime: codex          # codex | claude
    model: gpt-5.5          # or `default` for the CLI's own configured model
    priority: 10
    reasoning: high         # optional; the runtime's own effort name
    timeout_seconds: 300    # optional
    enabled: true
```

`runtime` is required and `base_url`/`api_key_env` are refused for `kind: local_cli`. Only
`codex` and `claude` are routable: the other five are detected and listed but refused. Four
of them — Cursor Agent, Amp, DeepSeek Harness, Pi — declare no bounded posture at all, so a
hand-written `research.yaml` naming one is refused the moment the routing table is read,
exactly as `add` refuses it. OpenCode declares a posture no installed version has proved,
so its entry loads and the refusal comes when a request would be routed. `research
providers scan` prints the reason for each.

`reasoning` is the runtime's own effort name, not a harness word: Codex takes `low`,
`medium`, `high`, `xhigh` and receives them as `-c model_reasoning_effort="…"`; Claude Code
takes those and `max`, and receives them as `--effort`. The names come from the runtime
definition, not from a probe, so the text scan does not print them: read them from
`reasoning_choices` in `providers scan --json`, or from the Web tab's selector.

**Bounded mode.** A runtime is routable only when the installed version proves a no-tools,
read-only posture. Codex runs `codex exec --json --skip-git-repo-check --ephemeral
--ignore-user-config --ignore-rules --sandbox read-only -c approval_policy="never"`, with
the response schema handed over as a file (`--output-schema`); Claude Code runs `claude -p
--tools "" --permission-mode dontAsk --permission-prompts none --strict-mcp-config
--disable-slash-commands --no-session-persistence --restricted`, where `--restricted`
removes the command- and code-running tools outright, ignores your user, project, and local
settings files, and refuses `bypassPermissions`. Both run in an empty temporary directory,
with every API-key, token, and cloud-credential variable removed from the environment, so a
subscription login cannot quietly become metered access. The other five runtimes are
detected and listed but not routable in this release. Cursor Agent, Amp, DeepSeek Harness,
and Pi report `no bounded mode` — Cursor Agent and Amp run headless only with an approval
bypass, and DeepSeek Harness's profile and Pi's RPC session execute tools of their own —
while OpenCode's environment-injected deny table is unproven until a version is verified, so
it reports `bounded mode unproven`. `add` refuses all five. A tool call during a bounded run
cancels the process and fails the request (`bounded_authority_violation`); there is no
prompt-only fallback.

**What a scan reports.** Installed state and version; login, as `logged in`,
`not logged in`, or `login unverified`; bounded mode, as `bounded mode ok`,
`no bounded mode`, or `bounded mode unproven`; compatibility; and the models the CLI
itself lists (`live`) or the shipped hints (`fallback`). Compatibility is `verified` for a
version with recorded fixtures, `warning` for any parseable version that is neither
verified nor blocked, `unknown` when the version string cannot be read, and `blocked` for a
version known to be incompatible or below a declared floor. Of those four only `blocked`
stops a runtime being routed on its own: bounded mode is a separate gate, answered for the
build that is actually installed, so an unrecognised version is a warning, not a refusal.
These are not report-only. The engine asks the same question again when a request is
actually routed, from the same 30-second cache, and refuses an entry whose runtime is not
routable right now — `bounded_mode_unsupported` when the installed build cannot prove the
no-tools posture, `version_blocked` for a known-incompatible version, `login_missing` when
the CLI is logged out, and `executable_missing` when it has been uninstalled — with the
same sentence the scan shows, before the prompt is rendered and before any process exists.
The one exception is a runtime whose posture is injected through the environment rather
than proved by a flag — OpenCode's, here: a help probe shows that a flag exists, never that
an injected setting denies anything, so only a `verified` version proves that posture, and
every other version leaves the bounded mode `unproven`. A runtime that cannot be routed
ends its line with the one reason that stops it — the same sentence `add` refuses with and
the Web cockpit shows. A scan edits nothing and sends no research content: it runs the
CLI's own `--version`, login-status, help, and model-list commands with short timeouts, and
the result is cached for 30 seconds so a selector stays responsive (`--rescan` bypasses the
cache). The Web cockpit's *Settings → Models & providers → Local CLIs* tab renders the same
report from the same capabilities.

**Traces and errors.** A CLI call is traced like any other under `.research/traces/`. An
ordinary `--provider codex-sub` call adds the runtime id, protocol family, transport, model,
and the redacted executable path; the version is on a `research providers test` trace only,
because answering a request never probes for one. Errors name the runtime, model, and version
— `version unknown` when none was probed — and a next action (run `codex login`); they never
contain a token, a credential path, or the raw process output.

### Binding a session instead of configuring the project

An entry in `research.yaml` is project-wide and persisted. One conversation can name a
runtime without one: `research chat configure` stores the choice on the *session record*
and writes nothing to `research.yaml`.

```console
$ research chat configure CS0001 --runtime codex --model gpt-5.5 --reasoning high
egress: session CS0001 sends research content to chatgpt.com through Codex CLI
bound to: session:codex/gpt-5.5 (reasoning high)

$ research chat configure CS0001 --entry codex-sub
bound to: entry codex-sub

$ research chat configure CS0001 --clear
bound to: project default
```

`--model` is a model id from `research providers scan`, or `default` for the CLI's own
configured model; `--reasoning` is the runtime's own effort name and is accepted only with
`--runtime`. Exactly one of `--runtime`, `--entry`, `--clear` is given. The egress sentence
is printed before the change, because a binding decides where the conversation will go.

The binding's words are the same on every surface: `research chat list` puts them in
brackets after the row, `research chat show` prints them as its second line, and the Web
cockpit's session rail and composer show the identical string —
`session:<runtime>/<model>`, with ` (reasoning <level>)` when one is set, or `entry <name>`,
or `project default`.

In the cockpit the binding *is* the composer's model picker: configured entries in one
group, one group per installed runtime, and a **Project default** row that clears it. The
Settings → *Models & providers* tab is not needed and is not the same act — that tab writes
a project entry, and a binding is never one.

**Precedence.** A per-message model wins over the binding, and the binding wins over the
project default: `research chat send CS0001 "…" --provider codex-sub` sends through
`codex-sub` whatever the session is bound to, and `--clear` returns the session to the
project default. A retry with no model follows the binding as it is at retry time.

**What is refused, and when.** A binding goes through the validator a hand-written entry
goes through, so it is refused in the entry's own words: `unknown runtime 'nope' (known:
codex, claude, cursor-agent, …)`, `runtime 'pi' has no proven bounded (no-tools, read-only)
mode and cannot be configured; …`, and `reasoning 'turbo' is not an effort name 'codex'
accepts (low, medium, high, xhigh)`. One sentence is the binding's own:
`codex does not list model 'gpt-9'`, which ends by telling you to run
`research providers scan`. An `--entry` naming something that is not an enabled entry is
refused with the same `no provider named '…' in research.yaml (have: …)` a stale
`--provider` gets.

A runtime that is installed but *not routable right now* is accepted, so a session can be
bound before `codex login` is run; the send is what refuses, with the scan's own sentence —
`bounded_mode_unsupported`, `version_blocked`, `login_missing`, or `executable_missing` —
and `privacy.external_models: disabled` refuses a bound send before any process exists,
exactly as it does for a configured entry.

**A private session cannot be bound to a runtime.** Every CLI runtime is external egress,
so binding one onto a private session would leave a conversation that looks configured and
can never answer. `session.configure` refuses it with the sentence the send path uses:

```console
$ research chat configure CS0001 --runtime codex --model gpt-5.5
egress: session CS0001 sends research content to chatgpt.com through Codex CLI
error: session CS0001 is private and session:codex/gpt-5.5 is an external provider, so
       nothing in this conversation may be sent to it (Product 34; workspace design SS7).
       Send it to a local provider, or make the session shareable with `research chat new
       --visibility project` on a new conversation.
```

Sessions are private by default — `session.create` and `research chat new` both default to
`private` — and **there is no capability that changes a session's visibility after it is
created**. So the way to use a bound runtime is to open the conversation as a project
session in the first place: `research chat new "…" --visibility project`. The cockpit asks
the same question rather than deciding it: its **New session** button opens a small dialog
whose *Visibility* list offers `Private (default)` and `Project`, over one sentence saying
that only a project session can be bound to a CLI runtime, that a private session never
sends to an external model, and that visibility cannot be changed once the session exists.
Leaving the default alone sends no `visibility` at all, so the daemon's own default stays
the default. An `--entry` binding is not affected:
an entry may name a local provider, so a private session may be bound to one.

## The scripted provider

`--provider scripted --script <file>` runs a provider that sends nothing anywhere and
answers from a JSON file. It is how the loop is demonstrated, tested, and debugged with no
key and no network. Three shapes, all hand-writable:

* a JSON list — replies consumed in order;
* an object whose keys are all role names — one queue per role;
* any other object — a single reply.

The role-keyed shape is the useful one, because a run calls several roles:

```json
{
  "evidence_extractor": [
    {
      "candidates": [
        {
          "block": "B0017",
          "char_start": 0,
          "char_end": 30,
          "exact_text": "All experiments use CICIDS2017",
          "field": "dataset",
          "evidence_type": "dataset_description",
          "origin": "source_observed",
          "strength": "direct",
          "numeric": null,
          "negative_state": null,
          "rationale": "The experiments section names the corpus.",
          "page": 3
        }
      ],
      "fields_not_found": []
    }
  ]
}
```

One reply is consumed per stage, in the order the workflow asks — one per field for
`interrogate`, one per staged candidate for `verify` (candidate ids in sorted order).
Running out is an error that names the role:

```console
error: script extract.json has no reply left for role 'evidence_extractor'; it lists evidence_extractor
```

`tests/e2e/test_evidence_cli_loop.py` builds both scripts from a real parse of
`tests/fixtures/synthetic_research_paper.pdf`; it is the reference for the exact shapes.

## Embeddings

The semantic index is separate configuration, chosen per command rather than in
`research.yaml`. `research index build --embedder` and `research search --embedder` take:

| embedder | model | where it runs |
|---|---|---|
| `hashing` (default) | `blake2b-…` | in-process; nothing leaves the workstation |
| `openai` | `text-embedding-3-small` | `api.openai.com`, `OPENAI_API_KEY` |
| `local` | the served model | `localhost`, `LOCAL_MODEL_API_KEY` |

Building a vector index sends the whole indexed corpus to whoever computes the vectors, so
the egress policy is checked before any text is sent. The index is disposable either way:
deleting `.research/index/` costs retrieval speed, never a conclusion (ADR-006).

## Egress policy

`research.yaml` carries a `privacy:` block; every field defaults to today's behaviour, so
an older workspace opens unchanged.

```yaml
privacy:
  external_models: allowed        # allowed | disabled
  allowed_hosts: []               # empty = any host a provider declares
  allow_source_text: true
  allow_identifiers: true
  search_providers: allowed       # allowed | disabled
  trace_retention_days: 30        # null = keep until purged
  redact_traces: false
```

Change it with `research privacy set` (only the options you pass are changed) and read it
with `research privacy show`:

```console
$ research privacy set --external-models disabled
updated external_models in research.yaml

privacy policy
  external models    disabled
  search providers   allowed
  allowed hosts      any declared host
  source text        may leave
  identifiers        may leave
  traces             verbatim, 30 days
```

The policy is applied during provider *selection*, before a request exists, so a refused
provider is never contacted — on every transport, not only on the CLI's. A long-running
capability asks before it starts, so a run refused by the policy is a refusal the caller
reads rather than a failed run record it has to go and find. When the policy is the only
thing between a caller and a provider, the error names the policy rather than the model:

```console
$ research interrogate W0001 --provider fast
WorkflowFailed: run run_20260902T215854Z_4c2b30d3 failed in stage 'extract.dataset': privacy
policy refuses the model provider 'openai/gpt-4o-mini' at api.openai.com: external model egress
is disabled for this project, and api.openai.com is not local (set privacy.external_models in
research.yaml, or run `research privacy set`, to change this)
```

## `research egress`

One row per provider the workspace could reach: the host, what the request carries, what
the policy says, and the *name* of the credential variable with a boolean. No field of
the report can hold a key, so it is safe to print, pipe, and paste into an issue. Building
it performs no network I/O.

```console
$ research egress
provider                        kind       endpoint                 sends              policy   key
fast/gpt-4o-mini                model      api.openai.com           source text + ids  allowed  OPENAI_API_KEY (unset)
local/qwen2.5:14b               model      127.0.0.1                nothing            allowed  LOCAL_MODEL_API_KEY (unset)
hashing/blake2b-w1-2-c3-cw0.35  embedding  (in-process)             nothing            allowed  -
openai/text-embedding-3-small   embedding  api.openai.com           source text        allowed  OPENAI_API_KEY (unset)
local/(the served model)        embedding  localhost                nothing            allowed  LOCAL_MODEL_API_KEY (unset)
crossref                        search     api.crossref.org         ids                allowed  -
openalex                        search     api.openalex.org         ids                allowed  -
semantic_scholar                search     api.semanticscholar.org  ids                allowed  SEMANTIC_SCHOLAR_API_KEY (unset)
dblp                            search     dblp.org                 nothing            allowed  -
arxiv                           search     export.arxiv.org         nothing            allowed  -
```

`--denied` shows only what the policy currently refuses, with the reason:

```console
$ research egress --denied
provider                       kind       endpoint        sends              policy  key
fast/gpt-4o-mini               model      api.openai.com  source text + ids  DENIED  OPENAI_API_KEY (unset)
openai/text-embedding-3-small  embedding  api.openai.com  source text        DENIED  OPENAI_API_KEY (unset)

denied  fast/gpt-4o-mini: external model egress is disabled for this project, and api.openai.com is not local
denied  openai/text-embedding-3-small: external model egress is disabled for this project, and api.openai.com is not local
```

Disabled entries are left out: they are not routed, so they send nothing. Model entries
come from `providers:`; embedding and discovery entries are every backend the CLI can
select, because those are chosen per command.

## Traces

`.research/traces/` is where provider prompts, latency, and retrieval traces belong. They
carry no scientific authority: deleting them loses nothing, which is why they live under
`.research/`.

Two controls sit on them, both in `privacy:`. `redact_traces` replaces source-text fields
(`content`, `exact_text`, `quoted_support`, `raw_text`, at any depth) with `sha256:<digest>`
plus the original length *as the trace is written*, so plaintext never reaches the disk.
`trace_retention_days` bounds how long they are kept.

**Every model call is traced, whichever surface started it.** The sink is attached where
the backend is chosen: `privacy/traces.py` supplies the `TracingRouter`, and both
`cli/providers.py` and `capabilities/extra_handlers.py` wrap whatever they resolve in one
carrying a `TraceWriter` for this workspace. So `interrogate`, `verify`, `claim audit`,
`manuscript audit`, and `manuscript draft` all record without passing a sink of their own —
and so does the same run started from the Web cockpit, an MCP host, or a `POST
/capabilities/work.interrogate`. The scripted provider is traced like any other: it
implements only the vendor call, so it goes through the same `ModelProvider.complete`.

```console
$ research interrogate W0001 --provider scripted --script extract.json
$ research traces list
2026-09-03  completion-1f4c9a02.json   4.1 kB
1 trace, 4.1 kB  ·  redact_traces false  ·  retention 30 days

$ research traces purge --older-than 7
```

`research traces purge --all` deletes every trace whatever its age.

One file per request fingerprint per day, named
`traces/<yyyy-mm-dd>/completion-<first 8 of the fingerprint>.json`: re-running the same
request on the same day rewrites one file instead of piling up duplicates. A trace carries
`"authority": "none"` in so many words, and failing to write one never fails the call.

## Cost

Nothing in the harness meters spend. What bounds it is the shape of the work:

* `interrogate` makes one model call per interrogation field, per Work;
* `verify` makes one per staged candidate;
* `claim audit` runs its model passes only when you pass `--provider` or `--script` — with
  neither, the deterministic audit is the whole result;
* `draft` makes one writer call per section.

`priority` and `roles` are the lever: put a small model first and restrict the expensive
one to `claim_auditor` and `evidence_verifier`, where the reading actually matters. The
`hashing` embedder costs nothing and needs no key, which is why it is the default.

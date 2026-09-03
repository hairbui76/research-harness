# The local HTTP daemon

`research serve` runs a FastAPI app over one workspace. It is a transport and nothing
more: it resolves who is calling, hands the call to the capability registry, and renders
the answer (ADR-004). There is no route that runs SQL, writes a caller-named file, or
patches an object field.

```console
$ research serve
serving /home/you/projects/traffic-survey on http://127.0.0.1:8765
local token          /home/you/projects/traffic-survey/.research/daemon-token
INFO:     Started server process [3780320]
INFO:     Application startup complete.
```

`--port` changes the port (default `8765`). `--reload` is for developing the server
itself. The bind address is `127.0.0.1` and is not configurable: local-first is a
boundary, not a default.

## The token

Authority is a file, `.research/daemon-token`, created on first start with mode `0600`. A
caller presenting it is the researcher; a caller without it is an `agent_host` that may
read and stage but never accept.

```console
$ research token
/home/you/projects/traffic-survey/.research/daemon-token
```

The command prints the path, never the secret: a token that reaches a shell history or a
log is no longer a local-only credential. Present it as a bearer token:

```bash
TOKEN=$(cat .research/daemon-token)
curl -s -H "authorization: Bearer $TOKEN" http://127.0.0.1:8765/overview
```

The token is regenerable runtime state under `.research/`. Deleting it costs a restart and
nothing else.

## Routes

| method | path | what it does |
|---|---|---|
| `GET` | `/health` | whether the daemon can serve its workspace, and what it is serving |
| `GET` | `/capabilities` | every capability with its permission and both JSON schemas |
| `POST` | `/capabilities/{name}` | invoke one capability; the body is that capability's request object |
| `GET` | `/runs/{run_id}` | the durable record of one long-running workflow |
| `POST` | `/runs/{run_id}/cancel` | ask a run to stop before its next stage |
| `GET` | `/objects/{object_id}` | one canonical object, read through the repository's typed accessors |
| `GET` | `/artifacts/{artifact_id}/bytes` | the immutable bytes an anchor was accepted against |
| `GET` | `/blocks/{artifact_id}` | the stored parse: page, order, and geometry per block |
| `GET` | `/candidates/{candidate_id}` | one staged candidate, verbatim |
| `GET` | `/index` | works, claims, questions, decisions, matrices, taxonomies, anchors — summarised |
| `GET` | `/overview` | what needs attention now, composed server-side |
| `GET` | `/runs/{run_id}/events` | server-sent events for one model call: `delta`, `status`, `error` |
| `POST` | `/sessions/{id}/attachments` | multipart-free byte intake for a session attachment |
| `GET` | `/sessions/{id}/attachments/{sa}/bytes` | the attachment's original bytes, inline and inert |
| `GET` | `/sessions/{id}/attachments/{sa}/preview` | a PNG page projection, rendered by the harness |
| `GET` | `/manuscript/builds/{build_id}/pdf` | one build's PDF; `latest` and `last-good` are accepted ids |

`POST /capabilities/{name}` is the entire write surface **with one documented exception**,
the attachment byte route below; everything else is a read. FastAPI also serves `/docs`,
`/redoc`, and `/openapi.json`. The route set is asserted in
`tests/contract/protocol/test_http.py`, so a new one cannot appear by accident.

When `web/dist` exists it is mounted at `/` with a single-page fallback; see
[Web cockpit](web.md).

```console
$ curl -s http://127.0.0.1:8765/health
{"ok":true,"workspace":"/home/you/projects/traffic-survey","project":"demo",
 "review_policy":"strict","capabilities":100,"version":"0.1.0"}
```

## Bytes: the four routes that are not JSON

Four things cannot travel as a JSON capability response, and each gets a read-only route:
an artifact's bytes, a session attachment's bytes, an attachment page preview, and a
compiled PDF. `GET /manuscript/builds/{build_id}/pdf` accepts `latest` and `last-good` as
build ids — the two questions a preview asks — and a failed build serves the last good PDF
rather than nothing. Attachment bytes and previews are served deliberately inert: the media
type is narrowed to the attachment allowlist (never `text/html`, never an SVG), with
`X-Content-Type-Options: nosniff` and `Content-Security-Policy: default-src 'none'`.

`POST /sessions/{session_id}/attachments` is **the one write that is not a capability
call**. The body is the raw file, `Content-Type` is its media type, and `?filename=` is
display metadata whose basename only is kept. It is narrow on purpose: it writes
session-only state through the same service `attachment.add` uses, it creates no Work,
Version, Artifact, or Evidence, and it is authorised exactly as `attachment.add` is
(`mutate`, researcher only), so it is not a way around a permission. The alternative was
base64-ing a 30 MB PDF through a JSON request, which buys no boundary.

```bash
curl -s -X POST "http://127.0.0.1:8765/sessions/CS0001/attachments?filename=paper.pdf" \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/pdf' \
  --data-binary @paper.pdf
```

## Streaming a model call

`session.send` and `session.retry` are capabilities that return a `run_id`;
`GET /runs/{run_id}/events` is the **read** that streams what the run recorded. Each
`data:` line is one JSON object and the stream ends after a terminal `status`:

```text
event: delta
data: {"message_id": "M0042", "attempt": 1, "text": "…appended text…"}

event: status
data: {"run_id": "run_…", "state": "running", "message_id": "M0042", "attempt": 1,
       "context_pack_id": "CP0007"}

event: error
data: {"code": "provider_unavailable", "message": "…", "retryable": true}
```

`state` is one of `queued`, `running`, `succeeded`, `failed`, `cancelled`, `incomplete`,
and an `error` frame's `code` is one of `provider_rate_limited`, `provider_unavailable`,
`provider_auth_failed`, `provider_error`, `capability_error`, `run_unreadable`, or
`internal_error`, each with its own `retryable`. Every delta is persisted into the message *before* it is emitted, so a client that
reconnects reads the same content from `session.get`, and a client that opens the stream
after the run finished gets the whole answer replayed and then the terminal status. A
stream that ends *without* a terminal status means the connection dropped, never that the
run succeeded — reconcile through `session.get`. `?after=<n>` resumes after the deltas you
already have.

## Calling a capability

The body is the capability's own request object. Read its JSON schema from
`GET /capabilities`, or from `research capabilities --schemas`; the CLI is often the
easier client, because it composes the full object for you.

Every call answers with the same envelope, success or failure:

```text
{"capability": <name>, "ok": <bool>, "result": <object|null>,
 "error": <object|null>, "run_id": <string|null>}
```

Failures carry a stable `code` — the message is not part of the contract, the code is:

| code | HTTP | when |
|---|---|---|
| `capability_not_found` | 404 | no capability with that name |
| `permission_denied` | 403 | the principal may not call it |
| `authority_error` | 403 | the actor lacks the scientific authority (e.g. a model accepting evidence) |
| `invalid_request` | 422 | the body does not validate against the request model |
| `transition_error` | 409 | an illegal state transition |
| `object_not_found` | 404 | the named object is not in this workspace |
| `workspace_error` | 409 | a workspace-level problem |
| `projection_error` | 409 | a projection-level problem |
| `capability_error` | 400 | any other harness error |
| `internal_error` | 400 | an unrecognised exception; never leaked verbatim |

An agent host attempting an accepted-state mutation gets the refusal as a response, not a
crash:

```console
$ curl -s -X POST http://127.0.0.1:8765/capabilities/evidence.accept \
    -H 'content-type: application/json' -d '{}'
{"capability":"evidence.accept","ok":false,"result":null,
 "error":{"code":"permission_denied",
          "message":"evidence.accept: a agent_host principal does not hold the 'mutate' permission (holds: read, stage)",
          "capability":"evidence.accept"},
 "run_id":null}
```

And an ill-formed body is rejected by the capability's own model, naming every field at
once:

```console
$ curl -s -X POST http://127.0.0.1:8765/capabilities/claim.create \
    -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{}'
{"capability":"claim.create","ok":false,"result":null,
 "error":{"code":"invalid_request","message":"claim.create: claim: Field required",
          "capability":"claim.create"},"run_id":null}
```

## Concurrency and long-running work

Accepted-state calls run under the workspace lock, so the CLI, an editor, and the daemon
cannot interleave writes. A long-running capability (`work.interrogate`,
`evidence.verify`) persists its run first and returns a durable `run_id`; poll
`GET /runs/{run_id}` rather than holding the connection open. `POST /runs/{id}/cancel`
sets a durable cancel flag the run checks before its next stage.

## When to use HTTP instead of MCP

MCP is the primary host boundary (ADR-009). The HTTP daemon exists for clients that need a
different transport — the Web cockpit, the VS Code extension, a shell script, a host that
cannot launch a stdio subprocess. Both go through the same registry, so the names, the
schemas, the refusals, and the payloads are identical. See [MCP hosts](mcp.md).

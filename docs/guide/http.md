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

`POST /capabilities/{name}` is the entire write surface; everything else is a read. FastAPI
also serves `/docs`, `/redoc`, and `/openapi.json`. The route set is asserted in
`tests/contract/protocol/test_http.py`, so a new one cannot appear by accident.

When `web/dist` exists it is mounted at `/` with a single-page fallback; see
[Web cockpit](web.md).

```console
$ curl -s http://127.0.0.1:8765/health
{"ok":true,"workspace":"/home/you/projects/traffic-survey","project":"demo",
 "review_policy":"strict","capabilities":64,"version":"0.1.0"}
```

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

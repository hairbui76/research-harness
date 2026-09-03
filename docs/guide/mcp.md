# Agent hosts over MCP

MCP is the primary host integration boundary (ADR-009). One command exposes a workspace to
Claude, ChatGPT, or any other MCP host, with **one tool per named capability** and the same
schemas, refusals, and payloads the HTTP daemon returns. There is no Claude-specific and no
ChatGPT-specific behaviour anywhere in the harness.

```console
$ research mcp --workspace /home/you/projects/traffic-survey
```

It speaks MCP over stdin/stdout and is meant to be launched by the host, not by you.
`--stdio` is the default and the only transport; `--host <label>` changes the string
recorded for the caller in the audit trail and nothing else.

## What a host may do

A host is an **`agent_host`** principal: it holds `read` and `stage`, never `mutate` or
`admin`. It may read the whole project, run interrogation and verification, draft from
accepted claims, and leave proposals in the review queue — which is how it asks for
approval. It may not accept evidence, audit a claim, attach a manuscript anchor, promote a
note, write a taxonomy, or rebuild state.

Refusals arrive as ordinary tool results, so the host can explain them rather than crash:

```json
{"capability": "evidence.accept", "ok": false, "result": null,
 "error": {"code": "permission_denied",
           "message": "evidence.accept: a agent_host principal does not hold the 'mutate' permission (holds: read, stage)",
           "capability": "evidence.accept"},
 "run_id": null}
```

The server's own instructions tell the host the same thing, so a well-behaved client asks
instead of trying: *"You may read the project and stage proposals; accepting evidence,
auditing a claim, and every other change to accepted state belongs to the researcher, so
ask rather than assume. Conversation is not project knowledge until it is promoted through
a capability."*

Every mutating tool's description repeats it: *"Changes accepted state, so it is refused
for an agent host: propose it and ask the researcher to accept."*

## Tool names

The mapping is the whole convention: **the capability name with dots replaced by
underscores.**

| capability | MCP tool |
|---|---|
| `review.inbox` | `review_inbox` |
| `claim.audit` | `claim_audit` |
| `work.interrogate` | `work_interrogate` |
| `retrieval.resolve_source` | `retrieval_resolve_source` |

It is deterministic and total, so a host that has seen a capability name knows the tool
name without asking. One tool is registered per capability; the full list is in
[Capabilities](capabilities.md), or from `research capabilities`.

Each tool advertises the registry's own request schema — the same object
`POST /capabilities/<name>` takes — so "the MCP schema equals the HTTP schema" is identity
rather than a copy that can drift. Tool metadata also carries `capability`, `permission`,
`human_only`, and `long_running`.

## Resources

Three read-only resources cover what a host reads most:

| URI | content |
|---|---|
| `research://inbox` | the review queue in priority order: what the researcher has to answer |
| `research://claims/{claim_id}` | one Claim with the evidence it records, grouped by relation |
| `research://evidence/{evidence_id}` | one accepted Evidence, reopened at its exact source location |

All three are `application/json` and are the same capability results (`review.inbox`,
`claim.find_support`, `retrieval.resolve_source`) served as resource bodies.

## Claude Desktop

Edit the config file:

* macOS — `~/Library/Application Support/Claude/claude_desktop_config.json`
* Windows — `%APPDATA%\Claude\claude_desktop_config.json`
* Linux — `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "research-harness": {
      "command": "/absolute/path/to/uv",
      "args": [
        "run",
        "--project", "/absolute/path/to/research-harness",
        "research", "mcp",
        "--workspace", "/absolute/path/to/traffic-survey"
      ]
    }
  }
}
```

Use an **absolute** path for `command` (`which uv`) and absolute paths in `args`: the app
does not reliably inherit your shell's `PATH` or working directory. Per-server keys are
`command`, `args`, and `env`. Restart Claude Desktop after editing.

If the harness is installed on your `PATH` rather than run from a source tree, the entry
is simply `"command": "/absolute/path/to/research", "args": ["mcp", "--workspace", "..."]`.

## Claude Code

```bash
claude mcp add --scope project --transport stdio research-harness -- \
  uv run --project /absolute/path/to/research-harness \
  research mcp --workspace /absolute/path/to/traffic-survey
```

`--scope project` writes `.mcp.json` in the repository, which you can check in:

```json
{
  "mcpServers": {
    "research-harness": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--project", "/absolute/path/to/research-harness",
        "research", "mcp",
        "--workspace", "/absolute/path/to/traffic-survey"
      ]
    }
  }
}
```

`--scope local` keeps it private to you in this project; `--scope user` applies it to all
your projects.

## ChatGPT and other hosts

ChatGPT's connectors accept **remote HTTPS MCP endpoints only** — the web and desktop apps
cannot launch a local stdio subprocess or reach `127.0.0.1`. Two honest options:

* **Bridge the stdio server to HTTP.** A stdio-to-HTTP MCP proxy (`mcp-remote`,
  `supergateway`, or similar) in front of `research mcp` gives you an endpoint a connector
  can reach. Exposing a research workspace beyond your workstation is a decision to make
  deliberately: the harness binds loopback and keeps its authority in a local file
  precisely so that it does not happen by accident.
* **Use the local HTTP daemon directly.** `research serve` already speaks JSON over
  loopback with the same capability names and schemas — see [HTTP daemon](http.md). This is
  the fallback ADR-009 names.

The **OpenAI Agents SDK** has no such restriction: `MCPServerStdio` launches
`research mcp` as a subprocess exactly like Claude Desktop does, so a Python agent can use
the workspace directly.

Whatever the host, it is an `agent_host` and the permission model above applies unchanged.

## Checking it works

Without a host, from Python:

```console
$ uv run python - <<'PY'
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command="uv",
        args=["run", "--project", "/path/to/research-harness", "research", "mcp",
              "--workspace", "/path/to/traffic-survey"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(init.server_info.name, init.server_info.version)
            print(len((await session.list_tools()).tools), "tools")
            print([str(r.uri) for r in (await session.list_resources()).resources])

asyncio.run(main())
PY
research-harness 0.1.0
65 tools
['research://inbox']
```

The tool count is however many capabilities this build registers; compare it with
`research capabilities`.

If the host reports the server exited immediately, run the same command in a terminal: a
missing workspace, a bad path, or an unreadable `research.yaml` prints one `error:` line
that the host swallows. See [Troubleshooting](troubleshooting.md).

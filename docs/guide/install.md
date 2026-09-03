# Install and first run

## Requirements

* Python 3.12 or newer.
* [uv](https://docs.astral.sh/uv/) for dependency management.
* SQLite with FTS5 — the module bundled with CPython on Linux and macOS has it. Exact
  terminology search and `research rebuild` both need it.

Optional, and only for the two GUI surfaces: Node and pnpm build the Web cockpit
(`web/`) and the VS Code extension (`vscode/`). Nothing in the CLI, the daemon, or the
MCP server needs them.

## Install

```bash
git clone <this repository> research-harness
cd research-harness
uv sync
```

`uv sync` installs the project and its dev tools into `.venv`. Everything below is run
through `uv run`; if you would rather have `research` on your `PATH`, activate the
environment (`source .venv/bin/activate`) and drop the `uv run` prefix.

## Check the install

```console
$ uv run research --version
research 0.1.0

$ uv run research doctor
[ok  ] research-harness  0.1.0
[ok  ] python            3.12.13 (requires >= 3.12)
[ok  ] pydantic          2.13.5
[ok  ] typer             0.27.2
[ok  ] sqlite-fts5       available
[note] node              not installed (only needed for Web cockpit and VS Code extension builds)
[note] pnpm              not installed (only needed for Web cockpit and VS Code extension builds)
```

`doctor` needs no network and no API keys. Lines marked `[note]` are information, never
failures; `doctor` exits non-zero only for something that will actually stop you. Run
from inside a workspace it also reports on that workspace — see
[Rebuild and recovery](rebuild-and-recovery.md#research-doctor).

## Create a workspace

```console
$ uv run research init ~/projects/traffic-survey --name traffic-survey
initialized traffic-survey at /home/you/projects/traffic-survey
  review policy      strict
  next               research ingest <pdf>
```

`init` creates the canonical directory tree, `research.yaml`, `.gitignore`, and the first
line of `events/research.jsonl`. `--policy` takes `strict` (the default; every acceptance
is a researcher action) or `policy_batch` (batch acceptance is additionally permitted
under the deterministic conditions in [Review](review.md#batch-acceptance)). The layout
is described in [Workspace](workspace.md).

## Which workspace a command acts on

Every command except `init` and `doctor` needs a workspace, and finds one in this order:

1. `--workspace` / `-w`;
2. the `RESEARCH_WORKSPACE` environment variable;
3. the nearest directory at or above the current one that contains `research.yaml`.

With none of the three:

```console
$ uv run research inbox
error: no research workspace at or above /tmp: run `research init <dir>`, pass --workspace, or set RESEARCH_WORKSPACE
```

Working inside the project directory is the usual case, so most examples in this guide
omit `-w`.

## Windows

The harness runs on Windows (PowerShell or cmd) with the same commands; two differences:

- The workspace lock uses a `msvcrt` byte-range lock instead of `flock`; behaviour is the
  same (one writer at a time, waiters see who holds it).
- Shell one-liners in this guide use POSIX syntax. The Web cockpit URL, for example, is

  ```powershell
  research serve
  Start-Process "http://127.0.0.1:8765/?token=$(Get-Content .research\daemon-token)"
  ```

Paths in `research.yaml` and in command output use the platform's separators; canonical
files are still UTF-8 with `\n` line endings, so a workspace moves between platforms
unchanged (configure Git with `core.autocrlf=false` for the workspace).

## Next

* [Workspace](workspace.md) — what `init` created and what belongs in Git.
* [Review](review.md) — the gate every model proposal passes through.
* [Providers](providers.md) — running with a real model, or offline with a script.

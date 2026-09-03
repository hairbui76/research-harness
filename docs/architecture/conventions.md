# Engineering conventions

Read this before touching code. `PRODUCT.md` is the specification; `ROADMAP.md` is the
plan and lists the acceptance requirements for every task. These conventions exist so
that work done by many people (and agents) in parallel still reads as one codebase.

## Layering (enforced by review, and by import checks where practical)

| Package | Owns | Must NOT import |
|---|---|---|
| `domain/` | pure Pydantic schemas, enums, IDs, errors, state transitions | anything outside `domain/` and the stdlib/pydantic |
| `workspace/` | canonical file layout, atomic persistence, locking, journal, events | projection, providers, cli, server |
| `projection/` | SQLite/FTS/vector projections; deletable and rebuildable | providers, cli, server |
| `ingest/`, `parsing/` | artifact ingestion, identity, DocumentIR, anchors | providers, cli, server |
| `providers/` | model/search/parser adapters behind neutral contracts | domain-specific business rules, cli, server |
| `roles/`, `workflows/`, `evidence/`, `claims/`, `manuscript/`, `retrieval/` | application logic | cli, server, protocol |
| `capabilities/` | **the only supported mutation surface** for accepted state | cli, server |
| `protocol/`, `server/`, `cli/` | transports; thin clients of `capabilities/` | each other's internals |

- No provider-, host-, or vendor-specific concept (OpenAI, Anthropic, Claude, ChatGPT, MCP)
  may appear in `domain/`.
- Frontends and transports never write canonical files or SQLite directly.
- Canonical files have scientific authority; everything under `.research/` is regenerable.

## Python style

- Python 3.12; `from __future__ import annotations` in every module.
- Pydantic v2. Canonical objects use `model_config = ConfigDict(frozen=True, extra="forbid")`
  and derive from the shared base in `domain/base.py`.
- Vocabularies are `enum.StrEnum` subclasses in `domain/enums.py`, never free strings.
- Stable IDs are typed (`domain/ids.py`); never pass raw strings where an ID type exists.
- Timestamps are timezone-aware UTC `datetime`s; serialize as ISO-8601.
- `mypy --strict` and `ruff check` must pass; do not add `# type: ignore` or `noqa`
  without a comment saying why.
- Errors derive from `research_harness.domain.errors.ResearchHarnessError`; use specific
  subclasses (`ValidationError`, `TransitionError`, `WorkspaceError`, ...).
- Keep modules focused; prefer small pure functions plus a thin service class.
- Docstrings: one line saying what and why; no narration of the obvious.
- Logging via `logging.getLogger(__name__)`; never `print` outside `cli/`.

## Canonical serialization

- Single objects (`Work`, `Claim`, `Decision`, ...) are YAML files, keys in a stable order,
  block style, UTF-8, trailing newline.
- Append-heavy collections (`evidence.jsonl`, `events/research.jsonl`) are JSON Lines,
  one object per line, keys sorted, no trailing whitespace.
- Every canonical object carries `schema_version`, `id`, `created_at`, `updated_at`, and
  `provenance`.
- Writes go through atomic replace (write temp file in the same directory, fsync, rename).

## Tests

- Layout: `tests/unit`, `tests/integration`, `tests/contract`, `tests/e2e`, `tests/fixtures`.
  Mirror responsibilities, not layers: `tests/unit/domain/`, `tests/integration/workspace/`.
- Every test directory is a package (`__init__.py`).
- Tests are deterministic, hermetic, and offline: no network, no real API keys, no sleeps.
  Provider adapters are tested with fake transports.
- Use `tmp_path` for any filesystem work.
- Use Hypothesis for invariants (round-trips, transition legality, idempotence).
- Test names state the invariant: `test_model_proposed_cannot_become_source_observed`.

## Tooling rules for parallel work

- Do **not** edit `pyproject.toml` or run `uv add`/`uv remove`; the project manager owns
  dependencies. If you need a package, say so in your report.
- Only create or modify the files assigned to you. If you must touch a shared file
  (`cli/app.py`, `domain/enums.py`, ...), keep the change minimal and list it in your report.
- Before reporting, run and pass all of:

  ```bash
  uv run pytest -q
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src
  ```

- Do not commit; the project manager commits at phase gates.

## Report format (for subagents)

Keep it under ~300 words:

1. Files created/modified.
2. Public interfaces (names + one-line semantics) other tasks will consume.
3. Acceptance requirements met, and any not met with the reason.
4. Gate output summary (test count, lint/type status).
5. Decisions or deviations the PM should know about; dependencies needed.

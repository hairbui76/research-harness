Read and follow AGENTS.md in the repository root. Every coding task must finish with
`pnpm run task:check` passing for the current source, followed by `pnpm run task:status`.
On failure, read `.task-gate/latest.json` and its logs, fix the cause, and rerun within
the bounded repair policy in AGENTS.md. Do not bypass hooks or weaken tests.

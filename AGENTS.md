# Repository instructions

## Verify every coding task (all agents)

Use a separate Git worktree for each concurrent coding task. Do not edit another agent's
working tree, or change files while verification runs.

1. Implement the task and regression tests for changed behavior. Focused tests are useful
   during development. Do not delete, skip, or weaken assertions to make a gate pass.
2. Before reporting completion, run `pnpm run task:check` from the repository root.
   It checks Python lint/format/types, frontend types/lint/design tokens, the complete
   default Python and JS test suites, production builds including VS Code, and browser
   tests using the real backend and disposable data.
3. On failure, read `.task-gate/latest.json` and the referenced logs. Fix the cause and
   rerun. Limit this to 3 repair rounds; stop sooner on missing prerequisites or no
   progress. Report the unresolved failure instead of claiming completion.
4. Run `pnpm run task:status` after your final source edit. Only a successful result is
   evidence for the current tree. Editing, staging, or committing invalidates old evidence.
5. Report the exact commands, outcomes, and remaining environment-gated coverage.

For a frontend change, extend browser tests for the affected user flow and inspect the
screenshots/traces in `.task-gate/browser-results`. Use Impeccable `audit` on the changed
web surface when available; use `critique` for UX/design changes. Follow the incumbent
design system. Batch visual review and corrections into at most two inspection passes;
do not start an unlimited polish loop or auto-approve screenshot baselines. Impeccable
review supplements automated checks; it does not replace them. If unavailable, report
that limitation and still run the automated checks.

`pnpm run task:loop --task-file <file> --agent-file <json>` provides an external loop for
any command-line agent adapter that accepts task text on stdin. See
`docs/guide/task-verification.md`. Agents launched through other UIs must follow this
completion protocol; there is no universal UI task-finished event across vendors.

Install dependencies and browser prerequisites once per machine/checkout with
`pnpm install` and `pnpm exec playwright install chromium`. On Linux CI use
`pnpm exec playwright install --with-deps chromium`. `pnpm run hooks:install` installs
the Git gate (also runs on dependency installation).

## Run every test before every push

Immediately before each `git push`, run `pnpm run test:pre-push` from the repository root. This command runs the complete default Python test suite and every pnpm workspace test suite. Focused tests used during development do not replace this final gate.

Do not push while any required test fails. Tests that are explicitly environment-gated may self-skip when their documented credential, platform, toolchain, or opt-in flag is unavailable. When a change affects an environment-gated surface, also run that surface's documented test command whenever its prerequisites are available.

Report the exact test commands run and their outcomes when handing work back to the user.

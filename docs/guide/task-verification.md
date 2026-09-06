# Task verification for every coding agent

The repository owns the checks. An agent's final message is not evidence that they passed.
Use one worktree per concurrent task and do not edit it during verification.

## Setup

Run `uv sync --locked`, `pnpm install`, and `pnpm exec playwright install chromium`.
On Linux CI, use `pnpm exec playwright install --with-deps chromium` instead.
Dependency installation installs the Git pre-push hook; `pnpm run hooks:install` reinstalls
it explicitly. Existing custom hooks are not overwritten. A new clone needs this setup;
Git does not install hooks just by cloning. Each machine needs its own browser install.

## Interactive tasks

1. Implement and run focused regression tests.
2. Run `pnpm run task:check`. A failure exits nonzero and records the failed command and
   full log in `.task-gate/latest.json`. Fix its cause and repeat, at most three repair
   rounds; stop early for unavailable prerequisites or no progress.
3. Run `pnpm run task:status` immediately before reporting completion. Evidence is tied to
   source contents, new files, the index, and HEAD. A subsequent edit, stage, or commit
   requires a new check. Ignored build outputs and reports do not invalidate it.
4. State the exact commands and outcomes. A skipped credential/platform-dependent test
   does not prove that integration works. Follow the additional test requirements in AGENTS.md.

Codex and other AGENTS.md-aware tools use the root instructions. Claude's `CLAUDE.md`
imports them; the project Stop hook also blocks completion without current evidence and
returns the instructions to the agent, up to three continuations.
UserPromptSubmit resets Claude's budget for a new task; discussions that leave the source
unchanged do not trigger a repair loop. Gemini has a root
GEMINI.md pointing to the same protocol. There is no universal task-finished hook for
unrelated desktop agents: use the external loop below for enforced orchestration, or
configure that agent's completion hook to call `pnpm run task:status`.

## External repair loop

Write the task to a UTF-8 text file. Write a JSON array of arguments to an adapter file,
for example `["python", "C:/tools/my-agent-adapter.py"]`. The adapter runs from the
worktree root, reads task/repair instructions from stdin, edits the task's source, and
exits nonzero if the agent fails. It must not push or merge. Select the adapter explicitly;
the loop does not assume a model, provider, credentials, or permission-bypass flags.

```bash
pnpm run task:loop --task-file .task-gate/task.txt --agent-file .task-gate/agent.json --rounds 3
```

The controller runs the agent, then the full gate. On failure it gives the adapter the
task and the paths of the failure report/logs, then verifies again. The default budget is
three agent rounds (maximum five), with a 1,200-second timeout per command. `--timeout`
changes that bound. No source change during a repair ends the loop early. Agent logs are
`.task-gate/agent-N.log`; the latest verification overwrites the numbered check logs.
Exit zero means verified, never pushed. `TASK_GATE_ACTIVE` prevents nested Claude Stop
hooks from recursively verifying while the outer controller owns the checks.

Do not run two controllers in one worktree. A concurrent check is rejected. After a hard
process crash, inspect the PID in `.task-gate/check.lock`; remove that single file only
after confirming the check is no longer running. A lock is never treated as a pass.

## What the gate covers

- Python lint, formatting, mypy, and all default contract/e2e/integration/perf/unit tests.
- Design, web, and extension tests and lint; frontend types and browser-test types.
- Production builds for design/web and the extension's explicit `compile` script.
- Chromium using the built frontend and real backend with disposable application data.
  Browser coverage starts with project creation, rename, reload/persistence, authentication
  refusal, project-home accessibility and horizontal overflow at desktop and tablet width.
  It does not call paid AI providers or alter the user's research registry.
- Browser screenshots and failure traces are saved under `.task-gate/browser-results`;
  `pnpm exec playwright show-report .task-gate/playwright-report` opens the HTML report.
  `TASK_BROWSER_PORT` chooses another port for concurrent worktrees; an existing server
  is never reused, to avoid testing another checkout or touching real data.

Extend browser coverage when changing other flows (PDF, chat streaming, manuscript, etc.).
These smoke tests are not exhaustive. Screenshots are review evidence, not approved pixel
baselines. Impeccable audit/critique supplements this gate for frontend changes; it runs
through the selected coding agent, not as an invented unattended pass/fail CLI. Keep visual
inspection bounded and never update image baselines solely to silence failures.

## Push and GitHub

The pre-push hook requires a clean tree and only permits updates pointing at checked-out
HEAD (deletions need no test). It runs `pnpm run test:pre-push`, which invokes the same full
gate afresh; cached completion evidence never skips this gate. Commit first, then push
that branch. Test other branches in their own worktrees. Local hooks can be bypassed by
someone controlling the machine; they are an accident-prevention layer.

The checked-in Verify workflow runs the gate on Linux and Windows for PRs and main pushes,
and uploads reports even on failure. It becomes active after this configuration is pushed.
In GitHub branch protection, require PRs and both `Verify (ubuntu-latest)` and
`Verify (windows-latest)` checks with the branch up to date; disable admin bypass if desired.
No local script silently edits GitHub protection or grants an agent merge permissions.

# Task 10b report: `provider.cli.test` success path proven in default CI

## BASE

Worktree `agent-a88dcec49225c6c17`, branch `worktree-agent-a88dcec49225c6c17`,
fast-forwarded onto the feature branch with `git merge --ff-only cli-providers`:

```
b33d2e4 Merge branch 'worktree-agent-a93d23d60156f60c3' into cli-providers
```

BASE = `b33d2e4`. No `src/` file was modified.

## What changed

- `tests/fixtures/cli/fakes.py` — the `PROGRAM` string gains a `fill(lines, nonce)` helper and,
  after stdin is read and recorded, finds the nonce with
  `re.search(r"provider\.cli\.test-[0-9a-f]{8}", stdin or "")` and substitutes `{{NONCE}}` in
  every `run.lines` entry (dicts are serialised with `json.dumps` first; `{"sleep": …}` entries
  pass through untouched so timing scripts keep working). `before_input` is deliberately not
  substituted — it is emitted before stdin is read. The module docstring documents the placeholder.
- `tests/contract/capabilities/test_cli_providers.py` — `probe_reply(echo="{{NONCE}}")`; the
  success test now asserts unconditionally; new
  `test_the_test_call_reports_a_wrong_echo_as_a_failure`.
- `tests/e2e/test_cli_providers_commands.py` — new
  `test_test_exits_zero_when_the_runtime_echoes_the_nonce` (text and `--json`), mirroring the
  existing exit-1 case's fixture wiring and invocation.

## RED evidence

Both success-path tests were written first and run against the unmodified fake
(`uv run pytest <the three new/changed tests> -q` → `2 failed, 1 passed`):

```
    assert report.runtime == "codex" and report.model == "gpt-5.5" and report.version == "0.150.1"
    assert report.egress_host == "chatgpt.com" and report.egress_kind == "external"
>   assert report.ok is True and report.diagnostic is None
E   AssertionError: assert (False is True)
E    +  where False = CliProviderTestReport(name='codex-sub', runtime='codex', model='gpt-5.5', version='0.150.1', egress_host='chatgpt.com'...tency_ms=57, message='the runtime answered a valid object, but did not echo the nonce', diagnostic='structured_output').ok

tests/contract/capabilities/test_cli_providers.py:360: AssertionError
```

```
    code, out = run("providers", "test", "codex-sub", "--workspace", str(workspace))

    lines_out = out.splitlines()
>   assert code == 0, out
E   AssertionError: egress: codex-sub sends research content to chatgpt.com through Codex CLI
E     codex-sub (codex/default, 0.150.1): failed
E       the runtime answered a valid object, but did not echo the nonce
E       diagnostic: structured_output
E
E   assert 1 == 0

tests/e2e/test_cli_providers_commands.py:146: AssertionError
```

```
=========================== short test summary info ============================
FAILED tests/contract/capabilities/test_cli_providers.py::test_the_test_call_runs_one_validated_request_and_reports_the_destination
FAILED tests/e2e/test_cli_providers_commands.py::test_test_exits_zero_when_the_runtime_echoes_the_nonce
2 failed, 1 passed in 4.98s
```

The third new test, `test_the_test_call_reports_a_wrong_echo_as_a_failure`, was green on its
first run: it pins an already-correct `src/` branch (the "valid object, wrong echo" branch of
`test_cli_provider`) that simply had no default coverage, and it does not depend on the fake's
new placeholder. It is a characterisation test, not a red-then-green one; that is stated here
rather than manufacturing red by changing `src/`, which the brief forbids.

After teaching the fake the placeholder, all three are green.

## Gates (all green, Step 4 of the brief)

| Command | Result |
| --- | --- |
| `uv run pytest tests/contract/capabilities/test_cli_providers.py tests/e2e/test_cli_providers_commands.py tests/unit/providers/cli -q` | `177 passed in 22.72s` |
| `uv run ruff check` | `All checks passed!` |
| `uv run ruff format --check` | `617 files already formatted` |
| `uv run mypy src` | `Success: no issues found in 239 source files` |
| `uv run pytest tests/unit/providers/cli tests/contract/providers tests/contract/capabilities/test_cli_providers.py tests/e2e/test_cli_providers_commands.py tests/e2e/test_cli_capability_parity.py -q` | `418 passed, 3 skipped in 36.37s` |

The three skips are the pre-existing opt-in live provider smoke tests in
`tests/contract/providers/test_live_smoke.py` (no live env var was set, and
`RESEARCH_HARNESS_LIVE_CLI_TESTS` was never set at any point). `grep -rl FakeCli tests/`
lists exactly seven files; every test module among them is inside the sweep above, so the
placeholder is proven inert for all existing fake users.

## Deviations from the brief

1. **Nonce-identity assertion.** The brief allowed "at minimum assert the regex finds exactly
   one nonce in stdin". Implemented as `len(set(NONCE.findall(run["stdin"]))) == 1`: the nonce
   appears more than once in the prompt (the instructions plus the `InputEnvelope`), so the
   useful invariant is that exactly one *distinct* nonce is present. Combined with
   `report.ok is True` — which `test_cli_provider` only returns when
   `response.parsed.echo == nonce` — this proves the fake echoed the nonce it received.
2. **e2e helper.** No shared `probe_reply` location exists (the contract module defines its own,
   and importing a test module from another test module is worse than duplication), so the e2e
   file got the sanctioned local copy.
3. **`--json` assertion** re-uses the script written by the test's first `set_run` rather than
   rewriting it; `script.json` persists across invocations of the fake.

## Concerns

- Minor: the substitution now applies to every run line for every test, so a future fixture
  stream that legitimately contained the literal `{{NONCE}}` would be rewritten. Nothing under
  `tests/fixtures/cli/streams/` contains it today, and the full fake-using sweep is green.
- The wrong-echo case asserts `report.message` verbatim, so a rewording in
  `src/research_harness/capabilities/cli_providers.py` must be mirrored here. Deliberate — the
  brief asked for that branch's exact values.
- No token, credential path, e-mail, or home path appears in any added fixture or assertion.

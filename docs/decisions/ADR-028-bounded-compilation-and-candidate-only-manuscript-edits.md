# ADR-028: Manuscript compilation is a bounded local process, and model edits are candidate diffs

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §30, §30.3, §30.4, §34, §42 (L, P); ROADMAP.md Phase 21, Gate P21; `docs/superpowers/specs/2026-09-03-latex-manuscript-workspace-design.md` §2, §4–§9; implemented in `manuscript/{toolchain,compile,files,synctex,suggest,workspace}.py`, `capabilities/manuscript_workspace.py`, `server/routes_manuscript.py`

## Context

A manuscript page that renders LaTeX to HTML is a demo; a scientific writing workspace has
to produce the PDF the venue will receive. That means running a real TeX toolchain, and a
TeX toolchain is a programmable execution environment: `\write18` and `-shell-escape` turn
a `.tex` file into arbitrary code, a project `latexmkrc` is unsandboxed Perl, and a
runaway run can hang for hours. At the same time the researcher, not the harness, is the
author of `manuscript/`: a model that improves a paragraph in place is data loss with good
intentions, and an editor that overwrites a co-author's change is worse.

## Decision

**The toolchain is discovered, allowlisted, and never installed.** `manuscript:` in
`research.yaml` may pin an `engine`, an `entry_file`, a `timeout_seconds`, `synctex`, and
`extra_args`; `extra_args` is an allowlist of eleven flags checked when the config is read,
because a compiler flag is an execution capability. Discovery only stats `PATH` — no engine
is executed to learn that it exists — and a pinned engine that is missing produces setup
guidance, never a silent fallback to a different one and never a source change.

**The process is confined and bounded.** The entry file must resolve inside `manuscript/`,
the working directory is `manuscript/`, `shell=False`, and the environment is rebuilt from
a small allowlist with `TEXINPUTS`/`BIBINPUTS` pinned to the project and `shell_escape=f`,
`openout_any=p` for TeX Live engines. `tectonic` runs `--untrusted`, never with
`-Z shell-escape`; **`latexmk` runs `-norc`**, because a project `latexmkrc` executes on
every compile while a `.tex` file without shell escape does not. The run gets its own
process group and a timeout; on expiry the whole group is killed and the log written so far
is still parsed, because "what had it complained about before it hung" is the next question.

**Outputs are disposable and the last good one survives.** Everything lands under
`.research/build/manuscript/<build_id>/` with a `build.json` provenance record (compiler,
argv, inputs fingerprint, timings, exit status). A successful build advances the
`last-good.json` pointer; a failed build leaves it alone and is reported as *stale with its
own timestamp*, so the preview keeps showing the last PDF that really compiled while the
diagnostics describe the source as it is now. A failed compile is a returned
`CompileResult`, not an exception.

**Compiler diagnostics and scientific audit findings are two lists that are never merged.**
`BuildView` carries them separately and sums neither: a document may compile cleanly and
fail its audit, or pass its audit and fail to compile. A view that reported "3 errors"
would be answering a question nobody asked.

**Model and humanizer output is always a candidate diff.** `manuscript.suggest` reads one
span, asks the writer role to rewrite it, and stages a `SuggestionCandidate` under
`.research/staging/manuscript/` carrying the protected-span analysis, the semantic diff, and
the audit verdict. It never opens the source for writing — the file's hash is taken before
and after, and a difference raises. `manuscript.apply_suggestion` is the only path to
source, and it refuses a candidate whose protected spans moved, whose audit did not pass,
or whose file changed underneath it; when it does write, it writes through `ManuscriptFiles`
— the same hash-checked, path-confined save a researcher's own edit uses — and records a
`manuscript.source_written` event. What blocks is what changes meaning: a changed protected
span, and a proposition added, removed, strengthened, or weakened. An anchor the rewrite
invalidates does *not* block, because every accepted reword breaks the fingerprint it was
anchored by; the answer to that is `manuscript.revalidate` (ADR-008).

**SyncTeX is read, not shelled out to, and "unavailable" is an answer.** The parser reads
`.synctex(.gz)` in pure Python, because a project compiled by `tectonic` may have no TeX
Live and therefore no `synctex` binary. A missing, unreadable, or unrecognised map reports
`SynctexUnavailable` with its reason rather than guessing a location.

## Consequences

### Positive

- The PDF in the preview is the PDF the venue gets, produced by the researcher's own
  engine with its argv on record.
- A broken build costs nothing that was working: last-good PDF intact, editor content
  untouched, diagnostics current.
- "A model wrote this sentence" is a reviewable diff and a Git-visible event, not an
  archaeology problem.

### Negative / costs

- Eleven allowlisted flags will not be enough for someone's build, and the answer is to
  extend the allowlist in a reviewed change rather than to pass the flag. `latexmk -norc`
  in particular ignores a `latexmkrc` a project may genuinely depend on.
- Confinement is per-process, not a sandbox: a TeX distribution with its own configured
  privileges is outside what an environment allowlist can reach.
- The harness owns the output directory, the working directory, and the SyncTeX flag, so a
  workflow that needs a different output layout cannot express it.
- The CLI's `manuscript build` takes a real build id and does not accept the `latest` /
  `last-good` aliases the HTTP PDF route accepts — an inconsistency between two surfaces of
  the same idea, recorded in `docs/plans/dogfood-2026-09-03-v1.1.md`.

## Invariants this ADR protects

- The compiler receives no implicit network or shell authority, and no flag that was not
  allowlisted before the process started (§42 P, PRODUCT §34).
- No compile writes a manuscript file; compilation output is disposable and deleting it
  loses no source, anchor, or conclusion (ADR-001).
- A failed compile never overwrites the last good PDF, and the stale label carries the
  timestamp of the build it came from.
- A successful compile is not an audit result and never implies one (§42 P).
- Model output cannot reach source except through an explicit, hash-checked apply of a
  candidate that preserved its protected spans and passed the audit (§42 L, ADR-007).
- An external change to a manuscript file is detected and refused rather than overwritten
  (LaTeX spec §4).
- A path from a transport cannot read or write outside `manuscript/`: `..`, absolute paths,
  and escaping symlinks are refused.
- Missing SyncTeX, missing PDF, and missing engine are reported as themselves.

## Rejected alternatives

- **Render LaTeX to HTML and call it a preview.** The spec's first non-goal: it is not what
  the venue compiles, and it hides exactly the failures that matter.
- **Ship or install a TeX distribution.** Hundreds of megabytes, a second update channel,
  and no improvement to the guarantee — the researcher's engine is the one that counts.
- **Pass `extra_args` through.** One `-shell-escape` in a `research.yaml` (or in a PR to
  one) is arbitrary code on every compile.
- **Let `latexmk` read its `latexmkrc`.** The convenient choice, and it executes project
  Perl on every build — a shell escape by another name.
- **Fall back to another engine when the pinned one is missing.** Silently changes what
  produced the PDF, which is provenance, not a preference.
- **Let a model edit the file and rely on Git to review it.** Not every workspace is
  committed at the right moment, and the protected-span and audit checks exist precisely to
  run *before* the write.
- **Merge compiler and audit findings into one count.** Optimises the summary line and
  destroys the distinction the product is for.

## Where it is enforced

- `manuscript/toolchain.py`: `ALLOWED_EXTRA_ARGS`, `ENGINE_PREFERENCE`, `ManuscriptSettings`,
  `discover_toolchain`, `ToolchainUnavailableError` (setup guidance).
- `manuscript/compile.py`: the argv builders (`--untrusted`, `-norc`), `_environment`
  (allowlist, `TEXINPUTS`/`BIBINPUTS`, `shell_escape=f`, `openout_any=p`), the process-group
  runner and timeout kill, `build.json`, `LAST_GOOD_FILENAME` and the stale reporting,
  the log diagnostic parser.
- `manuscript/files.py`: path confinement, `ManuscriptConflictError`, content-hash tokens.
- `manuscript/synctex.py`: `SynctexUnavailable` and its reasons.
- `manuscript/suggest.py`: `suggest_edit` (hash before/after), `_verdict`,
  `protected_violations`, `apply_suggestion` (refusals, `ManuscriptFiles` write,
  `manuscript.source_written`).
- `manuscript/workspace.py` (`BuildView`'s two lists), `capabilities/manuscript_workspace.py`,
  `server/routes_manuscript.py`.
- Tests: `tests/e2e/test_manuscript_workspace_gate.py`,
  `tests/integration/manuscript/{test_compile,test_workspace}.py`,
  `tests/unit/manuscript/{test_toolchain,test_compile_diagnostics,test_files,test_synctex,test_suggest}.py`,
  `tests/contract/capabilities/test_manuscript_workspace.py`, `tests/e2e/test_manuscript_cli.py`.

# The manuscript workspace

`manuscript/` holds ordinary, user-owned project files. The harness reads them, compiles
them with a real local LaTeX engine, audits the prose against the accepted research graph,
and writes one file of its own (`anchors.jsonl`). Nothing else in that directory is written
without you asking, and a model's rewrite is always a candidate diff (ADR-028, PRODUCT §30).

Two boundaries hold everywhere on this page:

* **A compile is not an audit.** Compiler diagnostics and scientific audit findings are two
  lists that are never merged. A document may compile cleanly and fail its audit, or pass
  its audit and fail to compile.
* **A missing answer is an answer.** No engine, no PDF, and no SyncTeX map are each
  reported as themselves — with the reason, and for a missing toolchain with setup
  guidance — never as an empty success.

## The toolchain

The harness never ships or installs a TeX distribution. It looks for engines already on
`PATH`, in the order `latexmk`, `tectonic`, `pdflatex`, `xelatex`, `lualatex`, and checks
them against the optional `manuscript:` section of `research.yaml`
([the workspace](workspace.md#the-latex-toolchain-manuscript)):

```yaml
manuscript:
  engine: tectonic          # pin one; a pinned engine not on PATH is a setup message
  entry_file: main.tex      # relative to manuscript/, must be a .tex file
  timeout_seconds: 120      # the process group is killed at this point
  extra_args: [-file-line-error, -halt-on-error]   # from a fixed allowlist
  synctex: true
```

Discovery only stats the filesystem, so opening the workspace runs nothing and can never
change a source file. With no engine at all:

```console
$ research manuscript compile
error: No LaTeX engine was found on PATH. Install one of: tectonic (a single binary that
fetches what a document needs, https://tectonic-typesetting.github.io), or a TeX
distribution providing latexmk/pdflatex/xelatex/lualatex (TeX Live, MacTeX, MiKTeX).
```

A pinned engine that is missing is a message naming what *is* installed, never a silent
fallback to a different engine — which engine produced a PDF is provenance, not a
preference.

## Files

```console
$ research manuscript files
manuscript/  (3 files, entry main.tex)
  main.tex            tex          744 bytes
  references.bib      bib          323 bytes
  sections/intro.tex  tex          300 bytes

$ research manuscript read sections/intro.tex
sections/intro.tex  tex  300 bytes
  content_hash       sha256:8012785c…
  modified_at        2026-09-03T11:35:40+00:00

\section{Introduction}
…
```

Saving requires the hash you read:

```console
$ research manuscript write sections/intro.tex --expected-hash sha256:8012785c… --from new.tex
```

If the bytes on disk no longer match, the save is refused rather than winning over whoever
changed them:

```console
error: sections/intro.tex changed outside the harness: expected sha256:0000…, found
       sha256:8012785c…; re-read the file before saving again
```

Paths are relative POSIX paths inside `manuscript/`. `..`, absolute paths, and symlinks
whose target leaves the directory are refused before the filesystem is touched.

## Compiling

```console
$ research manuscript compile
build 20260903T113542Z-6b865c69  succeeded
  engine             tectonic (0.38s, exit 0)
  compiler           0 errors, 0 warnings
  audit              2 findings (0 errors)
    [warning] unregistered_claim: sections/intro.tex:4: substantive sentence is attached to
              no Claim: 'Structured traffic classifiers degrade under sustained load…'
  pdf                .research/build/manuscript/20260903T113542Z-6b865c69/main.pdf
  synctex            available
```

The run is confined and bounded: the working directory is `manuscript/`, `shell=False`, the
environment is rebuilt from a small allowlist with `TEXINPUTS`/`BIBINPUTS` pinned to the
project and shell escape off, `tectonic` runs `--untrusted`, `latexmk` runs `-norc`, and the
whole process group is killed at `timeout_seconds` — with the log written so far still
parsed, because "what had it complained about before it hung" is the next question.

Everything lands under `.research/build/manuscript/<build id>/` with a `build.json`
recording the compiler, its argv, the input fingerprint, the timings, and the exit status.
That directory is disposable like the rest of `.research/`: deleting it costs build outputs
and never a manuscript file.

`--entry` compiles a different `.tex`, `--timeout` overrides the configured limit.

### When it fails

```console
$ research manuscript compile
build 20260903T113607Z-cb03d428  failed
  engine             tectonic (0.14s, exit 1)
  compiler           3 errors, 1 warnings
    [warning] sections/intro.tex:5: Citation `kraus2019' on page 1 undefined on input line 5.
    [error] main.tex:28: Undefined control sequence.
  audit              2 findings (0 errors)
  pdf                .research/build/manuscript/20260903T113554Z-3f13c5b1/main.pdf  (stale: the last good build)
  synctex            unavailable (missing_file): tectonic was asked for SyncTeX data and
                     produced none for build 20260903T113607Z-cb03d428
  Build 20260903T113607Z-cb03d428 failed: 3 compiler error(s) against the source as it is now.
  The preview is the last PDF that compiled (20260903T113554Z-3f13c5b1, …); it is stale.
```

The last good PDF is never overwritten by a failure, and it is labelled stale with the
timestamp of the build it came from, so the preview keeps showing the last document that
really compiled while the diagnostics describe the source as it is now.

`research manuscript build [BUILD_ID]` re-reads one build — the latest by default — and
prints the same two lists. `--no-audit` prints compiler diagnostics only; `--parse-sources`
re-parses source PDFs so anchors are checked as well.

## Source ↔ PDF navigation

```console
$ research manuscript synctex main.tex:20            # forward: source line to PDF boxes
page 1  x=148.2 y=468.6 w=0.0 h=0.0
…

$ research manuscript synctex --page 1 --x 200 --y 400   # inverse: PDF point to source
main.tex:31
```

Coordinates are PDF points from the **top-left** of the page. The parser reads the engine's
own `.synctex(.gz)` file in pure Python rather than shelling out to the `synctex` tool,
because a project compiled by `tectonic` may have no TeX Live installed at all. When the
map is missing, unreadable, or in a format the parser does not know, the answer is
`unavailable` with the reason — never a guessed location.

## Candidate diffs

A model or humanizer rewrite of a span is staged, never applied:

```console
$ research manuscript suggest sections/intro.tex:4-5 --style humanize --script writer.json
staged run_20260903T113631Z_43406b53  sections/intro.tex:4-5
  policy             manuscript.humanize
  audit              passed
  protected spans    1 (0 changed)
  semantic diff      0 added, 0 removed, 0 strengthened, 0 weakened, 0 protected span(s) altered, 1 unchanged
  @@ -1,8 +1,8 @@
  -Structured traffic classifiers degrade under sustained load, and the degradation is
  -rarely reported \cite{kraus2019}.
  +Structured traffic classifiers degrade under sustained load, and that degradation is
  +seldom reported \cite{kraus2019}.
  apply with         research manuscript apply run_20260903T113631Z_43406b53
```

The file is byte-identical afterwards — the command hashes it before and after and raises
if that is not true. `--style` is `humanize`, `venue`, or `copyedit`; `--session`,
`--message`, and `--context-pack` tie the suggestion back to the conversation that asked
for it.

Applying is an explicit, hash-checked source mutation:

```console
$ research manuscript apply run_20260903T113631Z_43406b53
applied run_20260903T113631Z_43406b53 to sections/intro.tex
  content_hash       sha256:2613e526…
  event              manuscript.source_written
```

It is refused when the candidate changed a protected span (a citation, an equation, a
number, a unit, an anchor, a qualifier), when the audit did not pass, or when the file
changed underneath it — the same conflict check your own save goes through. What blocks is
what changes meaning: a proposition added, removed, strengthened, or weakened, or a
sentence that now reads stronger than its anchored Claim allows. An anchor the rewrite
invalidates does *not* block, because every accepted reword breaks the fingerprint it was
anchored by; the answer to that is `research manuscript revalidate` (ADR-008).

## The claim-traceability commands

These predate the workspace and still do the same job:

| command | what it does |
|---|---|
| `research manuscript attach FILE:LINE C0001` | bind the sentence to a Claim |
| `research manuscript attach-text` | the same, finding the sentence by its text |
| `research manuscript anchors` | every stored anchor and its Claim |
| `research manuscript revalidate` | re-find every anchored sentence; a reword goes stale rather than moving |
| `research manuscript audit` | audit the prose against the accepted research graph |
| `research manuscript trace FILE:LINE` | sentence → Claim → Evidence → exact source span |

`build` runs the same audit against a compiled build, which is how a compiler error and an
unsupported sentence end up in one view without being confused for each other.

## From the daemon and the cockpit

`GET /manuscript/builds/{build_id}/pdf` streams a build's PDF inline, and accepts `latest`
and `last-good` as build ids — the two questions a preview asks. There is deliberately no
route that *writes* a manuscript file: saving is `manuscript.write_file` and applying a
candidate is `manuscript.apply_suggestion`, so the capability layer stays the only surface
that changes source. See [the daemon](http.md) and [the Web cockpit](web.md).

## See also

* [The workspace](workspace.md#the-latex-toolchain-manuscript) — the `manuscript:` section
  in full, including the `extra_args` allowlist.
* [Review](review.md) — the audit vocabulary a finding uses.
* [VS Code](vscode.md) — the same anchors and audit inside the editor.

# LaTeX Manuscript Workspace — Design Specification

**Status:** Design approved in conversation; awaiting review of this written specification.

**Scope:** Design only; no implementation is authorised by this document.

## 1. Purpose

Provide a real scientific writing workspace inside Research Harness: owned LaTeX source, actual local compilation, PDF preview, and provenance/audit tools in one view. Chat math rendering and manuscript compilation are related experiences but separate technical paths.

## 2. Two rendering paths

### Conversation rendering

Messages render Markdown plus inline and display mathematics with KaTeX. Rendering is presentation only; it does not claim that a full LaTeX document compiles.

### Manuscript rendering

The Manuscript page invokes an installed local LaTeX toolchain to produce a real PDF from the researcher's source. HTML approximation is not an acceptable substitute. The effective compiler, command policy, inputs, log, and output timestamp are visible.

## 3. Workspace layout

```text
┌──────────────────┬──────────────────────────┬─────────────────────────┐
│ File tree        │ Source editor            │ PDF preview             │
│ project files    │ main.tex / includes      │ pages / search / zoom   │
└──────────────────┴──────────────────────────┴─────────────────────────┘
                         collapsible audit inspector
                 Claims · Evidence · citations · stale · errors
```

The researcher can resize and hide panes. On constrained widths the editor and preview switch tabs while preserving cursor and page position.

## 4. Source ownership and editing

- Files under `manuscript/` remain ordinary user-owned project files.
- The interface reads and writes only after explicit edit/save actions.
- Model and humanizer output is always a candidate diff, never a silent source rewrite.
- A candidate must preserve protected citations, equations, numbers, units, anchors, qualifiers, and accepted meaning; existing manuscript audit and human review still apply.
- External editor changes are detected and never overwritten without conflict resolution.

## 5. Compilation

Compilation runs locally in a bounded process with:

- an explicit project root and entry file;
- allowlisted compiler/tool configuration;
- timeout and resource limits;
- captured stdout/stderr and structured file/line diagnostics;
- output written to disposable build storage;
- no implicit network access or shell execution beyond configured LaTeX tooling.

Successful output updates the preview. Failed compilation keeps the last successful PDF visible, clearly labelled as stale, while showing current errors against the current source.

## 6. Source and PDF navigation

When SyncTeX or equivalent mapping is available:

- source cursor/selection can jump to the corresponding PDF location;
- PDF selection or double-click can jump back to source;
- manuscript Claims, citations, and anchors remain navigable through the audit inspector.

When mapping is unavailable, compilation and preview still work and the interface explains that bidirectional navigation is unavailable rather than guessing.

## 7. Diagnostics and audit

Compiler errors and warnings are grouped by file and line and can open the exact source position. Scientific audit is distinct from compiler diagnostics and includes:

- unsupported or unregistered substantive statements;
- citation mismatch or missing bibliography key;
- stale linked Claims/Evidence;
- wording stronger than the accepted Claim;
- invalid source anchors;
- protected-span changes in candidate diffs.

A document may compile while failing scientific audit, or pass audit while failing compilation; the interface never conflates the two.

## 8. Conversation integration

- A manuscript file, selection, sentence anchor, Claim, or compiler diagnostic can be referenced in conversation.
- `Context used` states which source excerpts and accepted research objects were sent to the model.
- Suggested edits return as a reviewable diff tied to the originating message and context receipt.
- Applying an accepted candidate is an explicit source mutation with normal file conflict checks.

## 9. Failure and recovery

- Unsaved editor content survives compiler failure.
- The last good PDF survives subsequent bad builds and is visibly timestamped.
- Missing compiler/toolchain produces setup guidance without modifying manuscript source.
- A timed-out process is terminated and its diagnostics retained.
- Deleted build/index projections can be regenerated from manuscript source and canonical research state.

## 10. Acceptance scenarios

1. Open a LaTeX project, edit a file, compile with a local toolchain, and view the resulting PDF.
2. Introduce a syntax error; show its file/line while retaining the last good PDF as stale.
3. Render math correctly in chat without claiming manuscript compilation.
4. Jump source-to-PDF and PDF-to-source when SyncTeX is available, and degrade honestly when it is not.
5. Ask for a humanized paragraph and receive a candidate diff that cannot silently overwrite source.
6. Distinguish a successful compile from a failed citation/Claim audit.

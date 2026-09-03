# The VS Code extension

The manuscript surface, and deliberately the narrowest one. It answers *may I write this
sentence?* — hover a sentence to see the Claim behind it, attach a Claim to a sentence,
create one from a selection, and see `manuscript.audit` findings as editor diagnostics.
Everything else it hands to the CLI, the cockpit, or an agent host.

Full detail — the command table, the hover format, the diagnostic severities, the sentence
port and how its fixtures are kept honest, and the backend gaps it works around — is in
**[docs/architecture/vscode.md](../architecture/vscode.md)**.

## Setup

Needs Node and pnpm (`research doctor` reports whether you have them).

```bash
research serve                       # the local daemon, loopback only, in the workspace
cd vscode && pnpm install            # dev tooling only; zero runtime dependencies
pnpm run compile                     # tsc --noEmit, then esbuild -> dist/extension.js
```

Press **F5** in VS Code with `vscode/` open: the Extension Development Host starts with the
extension loaded. Open the workspace containing `.research/` in that window.

To install it into a normal VS Code instead:

```bash
cd vscode && pnpm run package        # runs `npx @vscode/vsce package`; needs network
code --install-extension research-harness-0.1.0.vsix
```

## Settings

| setting | default | meaning |
|---|---|---|
| `researchHarness.daemonUrl` | `http://127.0.0.1:8765` | where `research serve` is listening |
| `researchHarness.tokenPath` | `.research/daemon-token` | the local token, relative to the workspace root or absolute |
| `researchHarness.webUrl` | `http://127.0.0.1:8765` | the cockpit, for `[Open Claim]` and `[Open Evidence]` |
| `researchHarness.manuscriptRoot` | *(empty)* | manuscript project root; empty means the workspace's `manuscript/` |
| `researchHarness.mainTex` | `main.tex` | entry point inside that root |
| `researchHarness.auditOnSave` | `true` | re-audit after a save |
| `researchHarness.auditDebounceMs` | `750` | how long to coalesce saves |

The token file is what makes the extension the researcher rather than an agent host.
Without it every read still works and every mutation comes back `permission_denied`, which
the extension reports with the fix. Print the path with `research token`.

## The same state from the CLI

Nothing the extension writes is private to it:

```bash
research claim show C0003
research manuscript anchors
research manuscript trace main.tex:23
research manuscript audit
```

Same Claim, same anchor, same findings — one canonical object, not a copy.

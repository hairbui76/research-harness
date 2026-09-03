/**
 * The Research Harness VS Code client (Roadmap Phase 16).
 *
 * The extension is a transport, one of the four the product has (Product 1), and it is
 * deliberately the smallest of them: it edits nothing canonical, stores nothing of its own,
 * and reaches the workspace only through named capabilities on the local daemon (ADR-004,
 * ADR-009). Everything it shows - the hover, the diagnostics, the trace - is the answer some
 * capability gave, which is what makes Gate P16 demonstrable rather than argued: the same
 * Claim, seen from the editor, the CLI, the Web cockpit, and an agent host, is one object.
 *
 * Activation is cheap. Nothing contacts the daemon until a LaTeX file is open or a command
 * runs, and a daemon that is not running degrades to a status-bar warning rather than an
 * error on every keystroke.
 */

import * as vscode from "vscode";

import { HarnessClient } from "./client/HarnessClient";
import { registerCommands, type CommandContext } from "./commands";
import { manuscriptFilePath, readSettings, readToken, CONFIG_SECTION } from "./config";
import { ManuscriptCodeActions, ManuscriptDiagnostics } from "./manuscript/diagnostics";
import { ClaimHoverProvider } from "./manuscript/hoverProvider";
import { ManuscriptService } from "./manuscript/service";

/** Language ids this extension attaches to; VS Code names LaTeX `latex`, some setups `tex`. */
const TEX_SELECTOR: vscode.DocumentSelector = [
  { language: "latex", scheme: "file" },
  { language: "tex", scheme: "file" },
];

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("Research Harness");
  const client = buildClient();
  const manuscript = new ManuscriptService(client);
  const diagnostics = new ManuscriptDiagnostics();
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  status.command = "researchHarness.showClaimUnderCursor";

  let clientRef = client;

  const refreshDiagnostics = async (options: { force?: boolean } = {}): Promise<void> => {
    const settings = readSettings();
    try {
      const report = await manuscript.audit({ force: options.force ?? true });
      const total = diagnostics.refresh(report, (relative) =>
        manuscriptFilePath(settings, relative),
      );
      output.appendLine(
        `[audit] ${report.sentences_checked} substantive sentences, ` +
          `${report.findings.length} findings, ${total} diagnostics placed`,
      );
    } catch (error) {
      diagnostics.clear();
      output.appendLine(`[audit] ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const commandContext: CommandContext = {
    get client() {
      return clientRef;
    },
    manuscript,
    output,
    refreshDiagnostics,
  };

  const refreshStatus = async (): Promise<void> => {
    try {
      const health = await clientRef.health();
      status.text = `$(beaker) ${health.project}`;
      status.tooltip = `Research Harness ${health.version} — ${health.capabilities} capabilities, review policy ${health.review_policy}\n${health.workspace}`;
      status.backgroundColor = undefined;
    } catch (error) {
      status.text = "$(beaker) harness offline";
      status.tooltip =
        `${error instanceof Error ? error.message : String(error)}\n` +
        "Start the daemon with `research serve`.";
      status.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
    }
    status.show();
  };

  // Re-reading settings is cheap; rebuilding the client is not, so it happens only when a
  // setting this extension owns actually changed.
  const onConfigChange = vscode.workspace.onDidChangeConfiguration((event) => {
    if (!event.affectsConfiguration(CONFIG_SECTION)) {
      return;
    }
    clientRef = buildClient();
    manuscript.setClient(clientRef);
    manuscript.invalidate();
    void refreshStatus();
    void refreshDiagnostics({ force: true });
  });

  const onSave = vscode.workspace.onDidSaveTextDocument((document) => {
    const settings = readSettings();
    if (!settings.auditOnSave || !isTex(document)) {
      return;
    }
    scheduleAudit(settings.auditDebounceMs, refreshDiagnostics);
  });

  context.subscriptions.push(
    output,
    status,
    diagnostics,
    onConfigChange,
    onSave,
    vscode.languages.registerHoverProvider(TEX_SELECTOR, new ClaimHoverProvider(manuscript)),
    vscode.languages.registerCodeActionsProvider(TEX_SELECTOR, new ManuscriptCodeActions(), {
      providedCodeActionKinds: ManuscriptCodeActions.providedCodeActionKinds,
    }),
    ...registerCommands(commandContext),
  );

  void refreshStatus();
  if (vscode.window.activeTextEditor && isTex(vscode.window.activeTextEditor.document)) {
    void refreshDiagnostics({ force: true });
  }
}

export function deactivate(): void {
  // Every disposable is registered on the extension context, so the only thing left is the
  // debounce timer; the extension holds no workspace state of its own by design.
  if (auditTimer !== undefined) {
    clearTimeout(auditTimer);
    auditTimer = undefined;
  }
}

function buildClient(): HarnessClient {
  const settings = readSettings();
  return new HarnessClient({
    baseUrl: settings.daemonUrl,
    readToken: () => readToken(readSettings()),
  });
}

function isTex(document: vscode.TextDocument): boolean {
  return (
    document.languageId === "latex" ||
    document.languageId === "tex" ||
    document.uri.fsPath.endsWith(".tex")
  );
}

let auditTimer: ReturnType<typeof setTimeout> | undefined;

/** Coalesce saves: a formatter that rewrites five files should cost one audit, not five. */
function scheduleAudit(delayMs: number, run: () => Promise<void>): void {
  if (auditTimer !== undefined) {
    clearTimeout(auditTimer);
  }
  auditTimer = setTimeout(() => {
    auditTimer = undefined;
    void run();
  }, Math.max(0, delayMs));
}

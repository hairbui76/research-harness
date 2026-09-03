/**
 * A hand-written stand-in for the `vscode` module, aliased in by `vitest.config.ts`.
 *
 * Only the API the unit tests exercise is here: positions and ranges, diagnostics, code
 * actions, and enough of `workspace`/`window` for modules to import without an extension
 * host. It is deliberately small - anything needing real editor behaviour belongs in the
 * optional `@vscode/test-electron` suite, not in a mock that would slowly become a second,
 * subtly different editor.
 */

export class Position {
  constructor(
    readonly line: number,
    readonly character: number,
  ) {}

  isBefore(other: Position): boolean {
    return this.line < other.line || (this.line === other.line && this.character < other.character);
  }

  translate(lineDelta = 0, characterDelta = 0): Position {
    return new Position(this.line + lineDelta, this.character + characterDelta);
  }
}

export class Range {
  readonly start: Position;
  readonly end: Position;

  constructor(start: Position, end: Position) {
    this.start = start;
    this.end = end;
  }

  get isEmpty(): boolean {
    return this.start.line === this.end.line && this.start.character === this.end.character;
  }
}

export class Selection extends Range {}

export class Uri {
  private constructor(
    readonly scheme: string,
    readonly fsPath: string,
  ) {}

  static file(fsPath: string): Uri {
    return new Uri("file", fsPath);
  }

  static parse(value: string): Uri {
    return new Uri(value.split(":")[0] ?? "file", value);
  }

  toString(): string {
    return `${this.scheme}://${this.fsPath}`;
  }
}

export enum DiagnosticSeverity {
  Error = 0,
  Warning = 1,
  Information = 2,
  Hint = 3,
}

export class Diagnostic {
  source: string | undefined;
  code: string | number | undefined;
  relatedInformation: unknown[] | undefined;

  constructor(
    public range: Range,
    public message: string,
    public severity: DiagnosticSeverity = DiagnosticSeverity.Error,
  ) {}
}

export class CodeActionKind {
  private constructor(readonly value: string) {}
  static readonly QuickFix = new CodeActionKind("quickfix");
}

export class WorkspaceEdit {
  readonly inserts: Array<{ uri: Uri; position: Position; text: string }> = [];

  insert(uri: Uri, position: Position, text: string): void {
    this.inserts.push({ uri, position, text });
  }
}

export class CodeAction {
  edit: WorkspaceEdit | undefined;
  command: { command: string; title: string; arguments?: unknown[] } | undefined;
  diagnostics: Diagnostic[] | undefined;

  constructor(
    readonly title: string,
    readonly kind?: CodeActionKind,
  ) {}
}

export class MarkdownString {
  isTrusted = false;
  constructor(public value = "") {}
}

export class Hover {
  constructor(
    readonly contents: MarkdownString,
    readonly range?: Range,
  ) {}
}

export class ThemeColor {
  constructor(readonly id: string) {}
}

export class EventEmitter<T> {
  private listeners: Array<(value: T) => void> = [];
  readonly event = (listener: (value: T) => void): { dispose(): void } => {
    this.listeners.push(listener);
    return {
      dispose: () => {
        this.listeners = this.listeners.filter((item) => item !== listener);
      },
    };
  };
  fire(value: T): void {
    for (const listener of [...this.listeners]) {
      listener(value);
    }
  }
}

/** A `TextDocument` good enough for offset arithmetic and line ranges. */
export class FakeTextDocument {
  readonly uri: Uri;
  readonly languageId: string;
  private readonly lines: string[];

  constructor(fsPath: string, private readonly content: string, languageId = "latex") {
    this.uri = Uri.file(fsPath);
    this.languageId = languageId;
    this.lines = content.split("\n");
  }

  get lineCount(): number {
    return this.lines.length;
  }

  getText(range?: Range): string {
    if (!range) {
      return this.content;
    }
    return this.content.slice(this.offsetAt(range.start), this.offsetAt(range.end));
  }

  lineAt(line: number): { text: string; range: Range } {
    const text = this.lines[line] ?? "";
    return {
      text,
      range: new Range(new Position(line, 0), new Position(line, text.length)),
    };
  }

  offsetAt(position: Position): number {
    let offset = 0;
    for (let index = 0; index < position.line && index < this.lines.length; index += 1) {
      offset += (this.lines[index] as string).length + 1;
    }
    return offset + position.character;
  }

  positionAt(offset: number): Position {
    let remaining = Math.max(0, Math.min(offset, this.content.length));
    for (let line = 0; line < this.lines.length; line += 1) {
      const length = (this.lines[line] as string).length;
      if (remaining <= length) {
        return new Position(line, remaining);
      }
      remaining -= length + 1;
    }
    const last = Math.max(0, this.lines.length - 1);
    return new Position(last, (this.lines[last] ?? "").length);
  }
}

/** Diagnostics recorded per file, so tests can assert what was published. */
export class FakeDiagnosticCollection {
  readonly entries = new Map<string, Diagnostic[]>();

  set(uri: Uri, diagnostics: Diagnostic[]): void {
    this.entries.set(uri.fsPath, diagnostics);
  }

  clear(): void {
    this.entries.clear();
  }

  dispose(): void {
    this.entries.clear();
  }
}

/** Settings the tests can rewrite between cases. */
export const configurationValues = new Map<string, unknown>();

export const workspace = {
  workspaceFolders: undefined as Array<{ uri: Uri }> | undefined,
  textDocuments: [] as FakeTextDocument[],
  getConfiguration(section: string) {
    return {
      get<T>(key: string): T | undefined {
        return configurationValues.get(`${section}.${key}`) as T | undefined;
      },
    };
  },
  onDidSaveTextDocument(): { dispose(): void } {
    return { dispose() {} };
  },
  onDidChangeConfiguration(): { dispose(): void } {
    return { dispose() {} };
  },
};

export const window = {
  activeTextEditor: undefined as unknown,
  createOutputChannel() {
    return {
      lines: [] as string[],
      appendLine(line: string) {
        this.lines.push(line);
      },
      show() {},
      dispose() {},
    };
  },
  createStatusBarItem() {
    return { text: "", tooltip: "", command: "", backgroundColor: undefined, show() {}, dispose() {} };
  },
  createTerminal() {
    return { show() {}, sendText() {}, dispose() {} };
  },
  showQuickPick: async () => undefined,
  showInputBox: async () => undefined,
  showInformationMessage: async () => undefined,
  showWarningMessage: async () => undefined,
  showErrorMessage: async () => undefined,
};

export const languages = {
  createDiagnosticCollection(): FakeDiagnosticCollection {
    return new FakeDiagnosticCollection();
  },
  registerHoverProvider(): { dispose(): void } {
    return { dispose() {} };
  },
  registerCodeActionsProvider(): { dispose(): void } {
    return { dispose() {} };
  },
};

export const commands = {
  registerCommand(): { dispose(): void } {
    return { dispose() {} };
  },
  executeCommand: async () => undefined,
};

export const env = {
  openExternal: async () => true,
};

export enum StatusBarAlignment {
  Left = 1,
  Right = 2,
}

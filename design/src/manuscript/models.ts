/**
 * Presentation view models for the manuscript workspace.
 *
 * These are the shapes the Web client maps daemon DTOs onto before rendering. Nothing
 * here knows how to compile, how to audit, or what a protected span means: the fields
 * describe what to draw, and the components draw it.
 */

import type { IconName } from '../primitives/Icon';
import type { StatusName } from '../primitives/Badge';
import { researchLabel, researchMeaning } from '../research/labels';

/** What kind of thing a row in the file tree is. `dir` is the only branch. */
export type FileKind = 'tex' | 'bib' | 'image' | 'pdf' | 'other' | 'dir';

export interface FileNode {
  /** Project-relative path; also the row's identity. */
  path: string;
  /** Display name — usually the last path segment. */
  name: string;
  kind: FileKind;
  children?: FileNode[];
  /** Edited since the last save. Rendered as text, never as colour alone. */
  dirty?: boolean;
  /** Changed on disk under an unsaved edit. */
  conflict?: boolean;
  /** Bytes, when the host knows. */
  size?: number;
}

export interface EditorFrameState {
  /** Project-relative path of the open file; absent when nothing is open. */
  path?: string;
  dirty: boolean;
  /** Present when the file changed on disk under an unsaved edit. */
  conflict?: { message: string };
  readOnly?: boolean;
  readOnlyReason?: string;
  cursor?: { line: number; column: number };
}

export type BuildStatus = 'idle' | 'running' | 'succeeded' | 'failed' | 'timed_out' | 'unavailable';

export interface BuildModel {
  buildId?: string;
  status: BuildStatus;
  /** The compiler that actually ran, e.g. `latexmk -pdf`. */
  engine?: string;
  startedAt?: string;
  finishedAt?: string;
  /** The PDF for the current source. `stale` means the newest build failed. */
  pdf?: { url: string; stale: boolean; producedAt: string };
  /** The newest PDF that did compile, kept across later failures. */
  lastGood?: { url: string; producedAt: string };
  synctex: 'available' | 'unavailable';
  synctexReason?: string;
  /** Shown when the toolchain is missing; never a reason to touch the source. */
  setupGuidance?: string;
}

export type DiagnosticSeverity = 'error' | 'warning' | 'info';

export interface DiagnosticModel {
  id: string;
  severity: DiagnosticSeverity;
  file?: string;
  line?: number;
  column?: number;
  message: string;
  /** Compiler code such as `Undefined control sequence`. */
  code?: string;
  source: 'compiler';
}

/**
 * A scientific audit finding. Deliberately a different type from `DiagnosticModel`: a
 * document can compile and fail audit, or pass audit and fail to compile, and the
 * interface never merges the two lists.
 */
export interface AuditFindingModel {
  id: string;
  /** e.g. `unregistered_claim`, `citation_mismatch`, `stale_claim`. */
  kind: string;
  severity: DiagnosticSeverity;
  file?: string;
  line?: number;
  /**
   * The manuscript's own sentence, verbatim — the thing the finding is about.
   *
   * A finding card opens with it, so a researcher reads their own prose before reading a
   * verdict on it. Absent for a finding no single sentence produced.
   */
  sentence?: string;
  message: string;
  claim?: { id: string; label?: string };
  anchor?: { id: string };
  source: 'audit';
}

export type DiffLineKind = 'context' | 'added' | 'removed';

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
  /** Set when the line covers a citation, equation, number, unit, anchor or qualifier. */
  protected?: { kind: string; reason: string };
}

export interface DiffHunk {
  /** Unified-diff style header, e.g. `@@ -12,7 +12,8 @@`. */
  header?: string;
  lines: DiffLine[];
}

/** What a candidate does to the propositions in the source, in the reviewer's terms. */
export interface SemanticSummary {
  added: string[];
  removed: string[];
  weakened: string[];
  strengthened: string[];
}

export interface CandidateDiffModel {
  id: string;
  /** The assistant message this candidate came back from. */
  originMessageId?: string;
  /** The `Context used` receipt for that message. */
  contextPackId?: string;
  file: string;
  hunks: DiffHunk[];
  semanticSummary: SemanticSummary;
  auditStatus: 'pending' | 'passed' | 'failed';
  /** Why Apply is unavailable. Present means the button is disabled and says so. */
  blockedReason?: string;
}

const FILE_KIND_ICONS: Record<FileKind, IconName> = {
  tex: 'file-code',
  bib: 'book-marked',
  image: 'image',
  pdf: 'file-text',
  other: 'file',
  dir: 'folder',
};

/** Icon for a file kind; folders get the open glyph while they are expanded. */
export function fileKindIcon(kind: FileKind, expanded = false): IconName {
  if (kind === 'dir') return expanded ? 'folder-open' : 'folder';
  return FILE_KIND_ICONS[kind];
}

/** Human words for a file kind, used in the accessible name of a tree row. */
export const FILE_KIND_LABELS: Record<FileKind, string> = {
  tex: 'LaTeX source',
  bib: 'Bibliography',
  image: 'Image',
  pdf: 'PDF',
  other: 'File',
  dir: 'Folder',
};

export const BUILD_STATUS_META: Record<
  BuildStatus,
  { label: string; icon: IconName; tone: 'neutral' | 'info' | 'success' | 'warning' | 'error' }
> = {
  idle: { label: 'Not compiled yet', icon: 'circle-dashed', tone: 'neutral' },
  running: { label: 'Compiling', icon: 'loader', tone: 'info' },
  succeeded: { label: 'Compiled', icon: 'circle-check', tone: 'success' },
  failed: { label: 'Compilation failed', icon: 'alert-circle', tone: 'error' },
  timed_out: { label: 'Compilation timed out', icon: 'clock', tone: 'error' },
  unavailable: { label: 'No LaTeX toolchain', icon: 'wrench', tone: 'warning' },
};

/** Severity words for compiler output. Kept distinct from the audit vocabulary below. */
export const DIAGNOSTIC_SEVERITY_META: Record<
  DiagnosticSeverity,
  { label: string; icon: IconName }
> = {
  error: { label: 'Error', icon: 'alert-circle' },
  warning: { label: 'Warning', icon: 'alert-triangle' },
  info: { label: 'Info', icon: 'info' },
};

/**
 * What an audit severity means for the manuscript, and the scientific status family it is
 * drawn in.
 *
 * Different words from the compiler's on purpose: a reader glancing at one list must never
 * mistake it for the other. The `status` is not decoration — a manuscript sentence that
 * cannot be carried by accepted state is a statement about scientific truth, so it takes a
 * scientific status palette and never a feedback tone (DESIGN.md). It is the same mapping
 * the severity hairline down the side of a finding has always used.
 */
export const AUDIT_SEVERITY_META: Record<
  DiagnosticSeverity,
  { label: string; status: StatusName; description: string }
> = {
  error: {
    label: 'Must fix',
    status: 'contested',
    description: 'Accepted state contradicts the manuscript here. It cannot ship as it stands.',
  },
  warning: {
    label: 'Review',
    status: 'candidate',
    description: 'A researcher has to decide about this before the manuscript ships.',
  },
  info: {
    label: 'Note',
    status: 'qualified',
    description: 'Worth knowing. It does not stop the manuscript shipping.',
  },
};

/**
 * The words for one audit kind: the auditor's own name for it, and what it detects.
 *
 * The vocabulary itself lives with every other one the daemon sends
 * (`research/labels::MANUSCRIPT_FINDING_META`), which is what keeps this package's word for
 * a kind the same word the rest of the cockpit uses, and what gives a kind this build has
 * never met a readable phrase and the sentence the product states about the audit as a
 * whole rather than a `snake_case` token.
 */
export function describeAuditKind(kind: string): { label: string; description?: string } {
  const description = researchMeaning('manuscriptFinding', kind);
  return {
    label: researchLabel('manuscriptFinding', kind),
    ...(description === undefined ? {} : { description }),
  };
}

/**
 * A timestamp a snapshot can compare.
 *
 * `toLocaleString` depends on the host locale and time zone, which would make a DOM
 * snapshot and a compiler receipt disagree between machines, so the default is an
 * explicit UTC rendering. Surfaces that want the researcher's local format pass their own
 * formatter.
 */
export function formatTimestamp(iso: string | undefined): string {
  if (!iso) return 'unknown time';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  const pad = (value: number): string => String(value).padStart(2, '0');
  return (
    `${at.getUTCFullYear()}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())} ` +
    `${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())} UTC`
  );
}

/** Elapsed time between two ISO timestamps, or undefined when either is missing. */
export function formatDuration(startedAt?: string, finishedAt?: string): string | undefined {
  if (!startedAt || !finishedAt) return undefined;
  const start = new Date(startedAt).getTime();
  const end = new Date(finishedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return undefined;
  const seconds = Math.round((end - start) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`;
}

/** Flattened tree row, shared by `FileTree` and its tests. */
export interface FlatFileRow {
  node: FileNode;
  /** 1-based, matching `aria-level`. */
  level: number;
  /** 1-based position among its siblings, matching `aria-posinset`. */
  position: number;
  /** Number of siblings, matching `aria-setsize`. */
  setSize: number;
  parentPath?: string;
  hasChildren: boolean;
  expanded: boolean;
}

/** Depth-first walk that emits only the rows a researcher can currently see. */
export function flattenFileTree(
  nodes: readonly FileNode[],
  expanded: ReadonlySet<string>,
  level = 1,
  parentPath?: string,
): FlatFileRow[] {
  const rows: FlatFileRow[] = [];
  nodes.forEach((node, index) => {
    const hasChildren = node.kind === 'dir' && (node.children?.length ?? 0) > 0;
    const isExpanded = hasChildren && expanded.has(node.path);
    rows.push({
      node,
      level,
      position: index + 1,
      setSize: nodes.length,
      ...(parentPath === undefined ? {} : { parentPath }),
      hasChildren,
      expanded: isExpanded,
    });
    if (isExpanded && node.children) {
      rows.push(...flattenFileTree(node.children, expanded, level + 1, node.path));
    }
  });
  return rows;
}

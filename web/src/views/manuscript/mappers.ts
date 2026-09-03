/**
 * Daemon DTOs onto the Design System's manuscript view models.
 *
 * Everything here is presentation. No function decides whether a build is usable, whether
 * a candidate may be applied, or what an audit finding means — the daemon answered all
 * three, and these map its answers onto `FileNode`, `BuildModel`, `DiagnosticModel`,
 * `AuditFindingModel` and `CandidateDiffModel` so the package can draw them.
 *
 * Two things the wire does not carry are assembled here on purpose, and both are shape
 * rather than judgement: the file *tree* (`manuscript.files` answers a flat list, and the
 * directories are its path segments) and the `@@` hunk header (a Python property, so it is
 * not in the response model).
 */
import type {
  AuditFindingModel,
  BuildModel,
  BuildStatus,
  CandidateDiffModel,
  DiagnosticModel,
  DiagnosticSeverity,
  DiffHunk,
  DiffLine,
  FileKind,
  FileNode,
  SemanticSummary,
} from '@research-harness/design';
import type {
  BuildView,
  CompileDiagnostic,
  ManuscriptAuditFinding,
  ManuscriptFile,
  PdfLocation,
  ProtectedSpan,
  ProtectedViolation,
  PropositionChange,
  SuggestionCandidate,
  SuggestionDiffHunk,
  SuggestionDiffLine,
} from '../../api/dto';

// -- files ------------------------------------------------------------------------------

/** What a file's state is in the researcher's buffers, for the tree's written markers. */
export interface FileMarkers {
  dirty?: boolean;
  conflict?: boolean;
}

/**
 * `ManuscriptFileKind` onto the package's `FileKind`.
 *
 * The daemon files every image-like suffix under `image`, `.pdf` included; the package
 * draws a PDF with its own glyph, so the extension picks it out again here.
 */
export function fileKindOf(file: Pick<ManuscriptFile, 'path' | 'kind'>): FileKind {
  if (file.kind === 'image' && file.path.toLowerCase().endsWith('.pdf')) return 'pdf';
  return file.kind;
}

interface MutableNode {
  node: FileNode;
  children: Map<string, MutableNode>;
}

function directoryNode(path: string, name: string): MutableNode {
  return { node: { path, name, kind: 'dir', children: [] }, children: new Map() };
}

/** Directories before files, then by name, so the tree reads the same on every machine. */
function byKindThenName(left: FileNode, right: FileNode): number {
  if (left.kind === 'dir' && right.kind !== 'dir') return -1;
  if (left.kind !== 'dir' && right.kind === 'dir') return 1;
  return left.name.localeCompare(right.name);
}

function collapse(entry: MutableNode): FileNode {
  if (entry.node.kind !== 'dir') return entry.node;
  const children = [...entry.children.values()].map(collapse).sort(byKindThenName);
  // A folder wearing its descendants' markers is what stops a collapsed branch hiding an
  // unsaved file; the leaf still carries its own.
  const dirty = children.some((child) => child.dirty);
  const conflict = children.some((child) => child.conflict);
  return {
    ...entry.node,
    children,
    ...(dirty ? { dirty: true } : {}),
    ...(conflict ? { conflict: true } : {}),
  };
}

/**
 * The flat file list as the tree a researcher opens files from.
 *
 * `markers` is keyed by the same project-relative path the daemon uses, so a buffer's
 * unsaved or conflicted state reaches the row without the tree knowing what a buffer is.
 */
export function fileTreeFrom(
  files: readonly ManuscriptFile[],
  markers: Readonly<Record<string, FileMarkers>> = {},
): FileNode[] {
  const root = directoryNode('', '');
  for (const file of files) {
    const segments = file.path.split('/').filter(Boolean);
    const name = segments.pop();
    if (name === undefined) continue;
    let parent = root;
    let prefix = '';
    for (const segment of segments) {
      prefix = prefix ? `${prefix}/${segment}` : segment;
      const existing = parent.children.get(segment);
      const directory = existing ?? directoryNode(prefix, segment);
      if (!existing) parent.children.set(segment, directory);
      parent = directory;
    }
    const marker = markers[file.path] ?? {};
    parent.children.set(name, {
      node: {
        path: file.path,
        name,
        kind: fileKindOf(file),
        size: file.size_bytes,
        ...(marker.dirty ? { dirty: true } : {}),
        ...(marker.conflict ? { conflict: true } : {}),
      },
      children: new Map(),
    });
  }
  return collapse(root).children ?? [];
}

// -- the build --------------------------------------------------------------------------

/** Flags the engine actually ran with, minus the argv noise a reader cannot act on. */
function engineLine(view: BuildView): string | undefined {
  const result = view.result;
  if (!result) return view.toolchain.selected?.engine;
  const flags = result.args
    .slice(1)
    .filter(
      (arg) =>
        arg.startsWith('-') && arg !== '--outdir' && !arg.includes('/') && !arg.includes('\\'),
    );
  return [result.engine, ...flags].join(' ');
}

/**
 * The build's status, in the package's vocabulary.
 *
 * `unavailable` is decided by the toolchain rather than by a failed call: `manuscript.build`
 * is a read that answers for a workspace with no engine at all, so the workspace can say
 * "no LaTeX toolchain" and show the setup guidance without ever starting a compile that
 * would be refused (LaTeX spec §9).
 */
export function buildStatusOf(view: BuildView | null, compiling: boolean): BuildStatus {
  if (compiling) return 'running';
  if (!view) return 'idle';
  if (!view.toolchain.selected) return 'unavailable';
  if (view.status === 'succeeded' || view.status === 'failed' || view.status === 'timed_out') {
    return view.status;
  }
  return 'idle';
}

/** The reason SyncTeX is unavailable, in the daemon's own words; never a guess. */
export function synctexReasonOf(view: BuildView | null): string | undefined {
  if (!view || view.synctex_available) return undefined;
  return view.synctex_detail ?? readableReason(view.synctex_reason ?? undefined);
}

/** `unsupported_format` -> `unsupported format`, for the enum with no detail beside it. */
function readableReason(reason: string | undefined): string | undefined {
  if (!reason) return undefined;
  return reason.replace(/_+/g, ' ');
}

export interface BuildModelOptions {
  compiling: boolean;
  /** Where the bytes of the PDF being shown came from; used only for the model's `url`. */
  pdfUrl?: string;
  lastGoodUrl?: string;
}

/**
 * `BuildView` onto `BuildModel`.
 *
 * `pdf` is set only when this build produced one of its own. When it did not and there is a
 * last good build, only `lastGood` is set, which is exactly how `PdfPreview` decides to
 * keep the older document on screen under its stale banner — the failure keeps a PDF to
 * read, labelled honestly (LaTeX spec §5).
 */
export function buildModelFrom(
  view: BuildView | null,
  options: BuildModelOptions,
): BuildModel {
  const status = buildStatusOf(view, options.compiling);
  const guidance = view?.guidance.join(' ') ?? undefined;
  const reason = synctexReasonOf(view);
  return {
    ...(view?.build_id ? { buildId: view.build_id } : {}),
    status,
    ...(view ? withDefined('engine', engineLine(view)) : {}),
    ...(view?.result ? { startedAt: view.result.started_at, finishedAt: view.result.finished_at } : {}),
    ...(view?.pdf && view.result
      ? {
          pdf: {
            url: options.pdfUrl ?? '',
            stale: view.pdf_stale,
            producedAt: view.result.finished_at,
          },
        }
      : {}),
    ...(view?.last_good
      ? {
          lastGood: {
            url: options.lastGoodUrl ?? '',
            producedAt: view.last_good.compiled_at,
          },
        }
      : {}),
    synctex: view?.synctex_available ? 'available' : 'unavailable',
    ...withDefined('synctexReason', reason),
    ...(guidance ? { setupGuidance: guidance } : {}),
  };
}

function withDefined<K extends string, V>(key: K, value: V | undefined): Record<K, V> | object {
  return value === undefined ? {} : ({ [key]: value } as Record<K, V>);
}

// -- the two lists ----------------------------------------------------------------------

/**
 * Compiler diagnostics.
 *
 * Deliberately a different mapper from the audit one below, producing a different type: a
 * document can compile and fail its audit, and the two lists never merge (LaTeX spec §7).
 */
export function diagnosticsFrom(view: BuildView | null): DiagnosticModel[] {
  return (view?.diagnostics ?? []).map((diagnostic, index) =>
    diagnosticFrom(diagnostic, `compiler-${index}`),
  );
}

function diagnosticFrom(diagnostic: CompileDiagnostic, id: string): DiagnosticModel {
  return {
    id,
    severity: diagnostic.severity,
    message: diagnostic.message,
    ...(diagnostic.file ? { file: diagnostic.file } : {}),
    ...(diagnostic.line ? { line: diagnostic.line } : {}),
    ...(diagnostic.code ? { code: diagnostic.code } : {}),
    source: 'compiler',
  };
}

/** `FindingSeverity` and the package's `DiagnosticSeverity` share three words. */
function auditSeverity(severity: string): DiagnosticSeverity {
  return severity === 'error' || severity === 'info' ? severity : 'warning';
}

/** Scientific audit findings, placed by their own structured `location` (Product 30.3). */
export function auditFindingsFrom(
  findings: readonly ManuscriptAuditFinding[],
  idPrefix = 'audit',
): AuditFindingModel[] {
  return findings.map((finding, index) => {
    const location = finding.location ?? undefined;
    const anchor = finding.anchor ?? undefined;
    const file = location?.file ?? anchor?.file;
    const line = location?.line_start ?? anchor?.line_start;
    const claim = anchor?.claim ?? (finding.related ?? []).find((id) => /^C\d+$/.test(id));
    return {
      id: `${idPrefix}-${index}`,
      kind: finding.kind,
      severity: auditSeverity(finding.severity),
      message: finding.message,
      ...(file ? { file } : {}),
      ...(line ? { line } : {}),
      ...(claim ? { claim: { id: claim } } : {}),
      // A `ManuscriptAnchor` is a tracked object with no id of its own; `file:line` is the
      // key the anchor store and `AnchorImpact.anchor_key` both use.
      ...(anchor ? { anchor: { id: `${anchor.file}:${anchor.line_start}` } } : {}),
      source: 'audit',
    } satisfies AuditFindingModel;
  });
}

/**
 * Where a finding was raised, from the finding's own `location`.
 *
 * The auditor also writes `"<file>:<line>: "` into the message, but a client that parsed
 * prose to place a finding would be recomputing something the daemon already answered —
 * and it cannot answer for a finding no sentence produced, which is when this says so.
 */
export function whereOf(finding: ManuscriptAuditFinding): string {
  const location = finding.location;
  if (!location) return 'whole project';
  const lines =
    location.line_end > location.line_start
      ? `${location.line_start}-${location.line_end}`
      : `${location.line_start}`;
  return `${location.file}:${lines}`;
}

// -- candidate diffs --------------------------------------------------------------------

/** `number_with_unit` -> `number with unit`, so the written marker reads as English. */
function spanLabel(kind: string): string {
  return kind.replace(/_+/g, ' ');
}

function violationFor(
  span: ProtectedSpan,
  violations: readonly ProtectedViolation[],
): ProtectedViolation | undefined {
  return violations.find(
    (violation) =>
      violation.kind === span.kind &&
      (violation.before === span.text || violation.after === span.text),
  );
}

/**
 * The protected span a diff line covers, if any.
 *
 * The daemon decided *what* is protected and *whether* the rewrite moved it; all that
 * happens here is placing its answer on the line whose text contains the span, so a
 * reviewer sees the citation, equation, number or unit marked where it actually sits.
 */
function protectedOn(
  line: SuggestionDiffLine,
  spans: readonly ProtectedSpan[],
  violations: readonly ProtectedViolation[],
): { kind: string; reason: string } | undefined {
  const span = spans.find((candidate) => candidate.text !== '' && line.text.includes(candidate.text));
  if (!span) return undefined;
  const label = spanLabel(span.kind);
  const violation = violationFor(span, violations);
  return {
    kind: label,
    reason: violation
      ? `This candidate changed a protected ${label}, which a style pass has no authority to do.`
      : `A protected ${label}: the rewrite has to keep it exactly as it is.`,
  };
}

function diffLineFrom(
  line: SuggestionDiffLine,
  spans: readonly ProtectedSpan[],
  violations: readonly ProtectedViolation[],
): DiffLine {
  const covered = protectedOn(line, spans, violations);
  return {
    kind: line.kind,
    text: line.text,
    ...(covered ? { protected: covered } : {}),
  };
}

/** `@@ -a,b +c,d @@`, which is a Python property and so absent from the response model. */
export function hunkHeader(hunk: SuggestionDiffHunk): string {
  return `@@ -${hunk.old_start},${hunk.old_count} +${hunk.new_start},${hunk.new_count} @@`;
}

function hunkFrom(
  hunk: SuggestionDiffHunk,
  spans: readonly ProtectedSpan[],
  violations: readonly ProtectedViolation[],
): DiffHunk {
  return {
    header: hunkHeader(hunk),
    lines: hunk.lines.map((line) => diffLineFrom(line, spans, violations)),
  };
}

/** A moved proposition, shown as the movement rather than only as the new words. */
function movement(change: PropositionChange): string {
  return `${change.before.text} → ${change.after.text}`;
}

function semanticSummaryFrom(candidate: SuggestionCandidate): SemanticSummary {
  const diff = candidate.semantic_diff;
  return {
    added: diff.added.map((proposition) => proposition.text),
    removed: diff.removed.map((proposition) => proposition.text),
    weakened: diff.weakened.map(movement),
    strengthened: diff.strengthened.map(movement),
  };
}

/**
 * Why Apply is unavailable, in the daemon's words wherever it gave any.
 *
 * `blocked_reason` is the daemon's verdict and comes first. The two additions state facts
 * the response carries but does not phrase — an already-applied candidate, and a rewriter
 * that proposed nothing — because `applicable` is a Python property and is not on the wire.
 */
export function blockedReasonOf(candidate: SuggestionCandidate): string | undefined {
  if (candidate.blocked_reason) return candidate.blocked_reason;
  if (candidate.applied) return 'This candidate has already been applied to the source.';
  if (candidate.original_text === candidate.proposed_text) {
    return 'The rewriter proposed no change to this passage, so there is nothing to apply.';
  }
  return undefined;
}

/** `SuggestionCandidate` onto the reviewable diff the package draws. */
export function candidateDiffFrom(candidate: SuggestionCandidate): CandidateDiffModel {
  const blocked = blockedReasonOf(candidate);
  return {
    id: candidate.candidate_id,
    ...(candidate.provenance.message_id ? { originMessageId: candidate.provenance.message_id } : {}),
    ...(candidate.provenance.context_pack_id
      ? { contextPackId: candidate.provenance.context_pack_id }
      : {}),
    file: candidate.file,
    hunks: candidate.hunks.map((hunk) =>
      hunkFrom(hunk, candidate.protected_spans, candidate.protected_violations),
    ),
    semanticSummary: semanticSummaryFrom(candidate),
    auditStatus: candidate.audit_status,
    ...(blocked ? { blockedReason: blocked } : {}),
  };
}

// -- coordinates and references ---------------------------------------------------------

/**
 * A SyncTeX rectangle in the space `PdfPage` draws in.
 *
 * `PdfLocation` is in PDF points from the page's *top* left; `PdfPage` takes `[x0, y0, x1,
 * y1]` in PDF user space, whose origin is the *bottom* left. The flip is about the page's
 * real height, read back from pdf.js, so a preview of A4 and a preview of US Letter are
 * both right.
 */
export function toUserSpaceRect(
  location: PdfLocation,
  pageHeightPt: number,
): [number, number, number, number] {
  return [
    location.x,
    pageHeightPt - (location.y + location.height),
    location.x + location.width,
    pageHeightPt - location.y,
  ];
}

/** The same flip the other way: a point pdf.js reported, as SyncTeX wants to be asked. */
export function toSynctexPoint(
  x: number,
  y: number,
  pageHeightPt: number,
): { x: number; y: number } {
  return { x, y: pageHeightPt - y };
}

/**
 * A reference to one place in the manuscript, for use in conversation.
 *
 * `rh://manuscript/<file>?line=<n>`. The path segments are encoded individually so the
 * separators survive and the reference stays readable in a message.
 */
export function manuscriptReference(file: string, line: number): string {
  const path = file.split('/').map(encodeURIComponent).join('/');
  return `rh://manuscript/${path}?line=${line}`;
}

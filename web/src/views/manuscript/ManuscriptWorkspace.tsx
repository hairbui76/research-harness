/**
 * The manuscript workspace (PRODUCT §30, §42 P; LaTeX spec §3–§9).
 *
 * Files, source, a real PDF and a collapsible audit inspector, composed from the Design
 * System's `ManuscriptWorkspace` over this client's CodeMirror and pdf.js adapters. Every
 * judgement on screen is the daemon's: which files exist, whether a save may land, what the
 * compiler said, what the audit found, whether SyncTeX can answer, and whether a candidate
 * may reach the source. This route decides layout and nothing else.
 *
 * Four rules are worth stating because the code is arranged around them:
 *
 * *A save is an act.* Edits stay local until `Mod-S` or the Save button, and a save that
 * meets a changed file on disk is refused, not merged — the banner offers a reload or a
 * re-read that keeps the researcher's text and checks the *next* save against what is on
 * disk now (§4).
 *
 * *A failure keeps the last good PDF.* The preview shows it, labelled stale and timestamped,
 * while the diagnostics describe the source as it is now (§5).
 *
 * *The two lists never merge.* Compiler diagnostics and scientific findings are separate
 * lists with separate words and separate counts (§7).
 *
 * *Unsaved work survives everything.* A compile, a failed compile, a narrow-layout tab
 * switch: none of them touches a buffer (§9).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Button,
  CandidateDiff,
  Dialog,
  DialogBody,
  DialogHeader,
  FileTree,
  ManuscriptWorkspace as WorkspaceFrame,
  useToast,
} from '@research-harness/design';
import type { EditorFrameState, ManuscriptView, PaneSizes } from '@research-harness/design';
import type { CursorPosition, LatexEditorHandle } from '../../editor';
import { ErrorBox, Loading } from '../../components/Feedback';
import { useProjectPaths } from '../../app/projectPaths';
import { useSession } from '../../app/session';
import { AuditPane } from './AuditPane';
import { EditorPane } from './EditorPane';
import { PreviewPane } from './PreviewPane';
import { SuggestDialog } from './SuggestDialog';
import {
  auditFindingsFrom,
  buildModelFrom,
  candidateDiffFrom,
  diagnosticsFrom,
  fileTreeFrom,
  manuscriptReference,
  synctexReasonOf,
} from './mappers';
import { useBuild } from './useBuild';
import { useManuscriptFiles } from './useManuscriptFiles';
import { useSuggestion } from './useSuggestion';
import { useSynctex } from './useSynctex';

const COLUMN_KEY = 'rh.manuscript.columns';
const ROW_KEY = 'rh.manuscript.rows';
const INSPECTOR_KEY = 'rh.manuscript.inspector';

/**
 * A little state the browser remembers.
 *
 * Pane sizes and a collapsed inspector are conveniences, so every access is guarded: a
 * private window, a browser that refuses site data, or a stored value from an older layout
 * all fall back to the default rather than taking the workspace down with them.
 */
function usePersisted<T>(key: string, fallback: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      return stored === null ? fallback : (JSON.parse(stored) as T);
    } catch {
      return fallback;
    }
  });
  const store = useCallback(
    (next: T) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // Remembering the layout is not worth failing a render for.
      }
    },
    [key],
  );
  return [value, store];
}

/** What each answer to a conflict does, said before the researcher has to choose. */
function conflictMessage(refusal: string, path: string): string {
  return (
    `${refusal} Reload from disk replaces what you typed with the file as it is now. ` +
    `Keep mine re-reads ${path} only to learn its new hash: your text stays in the editor, ` +
    `and your next save is checked against the version on disk now.`
  );
}

export function ManuscriptPage() {
  const { client, canMutate, mutationBlockedReason } = useSession();
  const { href } = useProjectPaths();
  const { toast } = useToast();
  const navigate = useNavigate();

  const files = useManuscriptFiles(client);
  const build = useBuild(client);
  const suggestion = useSuggestion(client);
  const synctex = useSynctex(client, {
    buildId: build.view?.build_id ?? null,
    available: build.view?.synctex_available ?? false,
    reason: synctexReasonOf(build.view),
  });

  const editorRef = useRef<LatexEditorHandle | null>(null);
  const [cursor, setCursor] = useState<CursorPosition>({ line: 1, column: 1 });
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [suggestRange, setSuggestRange] = useState({ start: 1, end: 1 });
  const [syncLabel, setSyncLabel] = useState<string | undefined>(undefined);

  const [columnSizes, setColumnSizes] = usePersisted<PaneSizes>(COLUMN_KEY, {});
  const [rowSizes, setRowSizes] = usePersisted<PaneSizes>(ROW_KEY, {});
  const [inspectorOpen, setInspectorOpen] = usePersisted<boolean>(INSPECTOR_KEY, true);

  /*
   * Which view the narrow layout is showing.
   *
   * A workspace too narrow for three columns gives the source, the PDF and the inspector
   * turns over the same area, and the route holds that choice because the route is where
   * the acts that imply one happen: opening a file, following a diagnostic to its line,
   * and jumping from the cursor to the page it set. Each of those has always put its
   * answer in front of the researcher, and it still has to when the answer is behind a
   * tab. The wide layout ignores it: nothing there takes turns.
   */
  const [view, setView] = useState<ManuscriptView>('editor');

  const active = files.active;
  const entryFile = files.tree?.entry_file ?? 'main.tex';

  // `openAt` may have to wait for a file to load before the cursor can be put on a line, so
  // the request is held here and flushed when the editor is showing that file.
  const pending = useRef<{ file: string; line: number; column?: number } | null>(null);
  const activeRef = useRef(active);
  activeRef.current = active;

  const flushPending = useCallback((): void => {
    const target = pending.current;
    if (!target) return;
    if (activeRef.current?.path !== target.file) return;
    pending.current = null;
    editorRef.current?.goTo(target.line, target.column);
  }, []);

  useEffect(() => {
    flushPending();
  }, [flushPending, active]);

  const openFile = files.open;
  const openAt = useCallback(
    async (file: string, line: number, column?: number): Promise<void> => {
      pending.current = { file, line, ...(column === undefined ? {} : { column }) };
      // A line is being pointed at, so the source is what has to be on screen.
      setView('editor');
      await openFile(file);
      flushPending();
    },
    [flushPending, openFile],
  );

  // -- the first file --------------------------------------------------------
  //
  // The entry file is opened once, when the tree arrives. Anything the researcher opens
  // afterwards stays open: this must never reach past them and change the file on screen.
  const openedEntry = useRef(false);

  /* Deep links into the manuscript (task W3) ------------------------------------------
   *
   * `rh://manuscript/main.tex?line=120` resolves to `/manuscript?file=main.tex&line=120`
   * (`views/conversation/references/deepLinks.ts`), which is this read: open the file the
   * query names and put the cursor on the line. It happens once per address, so a later
   * navigation inside the workspace is never fought over, and it claims the entry-file slot
   * so the tree arriving afterwards does not replace the file the link asked for. */
  const [params] = useSearchParams();
  const linkedFile = params.get('file');
  const linkedLine = params.get('line');
  const followed = useRef<string | null>(null);
  useEffect(() => {
    if (!linkedFile) return;
    const address = `${linkedFile}#${linkedLine ?? ''}`;
    if (followed.current === address) return;
    followed.current = address;
    openedEntry.current = true;
    const line = Number.parseInt(linkedLine ?? '', 10);
    void openAt(linkedFile, Number.isFinite(line) && line > 0 ? line : 1);
  }, [linkedFile, linkedLine, openAt]);

  const tree = files.tree;
  useEffect(() => {
    if (openedEntry.current || !tree) return;
    const entry = tree.files.find((file) => file.path === tree.entry_file);
    const first = entry ?? tree.files.find((file) => file.kind === 'tex');
    if (!first) return;
    openedEntry.current = true;
    void openFile(first.path);
  }, [openFile, tree]);

  // -- models ----------------------------------------------------------------

  const nodes = useMemo(
    () => fileTreeFrom(files.tree?.files ?? [], files.markers),
    [files.markers, files.tree],
  );
  const expanded = useMemo(
    () => nodes.filter((node) => node.kind === 'dir').map((node) => node.path),
    [nodes],
  );

  const buildModel = useMemo(
    () =>
      buildModelFrom(build.view, {
        compiling: build.compiling,
        ...(build.pdfBuildId ? { pdfUrl: client.manuscriptBuildPdfUrl(build.pdfBuildId) } : {}),
        lastGoodUrl: client.manuscriptBuildPdfUrl('last-good'),
      }),
    [build.compiling, build.pdfBuildId, build.view, client],
  );
  const diagnostics = useMemo(() => diagnosticsFrom(build.view), [build.view]);
  const findings = useMemo(
    () => auditFindingsFrom(build.view?.audit_findings ?? []),
    [build.view],
  );

  const dirty = Boolean(active && active.text !== active.saved);
  const frameState: EditorFrameState = {
    ...(active ? { path: active.path } : {}),
    dirty,
    ...(active?.conflict
      ? { conflict: { message: conflictMessage(active.conflict, active.path) } }
      : {}),
    ...(canMutate ? {} : { readOnly: true, readOnlyReason: mutationBlockedReason ?? undefined }),
    cursor,
  };

  // -- actions ---------------------------------------------------------------

  const save = useCallback(async (): Promise<void> => {
    if (!canMutate) return;
    const saved = await files.save();
    if (!saved) return;
    toast({ tone: 'success', title: 'Saved' });
    // The audit is about the manuscript as it is *now*, so a save can move findings even
    // though it starts no compiler.
    build.refresh();
  }, [build, canMutate, files, toast]);

  const jumpToPdf = useCallback((): void => {
    if (!active) return;
    setSyncLabel(`${active.path}:${cursor.line}`);
    // The jump's whole point is the page it lands on, so the preview comes forward with it.
    setView('preview');
    void synctex.forward(active.path, cursor.line);
  }, [active, cursor.line, synctex]);

  const jumpToSource = useCallback(
    async (page: number, x: number, y: number) => {
      const source = await synctex.inverse(page, x, y);
      if (source) await openAt(source.file, source.line, source.column ?? undefined);
      return source;
    },
    [openAt, synctex],
  );

  const copyReference = useCallback((): void => {
    if (!active) return;
    const reference = manuscriptReference(active.path, cursor.line);
    // A browser that refuses the clipboard still gets the reference, to copy by hand.
    const show = (title: string): void => {
      toast({ tone: title === 'Reference copied' ? 'success' : 'info', title, description: reference });
    };
    try {
      void navigator.clipboard
        .writeText(reference)
        .then(() => show('Reference copied'))
        .catch(() => show('Copy this reference'));
    } catch {
      show('Copy this reference');
    }
  }, [active, cursor.line, toast]);

  const openSuggest = useCallback((): void => {
    if (!active) return;
    const view = editorRef.current?.getView();
    if (view) {
      const { from, to } = view.state.selection.main;
      setSuggestRange({
        start: view.state.doc.lineAt(from).number,
        end: view.state.doc.lineAt(to).number,
      });
    } else {
      setSuggestRange({ start: cursor.line, end: cursor.line });
    }
    setSuggestOpen(true);
  }, [active, cursor.line]);

  const candidate = suggestion.candidate;
  const candidateBuffer = candidate ? files.markers[candidate.file] : undefined;
  const diffModel = useMemo(() => {
    if (!candidate) return null;
    const model = candidateDiffFrom(candidate);
    // Two reasons this client adds, both about *this* window rather than the candidate:
    // an agent host may propose but not apply, and applying over an unsaved buffer would
    // throw the researcher's own words away.
    const blocked =
      model.blockedReason ??
      (canMutate ? undefined : (mutationBlockedReason ?? undefined)) ??
      (candidateBuffer?.dirty
        ? `Save or discard your unsaved changes to ${candidate.file} first; applying would overwrite them.`
        : undefined);
    return { ...model, ...(blocked ? { blockedReason: blocked } : {}) };
  }, [candidate, canMutate, candidateBuffer?.dirty, mutationBlockedReason]);

  const applyCandidate = useCallback(async (): Promise<void> => {
    if (!candidate) return;
    const buffer = files.activePath === candidate.file ? active : null;
    const applied = await suggestion.apply(buffer?.hash ?? null);
    if (!applied) return;
    // `AppliedSuggestion.snapshot` is the file the daemon wrote, read back under the same
    // lock — the re-read, without a second round trip that could see a third writer.
    files.adopt(applied.snapshot);
    build.refresh();
    toast({
      tone: 'success',
      title: 'Candidate applied',
      description:
        applied.anchors_to_revalidate.length > 0
          ? `${applied.anchors_to_revalidate.length} anchor(s) need revalidating.`
          : undefined,
    });
  }, [active, build, candidate, files, suggestion, toast]);

  // -- render ----------------------------------------------------------------

  if (files.treeError) {
    return (
      <div className="rh-web-stack">
        <ErrorBox error={files.treeError} retry={files.reloadTree} />
      </div>
    );
  }
  if (!files.tree) {
    return (
      <div className="rh-web-stack">
        <Loading what="the manuscript" />
      </div>
    );
  }

  return (
    <>
      <WorkspaceFrame
        view={view}
        onViewChange={setView}
        // `AuditPane` carries a strip of its own, so the tab that opens it is named for the
        // panel's role: two strips saying "Build and audit" one under the other would read
        // as a rendering fault rather than as a hierarchy.
        inspectorTabLabel="Inspector"
        columnSizes={columnSizes}
        onColumnSizesChange={setColumnSizes}
        rowSizes={rowSizes}
        onRowSizesChange={setRowSizes}
        inspectorOpen={inspectorOpen}
        onInspectorOpenChange={setInspectorOpen}
        toolbar={
          <>
            <h1 className="rh-text-h1">Manuscript</h1>
            <span className="rh-text-secondary">{`${files.tree.root}/${entryFile}`}</span>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              iconStart="sparkles"
              disabled={!active}
              onClick={openSuggest}
            >
              Suggest…
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              iconStart="link"
              disabled={!active}
              onClick={copyReference}
            >
              Copy reference
            </Button>
          </>
        }
        fileTree={
          <FileTree
            nodes={nodes}
            defaultExpanded={expanded}
            {...(files.activePath ? { selectedPath: files.activePath } : {})}
            onSelect={(path) => {
              setView('editor');
              void files.open(path);
            }}
            emptyDescription={`No files under ${files.tree.root}.`}
          />
        }
        editor={
          <EditorPane
            ref={editorRef}
            state={frameState}
            value={active?.text ?? null}
            {...(active ? { fileName: active.path } : {})}
            onChange={files.change}
            {...(canMutate ? { onSave: () => void save() } : {})}
            {...(canMutate ? { onCompile: () => void build.compile() } : {})}
            {...(active && synctex.available ? { onSyncForward: jumpToPdf } : {})}
            onCursorChange={setCursor}
            onReloadFromDisk={() => void files.reloadFromDisk()}
            onKeepMine={() => void files.keepMine()}
            synctex={synctex.available ? 'available' : 'unavailable'}
            {...(synctex.reason === undefined ? {} : { synctexReason: synctex.reason })}
            saving={files.saving}
            compiling={build.compiling}
            {...(canMutate ? {} : { readOnlyReason: mutationBlockedReason ?? undefined })}
          />
        }
        preview={
          <PreviewPane
            build={buildModel}
            bytes={build.pdfBytes}
            loading={build.pdfLoading}
            error={build.pdfError}
            {...(build.pdfBuildId
              ? { fileUrl: client.manuscriptBuildPdfUrl(build.pdfBuildId) }
              : {})}
            locations={synctex.locations}
            syncPage={synctex.page}
            {...(syncLabel === undefined ? {} : { syncLabel })}
            inverseEnabled={synctex.available}
            onInverseSync={jumpToSource}
          />
        }
        inspector={
          <AuditPane
            build={buildModel}
            diagnostics={diagnostics}
            findings={findings}
            entryFile={entryFile}
            {...(build.view?.audit_unavailable_reason
              ? { auditUnavailableReason: build.view.audit_unavailable_reason }
              : {})}
            {...(build.compileError ? { compileError: build.compileError } : {})}
            onOpenSource={(file, line) => void openAt(file, line)}
            onNavigate={(target) => {
              if (target.kind === 'claim') {
                navigate(href(`/claims/${target.id}`));
                return;
              }
              const at = target.id.lastIndexOf(':');
              if (at > 0) void openAt(target.id.slice(0, at), Number(target.id.slice(at + 1)));
            }}
          />
        }
      />

      {/* Everything below is a decision the researcher opened; nothing here runs on its own. */}
      {files.openError ? (
        <p className="rh-visually-hidden" role="status">
          {files.openError}
        </p>
      ) : null}
      {files.saveError ? (
        <p className="rh-visually-hidden" role="status">
          {files.saveError}
        </p>
      ) : null}
      {synctex.note ? (
        <p className="rh-visually-hidden" role="status">
          {synctex.note}
        </p>
      ) : null}

      <SuggestDialog
        open={suggestOpen}
        onOpenChange={setSuggestOpen}
        file={active?.path ?? entryFile}
        lineStart={suggestRange.start}
        lineEnd={suggestRange.end}
        suggesting={suggestion.suggesting}
        error={suggestion.error}
        onSubmit={(request) => {
          void suggestion.suggest(request).then((staged) => {
            if (staged) setSuggestOpen(false);
          });
        }}
      />

      <Dialog
        open={diffModel !== null}
        onOpenChange={(open) => {
          if (!open) suggestion.reject();
        }}
        size="lg"
      >
        <DialogHeader>Candidate edit</DialogHeader>
        <DialogBody>
          {diffModel ? (
            <CandidateDiff
              diff={diffModel}
              applying={suggestion.applying}
              onApply={() => void applyCandidate()}
              onReject={suggestion.reject}
            />
          ) : null}
          {suggestion.error ? <ErrorBox error={suggestion.error} /> : null}
        </DialogBody>
      </Dialog>
    </>
  );
}

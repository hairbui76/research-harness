import { SourceEditorFrame } from './SourceEditorFrame';

const source = `\\section{Results}
Tolerance rose with acclimation temperature \\cite{smith2024}.
\\input{sections/results}`;

export const title = 'SourceEditorFrame';

export const specimens = [
  {
    name: 'Saved',
    render: () => (
      <div className="gallery-block">
        <SourceEditorFrame
          state={{ path: 'manuscript/main.tex', dirty: false, cursor: { line: 12, column: 1 } }}
          onSave={() => undefined}
          onCompile={() => undefined}
          onSyncForward={() => undefined}
        >
          <pre style={{ margin: 0, padding: 'var(--rh-space-3)' }}>{source}</pre>
        </SourceEditorFrame>
      </div>
    ),
  },
  {
    name: 'Unsaved changes, compiling',
    render: () => (
      <div className="gallery-block">
        <SourceEditorFrame
          state={{ path: 'manuscript/main.tex', dirty: true, cursor: { line: 120, column: 3 } }}
          compiling
          onSave={() => undefined}
          onCompile={() => undefined}
          onSyncForward={() => undefined}
        >
          <pre style={{ margin: 0, padding: 'var(--rh-space-3)' }}>{source}</pre>
        </SourceEditorFrame>
      </div>
    ),
  },
  {
    name: 'Conflicted, read-only, no SyncTeX',
    render: () => (
      <div className="gallery-block">
        <SourceEditorFrame
          state={{
            path: 'manuscript/sections/results.tex',
            dirty: true,
            conflict: { message: 'The file changed on disk while you were editing it.' },
            readOnly: true,
            readOnlyReason: 'the workspace is mounted read-only',
            cursor: { line: 4, column: 18 },
          }}
          synctex="unavailable"
          synctexReason="the last build produced no .synctex.gz"
          onSyncForward={() => undefined}
          onReloadFromDisk={() => undefined}
          onKeepMine={() => undefined}
        >
          <pre style={{ margin: 0, padding: 'var(--rh-space-3)' }}>{source}</pre>
        </SourceEditorFrame>
      </div>
    ),
  },
  {
    name: 'No file open',
    render: () => (
      <div className="gallery-block">
        <SourceEditorFrame state={{ dirty: false }} />
      </div>
    ),
  },
];

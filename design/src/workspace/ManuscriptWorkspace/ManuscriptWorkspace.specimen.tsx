import type { ReactElement, ReactNode } from 'react';
import { ManuscriptWorkspace } from './ManuscriptWorkspace';
import { FileTree } from '../../manuscript/FileTree';
import { SourceEditorFrame } from '../../manuscript/SourceEditorFrame';
import { PdfPreview } from '../../manuscript/PdfPreview';
import { CompilerStatus } from '../../manuscript/CompilerStatus';
import { DiagnosticsPanel } from '../../manuscript/DiagnosticsPanel';
import {
  diagnostics,
  failedBuild,
  files,
  findings,
} from '../../manuscript/manuscript.specimen-data';

function framed(node: ReactNode): ReactElement {
  return (
    <div
      className="gallery-block"
      style={{
        blockSize: '38rem',
        border: '1px solid var(--rh-border-subtle)',
        borderRadius: 'var(--rh-radius-card)',
        overflow: 'hidden',
      }}
    >
      {node}
    </div>
  );
}

const source = `\\section{Results}
Tolerance rose with acclimation temperature \\cite{smith2024}.
$T_{\\max} = 34.2\\,^{\\circ}\\mathrm{C}$`;

const parts = {
  fileTree: (
    <FileTree
      nodes={files}
      defaultExpanded={['manuscript']}
      selectedPath="manuscript/main.tex"
      onSelect={() => undefined}
      onRename={() => undefined}
      onDelete={() => undefined}
      onNewFile={() => undefined}
    />
  ),
  editor: (
    <SourceEditorFrame
      state={{ path: 'manuscript/main.tex', dirty: true, cursor: { line: 120, column: 3 } }}
      synctex="unavailable"
      synctexReason="the failing run wrote no .synctex.gz"
      onSave={() => undefined}
      onCompile={() => undefined}
      onSyncForward={() => undefined}
    >
      <pre style={{ margin: 0, padding: 'var(--rh-space-3)' }}>{source}</pre>
    </SourceEditorFrame>
  ),
  preview: <PdfPreview build={failedBuild} pageCount={12} onSearch={() => undefined} />,
  inspector: (
    <DiagnosticsPanel
      diagnostics={diagnostics}
      findings={findings}
      status={<CompilerStatus build={failedBuild} onCompile={() => undefined} />}
      onOpenSource={() => undefined}
      onNavigate={() => undefined}
    />
  ),
};

export const title = 'ManuscriptWorkspace';

export const specimens = [
  {
    name: 'Wide — files, source, PDF, with the audit inspector below',
    render: () => framed(<ManuscriptWorkspace narrow={false} {...parts} />),
  },
  {
    name: 'Audit inspector on the end instead of the bottom',
    render: () => framed(<ManuscriptWorkspace narrow={false} inspectorPlacement="end" {...parts} />),
  },
  {
    name: 'Inspector collapsed',
    render: () =>
      framed(<ManuscriptWorkspace narrow={false} defaultInspectorOpen={false} {...parts} />),
  },
  {
    name: 'Narrow — source and PDF become tabs, both panels stay mounted',
    render: () => framed(<ManuscriptWorkspace narrow {...parts} />),
  },
];

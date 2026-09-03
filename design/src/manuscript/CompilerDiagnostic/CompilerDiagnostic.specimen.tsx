import { CompilerDiagnosticList } from './CompilerDiagnostic';
import { diagnostics } from '../manuscript.specimen-data';

export const title = 'CompilerDiagnostic';

export const specimens = [
  {
    name: 'Grouped by file, openable',
    render: () => (
      <div className="gallery-block">
        <CompilerDiagnosticList diagnostics={diagnostics} onOpen={() => undefined} />
      </div>
    ),
  },
  {
    name: 'Read-only — the host cannot open a source position',
    render: () => (
      <div className="gallery-block">
        <CompilerDiagnosticList diagnostics={diagnostics} />
      </div>
    ),
  },
  {
    name: 'Clean build',
    render: () => (
      <div className="gallery-block">
        <CompilerDiagnosticList diagnostics={[]} />
      </div>
    ),
  },
];

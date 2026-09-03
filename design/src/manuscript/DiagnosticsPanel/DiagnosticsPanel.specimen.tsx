import { DiagnosticsPanel } from './DiagnosticsPanel';
import { CompilerStatus } from '../CompilerStatus';
import { diagnostics, failedBuild, findings, succeededBuild } from '../manuscript.specimen-data';

export const title = 'DiagnosticsPanel';

export const specimens = [
  {
    name: 'Both lists, under headings that never merge',
    render: () => (
      <div className="gallery-block">
        <DiagnosticsPanel
          diagnostics={diagnostics}
          findings={findings}
          status={<CompilerStatus build={failedBuild} onCompile={() => undefined} />}
          onOpenSource={() => undefined}
          onNavigate={() => undefined}
        />
      </div>
    ),
  },
  {
    name: 'Compiles cleanly, still fails the scientific audit',
    render: () => (
      <div className="gallery-block">
        <DiagnosticsPanel
          diagnostics={[]}
          findings={findings}
          status={<CompilerStatus build={succeededBuild} />}
          onOpenSource={() => undefined}
        />
      </div>
    ),
  },
  {
    name: 'Passes the audit, fails to compile',
    render: () => (
      <div className="gallery-block">
        <DiagnosticsPanel
          diagnostics={diagnostics}
          findings={[]}
          status={<CompilerStatus build={failedBuild} />}
          onOpenSource={() => undefined}
        />
      </div>
    ),
  },
];

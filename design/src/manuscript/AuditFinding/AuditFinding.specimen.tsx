import { AuditFindingList } from './AuditFinding';
import { findings } from '../manuscript.specimen-data';

export const title = 'AuditFinding';

export const specimens = [
  {
    name: 'Every kind, with its own severity words',
    render: () => (
      <div className="gallery-block">
        <AuditFindingList
          findings={findings}
          onOpen={() => undefined}
          onNavigate={() => undefined}
        />
      </div>
    ),
  },
  {
    name: 'An unregistered kind still renders',
    render: () => (
      <div className="gallery-block">
        <AuditFindingList
          findings={[
            {
              id: 'A9',
              kind: 'protected_span_changed',
              severity: 'error',
              file: 'manuscript/main.tex',
              line: 92,
              message: 'A candidate rewrote the citation \\cite{smith2024}.',
              source: 'audit',
            },
            {
              id: 'A10',
              kind: 'some_future_rule',
              severity: 'warning',
              message: 'A kind this package has never heard of is humanised, not dropped.',
              source: 'audit',
            },
          ]}
          onOpen={() => undefined}
        />
      </div>
    ),
  },
  {
    name: 'Nothing to answer for',
    render: () => (
      <div className="gallery-block">
        <AuditFindingList findings={[]} />
      </div>
    ),
  },
];

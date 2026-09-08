import { AuditFindingList } from './AuditFinding';
import { findings } from '../manuscript.specimen-data';

export const title = 'AuditFinding';

export const specimens = [
  {
    name: 'The sentence, what the audit found, and the one act it asks for',
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
    name: 'A finding with no sentence, and a kind this build has never met',
    render: () => (
      <div className="gallery-block">
        <AuditFindingList
          findings={[
            {
              id: 'A9',
              kind: 'unsupported_numeric',
              severity: 'error',
              file: 'manuscript/sections/results.tex',
              line: 92,
              sentence: 'Exfiltration recall rises from 0.42 to 0.61 on the held-out split.',
              message:
                "'0.61' is not measured by any accepted, source-observed Evidence behind C0041",
              claim: { id: 'C0041' },
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
          onNavigate={() => undefined}
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

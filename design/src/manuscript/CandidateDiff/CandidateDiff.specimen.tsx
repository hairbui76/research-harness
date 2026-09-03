import { CandidateDiff } from './CandidateDiff';
import { candidate } from '../manuscript.specimen-data';

export const title = 'CandidateDiff';

export const specimens = [
  {
    name: 'Audit passed — unified',
    render: () => (
      <div className="gallery-block">
        <CandidateDiff
          diff={candidate}
          onApply={() => undefined}
          onReject={() => undefined}
          onOpenOrigin={() => undefined}
        />
      </div>
    ),
  },
  {
    name: 'Side by side',
    render: () => (
      <div className="gallery-block">
        <CandidateDiff
          diff={candidate}
          defaultView="side-by-side"
          onApply={() => undefined}
          onReject={() => undefined}
          onOpenOrigin={() => undefined}
        />
      </div>
    ),
  },
  {
    name: 'Audit pending',
    render: () => (
      <div className="gallery-block">
        <CandidateDiff
          diff={{ ...candidate, auditStatus: 'pending' }}
          onApply={() => undefined}
          onReject={() => undefined}
        />
      </div>
    ),
  },
  {
    name: 'Blocked — a protected span changed',
    render: () => (
      <div className="gallery-block">
        <CandidateDiff
          diff={{
            ...candidate,
            auditStatus: 'failed',
            blockedReason:
              'The candidate rewrote a protected citation span. Apply stays unavailable until the citation is restored.',
          }}
          onApply={() => undefined}
          onReject={() => undefined}
        />
      </div>
    ),
  },
  {
    name: 'Wording only — no propositional change',
    render: () => (
      <div className="gallery-block">
        <CandidateDiff
          diff={{
            ...candidate,
            semanticSummary: { added: [], removed: [], weakened: [], strengthened: [] },
          }}
          onApply={() => undefined}
          onReject={() => undefined}
        />
      </div>
    ),
  },
];

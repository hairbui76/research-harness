import { useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import type { SessionSummary } from '../models';
import { SAMPLE_SESSIONS } from '../samples';
import { SessionList } from './SessionList';

export const title = 'SessionList';

const MANY: SessionSummary[] = Array.from({ length: 80 }, (_, index) => ({
  id: `CS${String(index + 1).padStart(4, '0')}`,
  title: `Session ${index + 1}`,
  updatedAt: '2026-09-01T10:00:00Z',
  messageCount: index + 1,
  visibility: index % 7 === 0 ? 'private' : 'project',
}));

function Live({ sessions }: { sessions: SessionSummary[] }): ReactElement {
  const [active, setActive] = useState(sessions[0]?.id ?? null);
  const [query, setQuery] = useState('');
  const [titles, setTitles] = useState<Record<string, string>>({});
  const shown = sessions
    .map((session) => ({ ...session, title: titles[session.id] ?? session.title }))
    .filter((session) => session.title.toLowerCase().includes(query.toLowerCase()));
  return (
    <div style={{ maxWidth: '22rem' }}>
      <SessionList
        sessions={shown}
        activeId={active}
        onSelect={setActive}
        query={query}
        onQueryChange={setQuery}
        onNewSession={() => undefined}
        onRename={(id, title) => setTitles((previous) => ({ ...previous, [id]: title }))}
      />
    </div>
  );
}

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  { name: 'A short history', render: () => <Live sessions={SAMPLE_SESSIONS} /> },
  { name: 'A long history — windowed', render: () => <Live sessions={MANY} /> },
  {
    name: 'Empty',
    render: () => (
      <div style={{ maxWidth: '22rem' }}>
        <SessionList sessions={[]} onNewSession={() => undefined} />
      </div>
    ),
  },
  {
    name: 'Loading',
    render: () => (
      <div style={{ maxWidth: '22rem' }}>
        <SessionList sessions={[]} loading />
      </div>
    ),
  },
];

import { useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { SAMPLE_REFERENCE_RESULTS } from '../samples';
import { ReferencePicker } from './ReferencePicker';

export const title = 'ReferencePicker';

function Live({ loading = false }: { loading?: boolean }): ReactElement {
  const [query, setQuery] = useState('');
  const results = SAMPLE_REFERENCE_RESULTS.filter((entity) =>
    `${entity.id} ${entity.label ?? ''}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div style={{ maxWidth: '28rem' }}>
      <ReferencePicker
        results={results}
        query={query}
        onQueryChange={setQuery}
        onSelect={() => undefined}
        loading={loading}
        defaultOpen
      />
    </div>
  );
}

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  { name: 'Grouped by kind', render: () => <Live /> },
  { name: 'Searching', render: () => <Live loading /> },
  {
    name: 'No matches',
    render: () => (
      <div style={{ maxWidth: '28rem' }}>
        <ReferencePicker
          results={[]}
          query="zzz"
          onQueryChange={() => undefined}
          onSelect={() => undefined}
          defaultOpen
        />
      </div>
    ),
  },
];

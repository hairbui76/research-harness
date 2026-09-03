import { useState } from 'react';
import type { ReactElement } from 'react';
import { FileTree } from './FileTree';
import { files } from '../manuscript.specimen-data';

function Interactive(): ReactElement {
  const [selected, setSelected] = useState('manuscript/main.tex');
  return (
    <div
      style={{
        inlineSize: 320,
        border: '1px solid var(--rh-border-subtle)',
        borderRadius: 'var(--rh-radius-card)',
      }}
    >
      <FileTree
        nodes={files}
        defaultExpanded={['manuscript', 'manuscript/sections']}
        selectedPath={selected}
        onSelect={setSelected}
        onRename={() => undefined}
        onDelete={() => undefined}
        onNewFile={() => undefined}
      />
    </div>
  );
}

export const title = 'FileTree';

export const specimens = [
  {
    name: 'Kinds, dirty and conflicted markers, context menu',
    render: () => <Interactive />,
  },
  {
    name: 'Collapsed',
    render: () => (
      <div style={{ inlineSize: 320 }}>
        <FileTree nodes={files} />
      </div>
    ),
  },
  {
    name: 'Empty',
    render: () => (
      <div style={{ inlineSize: 320 }}>
        <FileTree nodes={[]} />
      </div>
    ),
  },
];

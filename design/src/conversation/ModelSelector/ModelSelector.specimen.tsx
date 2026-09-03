import { useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import type { ModelOption } from '../models';
import { SAMPLE_MODELS } from '../samples';
import { ModelSelector } from './ModelSelector';

export const title = 'ModelSelector';

function Live({ initial = 'claude-opus-5' }: { initial?: string }): ReactElement {
  const [value, setValue] = useState(initial);
  return (
    <ModelSelector
      options={SAMPLE_MODELS}
      value={value}
      onChange={(option: ModelOption) => setValue(option.id)}
    />
  );
}

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  { name: 'External model selected', render: () => <Live /> },
  { name: 'Local model selected', render: () => <Live initial="local-llama" /> },
  {
    name: 'Nothing selected yet',
    render: () => (
      <ModelSelector options={SAMPLE_MODELS} value="" onChange={() => undefined} />
    ),
  },
  {
    name: 'Disabled while a request is in flight',
    render: () => (
      <ModelSelector
        options={SAMPLE_MODELS}
        value="claude-opus-5"
        onChange={() => undefined}
        disabled
      />
    ),
  },
];

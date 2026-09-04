import { useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import type { ModelOption, ModelOptionGroup } from '../models';
import { SAMPLE_MODELS } from '../samples';
import { ModelSelector } from './ModelSelector';

export const title = 'ModelSelector';

/**
 * A detected CLI runtime and the models it offers. The runtime declares no context window,
 * and one of its models has no tested bounded mode — both states the selector has to show.
 */
const RUNTIME_GROUPS: readonly ModelOptionGroup[] = [
  {
    id: 'codex',
    label: 'Codex CLI 0.150.1',
    options: [
      {
        id: 'runtime:codex:gpt-5.5',
        label: 'gpt-5.5',
        provider: 'Codex CLI',
        egressClass: 'external',
        vision: true,
        contextTokens: null,
        available: true,
      },
      {
        id: 'runtime:cursor-agent',
        label: 'Cursor Agent 1.4.0',
        provider: 'Cursor Agent',
        egressClass: 'external',
        vision: false,
        contextTokens: null,
        available: false,
        unavailableReason:
          'cursor-agent 1.4.0 has no tested bounded (no-tools, read-only) mode',
      },
    ],
  },
];

function Live({
  initial = 'claude-opus-5',
  groups,
}: {
  initial?: string;
  groups?: readonly ModelOptionGroup[];
}): ReactElement {
  const [value, setValue] = useState(initial);
  return (
    <ModelSelector
      options={SAMPLE_MODELS}
      groups={groups}
      value={value}
      onChange={(option: ModelOption) => setValue(option.id)}
    />
  );
}

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  { name: 'External model selected', render: () => <Live /> },
  { name: 'Local model selected', render: () => <Live initial="local-llama" /> },
  {
    name: 'A detected CLI runtime, grouped',
    render: () => <Live initial="runtime:codex:gpt-5.5" groups={RUNTIME_GROUPS} />,
  },
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

import type { ReactNode } from 'react';
import { SAMPLE_RECEIPT } from '../samples';
import { ContextReceipt } from './ContextReceipt';

export const title = 'ContextReceipt';

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'External call, two omissions — open by default',
    render: () => <ContextReceipt receipt={SAMPLE_RECEIPT} onOpenRef={() => undefined} />,
  },
  {
    name: 'Local model, nothing omitted — collapsed',
    render: () => (
      <ContextReceipt
        receipt={{
          ...SAMPLE_RECEIPT,
          packId: 'CP0008',
          provider: 'Ollama (local)',
          model: 'llama-3.1-70b',
          egressClass: 'local',
          omitted: [],
        }}
      />
    ),
  },
  {
    name: 'Collapsed, but the omission count still shows',
    render: () => <ContextReceipt receipt={SAMPLE_RECEIPT} defaultOpen={false} />,
  },
];

import type { ReactNode } from 'react';
import { SAMPLE_IDENTITY_CHOICES, SAMPLE_STALE_REF, SAMPLE_WORK } from '../samples';
import { SaveToCorpusAction } from './SaveToCorpusAction';

export const title = 'SaveToCorpusAction';

const NAME = 'lee-2024-hydrogel-preprint.pdf';

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Idle',
    render: () => (
      <SaveToCorpusAction state="idle" name={NAME} onStart={() => undefined} onConfirm={() => undefined} />
    ),
  },
  {
    name: 'Resolving identity',
    render: () => <SaveToCorpusAction state="resolving" name={NAME} onConfirm={() => undefined} />,
  },
  {
    name: 'Choosing an identity',
    render: () => (
      <SaveToCorpusAction
        state="choose_identity"
        name={NAME}
        choices={SAMPLE_IDENTITY_CHOICES}
        onConfirm={() => undefined}
        onCancel={() => undefined}
      />
    ),
  },
  {
    name: 'In the corpus',
    render: () => (
      <SaveToCorpusAction
        state="in_corpus"
        name={NAME}
        corpus={{ work: SAMPLE_WORK, artifact: { ...SAMPLE_STALE_REF, resolution: 'resolved' } }}
        onConfirm={() => undefined}
      />
    ),
  },
  {
    name: 'Failed — the session copy survives',
    render: () => (
      <SaveToCorpusAction
        state="failed"
        name={NAME}
        error="The corpus index was locked by another process."
        onConfirm={() => undefined}
        onRetry={() => undefined}
        onCancel={() => undefined}
      />
    ),
  },
];

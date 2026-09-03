import type { ReactNode } from 'react';
import { SAMPLE_CLAIM_REF } from '../../research/samples';
import { SAMPLE_ASSISTANT_MESSAGE, SAMPLE_IMAGE, SAMPLE_PDF } from '../samples';
import { MessageContent } from './MessageContent';

export const title = 'MessageContent';

const plain = (text: string): ReactNode => <p style={{ margin: 0 }}>{text}</p>;

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Prose and a reference',
    render: () => (
      <MessageContent blocks={SAMPLE_ASSISTANT_MESSAGE.blocks} renderMarkdown={plain} onOpenRef={() => undefined} />
    ),
  },
  {
    name: 'Mixed attachments',
    render: () => (
      <MessageContent
        blocks={[
          { kind: 'text', text: 'Here is the figure and the preprint it came from.' },
          { kind: 'attachment', attachment: SAMPLE_IMAGE },
          { kind: 'attachment', attachment: SAMPLE_PDF },
          { kind: 'reference', ref: SAMPLE_CLAIM_REF },
        ]}
        renderMarkdown={plain}
      />
    ),
  },
  {
    name: 'Streaming',
    render: () => (
      <MessageContent
        blocks={[{ kind: 'text', text: 'Reading the accepted evidence for C0041' }]}
        renderMarkdown={plain}
        status="streaming"
      />
    ),
  },
  {
    name: 'Interrupted',
    render: () => (
      <MessageContent
        blocks={[{ kind: 'text', text: 'The three measurements that bear on this are' }]}
        renderMarkdown={plain}
        status="incomplete"
        onRetry={() => undefined}
      />
    ),
  },
  {
    name: 'A failure inside the turn',
    render: () => (
      <MessageContent
        blocks={[
          { kind: 'text', text: 'Partial answer before the provider dropped:' },
          { kind: 'error', message: 'The provider did not respond after 30 s.', retryable: true },
        ]}
        renderMarkdown={plain}
        onRetry={() => undefined}
      />
    ),
  },
];

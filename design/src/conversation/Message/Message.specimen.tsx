import type { ReactNode } from 'react';
import {
  SAMPLE_ASSISTANT_MESSAGE,
  SAMPLE_FAILED_MESSAGE,
  SAMPLE_INCOMPLETE_MESSAGE,
  SAMPLE_STREAMING_MESSAGE,
  SAMPLE_USER_MESSAGE,
} from '../samples';
import { Message } from './Message';

export const title = 'Message';

/** The gallery has no Markdown engine; the Web client passes react-markdown here. */
const plain = (text: string): ReactNode => <p style={{ margin: 0 }}>{text}</p>;

const noop = (): void => undefined;

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'A turn each way',
    render: () => (
      <div>
        <Message message={SAMPLE_USER_MESSAGE} renderMarkdown={plain} onCopy={noop} />
        <Message
          message={SAMPLE_ASSISTANT_MESSAGE}
          renderMarkdown={plain}
          onCopy={noop}
          onRetry={noop}
          onOpenReceipt={noop}
          onPromote={noop}
        />
      </div>
    ),
  },
  {
    name: 'Streaming',
    render: () => <Message message={SAMPLE_STREAMING_MESSAGE} renderMarkdown={plain} />,
  },
  {
    name: 'Interrupted, with what arrived kept',
    render: () => (
      <Message message={SAMPLE_INCOMPLETE_MESSAGE} renderMarkdown={plain} onRetry={noop} />
    ),
  },
  {
    name: 'Failed attempt',
    render: () => <Message message={SAMPLE_FAILED_MESSAGE} renderMarkdown={plain} onRetry={noop} />,
  },
  {
    name: 'System and tool turns',
    render: () => (
      <div>
        <Message
          message={{
            id: 'M0001',
            role: 'system',
            createdAt: '2026-09-03T14:00:00Z',
            status: 'complete',
            blocks: [{ kind: 'text', text: 'Project policy: external providers may not see private sessions.' }],
          }}
          renderMarkdown={plain}
        />
        <Message
          message={{
            id: 'M0043',
            role: 'tool',
            author: 'graph.query',
            createdAt: '2026-09-03T14:20:30Z',
            status: 'complete',
            blocks: [{ kind: 'text', text: '4 supporting, 1 contradicting, 2 qualifying.' }],
          }}
          renderMarkdown={plain}
        />
      </div>
    ),
  },
];

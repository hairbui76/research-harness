import type { ReactNode } from 'react';
import { SAMPLE_IDENTITY_CHOICES } from '../../research/samples';
import {
  SAMPLE_BLOCKED_ATTACHMENT,
  SAMPLE_FAILED_ATTACHMENT,
  SAMPLE_IMAGE,
  SAMPLE_IMAGE_2,
  SAMPLE_PDF,
} from '../samples';
import { AttachmentTray } from './AttachmentTray';

export const title = 'AttachmentTray';

const noop = (): void => undefined;

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'A mixed draft',
    render: () => (
      <AttachmentTray
        attachments={[SAMPLE_IMAGE, SAMPLE_IMAGE_2, SAMPLE_PDF]}
        onRemove={noop}
        onRetry={noop}
      />
    ),
  },
  {
    name: 'One item blocked, one failed — the rest survive',
    render: () => (
      <AttachmentTray
        attachments={[SAMPLE_PDF, SAMPLE_BLOCKED_ATTACHMENT, SAMPLE_FAILED_ATTACHMENT]}
        onRemove={noop}
        onRetry={noop}
      />
    ),
  },
  {
    name: 'Save to corpus, mid-flow',
    render: () => (
      <AttachmentTray
        attachments={[SAMPLE_PDF, { ...SAMPLE_IMAGE, id: 'SA0009', state: 'in_corpus' }]}
        save={{
          [SAMPLE_PDF.id]: { state: 'choose_identity', choices: SAMPLE_IDENTITY_CHOICES },
          SA0009: { state: 'in_corpus' },
        }}
        onSaveStart={noop}
        onSaveConfirm={noop}
        onSaveCancel={noop}
        onRemove={noop}
      />
    ),
  },
  {
    name: 'Empty',
    render: () => <AttachmentTray attachments={[]} emptyMessage="No files on this draft" />,
  },
];

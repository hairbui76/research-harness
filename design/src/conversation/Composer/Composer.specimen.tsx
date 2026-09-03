import { useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { SAMPLE_EVIDENCE_REF } from '../../research/samples';
import { AttachmentTray } from '../AttachmentTray';
import { ModelSelector } from '../ModelSelector';
import type { ComposerValue } from '../models';
import {
  SAMPLE_BLOCKED_ATTACHMENT,
  SAMPLE_IMAGE,
  SAMPLE_MODELS,
  SAMPLE_PDF,
  SAMPLE_REFERENCE_RESULTS,
} from '../samples';
import { Composer } from './Composer';
import type { ComposerProps } from './Composer';

export const title = 'Composer';

type LiveProps = Partial<Omit<ComposerProps, 'value' | 'onChange'>> & { initial?: ComposerValue };

/** The application owns the draft; the specimen stands in for it. */
function Live({ initial, ...props }: LiveProps): ReactElement {
  const [value, setValue] = useState<ComposerValue>(initial ?? { text: '', tokens: [] });
  const [query, setQuery] = useState('');
  const results = SAMPLE_REFERENCE_RESULTS.filter((entity) =>
    `${entity.id} ${entity.label ?? ''}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <Composer
      value={value}
      onChange={setValue}
      onSend={() => setValue({ text: '', tokens: [] })}
      referenceResults={results}
      onReferenceQuery={setQuery}
      {...props}
    />
  );
}

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Empty — type @ to search the graph',
    render: () => <Live onAttach={() => undefined} />,
  },
  {
    name: 'A draft with a reference token',
    render: () => (
      <Live
        initial={{
          text: 'Does the stiffness sweep support the causal wording?',
          tokens: [SAMPLE_EVIDENCE_REF],
        }}
        onAttach={() => undefined}
        modelSelector={
          <ModelSelector options={SAMPLE_MODELS} value="claude-opus-5" onChange={() => undefined} />
        }
      />
    ),
  },
  {
    name: 'With attachments',
    render: () => (
      <Live
        initial={{ text: 'Both of these are from the same preprint.', tokens: [] }}
        onAttach={() => undefined}
        attachmentTray={
          <AttachmentTray attachments={[SAMPLE_IMAGE, SAMPLE_PDF]} onRemove={() => undefined} />
        }
        modelSelector={
          <ModelSelector options={SAMPLE_MODELS} value="claude-opus-5" onChange={() => undefined} />
        }
      />
    ),
  },
  {
    name: 'Send blocked — the draft is untouched',
    render: () => (
      <Live
        initial={{ text: 'Can you read these traces?', tokens: [] }}
        attachmentTray={<AttachmentTray attachments={[SAMPLE_BLOCKED_ATTACHMENT]} />}
        blockedReasons={[
          {
            attachmentId: SAMPLE_BLOCKED_ATTACHMENT.id,
            reason: 'raw-traces.h5 cannot be read by Claude Opus 5.',
            suggestedModel: 'a local analysis tool',
          },
        ]}
        modelSelector={
          <ModelSelector options={SAMPLE_MODELS} value="claude-opus-5" onChange={() => undefined} />
        }
      />
    ),
  },
  {
    name: 'Streaming — stop is offered',
    render: () => (
      <Live
        initial={{ text: 'Summarise the accepted evidence.', tokens: [] }}
        sendState="streaming"
        onStop={() => undefined}
      />
    ),
  },
];

import type { ReactNode } from 'react';
import { IconButton } from '../../primitives/IconButton';
import { SAMPLE_IMAGE, SAMPLE_IMAGE_2 } from '../samples';
import { ImageAttachment } from './ImageAttachment';

export const title = 'ImageAttachment';

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Thumbnail with described alt text',
    render: () => (
      <ImageAttachment
        attachment={SAMPLE_IMAGE}
        alt="Storage modulus rising from 1.2 to 8.4 kPa over 24 hours"
        actions={<IconButton icon="trash-2" label="Remove figure-3" size="sm" />}
      />
    ),
  },
  {
    name: 'A gallery — arrow keys move between images',
    render: () => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {[SAMPLE_IMAGE, SAMPLE_IMAGE_2].map((image) => (
          <ImageAttachment key={image.id} attachment={image} gallery={[SAMPLE_IMAGE, SAMPLE_IMAGE_2]} />
        ))}
      </div>
    ),
  },
  {
    name: 'No thumbnail yet',
    render: () => (
      <ImageAttachment
        attachment={{ ...SAMPLE_IMAGE, thumbnailUrl: undefined, state: 'validating' }}
      />
    ),
  },
  {
    name: 'Cannot be sent to the selected model',
    render: () => (
      <ImageAttachment
        attachment={{
          ...SAMPLE_IMAGE,
          sendability: {
            ok: false,
            reason: 'The selected model reads text only.',
            suggestedModel: 'Claude Opus 5',
          },
        }}
      />
    ),
  },
];

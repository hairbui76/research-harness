import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { SAMPLE_IDENTITY_CHOICES } from '../../research/samples';
import {
  SAMPLE_BLOCKED_ATTACHMENT,
  SAMPLE_FAILED_ATTACHMENT,
  SAMPLE_IMAGE,
  SAMPLE_PDF,
} from '../samples';
import { AttachmentTray } from './AttachmentTray';

const ATTACHMENTS = [SAMPLE_IMAGE, SAMPLE_PDF, SAMPLE_BLOCKED_ATTACHMENT];

describe('AttachmentTray', () => {
  it('renders nothing when there is nothing attached', () => {
    const { container } = render(<AttachmentTray attachments={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows an empty state only when the surface asks for one', () => {
    render(<AttachmentTray attachments={[]} emptyMessage="No files on this draft" />);
    expect(screen.getByText('No files on this draft')).toBeInTheDocument();
  });

  it('gives every file the presentation its type deserves', () => {
    const { container } = render(<AttachmentTray attachments={ATTACHMENTS} />);
    expect(container.querySelector('.rh-image-attachment')).not.toBeNull();
    expect(container.querySelector('.rh-pdf-attachment')).not.toBeNull();
    // An unsupported type is still listed, named and explained.
    expect(screen.getByText(SAMPLE_BLOCKED_ATTACHMENT.name)).toBeInTheDocument();
    expect(screen.getByText(/cannot read HDF5 files/)).toBeInTheDocument();
  });

  it('removes one file without disturbing the others', async () => {
    const user = userEvent.setup();
    const onRemove = vi.fn();
    render(<AttachmentTray attachments={ATTACHMENTS} onRemove={onRemove} />);
    await user.click(screen.getByRole('button', { name: `Remove ${SAMPLE_PDF.name}` }));
    expect(onRemove).toHaveBeenCalledWith(SAMPLE_PDF.id);
    expect(screen.getByText(SAMPLE_IMAGE.name)).toBeInTheDocument();
  });

  it('offers a retry only on the item that failed', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <AttachmentTray attachments={[SAMPLE_PDF, SAMPLE_FAILED_ATTACHMENT]} onRetry={onRetry} />,
    );
    const retries = screen.getAllByRole('button', { name: /^Retry / });
    expect(retries).toHaveLength(1);
    await user.click(retries[0] as HTMLElement);
    expect(onRetry).toHaveBeenCalledWith(SAMPLE_FAILED_ATTACHMENT.id);
  });

  it('offers Save to corpus only where the lifecycle allows it', () => {
    render(
      <AttachmentTray
        attachments={[SAMPLE_PDF, SAMPLE_FAILED_ATTACHMENT]}
        save={{
          [SAMPLE_PDF.id]: { state: 'idle' },
          [SAMPLE_FAILED_ATTACHMENT.id]: { state: 'idle' },
        }}
        onSaveConfirm={() => undefined}
      />,
    );
    expect(screen.getAllByRole('button', { name: 'Save to corpus' })).toHaveLength(1);
  });

  it('runs the save flow for one attachment at a time', async () => {
    const user = userEvent.setup();
    const onSaveConfirm = vi.fn();
    render(
      <AttachmentTray
        attachments={[SAMPLE_PDF]}
        save={{ [SAMPLE_PDF.id]: { state: 'choose_identity', choices: SAMPLE_IDENTITY_CHOICES } }}
        onSaveConfirm={onSaveConfirm}
      />,
    );
    await user.click(screen.getByRole('radio', { name: /New version of W0017/ }));
    await user.click(screen.getByRole('button', { name: 'Confirm and save' }));
    expect(onSaveConfirm).toHaveBeenCalledWith(SAMPLE_PDF.id, SAMPLE_IDENTITY_CHOICES[1]);
  });

  it('cannot remove an attachment while work is in flight', () => {
    render(
      <AttachmentTray
        attachments={[{ ...SAMPLE_PDF, state: 'promoting' }]}
        onRemove={() => undefined}
      />,
    );
    expect(screen.getByRole('button', { name: `Remove ${SAMPLE_PDF.name}` })).toBeDisabled();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <AttachmentTray
        attachments={ATTACHMENTS}
        onRemove={() => undefined}
        onRetry={() => undefined}
        save={{ [SAMPLE_PDF.id]: { state: 'idle' } }}
        onSaveConfirm={() => undefined}
      />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('AttachmentTray', () => (
  <AttachmentTray attachments={ATTACHMENTS} onRemove={() => undefined} />
));

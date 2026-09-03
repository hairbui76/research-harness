import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { SAMPLE_IMAGE, SAMPLE_IMAGE_2 } from '../samples';
import { ImageAttachment } from './ImageAttachment';

const GALLERY = [SAMPLE_IMAGE, SAMPLE_IMAGE_2];

describe('ImageAttachment', () => {
  it('shows a thumbnail with alt text and the file facts', () => {
    render(<ImageAttachment attachment={SAMPLE_IMAGE} alt="Storage modulus against time" />);
    expect(screen.getByAltText('Storage modulus against time')).toBeInTheDocument();
    expect(screen.getByText('482 kB')).toBeInTheDocument();
    expect(screen.getByText('Session only')).toBeInTheDocument();
  });

  it('falls back to the file name when there is no thumbnail, without an empty img', () => {
    const { container } = render(
      <ImageAttachment attachment={{ ...SAMPLE_IMAGE, thumbnailUrl: undefined }} />,
    );
    expect(container.querySelector('.rh-image-attachment__thumb img')).toBeNull();
    expect(screen.getAllByText(SAMPLE_IMAGE.name).length).toBeGreaterThan(0);
  });

  it('opens the viewer and reports the position in the gallery', async () => {
    const user = userEvent.setup();
    render(<ImageAttachment attachment={SAMPLE_IMAGE} gallery={GALLERY} />);
    await user.click(screen.getByRole('button', { name: `Open ${SAMPLE_IMAGE.name}` }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('1 of 2');
    expect(screen.getByRole('status')).toHaveTextContent('100%');
  });

  it('moves between images with the arrow keys and resets the zoom', async () => {
    const user = userEvent.setup();
    render(<ImageAttachment attachment={SAMPLE_IMAGE} gallery={GALLERY} defaultOpen />);
    await user.keyboard('+');
    expect(screen.getByRole('status')).toHaveTextContent('125%');
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('status')).toHaveTextContent('2 of 2');
    expect(screen.getByRole('status')).toHaveTextContent('100%');
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('status')).toHaveTextContent('1 of 2');
  });

  it('zooms with +, - and 0 as a CSS transform on the original bytes', async () => {
    const user = userEvent.setup();
    const { baseElement } = render(
      <ImageAttachment attachment={SAMPLE_IMAGE} defaultOpen alt="Figure 3" />,
    );
    const image = baseElement.querySelector('.rh-image-gallery__image') as HTMLElement;
    await user.keyboard('++');
    expect(image.style.transform).toBe('scale(1.5)');
    await user.keyboard('-');
    expect(image.style.transform).toBe('scale(1.25)');
    await user.keyboard('0');
    expect(image.style.transform).toBe('scale(1)');
  });

  it('offers the original file for download', () => {
    const { baseElement } = render(<ImageAttachment attachment={SAMPLE_IMAGE} defaultOpen />);
    const link = baseElement.querySelector('.rh-image-gallery__download');
    expect(link).toHaveAttribute('download', SAMPLE_IMAGE.name);
  });

  it('says why an attachment cannot be sent, beside the attachment', () => {
    render(
      <ImageAttachment
        attachment={{
          ...SAMPLE_IMAGE,
          sendability: { ok: false, reason: 'This model reads text only.', suggestedModel: 'Opus' },
        }}
      />,
    );
    expect(screen.getByText(/This model reads text only/)).toBeInTheDocument();
    expect(screen.getByText(/Try Opus/)).toBeInTheDocument();
  });

  it('has no accessibility violations, closed or open', async () => {
    const { container } = render(<ImageAttachment attachment={SAMPLE_IMAGE} alt="Figure 3" />);
    await expectNoAxeViolations(container);

    render(<ImageAttachment attachment={SAMPLE_IMAGE} gallery={GALLERY} defaultOpen alt="Figure 3" />);
    await expectNoAxeViolations(document.body);
  });
});

describeThemeDensitySnapshots('ImageAttachment', () => (
  <ImageAttachment attachment={SAMPLE_IMAGE} alt="Figure 3" />
));

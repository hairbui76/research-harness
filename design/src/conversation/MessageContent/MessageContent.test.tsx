import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { SAMPLE_CLAIM_REF } from '../../research/samples';
import { SAMPLE_ASSISTANT_MESSAGE, SAMPLE_PDF, SAMPLE_USER_MESSAGE } from '../samples';
import { MessageContent } from './MessageContent';

const plain = (text: string) => <p>{text}</p>;

describe('MessageContent', () => {
  it('draws prose through the renderer the application supplies', () => {
    const renderMarkdown = vi.fn(plain);
    render(<MessageContent blocks={SAMPLE_ASSISTANT_MESSAGE.blocks} renderMarkdown={renderMarkdown} />);
    expect(renderMarkdown).toHaveBeenCalledWith(
      expect.stringContaining('The sweep supports an association'),
    );
    expect(screen.getByText(/The sweep supports an association/)).toBeInTheDocument();
  });

  it('renders reference blocks as reference chips', () => {
    render(<MessageContent blocks={SAMPLE_ASSISTANT_MESSAGE.blocks} renderMarkdown={plain} />);
    expect(screen.getByText('E0482')).toBeInTheDocument();
  });

  it('renders attachment blocks with their own state', () => {
    render(<MessageContent blocks={SAMPLE_USER_MESSAGE.blocks} renderMarkdown={plain} />);
    expect(screen.getByText(SAMPLE_PDF.name)).toBeInTheDocument();
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('announces a streaming reply politely', () => {
    const { container } = render(
      <MessageContent
        blocks={[{ kind: 'text', text: 'Reading' }]}
        renderMarkdown={plain}
        status="streaming"
      />,
    );
    const region = container.querySelector('.rh-message-content');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByText('Streaming…')).toBeInTheDocument();
  });

  it('keeps what arrived and says an interrupted reply is incomplete', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <MessageContent
        blocks={[{ kind: 'text', text: 'The three measurements' }]}
        renderMarkdown={plain}
        status="incomplete"
        onRetry={onRetry}
      />,
    );
    expect(screen.getByText('The three measurements')).toBeInTheDocument();
    expect(screen.getByText(/Incomplete — response was interrupted/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalled();
  });

  it('offers a retry on a retryable error block and none on a fatal one', () => {
    const { rerender } = render(
      <MessageContent
        blocks={[{ kind: 'error', message: 'Provider timed out.', retryable: true }]}
        renderMarkdown={plain}
        onRetry={() => undefined}
      />,
    );
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();

    rerender(
      <MessageContent
        blocks={[{ kind: 'error', message: 'The project is read-only.', retryable: false }]}
        renderMarkdown={plain}
        onRetry={() => undefined}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();
  });

  it('opens a reference from the keyboard', async () => {
    const user = userEvent.setup();
    const onOpenRef = vi.fn();
    render(
      <MessageContent
        blocks={[{ kind: 'reference', ref: SAMPLE_CLAIM_REF }]}
        renderMarkdown={plain}
        onOpenRef={onOpenRef}
      />,
    );
    await user.tab();
    await user.keyboard('{Enter}');
    expect(onOpenRef).toHaveBeenCalledWith(SAMPLE_CLAIM_REF);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <MessageContent
        blocks={SAMPLE_USER_MESSAGE.blocks}
        renderMarkdown={plain}
        status="incomplete"
        onRetry={() => undefined}
      />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('MessageContent', () => (
  <MessageContent blocks={SAMPLE_ASSISTANT_MESSAGE.blocks} renderMarkdown={plain} />
));

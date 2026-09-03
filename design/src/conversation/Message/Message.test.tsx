import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { PROMOTION_TARGET_META } from '../models';
import {
  SAMPLE_ASSISTANT_MESSAGE,
  SAMPLE_FAILED_MESSAGE,
  SAMPLE_INCOMPLETE_MESSAGE,
  SAMPLE_STREAMING_MESSAGE,
  SAMPLE_USER_MESSAGE,
} from '../samples';
import { Message } from './Message';

const plain = (text: string) => <p>{text}</p>;

describe('Message', () => {
  it('records who said it, when, and with which model', () => {
    render(<Message message={SAMPLE_ASSISTANT_MESSAGE} renderMarkdown={plain} />);
    expect(screen.getByText('Assistant')).toBeInTheDocument();
    expect(screen.getByText('M0042')).toBeInTheDocument();
    expect(screen.getByText('Anthropic')).toBeInTheDocument();
    expect(screen.getByText('claude-opus-5')).toBeInTheDocument();
    expect(screen.getByText('attempt 2 of 2')).toBeInTheDocument();
  });

  it('formats the timestamp without depending on a locale', () => {
    const { container } = render(
      <Message message={SAMPLE_ASSISTANT_MESSAGE} renderMarkdown={plain} />,
    );
    const time = container.querySelector('time');
    expect(time).toHaveAttribute('datetime', '2026-09-03T14:20:38Z');
    expect(time).toHaveTextContent('2026-09-03 14:20');
  });

  it.each([
    [SAMPLE_STREAMING_MESSAGE, 'Streaming'],
    [SAMPLE_INCOMPLETE_MESSAGE, 'Incomplete'],
    [SAMPLE_FAILED_MESSAGE, 'Failed'],
  ])('states an unusual status in words', (message, label) => {
    render(<Message message={message} renderMarkdown={plain} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it('keeps every action in the tab order rather than behind a hover', async () => {
    const user = userEvent.setup();
    const onCopy = vi.fn();
    render(
      <Message
        message={SAMPLE_ASSISTANT_MESSAGE}
        renderMarkdown={plain}
        onCopy={onCopy}
        onRetry={() => undefined}
        onOpenReceipt={() => undefined}
        onPromote={() => undefined}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Copy message' }));
    expect(onCopy).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /Context used \(CP0007\)/ })).toBeInTheDocument();
  });

  it('opens the context receipt with the pack id of the call that produced it', async () => {
    const user = userEvent.setup();
    const onOpenReceipt = vi.fn();
    render(
      <Message
        message={SAMPLE_ASSISTANT_MESSAGE}
        renderMarkdown={plain}
        onOpenReceipt={onOpenReceipt}
      />,
    );
    await user.click(screen.getByRole('button', { name: /Context used/ }));
    expect(onOpenReceipt).toHaveBeenCalledWith('CP0007');
  });

  it('offers promotion through a keyboard-operable menu', async () => {
    const user = userEvent.setup();
    const onPromote = vi.fn();
    render(
      <Message message={SAMPLE_ASSISTANT_MESSAGE} renderMarkdown={plain} onPromote={onPromote} />,
    );
    await user.click(screen.getByRole('button', { name: 'Promote this message' }));
    const items = screen.getAllByRole('menuitem');
    expect(items).toHaveLength(4);
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');
    expect(onPromote).toHaveBeenCalledWith('claim_candidate');
  });

  it('lets a host offer only some promotions', async () => {
    const user = userEvent.setup();
    render(
      <Message
        message={SAMPLE_ASSISTANT_MESSAGE}
        renderMarkdown={plain}
        onPromote={() => undefined}
        promotionTargets={['note']}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Promote this message' }));
    expect(screen.getAllByRole('menuitem')).toHaveLength(1);
    expect(screen.getByRole('menuitem', { name: PROMOTION_TARGET_META.note.label })).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        <Message message={SAMPLE_USER_MESSAGE} renderMarkdown={plain} />
        <Message
          message={SAMPLE_ASSISTANT_MESSAGE}
          renderMarkdown={plain}
          onCopy={() => undefined}
          onRetry={() => undefined}
          onOpenReceipt={() => undefined}
          onPromote={() => undefined}
        />
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('Message', () => (
  <div>
    <Message message={SAMPLE_USER_MESSAGE} renderMarkdown={plain} />
    <Message
      message={SAMPLE_ASSISTANT_MESSAGE}
      renderMarkdown={plain}
      onCopy={() => undefined}
      onOpenReceipt={() => undefined}
    />
  </div>
));

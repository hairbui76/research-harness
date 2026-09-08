import { render, screen, within } from '@testing-library/react';
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
  /*
   * The strip printed `M0042 2026-09-03 14:20 Anthropic claude-opus-5 attempt 2 of 2` over
   * every turn — a receipt header above a paragraph of prose. Two of those five are facts
   * a person reads, and they stay; the id and the attempt are what a receipt needs, and
   * the assertions for them moved to the overflow that carries the receipt.
   */
  it('records who said it, when, and which runtime answered', () => {
    render(<Message message={SAMPLE_ASSISTANT_MESSAGE} renderMarkdown={plain} />);
    expect(screen.getByText('Assistant')).toBeInTheDocument();
    expect(screen.getByText(/Answered by/)).toBeInTheDocument();
    expect(screen.getByText('Anthropic')).toBeInTheDocument();
    expect(screen.getByText('claude-opus-5')).toBeInTheDocument();
    // Not over the prose: neither the row's id nor which attempt it is belongs there.
    expect(screen.queryByText('M0042')).toBeNull();
    expect(screen.queryByText(/attempt 2 of 2/)).toBeNull();
  });

  it('keeps the row’s id and attempt with the receipt, in the overflow', async () => {
    const user = userEvent.setup();
    render(
      <Message
        message={SAMPLE_ASSISTANT_MESSAGE}
        renderMarkdown={plain}
        secondaryActions="menu"
        onCopy={() => undefined}
        onRetry={() => undefined}
        onOpenReceipt={() => undefined}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'More actions' }));
    const overflow = await screen.findByRole('menu', { name: 'More actions for M0042' });
    // The identity heads the group the receipt sits in, so what the receipt names and what
    // opens it are read together.
    expect(within(overflow).getByText('M0042 · attempt 2 of 2')).toBeInTheDocument();
    expect(
      within(overflow).getByRole('menuitem', { name: 'Context used (CP0007)' }),
    ).toBeInTheDocument();
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
    await user.click(screen.getByRole('button', { name: 'Promote…' }));
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
    await user.click(screen.getByRole('button', { name: 'Promote…' }));
    expect(screen.getAllByRole('menuitem')).toHaveLength(1);
    expect(screen.getByRole('menuitem', { name: PROMOTION_TARGET_META.note.label })).toBeInTheDocument();
  });

  it('names the action row, so the controls read as one group rather than a scatter', () => {
    render(
      <Message
        message={SAMPLE_ASSISTANT_MESSAGE}
        renderMarkdown={plain}
        onCopy={() => undefined}
        onPromote={() => undefined}
      />,
    );
    expect(screen.getByRole('group', { name: 'Actions for M0042' })).toBeInTheDocument();
  });

  /*
   * Eight controls beside one paragraph is not a toolbar, it is a scatter. The row keeps a
   * primary action on the page — promotion is how a chat answer becomes reviewable state —
   * and folds the rest into one overflow, without going back to hover: everything is still
   * reachable by keyboard from the row itself.
   */
  it('folds the secondary controls into one overflow when the host asks', async () => {
    const user = userEvent.setup();
    const onCopy = vi.fn();
    render(
      <Message
        message={SAMPLE_ASSISTANT_MESSAGE}
        renderMarkdown={plain}
        secondaryActions="menu"
        onCopy={onCopy}
        onRetry={() => undefined}
        onOpenReceipt={() => undefined}
        onPromote={() => undefined}
      />,
    );

    const row = screen.getByRole('group', { name: 'Actions for M0042' });
    // The act that leads somewhere carries its name; the overflow is the only icon left.
    expect(within(row).getAllByRole('button').map((button) => button.textContent)).toEqual([
      'Promote…',
      '',
    ]);
    expect(within(row).getByRole('button', { name: 'More actions' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'More actions' }));
    expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual([
      'Copy message',
      'Ask again',
      'Context used (CP0007)',
    ]);

    await user.click(screen.getByRole('menuitem', { name: 'Copy message' }));
    expect(onCopy).toHaveBeenCalled();
  });

  it('keeps recovery on the row: a failed turn does not hide its retry in the overflow', async () => {
    const user = userEvent.setup();
    render(
      <Message
        message={SAMPLE_FAILED_MESSAGE}
        renderMarkdown={plain}
        secondaryActions="menu"
        onCopy={() => undefined}
        onRetry={() => undefined}
        onOpenReceipt={() => undefined}
        onPromote={() => undefined}
      />,
    );

    const row = screen.getByRole('group', { name: `Actions for ${SAMPLE_FAILED_MESSAGE.id}` });
    expect(within(row).getByRole('button', { name: 'Retry this turn' })).toBeInTheDocument();

    await user.click(within(row).getByRole('button', { name: 'More actions' }));
    expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual([
      'Copy message',
      `Context used (${SAMPLE_FAILED_MESSAGE.contextPackId})`,
    ]);
  });

  it('leaves a lone secondary control on the row rather than hiding it behind a menu', () => {
    render(
      <Message
        message={SAMPLE_ASSISTANT_MESSAGE}
        renderMarkdown={plain}
        secondaryActions="menu"
        onCopy={() => undefined}
        onPromote={() => undefined}
      />,
    );
    expect(screen.getByRole('button', { name: 'Copy message' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'More actions' })).not.toBeInTheDocument();
  });

  it('has no accessibility violations with the overflow in place', async () => {
    const { container } = render(
      <Message
        message={SAMPLE_ASSISTANT_MESSAGE}
        renderMarkdown={plain}
        secondaryActions="menu"
        onCopy={() => undefined}
        onRetry={() => undefined}
        onOpenReceipt={() => undefined}
        onPromote={() => undefined}
      />,
    );
    await expectNoAxeViolations(container);
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

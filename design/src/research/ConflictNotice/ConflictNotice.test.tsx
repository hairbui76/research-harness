import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { SAMPLE_CLAIM_REF, SAMPLE_CONFLICT } from '../samples';
import { ConflictNotice } from './ConflictNotice';

describe('ConflictNotice', () => {
  it('says in words which side was used and which was not', () => {
    render(<ConflictNotice conflict={SAMPLE_CONFLICT} />);
    expect(screen.getByText('Accepted — sent to the model')).toBeInTheDocument();
    expect(screen.getByText('From this conversation — not used')).toBeInTheDocument();
  });

  it('shows both excerpts and the explanation', () => {
    render(<ConflictNotice conflict={SAMPLE_CONFLICT} />);
    expect(screen.getByText(SAMPLE_CONFLICT.accepted.excerpt)).toBeInTheDocument();
    expect(screen.getByText(SAMPLE_CONFLICT.chat.excerpt)).toBeInTheDocument();
    expect(screen.getByText(SAMPLE_CONFLICT.explanation)).toBeInTheDocument();
  });

  it('opens either side', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<ConflictNotice conflict={SAMPLE_CONFLICT} onOpen={onOpen} />);
    await user.click(screen.getByText('C0041'));
    expect(onOpen).toHaveBeenCalledWith(SAMPLE_CLAIM_REF);
    await user.click(screen.getByText('M0042'));
    expect(onOpen).toHaveBeenCalledWith(SAMPLE_CONFLICT.chat.ref);
  });

  it('marks the accepted side as the winner in the DOM as well as in the text', () => {
    const { container } = render(<ConflictNotice conflict={SAMPLE_CONFLICT} />);
    expect(container.querySelector('[data-side="accepted"]')).not.toBeNull();
    expect(container.querySelector('[data-side="chat"]')).not.toBeNull();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <ConflictNotice conflict={SAMPLE_CONFLICT} onOpen={() => undefined} />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('ConflictNotice', () => (
  <ConflictNotice conflict={SAMPLE_CONFLICT} />
));

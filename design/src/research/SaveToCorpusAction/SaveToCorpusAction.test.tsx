import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { SAMPLE_IDENTITY_CHOICES, SAMPLE_WORK } from '../samples';
import { SaveToCorpusAction } from './SaveToCorpusAction';

describe('SaveToCorpusAction', () => {
  it('offers the action while idle and starts identity resolution', async () => {
    const user = userEvent.setup();
    const onStart = vi.fn();
    render(<SaveToCorpusAction state="idle" onStart={onStart} onConfirm={() => undefined} />);
    await user.click(screen.getByRole('button', { name: 'Save to corpus' }));
    expect(onStart).toHaveBeenCalled();
  });

  it('shows the resolving and promoting states as busy', () => {
    const { rerender } = render(
      <SaveToCorpusAction state="resolving" onConfirm={() => undefined} />,
    );
    expect(screen.getByRole('button')).toHaveAttribute('aria-busy', 'true');
    rerender(<SaveToCorpusAction state="promoting" onConfirm={() => undefined} />);
    expect(screen.getByRole('button')).toHaveAttribute('aria-busy', 'true');
  });

  it('renders the identities the host resolved and preselects none of them', () => {
    render(
      <SaveToCorpusAction
        state="choose_identity"
        choices={SAMPLE_IDENTITY_CHOICES}
        name="lee-2024.pdf"
        onConfirm={() => undefined}
      />,
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getAllByRole('radio')).toHaveLength(3);
    for (const radio of screen.getAllByRole('radio')) expect(radio).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Confirm and save' })).toBeDisabled();
  });

  it('reports the confirmed choice and nothing else', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <SaveToCorpusAction
        state="choose_identity"
        choices={SAMPLE_IDENTITY_CHOICES}
        onConfirm={onConfirm}
      />,
    );
    await user.click(screen.getByRole('radio', { name: /New version of W0017/ }));
    await user.click(screen.getByRole('button', { name: 'Confirm and save' }));
    expect(onConfirm).toHaveBeenCalledWith(SAMPLE_IDENTITY_CHOICES[1]);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('says that saving is identity, not evidence acceptance', () => {
    render(
      <SaveToCorpusAction
        state="choose_identity"
        choices={SAMPLE_IDENTITY_CHOICES}
        onConfirm={() => undefined}
      />,
    );
    expect(screen.getByText(/does not create evidence or accept anything/i)).toBeInTheDocument();
  });

  it('cancels from the keyboard with Escape', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <SaveToCorpusAction
        state="choose_identity"
        choices={SAMPLE_IDENTITY_CHOICES}
        onConfirm={() => undefined}
        onCancel={onCancel}
      />,
    );
    await user.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalled();
  });

  it('keeps the session copy intact and retryable after a failure', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <SaveToCorpusAction
        state="failed"
        name="lee-2024.pdf"
        error="The corpus index was locked."
        onConfirm={() => undefined}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByText(/The session copy of lee-2024.pdf is unchanged/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalled();
  });

  it('shows where the bytes ended up once they are in the corpus', () => {
    render(
      <SaveToCorpusAction
        state="in_corpus"
        corpus={{ work: SAMPLE_WORK }}
        onConfirm={() => undefined}
      />,
    );
    expect(screen.getByText('In corpus')).toBeInTheDocument();
    expect(screen.getByText('W0017')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save to corpus' })).toBeNull();
  });

  it('has no accessibility violations while choosing an identity', async () => {
    render(
      <SaveToCorpusAction
        state="choose_identity"
        choices={SAMPLE_IDENTITY_CHOICES}
        name="lee-2024.pdf"
        onConfirm={() => undefined}
      />,
    );
    await expectNoAxeViolations(document.body);
  });
});

describeThemeDensitySnapshots('SaveToCorpusAction', () => (
  <SaveToCorpusAction state="idle" onStart={() => undefined} onConfirm={() => undefined} />
));

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { SAMPLE_EVIDENCE_REF } from '../../research/samples';
import type { ComposerValue } from '../models';
import { SAMPLE_REFERENCE_RESULTS } from '../samples';
import { Composer } from './Composer';
import type { ComposerProps } from './Composer';

type ExampleProps = Partial<Omit<ComposerProps, 'value' | 'onChange'>> & {
  initial?: ComposerValue;
  onValueChange?: (value: ComposerValue) => void;
};

/** The application owns the draft; this stands in for it. */
function Example({ initial, onValueChange, ...props }: ExampleProps = {}) {
  const [value, setValue] = useState<ComposerValue>(initial ?? { text: '', tokens: [] });
  return (
    <Composer
      value={value}
      onChange={(next) => {
        setValue(next);
        onValueChange?.(next);
      }}
      onSend={() => undefined}
      referenceResults={SAMPLE_REFERENCE_RESULTS}
      {...props}
    />
  );
}

describe('Composer', () => {
  it('documents the keyboard contract on the page', () => {
    render(<Example />);
    expect(screen.getByText(/Enter sends · Shift\+Enter starts a new line/)).toBeInTheDocument();
  });

  it('sends on Enter and returns focus to the text box', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<Example initial={{ text: 'Does this support C0041?', tokens: [] }} onSend={onSend} />);
    const textarea = screen.getByRole('textbox', { name: 'Message' });
    await user.click(textarea);
    await user.keyboard('{Enter}');
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(textarea).toHaveFocus();
  });

  it('starts a new line on Shift+Enter without sending', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<Example initial={{ text: 'one', tokens: [] }} onSend={onSend} />);
    const textarea = screen.getByRole('textbox', { name: 'Message' });
    await user.click(textarea);
    await user.keyboard('{Shift>}{Enter}{/Shift}two');
    expect(onSend).not.toHaveBeenCalled();
    expect(textarea).toHaveValue('one\ntwo');
  });

  it('refuses to send an empty draft', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<Example onSend={onSend} />);
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    await user.click(screen.getByRole('textbox', { name: 'Message' }));
    await user.keyboard('{Enter}');
    expect(onSend).not.toHaveBeenCalled();
  });

  it('opens the reference picker on @ at a word boundary', async () => {
    const user = userEvent.setup();
    const onReferenceQuery = vi.fn();
    render(<Example onReferenceQuery={onReferenceQuery} />);
    await user.click(screen.getByRole('textbox', { name: 'Message' }));
    await user.keyboard('see @');
    expect(screen.getByRole('combobox', { name: /Insert a research reference/ })).toBeInTheDocument();
    expect(onReferenceQuery).toHaveBeenCalledWith('');
  });

  it('leaves an @ inside a word alone', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole('textbox', { name: 'Message' }));
    await user.keyboard('mail me at name@');
    expect(screen.queryByRole('combobox')).toBeNull();
  });

  it('inserts a structured token, not raw text, and drops the @ fragment', async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(<Example onValueChange={onValueChange} />);
    const textarea = screen.getByRole('textbox', { name: 'Message' });
    await user.click(textarea);
    await user.keyboard('check @');
    await user.click(screen.getByRole('option', { name: /E0482/ }));

    const last = onValueChange.mock.calls.at(-1)?.[0] as ComposerValue;
    expect(last.tokens).toEqual([SAMPLE_EVIDENCE_REF]);
    expect(last.text).toBe('check ');
    expect(textarea).toHaveFocus();
    expect(screen.getByText(/E0482/)).toBeInTheDocument();
  });

  it('closes the picker on Escape and puts focus back in the text box', async () => {
    const user = userEvent.setup();
    render(<Example />);
    const textarea = screen.getByRole('textbox', { name: 'Message' });
    await user.click(textarea);
    await user.keyboard('@');
    expect(screen.getByRole('combobox')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(textarea).toHaveFocus();
  });

  it('removes a reference token without touching the prose', async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <Example
        initial={{ text: 'keep this', tokens: [SAMPLE_EVIDENCE_REF] }}
        onValueChange={onValueChange}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Remove reference E0482' }));
    const last = onValueChange.mock.calls.at(-1)?.[0] as ComposerValue;
    expect(last.tokens).toEqual([]);
    expect(last.text).toBe('keep this');
  });

  it('blocks send with a per-item reason and leaves the draft alone', () => {
    render(
      <Example
        initial={{ text: 'here are the traces', tokens: [] }}
        blockedReasons={[
          {
            attachmentId: 'SA0005',
            reason: 'raw-traces.h5 cannot be read by the selected model.',
            suggestedModel: 'a local analysis tool',
          },
        ]}
      />,
    );
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(
      screen.getByText(/raw-traces.h5 cannot be read by the selected model/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Try a local analysis tool/)).toBeInTheDocument();
    expect(screen.getByText(/Your message and its attachments are untouched/)).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('here are the traces');
  });

  it('offers stop while streaming and returns focus after stopping', async () => {
    const user = userEvent.setup();
    const onStop = vi.fn();
    render(
      <Example
        initial={{ text: 'ask', tokens: [] }}
        sendState="streaming"
        onStop={onStop}
      />,
    );
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Stop' }));
    expect(onStop).toHaveBeenCalled();
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveFocus();
  });

  it('accepts dropped files without validating them', () => {
    const onAttach = vi.fn();
    const { container } = render(<Example onAttach={onAttach} />);
    const composer = container.querySelector('.rh-composer') as HTMLElement;
    const file = new File(['x'], 'figure.png', { type: 'image/png' });
    const dataTransfer = { files: [file] };
    const drop = new Event('drop', { bubbles: true });
    Object.defineProperty(drop, 'dataTransfer', { value: dataTransfer });
    composer.dispatchEvent(drop);
    expect(onAttach).toHaveBeenCalledWith([file]);
  });

  it('renders the attachment tray and model selector slots', () => {
    render(
      <Example
        attachmentTray={<p>tray slot</p>}
        modelSelector={<p>model slot</p>}
      />,
    );
    expect(screen.getByText('tray slot')).toBeInTheDocument();
    expect(screen.getByText('model slot')).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <Example
        initial={{ text: 'draft', tokens: [SAMPLE_EVIDENCE_REF] }}
        onAttach={() => undefined}
        onRetry={() => undefined}
        blockedReasons={[{ reason: 'The provider is offline.' }]}
      />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('Composer', () => (
  <Composer
    value={{ text: 'Does the sweep support C0041?', tokens: [SAMPLE_EVIDENCE_REF] }}
    onChange={() => undefined}
    onSend={() => undefined}
    onAttach={() => undefined}
  />
));

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { SAMPLE_MODELS } from '../samples';
import { ModelSelector } from './ModelSelector';

describe('ModelSelector', () => {
  it('names the current model and where its requests go', () => {
    render(
      <ModelSelector options={SAMPLE_MODELS} value="local-llama" onChange={() => undefined} />,
    );
    const trigger = screen.getByRole('button', { name: /Model: Llama 3.1 70B/ });
    expect(trigger).toHaveTextContent('Llama 3.1 70B');
    expect(trigger).toHaveTextContent('Local');
  });

  it('states egress and vision in words on every option', async () => {
    const user = userEvent.setup();
    render(
      <ModelSelector options={SAMPLE_MODELS} value="claude-opus-5" onChange={() => undefined} />,
    );
    await user.click(screen.getByRole('button', { name: /Model:/ }));
    const local = screen.getByRole('menuitem', { name: /Llama 3.1 70B/ });
    expect(local).toHaveTextContent('Local');
    expect(local).toHaveTextContent('Text only');
    const opus = screen.getByRole('menuitem', { name: /Claude Opus 5/ });
    expect(opus).toHaveTextContent('External');
    expect(opus).toHaveTextContent('Reads images');
    expect(opus).toHaveTextContent('200,000 tok context');
  });

  it('keeps an unavailable model visible with its reason', async () => {
    const user = userEvent.setup();
    render(
      <ModelSelector options={SAMPLE_MODELS} value="claude-opus-5" onChange={() => undefined} />,
    );
    await user.click(screen.getByRole('button', { name: /Model:/ }));
    const blocked = screen.getByRole('menuitem', { name: /Vision preview/ });
    expect(blocked).toHaveAttribute('aria-disabled', 'true');
    expect(blocked).toHaveTextContent('No API key is configured for this provider.');
  });

  it('chooses a model from the keyboard', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ModelSelector options={SAMPLE_MODELS} value="claude-opus-5" onChange={onChange} />);
    await user.tab();
    await user.keyboard('{ArrowDown}');
    await user.keyboard('{ArrowDown}{Enter}');
    expect(onChange).toHaveBeenCalledWith(SAMPLE_MODELS[1]);
  });

  it('does not choose a model the host says is unavailable', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ModelSelector options={SAMPLE_MODELS} value="claude-opus-5" onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: /Model:/ }));
    await user.click(screen.getByRole('menuitem', { name: /Vision preview/ }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('has no accessibility violations', async () => {
    const user = userEvent.setup();
    render(
      <ModelSelector options={SAMPLE_MODELS} value="claude-opus-5" onChange={() => undefined} />,
    );
    await expectNoAxeViolations(document.body);
    await user.click(screen.getByRole('button', { name: /Model:/ }));
    await expectNoAxeViolations(document.body);
  });
});

describeThemeDensitySnapshots('ModelSelector', () => (
  <ModelSelector options={SAMPLE_MODELS} value="claude-opus-5" onChange={() => undefined} />
));

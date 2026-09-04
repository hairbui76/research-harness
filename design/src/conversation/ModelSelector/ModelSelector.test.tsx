import { render, screen, within } from '@testing-library/react';
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

  it('renders groups with their label as the accessible name and keeps disabled reasons', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ModelSelector
        options={SAMPLE_MODELS.slice(0, 1)}
        groups={[
          {
            id: 'codex',
            label: 'Codex CLI 0.150.1',
            options: [
              {
                id: 'runtime:codex:gpt-5.5',
                label: 'gpt-5.5',
                provider: 'Codex CLI',
                egressClass: 'external',
                vision: true,
                contextTokens: null,
                available: true,
              },
              {
                id: 'runtime:cursor-agent',
                label: 'Cursor Agent 1.4.0',
                provider: 'Cursor Agent',
                egressClass: 'external',
                vision: false,
                contextTokens: null,
                available: false,
                unavailableReason:
                  'cursor-agent 1.4.0 has no tested bounded (no-tools, read-only) mode',
              },
            ],
          },
        ]}
        value="claude-opus-5"
        onChange={onChange}
      />,
    );
    await user.click(screen.getByRole('button', { name: /Model:/ }));
    const group = screen.getByRole('group', { name: 'Codex CLI 0.150.1' });
    expect(within(group).getByRole('menuitem', { name: /gpt-5\.5/ })).toBeEnabled();
    const blocked = within(group).getByRole('menuitem', { name: /Cursor Agent 1\.4\.0/ });
    expect(blocked).toHaveAttribute('aria-disabled', 'true');
    expect(within(group).getByText(/has no tested bounded/)).toBeInTheDocument();
    await user.click(within(group).getByRole('menuitem', { name: /gpt-5\.5/ }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'runtime:codex:gpt-5.5' }),
    );
  });

  it('renders a model with no declared context window without a token count', async () => {
    const user = userEvent.setup();
    render(
      <ModelSelector
        options={[
          {
            id: 'runtime:codex:gpt-5.5',
            label: 'gpt-5.5',
            provider: 'Codex CLI',
            egressClass: 'external',
            vision: true,
            contextTokens: null,
            available: true,
          },
        ]}
        value="runtime:codex:gpt-5.5"
        onChange={() => undefined}
      />,
    );
    await user.click(screen.getByRole('button', { name: /Model:/ }));
    expect(screen.queryByText(/ctx|tokens|k\b/)).not.toBeInTheDocument();
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

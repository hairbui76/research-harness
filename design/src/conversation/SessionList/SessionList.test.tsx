import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import type { SessionSummary } from '../models';
import { SAMPLE_SESSIONS } from '../samples';
import { SessionList } from './SessionList';

const MANY: SessionSummary[] = Array.from({ length: 60 }, (_, index) => ({
  id: `CS${String(index + 1).padStart(4, '0')}`,
  title: `Session ${index + 1}`,
  updatedAt: '2026-09-01T10:00:00Z',
  messageCount: index,
  visibility: 'project',
}));

describe('SessionList', () => {
  it('lists sessions with their id, time and message count', () => {
    render(<SessionList sessions={SAMPLE_SESSIONS} />);
    expect(screen.getByText('Stiffness threshold for C0041')).toBeInTheDocument();
    expect(screen.getByText('CS0001')).toBeInTheDocument();
    expect(screen.getByText('24 messages')).toBeInTheDocument();
  });

  it('shows a session binding under the title when the record has one', () => {
    render(
      <SessionList
        sessions={[
          {
            id: 'CS0001',
            title: 'Stiffness threshold for C0041',
            updatedAt: '2026-09-03T14:20:38Z',
            messageCount: 24,
            visibility: 'project',
            binding: 'session:codex/gpt-5.5 (reasoning high)',
          },
        ]}
        activeId={null}
        onSelect={() => undefined}
        query=""
        onQueryChange={() => undefined}
      />,
    );
    expect(screen.getByText('session:codex/gpt-5.5 (reasoning high)')).toBeInTheDocument();
  });

  it('marks a private session so local-only data says so', () => {
    const { container } = render(<SessionList sessions={SAMPLE_SESSIONS} />);
    const badges = container.querySelectorAll('[data-status="private"]');
    expect(badges).toHaveLength(1);
    expect(badges[0]).toHaveTextContent('Private');
  });

  it('marks the active session for assistive technology', () => {
    render(<SessionList sessions={SAMPLE_SESSIONS} activeId="CS0004" />);
    expect(screen.getByRole('button', { name: /Grant notes/ })).toHaveAttribute(
      'aria-current',
      'true',
    );
  });

  it('selects a session and starts a new one', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onNewSession = vi.fn();
    render(
      <SessionList sessions={SAMPLE_SESSIONS} onSelect={onSelect} onNewSession={onNewSession} />,
    );
    await user.click(screen.getByRole('button', { name: /Taxonomy clean-up/ }));
    expect(onSelect).toHaveBeenCalledWith('CS0007');
    await user.click(screen.getByRole('button', { name: 'New' }));
    expect(onNewSession).toHaveBeenCalled();
  });

  it('reports typing in the search box', async () => {
    const user = userEvent.setup();
    const onQueryChange = vi.fn();
    render(<SessionList sessions={SAMPLE_SESSIONS} onQueryChange={onQueryChange} />);
    await user.type(screen.getByRole('searchbox', { name: 'Search sessions' }), 'sti');
    expect(onQueryChange).toHaveBeenCalledTimes(3);
  });

  it('renames inline: Enter commits', async () => {
    const user = userEvent.setup();
    const onRename = vi.fn();
    render(<SessionList sessions={SAMPLE_SESSIONS} onRename={onRename} />);
    await user.click(screen.getByRole('button', { name: 'Rename Grant notes' }));
    const input = screen.getByRole('textbox', { name: 'Rename Grant notes' });
    await user.clear(input);
    await user.type(input, 'Funding notes{Enter}');
    expect(onRename).toHaveBeenCalledWith('CS0004', 'Funding notes');
  });

  it('renames inline: Escape cancels and keeps the old title', async () => {
    const user = userEvent.setup();
    const onRename = vi.fn();
    render(<SessionList sessions={SAMPLE_SESSIONS} onRename={onRename} />);
    await user.click(screen.getByRole('button', { name: 'Rename Grant notes' }));
    const input = screen.getByRole('textbox', { name: 'Rename Grant notes' });
    await user.clear(input);
    await user.type(input, 'Something else{Escape}');
    expect(onRename).not.toHaveBeenCalled();
    expect(screen.queryByRole('textbox', { name: 'Rename Grant notes' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Rename Grant notes' })).toBeInTheDocument();
  });

  it('shows an empty state rather than an empty box', () => {
    render(<SessionList sessions={[]} onNewSession={() => undefined} />);
    expect(screen.getByText('No sessions yet')).toBeInTheDocument();
    expect(screen.getByText(/Start a session to ask a question/)).toBeInTheDocument();
  });

  it('shows a loading state while the host is fetching', () => {
    render(<SessionList sessions={[]} loading />);
    expect(screen.getByText('Loading sessions')).toBeInTheDocument();
  });

  it('windows a long history instead of rendering a thousand rows', () => {
    render(<SessionList sessions={MANY} label="Sessions" />);
    const list = screen.getByRole('list', { name: 'Sessions' });
    expect(list).toHaveClass('rh-virtual-list');
    expect(screen.getAllByRole('listitem').length).toBeLessThan(MANY.length);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <SessionList
        sessions={SAMPLE_SESSIONS}
        activeId="CS0001"
        onSelect={() => undefined}
        onNewSession={() => undefined}
        onRename={() => undefined}
        onQueryChange={() => undefined}
        query=""
      />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('SessionList', () => (
  <SessionList
    sessions={SAMPLE_SESSIONS}
    activeId="CS0001"
    onSelect={() => undefined}
    onNewSession={() => undefined}
    onRename={() => undefined}
  />
));

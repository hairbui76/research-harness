/**
 * The shortcut layer (critique P1: "zero shortcuts, no palette").
 *
 * Two properties carry the whole feature. A key must reach the page's own handler — the
 * command runs what the button runs, so a shortcut and a control cannot drift apart — and a
 * key must stay out of the way while a researcher is writing a sentence a decision will be
 * recorded with, or answering a dialog they are already inside.
 */
import { describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Dialog, DialogBody, DialogHeader, ThemeProvider } from '@research-harness/design';
import { CommandsProvider, useRegisterCommands } from './CommandsProvider';
import { groupCommands, matchCommands } from './model';
import { expectNoAxeViolations } from '../../test/harness';

const DESTINATIONS = [
  { id: 'overview', label: 'Overview', to: '/overview' },
  { id: 'review', label: 'Review inbox', to: '/review' },
  { id: 'corpus', label: 'Corpus', to: '/corpus' },
];

function Page({ accept, children }: { accept: () => void; children?: ReactNode }) {
  useRegisterCommands(
    () => [
      {
        id: 'review:accept',
        label: 'Accept',
        group: 'Review',
        shortcut: 'a',
        hint: 'Record this candidate as accepted Evidence.',
        run: accept,
      },
    ],
    [accept],
  );
  return <div>{children ?? <p>the page</p>}</div>;
}

function renderShell(ui: ReactNode) {
  return render(
    <ThemeProvider defaultTheme="dark" storageKey={null}>
      <MemoryRouter
        initialEntries={['/']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <CommandsProvider destinations={DESTINATIONS}>
          <Routes>
            <Route path="/" element={<>{ui}</>} />
            <Route path="/review" element={<h1>Review inbox</h1>} />
            <Route path="/corpus" element={<h1>Corpus</h1>} />
          </Routes>
        </CommandsProvider>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('matching', () => {
  const commands = [
    { id: 'a', label: 'Review inbox', group: 'Go to', run: () => {} },
    { id: 'b', label: 'Corpus', group: 'Go to', run: () => {} },
    { id: 'c', label: 'Accept', group: 'Review', hint: 'accepted Evidence', run: () => {} },
  ];

  it('needs every term, so two words narrow further than one', () => {
    expect(matchCommands(commands, 'rev').map((command) => command.id)).toEqual(['a', 'c']);
    expect(matchCommands(commands, 'rev inb').map((command) => command.id)).toEqual(['a']);
  });

  it('keeps the registration order rather than ranking anything', () => {
    expect(matchCommands(commands, '').map((command) => command.id)).toEqual(['a', 'b', 'c']);
  });

  it('groups under the heading each command named, in first-seen order', () => {
    expect(groupCommands(commands).map(([group]) => group)).toEqual(['Go to', 'Review']);
  });
});

describe('the command palette', () => {
  it('opens on Ctrl+K listing the rail’s destinations and the page’s own actions', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('{Control>}k{/Control}');

    expect(screen.getByRole('dialog', { name: 'Go to, or do' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Review inbox/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Accept/ })).toBeInTheDocument();
  });

  it('narrows as the researcher types and runs the match Enter lands on', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('{Control>}k{/Control}');
    await user.type(screen.getByRole('combobox'), 'corp');

    expect(screen.getAllByRole('option')).toHaveLength(1);
    await user.keyboard('{Enter}');

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Corpus' })).toBeInTheDocument());
  });

  it('runs the page’s own handler, never a copy of it', async () => {
    const accept = vi.fn();
    const user = userEvent.setup();
    renderShell(<Page accept={accept} />);

    await user.keyboard('{Control>}k{/Control}');
    await user.type(screen.getByRole('combobox'), 'accept');
    await user.keyboard('{Enter}');

    expect(accept).toHaveBeenCalledTimes(1);
  });

  it('says nothing matched rather than showing an empty list', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('{Control>}k{/Control}');
    await user.type(screen.getByRole('combobox'), 'zzzz');

    expect(screen.queryAllByRole('option')).toHaveLength(0);
    expect(screen.getByText(/Nothing here is called/)).toBeInTheDocument();
  });

  it('has no automatically detectable accessibility violation', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('{Control>}k{/Control}');
    await expectNoAxeViolations(document.body);
  });
});

describe('the shortcut help sheet', () => {
  it('lists the shell’s keys and every key the open page bound', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('?');

    const sheet = screen.getByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(sheet).toHaveTextContent('Command palette');
    expect(sheet).toHaveTextContent('Accept');
    expect(sheet).toHaveTextContent('Record this candidate as accepted Evidence.');
  });

  it('has no automatically detectable accessibility violation', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('?');
    await expectNoAxeViolations(document.body);
  });
});

describe('when a shortcut must not fire', () => {
  it('runs a registered key when the researcher is not typing', async () => {
    const accept = vi.fn();
    const user = userEvent.setup();
    renderShell(<Page accept={accept} />);

    await user.keyboard('a');

    expect(accept).toHaveBeenCalledTimes(1);
  });

  it('stays out of a text box, where “a” is a letter of a sentence', async () => {
    const accept = vi.fn();
    const user = userEvent.setup();
    renderShell(
      <Page accept={accept}>
        <textarea aria-label="Why this candidate is refused" />
      </Page>,
    );

    await user.click(screen.getByLabelText('Why this candidate is refused'));
    await user.keyboard('a candidate about anchors');

    expect(accept).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Why this candidate is refused')).toHaveValue(
      'a candidate about anchors',
    );
  });

  it('does not reach past a dialog the researcher is already answering', async () => {
    const accept = vi.fn();
    const user = userEvent.setup();
    renderShell(
      <Page accept={accept}>
        <Dialog open>
          <DialogHeader>Edit the proposed evidence</DialogHeader>
          <DialogBody>
            <button type="button">Save</button>
          </DialogBody>
        </Dialog>
      </Page>,
    );

    await user.keyboard('a');
    await user.keyboard('{Control>}k{/Control}');

    expect(accept).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog', { name: 'Go to, or do' })).not.toBeInTheDocument();
  });

  it('still works under a closed drawer, which stays in the document while hidden', async () => {
    const accept = vi.fn();
    const user = userEvent.setup();
    renderShell(
      <Page accept={accept}>
        {/* What `AppShell` renders below its breakpoint: a drawer that is mounted and
            hidden. It is a dialog in the markup and nothing at all on the screen. */}
        <div hidden>
          <div role="dialog" aria-modal="false" aria-label="Project navigation" />
        </div>
      </Page>,
    );

    await user.keyboard('a');

    expect(accept).toHaveBeenCalledTimes(1);
  });

  it('forgets a page’s keys as soon as the page is gone', async () => {
    const accept = vi.fn();
    const user = userEvent.setup();
    const { rerender } = renderShell(<Page accept={accept} />);

    rerender(
      <ThemeProvider defaultTheme="dark" storageKey={null}>
        <MemoryRouter
          initialEntries={['/']}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <CommandsProvider destinations={DESTINATIONS}>
            <p>another screen</p>
          </CommandsProvider>
        </MemoryRouter>
      </ThemeProvider>,
    );

    await user.keyboard('a');

    expect(accept).not.toHaveBeenCalled();
  });
});

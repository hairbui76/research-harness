/**
 * The shortcut layer (critique P1: "zero shortcuts, no palette").
 *
 * Two properties carry the whole feature. A key must reach the page's own handler — the
 * command runs what the button runs, so a shortcut and a control cannot drift apart — and a
 * key must stay out of the way while a researcher is writing a sentence a decision will be
 * recorded with, or answering a dialog they are already inside.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Dialog, DialogBody, DialogHeader, ThemeProvider } from '@research-harness/design';
import { CommandsProvider, SINGLE_KEY_SHORTCUTS, useRegisterCommands } from './CommandsProvider';
import { groupCommands, matchCommands } from './model';
import { expectNoAxeViolations } from '../../test/harness';

beforeEach(() => {
  window.localStorage.clear();
});

/** The rail's own list, headings and all: the palette files a destination where the rail does. */
const DESTINATIONS = [
  { id: 'overview', label: 'Overview', to: '/overview' },
  { id: 'review', label: 'Review inbox', to: '/review', group: 'Waiting' },
  { id: 'corpus', label: 'Corpus', to: '/corpus', group: 'The record' },
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

  it('files a destination under the rail’s own heading', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('{Control>}k{/Control}');

    // Roadmap 3L: the rail groups its destinations, and the palette must not call the same
    // page something else. An ungrouped way in is still filed under "Go to".
    // The palette has two sections — where you can go, and what you can do here — and the
    // rail's own headings sit inside the first (wave 5J added the sections; before them the
    // list ran destinations into actions with nothing saying which was which).
    expect(
      screen
        .getAllByRole('group')
        .map((group) => group.getAttribute('aria-label')),
    ).toEqual(['Go to', 'Waiting', 'The record', 'Actions', 'Review', 'Anywhere']);
    expect(
      within(screen.getByRole('group', { name: 'Waiting' })).getByRole('option', {
        name: /Review inbox/,
      }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('group', { name: 'Go to' })).getByRole('option', {
        name: /Overview/,
      }),
    ).toBeInTheDocument();
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

/**
 * `g` then a letter, the way every keyboard-first product does it.
 *
 * A destination is not an action, so it does not take a single letter: those belong to the
 * screen in front of the researcher, where `a` accepts a candidate. The chord is a lead key
 * that binds nothing on its own, and the letter after it is consumed by the chord whether
 * or not it names a destination — so `g` followed by a stray `a` goes nowhere rather than
 * accepting something.
 */
describe('the chords that go somewhere', () => {
  it('takes the researcher to a screen on “g” then its letter', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('g');
    await user.keyboard('r');

    expect(await screen.findByRole('heading', { name: 'Review inbox' })).toBeInTheDocument();
  });

  it('consumes the letter after “g”, so a stray one decides nothing', async () => {
    const accept = vi.fn();
    const user = userEvent.setup();
    renderShell(<Page accept={accept} />);

    await user.keyboard('g');
    await user.keyboard('a');

    expect(accept, 'the second key belongs to the chord, not to the page').not.toHaveBeenCalled();
    expect(screen.getByText('the page')).toBeInTheDocument();
  });

  it('runs the page’s own keys again once the chord is over', async () => {
    const accept = vi.fn();
    const user = userEvent.setup();
    renderShell(<Page accept={accept} />);

    await user.keyboard('g');
    await user.keyboard('{Escape}');
    await user.keyboard('a');

    expect(accept).toHaveBeenCalledTimes(1);
  });

  it('says a chord is waiting rather than swallowing a key in silence', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('g');
    const waiting = screen.getByRole('status');
    expect(waiting).toHaveTextContent(/Go to/);

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('prints the chord beside the destination in the palette', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('{Control>}k{/Control}');

    const destination = screen.getByRole('option', { name: /Review inbox/ });
    expect(
      Array.from(destination.querySelectorAll('kbd')).map((key) => key.textContent),
    ).toEqual(['g', 'r']);
    expect(
      Array.from(
        screen.getByRole('option', { name: /Accept/ }).querySelectorAll('kbd'),
      ).map((key) => key.textContent),
      'a page action keeps its own single key',
    ).toEqual(['a']);
  });

  it('lists every chord in the help sheet, under its own heading', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('?');

    const going = screen.getByRole('heading', { name: 'Go to a screen' }).parentElement!;
    expect(going).toHaveTextContent('Review inbox');
    expect(going).toHaveTextContent('Corpus');
    // Two keys printed per row, in the order they are pressed. The section's own note
    // names the lead key once more, above the list, which is why the list is read here.
    expect(
      Array.from(going.querySelector('dl')!.querySelectorAll('kbd')).map((key) => key.textContent),
    ).toEqual(['g', 'o', 'g', 'r', 'g', 'c']);
  });

  it('goes off with the single keys, and stops being printed', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(SINGLE_KEY_SHORTCUTS, 'false');
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('g');
    await user.keyboard('r');
    expect(screen.queryByRole('heading', { name: 'Review inbox' })).toBeNull();

    await user.keyboard('{Control>}k{/Control}');
    expect(
      screen.getByRole('dialog', { name: 'Go to, or do' }).querySelectorAll('kbd'),
      'a key that would not fire is not printed as if it would',
    ).toHaveLength(0);
  });
});

/**
 * The palette says which half of it is which.
 *
 * Alex opens it and sees a list of screens; nothing tells him this page has actions at all
 * (critique H7). The two sections are the answer, and the actions one is on screen before
 * anything is typed — on a page that registers none, it still holds the shell's own.
 */
describe('the palette’s two sections', () => {
  it('shows what this screen can do, in a group named for what they are', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('{Control>}k{/Control}');

    const actions = screen.getByRole('group', { name: 'Actions' });
    expect(within(actions).getByRole('option', { name: /Accept/ })).toBeInTheDocument();
    expect(within(actions).getByRole('option', { name: /Keyboard shortcuts/ })).toBeInTheDocument();
    expect(within(actions).queryByRole('option', { name: /Corpus/ })).toBeNull();
  });

  it('offers the actions group on a screen that registers none of its own', async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider defaultTheme="dark" storageKey={null}>
        <MemoryRouter
          initialEntries={['/']}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <CommandsProvider destinations={DESTINATIONS}>
            <p>a screen with no actions of its own</p>
          </CommandsProvider>
        </MemoryRouter>
      </ThemeProvider>,
    );

    await user.keyboard('{Control>}k{/Control}');

    expect(screen.getByRole('group', { name: 'Actions' })).toBeInTheDocument();
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

/**
 * WCAG 2.1.4: a shortcut bound to a single character must be switchable off.
 *
 * The keys here are letters pressed with no modifier at all, and one of them accepts a
 * candidate. Someone dictating, or driving the cockpit with a switch device, sends stray
 * characters into the page — so the layer has to be turnable off, and nothing may become
 * unreachable when it is.
 */
describe('turning the single-key shortcuts off', () => {
  it('is offered in the help sheet and remembered', async () => {
    const user = userEvent.setup();
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('?');
    const toggle = screen.getByRole('switch', { name: 'Single-key shortcuts' });
    expect(toggle).toBeChecked();

    await user.click(toggle);

    expect(screen.getByRole('switch', { name: 'Single-key shortcuts' })).not.toBeChecked();
    expect(window.localStorage.getItem(SINGLE_KEY_SHORTCUTS)).toBe('false');
  });

  it('stops a single letter from running anything', async () => {
    const accept = vi.fn();
    const user = userEvent.setup();
    window.localStorage.setItem(SINGLE_KEY_SHORTCUTS, 'false');
    renderShell(<Page accept={accept} />);

    await user.keyboard('a');
    await user.keyboard('?');

    expect(accept).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).not.toBeInTheDocument();
  });

  it('keeps the modifier chord, so the palette is still one keystroke away', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(SINGLE_KEY_SHORTCUTS, 'false');
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('{Control>}k{/Control}');

    expect(screen.getByRole('dialog', { name: 'Go to, or do' })).toBeInTheDocument();
  });

  it('leaves the help sheet reachable through the palette', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(SINGLE_KEY_SHORTCUTS, 'false');
    renderShell(<Page accept={() => {}} />);

    await user.keyboard('{Control>}k{/Control}');
    await user.type(screen.getByRole('combobox'), 'keyboard');
    await user.keyboard('{Enter}');

    const sheet = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(sheet).toHaveTextContent('Single-key shortcuts');
  });

  it('survives a reload, because the preference is not held in the page', async () => {
    const accept = vi.fn();
    const user = userEvent.setup();
    const { unmount } = renderShell(<Page accept={accept} />);

    await user.keyboard('?');
    await user.click(screen.getByRole('switch', { name: 'Single-key shortcuts' }));
    unmount();

    renderShell(<Page accept={accept} />);
    await user.keyboard('a');

    expect(accept).not.toHaveBeenCalled();
    await user.keyboard('{Control>}k{/Control}');
    await user.type(screen.getByRole('combobox'), 'keyboard');
    await user.keyboard('{Enter}');
    expect(
      await screen.findByRole('switch', { name: 'Single-key shortcuts' }),
    ).not.toBeChecked();
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

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { AppShell } from './AppShell';
import { ThemeProvider } from '../ThemeProvider';

function Draft(): JSX.Element {
  const [text, setText] = useState('');
  return (
    <label>
      Draft
      <textarea value={text} onChange={(event) => setText(event.target.value)} />
    </label>
  );
}

function Example({ narrow }: { narrow?: boolean }): JSX.Element {
  const [railOpen, setRailOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  return (
    <AppShell
      narrow={narrow}
      rail={
        <nav aria-label="Sessions">
          <a href="#one">Session one</a>
        </nav>
      }
      main={<Draft />}
      inspector={<section aria-label="Inspector body">Evidence</section>}
      railOpen={railOpen}
      onRailOpenChange={setRailOpen}
      inspectorOpen={inspectorOpen}
      onInspectorOpenChange={setInspectorOpen}
    />
  );
}

describe('AppShell', () => {
  it('puts a skip link ahead of the rail and points it at main', async () => {
    const user = userEvent.setup();
    render(<Example />);
    const skip = screen.getByRole('link', { name: 'Skip to main content' });
    const main = screen.getByRole('main');
    expect(skip.getAttribute('href')).toBe(`#${main.id}`);

    await user.tab();
    expect(skip).toHaveFocus();
  });

  it('lays the three slots out side by side on a wide screen', () => {
    render(
      <AppShell
        narrow={false}
        rail={<nav aria-label="Sessions">rail</nav>}
        main={<p>main</p>}
        inspector={<section aria-label="Inspector body">inspector</section>}
        inspectorOpen
      />,
    );
    expect(screen.getByRole('navigation', { name: 'Sessions' })).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'Research inspector' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('turns the side panes into non-modal drawers below the breakpoint', async () => {
    const user = userEvent.setup();
    render(<Example narrow />);

    await user.click(screen.getByRole('button', { name: 'Project navigation' }));
    const drawer = screen.getByRole('dialog', { name: 'Project navigation' });
    expect(drawer).toHaveAttribute('aria-modal', 'false');
    // The main surface is still mounted behind the scrim.
    expect(screen.getByLabelText('Draft')).toBeInTheDocument();
  });

  it('keeps the draft mounted while a drawer opens and closes', async () => {
    const user = userEvent.setup();
    render(<Example narrow />);
    const draft = screen.getByLabelText('Draft');
    await user.type(draft, 'unsent words');

    await user.click(screen.getByRole('button', { name: 'Research inspector' }));
    expect(screen.getByRole('dialog', { name: 'Research inspector' })).toBeInTheDocument();
    expect(screen.getByLabelText('Draft')).toHaveValue('unsent words');

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Draft')).toHaveValue('unsent words');
  });

  it('moves focus into a drawer and gives it back when it closes', async () => {
    const user = userEvent.setup();
    render(<Example narrow />);
    const opener = screen.getByRole('button', { name: 'Project navigation' });
    await user.click(opener);
    expect(
      screen.getByRole('button', { name: 'Close project navigation' }),
    ).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(opener).toHaveFocus();
  });

  it('mirrors the appearance from the ThemeProvider onto its root', () => {
    const { container } = render(
      <ThemeProvider theme="light" density="compact" storageKey={null}>
        <AppShell narrow={false} main={<p>main</p>} />
      </ThemeProvider>,
    );
    expect(container.firstChild).toHaveAttribute('data-theme', 'light');
    expect(container.firstChild).toHaveAttribute('data-density', 'compact');
  });

  it('has no axe violations, wide or narrow', async () => {
    const wide = render(
      <AppShell
        narrow={false}
        rail={<nav aria-label="Sessions">rail</nav>}
        main={<p>main</p>}
        inspector={<section aria-label="Inspector body">inspector</section>}
        inspectorOpen
      />,
    );
    await expectNoAxeViolations(wide.container);
    wide.unmount();

    const user = userEvent.setup();
    const narrow = render(<Example narrow />);
    await user.click(screen.getByRole('button', { name: 'Project navigation' }));
    await expectNoAxeViolations(narrow.container);
  });

  it('does not force a drawer without matchMedia', () => {
    const original = window.matchMedia;
    // jsdom has no matchMedia; the shell must render the wide layout rather than crash.
    Reflect.deleteProperty(window, 'matchMedia');
    render(<AppShell main={<p>main</p>} inspector={<section aria-label="i">x</section>} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    if (original) window.matchMedia = original;
  });
});

describeThemeDensitySnapshots('AppShell', () => (
  <AppShell
    narrow={false}
    rail={<nav aria-label="Sessions">rail</nav>}
    main={<p>main</p>}
    inspector={<section aria-label="Inspector body">inspector</section>}
    inspectorOpen
    onInspectorOpenChange={vi.fn()}
  />
));

import { render, screen, within } from '@testing-library/react';
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

  it('names the destination on show beside the context it sits in', () => {
    render(
      <AppShell
        narrow
        rail={<nav aria-label="Sessions">rail</nav>}
        main={<p>main</p>}
        barTitle="Latency study"
        pageLabel="Review inbox"
      />,
    );

    // Below the breakpoint the rail is a drawer, so the bar is the only place left that
    // can say where you are: which workspace, and which of its screens.
    const bar = screen.getByRole('banner');
    expect(within(bar).getByText('Latency study')).toBeInTheDocument();
    expect(within(bar).getByText('Review inbox')).toBeInTheDocument();
    // The drawer control keeps its own name; the title is text beside it, not on it.
    expect(within(bar).getByRole('button', { name: 'Project navigation' })).toBeInTheDocument();
    // The glyph between the two is decoration, and is never read out as one.
    expect(bar.querySelector('.rh-app-shell__bar-separator')).toHaveAttribute(
      'aria-hidden',
      'true',
    );
  });

  it('falls back to the main landmark name when no destination is named', () => {
    render(<AppShell narrow main={<p>main</p>} mainLabel="Research workspace" />);

    const bar = screen.getByRole('banner');
    expect(bar).toHaveTextContent('Research workspace');
    expect(bar.querySelector('.rh-app-shell__bar-page')).toBeNull();
  });

  it('gives the context away before the page name, and only the context', () => {
    render(
      <AppShell
        narrow
        main={<p>main</p>}
        barTitle="A workspace with a very long display name indeed"
        pageLabel="Manuscript"
      />,
    );

    const bar = screen.getByRole('banner');
    const context = bar.querySelector('.rh-app-shell__bar-context');
    const page = bar.querySelector('.rh-app-shell__bar-page');
    // The rule is in the stylesheet, so what a jsdom test can hold is the structure the
    // stylesheet targets: two parts, each one findable, in that order. `fit.spec.ts`
    // measures the page name against a real 768px viewport.
    expect(context).not.toBeNull();
    expect(page).not.toBeNull();
    expect(context?.compareDocumentPosition(page as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
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

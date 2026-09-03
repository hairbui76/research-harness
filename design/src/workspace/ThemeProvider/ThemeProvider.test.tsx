import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { THEME_STORAGE_KEY, ThemeProvider, useOptionalTheme, useTheme } from './ThemeProvider';

function Appearance(): JSX.Element {
  const { theme, density, setTheme, setDensity, prefersReducedMotion } = useTheme();
  return (
    <div>
      <p data-testid="state">{`${theme}/${density}/${prefersReducedMotion}`}</p>
      <button type="button" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
        Toggle theme
      </button>
      <button
        type="button"
        onClick={() => setDensity(density === 'comfortable' ? 'compact' : 'comfortable')}
      >
        Toggle density
      </button>
    </div>
  );
}

function OptionalAppearance(): JSX.Element {
  const appearance = useOptionalTheme();
  return <p data-testid="optional">{appearance === null ? 'no provider' : appearance.theme}</p>;
}

describe('ThemeProvider', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    document.documentElement.removeAttribute('data-density');
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it('defaults to dark and comfortable and writes them onto the document element', () => {
    render(
      <ThemeProvider>
        <Appearance />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('state')).toHaveTextContent('dark/comfortable/false');
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(document.documentElement).toHaveAttribute('data-density', 'comfortable');
  });

  it('switches theme and density and persists both under a namespaced key', async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <Appearance />
      </ThemeProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'Toggle theme' }));
    await user.click(screen.getByRole('button', { name: 'Toggle density' }));

    expect(screen.getByTestId('state')).toHaveTextContent('light/compact');
    expect(document.documentElement).toHaveAttribute('data-theme', 'light');
    expect(document.documentElement).toHaveAttribute('data-density', 'compact');
    expect(JSON.parse(window.localStorage.getItem(THEME_STORAGE_KEY) ?? '{}')).toEqual({
      theme: 'light',
      density: 'compact',
    });
  });

  it('starts from the stored preference', () => {
    window.localStorage.setItem(
      THEME_STORAGE_KEY,
      JSON.stringify({ theme: 'light', density: 'compact' }),
    );
    render(
      <ThemeProvider>
        <Appearance />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('state')).toHaveTextContent('light/compact');
  });

  it('ignores stored rubbish rather than rendering an unknown theme', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, '{"theme":"neon","density":42}');
    render(
      <ThemeProvider>
        <Appearance />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('state')).toHaveTextContent('dark/comfortable');
  });

  it('survives a localStorage that throws', () => {
    const getItem = vi
      .spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => {
        throw new Error('The operation is insecure.');
      });
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });

    render(
      <ThemeProvider>
        <Appearance />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('state')).toHaveTextContent('dark/comfortable');
    getItem.mockRestore();
    setItem.mockRestore();
  });

  it('stores nothing when the storage key is null', async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider storageKey={null}>
        <Appearance />
      </ThemeProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Toggle theme' }));
    expect(window.localStorage.length).toBe(0);
  });

  it('honours a controlled theme and reports the change to the caller', async () => {
    const user = userEvent.setup();
    const onThemeChange = vi.fn();
    render(
      <ThemeProvider theme="light" onThemeChange={onThemeChange}>
        <Appearance />
      </ThemeProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Toggle theme' }));
    expect(onThemeChange).toHaveBeenCalledWith('dark');
    // Controlled: the provider does not move on its own.
    expect(screen.getByTestId('state')).toHaveTextContent('light/comfortable');
  });

  it('can scope the attributes to a subtree instead of the document', () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    render(
      <ThemeProvider target={host} theme="light" density="compact">
        <Appearance />
      </ThemeProvider>,
    );
    expect(host).toHaveAttribute('data-theme', 'light');
    expect(document.documentElement).not.toHaveAttribute('data-theme');
    host.remove();
  });

  it('restores the previous attributes when it unmounts', () => {
    document.documentElement.setAttribute('data-theme', 'light');
    const { unmount } = render(
      <ThemeProvider theme="dark">
        <Appearance />
      </ThemeProvider>,
    );
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    unmount();
    expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  });

  it('throws from useTheme outside a provider and returns null from useOptionalTheme', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    expect(() => render(<Appearance />)).toThrow(/must be called inside a <ThemeProvider>/);
    error.mockRestore();

    render(<OptionalAppearance />);
    expect(screen.getByTestId('optional')).toHaveTextContent('no provider');
  });
});

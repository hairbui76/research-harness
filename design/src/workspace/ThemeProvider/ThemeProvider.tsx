import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { useReducedMotion } from '../../hooks/useReducedMotion';

/** The themes the package ships. Dark is the default and needs no attribute. */
export type Theme = 'dark' | 'light';
/** Density modes. `comfortable` reads, `compact` scans. */
export type Density = 'comfortable' | 'compact';

const THEME_VALUES: readonly Theme[] = ['dark', 'light'];
const DENSITY_VALUES: readonly Density[] = ['comfortable', 'compact'];

/** Namespaced so the Design System never collides with an application's own storage. */
export const THEME_STORAGE_KEY = 'research-harness:design:appearance';

export interface ThemeContextValue {
  theme: Theme;
  density: Density;
  setTheme: (theme: Theme) => void;
  setDensity: (density: Density) => void;
  /** Mirrors `prefers-reduced-motion: reduce`, for the rare JS-driven animation. */
  prefersReducedMotion: boolean;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export interface ThemeProviderProps {
  /** Controlled theme. Omit to let the provider own it. */
  theme?: Theme;
  defaultTheme?: Theme;
  onThemeChange?: (theme: Theme) => void;
  /** Controlled density. Omit to let the provider own it. */
  density?: Density;
  defaultDensity?: Density;
  onDensityChange?: (density: Density) => void;
  /** `localStorage` key. Pass `null` to keep the choice in memory only. */
  storageKey?: string | null;
  /**
   * Element that carries `data-theme` / `data-density`. Defaults to
   * `document.documentElement`; a test or an embedded surface can scope it to a subtree.
   */
  target?: HTMLElement | null;
  children?: ReactNode;
}

interface StoredAppearance {
  theme?: Theme;
  density?: Density;
}

function isTheme(value: unknown): value is Theme {
  return typeof value === 'string' && (THEME_VALUES as readonly string[]).includes(value);
}

function isDensity(value: unknown): value is Density {
  return typeof value === 'string' && (DENSITY_VALUES as readonly string[]).includes(value);
}

/**
 * Reads the stored preference.
 *
 * Every access is guarded: `localStorage` throws outright in a Safari private window and
 * under a "block all cookies" policy, and it does not exist at all during SSR. A theme
 * preference is never worth a crash, so a failure silently means "no preference".
 */
function readStored(key: string | null): StoredAppearance {
  if (key === null || typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return {};
    const record = parsed as Record<string, unknown>;
    return {
      ...(isTheme(record.theme) ? { theme: record.theme } : {}),
      ...(isDensity(record.density) ? { density: record.density } : {}),
    };
  } catch {
    return {};
  }
}

function writeStored(key: string | null, value: StoredAppearance): void {
  if (key === null || typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // A full quota or a blocked store is not a reason to fail a render.
  }
}

/**
 * Owns the appearance of a Research Harness surface: the theme, the density, and the
 * researcher's reduced-motion preference.
 *
 * It renders no DOM of its own. The choice is written to `data-theme` and `data-density`
 * on the document element (or on `target`), which is how every token switches, and
 * persisted under a namespaced `localStorage` key inside try/catch — a stored preference
 * is a convenience and never scientific state, so a browser that refuses to store it
 * simply starts from the defaults.
 */
export function ThemeProvider({
  theme,
  defaultTheme = 'dark',
  onThemeChange,
  density,
  defaultDensity = 'comfortable',
  onDensityChange,
  storageKey = THEME_STORAGE_KEY,
  target,
  children,
}: ThemeProviderProps): ReactElement {
  // The initialiser also runs on the server, where `window` is absent, so the stored
  // value is read behind the same guard rather than in an effect — which keeps the first
  // client paint from flashing the default theme.
  const [storedTheme, setStoredTheme] = useState<Theme>(
    () => readStored(storageKey).theme ?? defaultTheme,
  );
  const [storedDensity, setStoredDensity] = useState<Density>(
    () => readStored(storageKey).density ?? defaultDensity,
  );

  const currentTheme = theme ?? storedTheme;
  const currentDensity = density ?? storedDensity;

  const setTheme = useCallback(
    (next: Theme): void => {
      if (theme === undefined) setStoredTheme(next);
      onThemeChange?.(next);
    },
    [onThemeChange, theme],
  );

  const setDensity = useCallback(
    (next: Density): void => {
      if (density === undefined) setStoredDensity(next);
      onDensityChange?.(next);
    },
    [density, onDensityChange],
  );

  // One writer: whatever is actually in force, controlled or not, so a reload comes back
  // to the same surface and a controlled caller never has to persist it twice.
  useEffect(() => {
    writeStored(storageKey, { theme: currentTheme, density: currentDensity });
  }, [currentDensity, currentTheme, storageKey]);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    const element = target ?? document.documentElement;
    const previousTheme = element.getAttribute('data-theme');
    const previousDensity = element.getAttribute('data-density');
    element.setAttribute('data-theme', currentTheme);
    element.setAttribute('data-density', currentDensity);
    return () => {
      if (previousTheme === null) element.removeAttribute('data-theme');
      else element.setAttribute('data-theme', previousTheme);
      if (previousDensity === null) element.removeAttribute('data-density');
      else element.setAttribute('data-density', previousDensity);
    };
  }, [currentDensity, currentTheme, target]);

  const prefersReducedMotion = useReducedMotion();

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: currentTheme,
      density: currentDensity,
      setTheme,
      setDensity,
      prefersReducedMotion,
    }),
    [currentDensity, currentTheme, prefersReducedMotion, setDensity, setTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/** The appearance in force. Throws outside a `ThemeProvider`, like every other context here. */
export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) throw new Error('useTheme() must be called inside a <ThemeProvider>.');
  return context;
}

/**
 * The appearance in force, or `null` when there is no provider.
 *
 * Composition components use this so they still render in a test or a fragment that has
 * not been wrapped; product surfaces should use {@link useTheme}.
 */
export function useOptionalTheme(): ThemeContextValue | null {
  return useContext(ThemeContext);
}

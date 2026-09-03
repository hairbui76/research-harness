import { useEffect, useState } from 'react';

const QUERY = '(prefers-reduced-motion: reduce)';

/**
 * Tracks `prefers-reduced-motion`. Returns `false` during SSR and in environments without
 * `matchMedia` (jsdom), so animation is opt-out rather than crash-prone; CSS still carries
 * its own `@media (prefers-reduced-motion: reduce)` rules as the primary defence.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia(QUERY);
    setReduced(query.matches);
    const listener = (event: MediaQueryListEvent): void => setReduced(event.matches);
    if (typeof query.addEventListener === 'function') {
      query.addEventListener('change', listener);
      return () => query.removeEventListener('change', listener);
    }
    // Safari < 14 and older jsdom shims.
    query.addListener(listener);
    return () => query.removeListener(listener);
  }, []);

  return reduced;
}

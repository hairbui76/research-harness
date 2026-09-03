import { useEffect, useState } from 'react';

export interface UsePortalOptions {
  /** Where the portal node is appended. Defaults to `document.body`. */
  container?: HTMLElement | null | undefined;
  /** When false the hook creates nothing and returns `null` (render inline instead). */
  enabled?: boolean | undefined;
  /** Written to `data-rh-portal` so overlays can be found and grouped in the DOM. */
  name?: string | undefined;
}

/**
 * Creates a detached host element for an overlay and returns it once mounted.
 *
 * Returns `null` during SSR and on the first client render, so callers render nothing
 * until a real DOM node exists - `createPortal` is never called with a null container.
 */
export function usePortal({ container, enabled = true, name = 'overlay' }: UsePortalOptions = {}): HTMLElement | null {
  const [host, setHost] = useState<HTMLElement | null>(null);

  useEffect(() => {
    if (!enabled) {
      setHost(null);
      return;
    }
    if (typeof document === 'undefined') return;
    const parent = container ?? document.body;
    const node = document.createElement('div');
    node.setAttribute('data-rh-portal', name);
    parent.appendChild(node);
    setHost(node);
    return () => {
      setHost(null);
      node.remove();
    };
  }, [container, enabled, name]);

  return host;
}

import { useAutoId } from '../utils/ids';

/**
 * A stable, SSR-safe DOM id.
 *
 * React 18's `useId` returns values containing `:`, which are legal in an `id` attribute
 * but not in a CSS selector, so the colons are stripped. Passing `providedId` lets a
 * caller keep ownership of the id (for `aria-labelledby` wiring across components).
 *
 * This is the overlay-side name for the package's one id helper; it delegates to
 * `utils/ids` so a single implementation backs every component.
 */
export function useId(providedId?: string | undefined, prefix = 'rh'): string {
  return useAutoId(providedId, prefix);
}

/**
 * Like {@link useId} but returns `undefined` when the feature the id would describe is
 * absent, so an `aria-describedby` is omitted rather than pointing at nothing.
 */
export function useOptionalId(
  enabled: boolean,
  providedId?: string | undefined,
  prefix = 'rh',
): string | undefined {
  const id = useId(providedId, prefix);
  return enabled ? id : undefined;
}

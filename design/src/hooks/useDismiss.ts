import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';

export type DismissReason = 'escape' | 'outside-press';

export interface UseDismissOptions {
  /** Only listens while true. */
  enabled: boolean;
  /** Called with the reason the surface should close. */
  onDismiss: (reason: DismissReason) => void;
  /** Elements that count as "inside": the surface plus its trigger/anchor. */
  refs: ReadonlyArray<RefObject<HTMLElement | null>>;
  /** Escape closes. Default true. */
  escapeKey?: boolean | undefined;
  /** A press outside every ref closes. Default true. */
  outsidePress?: boolean | undefined;
}

/**
 * Open surfaces, oldest first. Only the top layer reacts to Escape or an outside press, so
 * a Menu opened inside a Dialog closes on Escape without also closing the Dialog.
 */
const layers: object[] = [];

/**
 * Outside-press and Escape dismissal for non-modal surfaces (Popover, Menu, Combobox,
 * Tooltip). Presses are observed on the down event so a drag that starts inside and ends
 * outside does not close the surface. `pointerdown` is used where available and
 * `mousedown`/`touchstart` otherwise, which is also the jsdom path.
 */
export function useDismiss({
  enabled,
  onDismiss,
  refs,
  escapeKey = true,
  outsidePress = true,
}: UseDismissOptions): void {
  const onDismissRef = useRef(onDismiss);
  onDismissRef.current = onDismiss;
  const refsRef = useRef(refs);
  refsRef.current = refs;
  const layerRef = useRef<object>({});

  useEffect(() => {
    if (!enabled) return;
    if (typeof document === 'undefined') return;

    const layer = layerRef.current;
    layers.push(layer);
    const isTopLayer = (): boolean => layers[layers.length - 1] === layer;

    const isInside = (target: EventTarget | null): boolean => {
      if (!(target instanceof Node)) return false;
      return refsRef.current.some((ref) => {
        const element = ref.current;
        return element !== null && element.contains(target);
      });
    };

    const onKeyDown = (event: KeyboardEvent): void => {
      if (!escapeKey || !isTopLayer()) return;
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      onDismissRef.current('escape');
    };

    const onPress = (event: Event): void => {
      if (!outsidePress || !isTopLayer()) return;
      if (isInside(event.target)) return;
      onDismissRef.current('outside-press');
    };

    document.addEventListener('keydown', onKeyDown);
    const pressEvents =
      typeof window !== 'undefined' && 'PointerEvent' in window
        ? (['pointerdown'] as const)
        : (['mousedown', 'touchstart'] as const);
    for (const name of pressEvents) document.addEventListener(name, onPress, true);

    return () => {
      const index = layers.indexOf(layer);
      if (index >= 0) layers.splice(index, 1);
      document.removeEventListener('keydown', onKeyDown);
      for (const name of pressEvents) document.removeEventListener(name, onPress, true);
    };
  }, [enabled, escapeKey, outsidePress]);
}

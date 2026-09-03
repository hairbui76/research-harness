import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import { focusElement, getTabbable } from './focusable';

export interface UseFocusTrapOptions {
  /** While true, Tab cycles inside the container and focus is moved into it. */
  active: boolean;
  /** The trapping container. */
  containerRef: RefObject<HTMLElement | null>;
  /** Element to focus when the trap activates. Defaults to the first tabbable child. */
  initialFocusRef?: RefObject<HTMLElement | null> | undefined;
  /** Element to focus when the trap deactivates. Defaults to the previously focused element. */
  finalFocusRef?: RefObject<HTMLElement | null> | undefined;
  /** Restore focus to the opener on deactivate. Default true. */
  restoreFocus?: boolean | undefined;
  /** Move focus into the container on activate. Default true. */
  autoFocus?: boolean | undefined;
}

/**
 * Modal focus containment: remembers the opener, moves focus in, keeps Tab and Shift+Tab
 * inside the container, and restores focus on close. Used by Dialog; Popover and Menu use
 * the lighter {@link useDismiss} instead because they are not modal.
 */
export function useFocusTrap({
  active,
  containerRef,
  initialFocusRef,
  finalFocusRef,
  restoreFocus = true,
  autoFocus = true,
}: UseFocusTrapOptions): void {
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const finalFocusRefStable = useRef(finalFocusRef);
  finalFocusRefStable.current = finalFocusRef;
  const initialFocusRefStable = useRef(initialFocusRef);
  initialFocusRefStable.current = initialFocusRef;

  useEffect(() => {
    if (!active) return;
    const container = containerRef.current;
    if (!container) return;

    const opener = document.activeElement;
    previouslyFocused.current = opener instanceof HTMLElement ? opener : null;

    if (autoFocus) {
      const explicit = initialFocusRefStable.current?.current ?? null;
      const target = explicit ?? getTabbable(container)[0] ?? container;
      if (target === container && !container.hasAttribute('tabindex')) {
        container.setAttribute('tabindex', '-1');
      }
      focusElement(target);
    }

    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== 'Tab') return;
      const tabbable = getTabbable(container);
      if (tabbable.length === 0) {
        event.preventDefault();
        focusElement(container);
        return;
      }
      const first = tabbable[0] as HTMLElement;
      const last = tabbable[tabbable.length - 1] as HTMLElement;
      const activeElement = document.activeElement;
      const insideContainer = activeElement instanceof Node && container.contains(activeElement);

      if (!insideContainer) {
        event.preventDefault();
        focusElement(event.shiftKey ? last : first);
        return;
      }
      if (event.shiftKey && activeElement === first) {
        event.preventDefault();
        focusElement(last);
        return;
      }
      if (!event.shiftKey && activeElement === last) {
        event.preventDefault();
        focusElement(first);
      }
    };

    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      if (!restoreFocus) return;
      const target = finalFocusRefStable.current?.current ?? previouslyFocused.current;
      if (target && target.isConnected) focusElement(target);
    };
  }, [active, autoFocus, containerRef, restoreFocus]);
}

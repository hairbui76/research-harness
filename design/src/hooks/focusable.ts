/**
 * Focus utilities shared by the overlay primitives.
 *
 * jsdom has no layout engine, so visibility is decided from the DOM (hidden / inert /
 * aria-hidden) rather than from computed geometry. That keeps the focus trap and the
 * roving tab index behaving identically in tests and in a browser.
 */

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'iframe',
  'audio[controls]',
  'video[controls]',
  '[contenteditable]:not([contenteditable="false"])',
  '[tabindex]',
].join(',');

/** True when the element is not hidden from the accessibility tree or from interaction. */
export function isFocusVisible(element: HTMLElement): boolean {
  if (element.hidden) return false;
  if (element.getAttribute('aria-hidden') === 'true') return false;
  if (element.closest('[hidden]') !== null) return false;
  if (element.closest('[inert]') !== null) return false;
  if (element.closest('[aria-hidden="true"]') !== null) return false;
  const { display, visibility } = element.style;
  if (display === 'none' || visibility === 'hidden') return false;
  return true;
}

/** True when the element is disabled, either natively or through `aria-disabled`. */
export function isDisabledElement(element: HTMLElement): boolean {
  if (element.getAttribute('aria-disabled') === 'true') return true;
  const candidate = element as HTMLElement & { disabled?: boolean };
  return candidate.disabled === true;
}

/** Every element inside `container` that can be reached with Tab, in document order. */
export function getTabbable(container: HTMLElement | null | undefined): HTMLElement[] {
  if (!container) return [];
  const found = Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
  return found.filter((element) => {
    const tabIndexAttribute = element.getAttribute('tabindex');
    if (tabIndexAttribute !== null && Number(tabIndexAttribute) < 0) return false;
    if (isDisabledElement(element)) return false;
    return isFocusVisible(element);
  });
}

/** Focus `element` without scrolling the page when the browser supports the option. */
export function focusElement(element: HTMLElement | null | undefined): void {
  if (!element) return;
  element.focus({ preventScroll: true });
}

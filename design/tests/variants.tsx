import { render } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

export const THEMES = ['dark', 'light'] as const;
export const DENSITIES = ['comfortable', 'compact'] as const;

export type Theme = (typeof THEMES)[number];
export type Density = (typeof DENSITIES)[number];

export interface ThemeDensityProps {
  theme: Theme;
  density: Density;
  children: ReactNode;
}

/** The wrapper the snapshot variants render inside: theme and density are attribute-driven. */
export function ThemeDensity({ theme, density, children }: ThemeDensityProps): ReactElement {
  return (
    <div data-theme={theme} data-density={density}>
      {children}
    </div>
  );
}

export type SnapshotTarget = 'container' | 'portal' | 'body';

const ID_ATTRIBUTES = [
  'id',
  'for',
  'aria-labelledby',
  'aria-describedby',
  'aria-controls',
  'aria-activedescendant',
  'aria-owns',
  'headers',
  // A skip link points at a generated id, so its `href` is one end of the same
  // relationship — and the only attribute here that also holds ordinary URLs. The
  // replacement below only touches `rh-<name>-r<counter>`, so `#one` and `/review` survive.
  'href',
];

/**
 * React's `useId` counter depends on how many components rendered before it in the file,
 * so generated ids would make every snapshot break whenever a test is added above it.
 * The wiring still matters, so ids are normalised rather than dropped: identical
 * placeholders on both ends of a relationship prove the pairing is intact.
 */
function normaliseGeneratedIds<T extends Node>(node: T): T {
  const clone = node.cloneNode(true) as T;
  const elements: Element[] = [];
  if (clone instanceof Element) elements.push(clone);
  if (clone instanceof Element || clone instanceof Document) {
    elements.push(...Array.from(clone.querySelectorAll('*')));
  }
  for (const element of elements) {
    for (const attribute of ID_ATTRIBUTES) {
      const value = element.getAttribute(attribute);
      if (value === null) continue;
      element.setAttribute(attribute, value.replace(/(rh-[a-z]+)-r[0-9a-z]+/g, '$1-ID'));
    }
  }
  return clone;
}

/**
 * DOM snapshots stand in for screenshot regression (there is no browser in this
 * workspace): every component is captured in dark and light, comfortable and compact.
 */
export function describeThemeDensitySnapshots(
  label: string,
  ui: () => ReactElement,
  options: { target?: SnapshotTarget } = {},
): void {
  const target = options.target ?? 'container';
  describe(`${label} theme x density`, () => {
    for (const theme of THEMES) {
      for (const density of DENSITIES) {
        it(`matches the ${theme} / ${density} snapshot`, () => {
          const { container, unmount } = render(
            <ThemeDensity theme={theme} density={density}>
              {ui()}
            </ThemeDensity>,
          );
          const node =
            target === 'container'
              ? container.firstChild
              : target === 'portal'
                ? document.body.querySelector('[data-rh-portal]')
                : document.body;
          expect(node === null ? null : normaliseGeneratedIds(node)).toMatchSnapshot();
          unmount();
        });
      }
    }
  });
}

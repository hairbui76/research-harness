/**
 * What the three PDF evidence highlights are painted with.
 *
 * A highlight is a fill under `mix-blend-mode: multiply` over `--rh-surface-paper`, and
 * paper stays near-white in both themes. That makes the choice of token load-bearing in a
 * way a component test cannot see: a dark-canvas tint such as `--rh-accent-subtle` looks
 * right in light mode and multiplies down to near-black in dark mode, taking the page ink
 * with it to about 1.1:1. The design package therefore ships paper-specific highlight
 * tokens that are light tints in both themes, and `design/scripts/check-contrast.mjs`
 * gates their measured ratios.
 *
 * This test guards the other half — that the stylesheet actually reaches for those tokens
 * — because that is the half a contrast gate over tokens cannot check.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

// Read the source, not the DOM: jsdom applies no stylesheet and resolves no `var()`, so
// the stylesheet itself is the only honest thing to assert against without a browser.
// `import.meta.url` is a served URL under Vite's transform, so the path comes from the
// package root that `vitest run` is started in.
const css = readFileSync(join(process.cwd(), 'src', 'pdf', 'pdf.css'), 'utf8');

/** The declarations of the first rule whose selector matches, comments stripped. */
function ruleFor(selector: string): string {
  const bodies = css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g);
  for (const match of bodies) {
    if ((match[1] ?? '').trim() === selector) return match[2] ?? '';
  }
  throw new Error(`no rule for ${selector} in pdf.css`);
}

const KINDS = [
  { selector: '.rh-pdf__highlight', fill: '--rh-highlight-on-paper', edge: '--rh-highlight-on-paper-border' },
  {
    selector: ".rh-pdf__highlight[data-kind='anchor']",
    fill: '--rh-highlight-on-paper-anchor',
    edge: '--rh-highlight-on-paper-anchor-border',
  },
  {
    selector: ".rh-pdf__highlight[data-kind='match']",
    fill: '--rh-highlight-on-paper-match',
    edge: '--rh-highlight-on-paper-match-border',
  },
];

describe('highlight tokens', () => {
  it.each(KINDS)('paints $selector from the paper highlight tokens', ({ selector, fill, edge }) => {
    const rule = ruleFor(selector);
    expect(rule).toMatch(new RegExp(`background:\\s*var\\(${fill}\\)`));
    expect(rule).toMatch(new RegExp(`border(?:-color)?:[^;]*var\\(${edge}\\)`));
  });

  it('keeps the fill multiplied, so the glyphs stay visible through it', () => {
    expect(ruleFor('.rh-pdf__highlight')).toMatch(/mix-blend-mode:\s*multiply/);
  });

  it('reaches for no colour that belongs to the application canvas', () => {
    // These are the tints the defect used. They are correct on a pane and wrong on paper,
    // and nothing under `.rh-pdf__highlight` may go back to them.
    const highlights = css
      .split(/(?=\.rh-pdf__)/)
      .filter((block) => block.startsWith('.rh-pdf__highlight'))
      .join('\n');
    expect(highlights).not.toMatch(/--rh-accent-subtle|--rh-status-|--rh-feedback-/);
    // Nor may any of them be a literal: the palette is the only place a colour is written.
    expect(highlights).not.toMatch(/#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/);
  });
});

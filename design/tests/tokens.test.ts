import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The token contract.
 *
 * Components across the package (and, after the migration, the Web client) address colour
 * only through these names, so a rename or a dropped declaration is a breaking change.
 * These tests read the stylesheets rather than the DOM: jsdom applies no stylesheet and
 * resolves no `var()`, so asserting against the source is the only honest check available
 * without a browser. The resolved-value snapshots stand in for a screenshot of the palette.
 */

const src = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');

const TOKEN_FILES = [
  'tokens/palette.css',
  'tokens/spacing.css',
  'tokens/radius.css',
  'tokens/typography.css',
  'tokens/motion.css',
  'tokens/density.css',
  'tokens/semantic.css',
  'themes/dark.css',
  'themes/light.css',
];

function read(relative: string): string {
  return readFileSync(join(src, relative), 'utf8');
}

/** Drop comments and any `@media` block, so a reduced-motion override is not read as base. */
function normalise(css: string): string {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '');
  let out = '';
  let index = 0;
  while (index < withoutComments.length) {
    const at = withoutComments.indexOf('@media', index);
    if (at === -1) {
      out += withoutComments.slice(index);
      break;
    }
    out += withoutComments.slice(index, at);
    let cursor = withoutComments.indexOf('{', at);
    let depth = 0;
    while (cursor < withoutComments.length) {
      if (withoutComments[cursor] === '{') depth += 1;
      else if (withoutComments[cursor] === '}') {
        depth -= 1;
        if (depth === 0) break;
      }
      cursor += 1;
    }
    index = cursor + 1;
  }
  return out;
}

interface Block {
  selector: string;
  declarations: Map<string, string>;
}

function blocks(css: string): Block[] {
  const out: Block[] = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(css)) !== null) {
    const declarations = new Map<string, string>();
    for (const part of (match[2] ?? '').split(';')) {
      const colon = part.indexOf(':');
      if (colon === -1) continue;
      const name = part.slice(0, colon).trim();
      if (!name.startsWith('--')) continue;
      declarations.set(name, part.slice(colon + 1).trim());
    }
    out.push({ selector: (match[1] ?? '').trim(), declarations });
  }
  return out;
}

const allBlocks = TOKEN_FILES.flatMap((file) => blocks(normalise(read(file))));

function mapFor(predicate: (selector: string) => boolean): Map<string, string> {
  const map = new Map<string, string>();
  for (const block of allBlocks) {
    if (!predicate(block.selector)) continue;
    for (const [name, value] of block.declarations) map.set(name, value);
  }
  return map;
}

/** A block applies with no attribute set when one of its selectors is a bare `:root`. */
const appliesBare = (selector: string) =>
  selector.split(',').some((part) => part.trim() === ':root');

const base = mapFor(appliesBare);
const dark = new Map(base);
for (const block of allBlocks) {
  if (/\[data-theme=['"]dark['"]\]/.test(block.selector)) {
    for (const [name, value] of block.declarations) dark.set(name, value);
  }
}
const light = new Map(dark);
for (const block of allBlocks) {
  if (/\[data-theme=['"]light['"]\]/.test(block.selector)) {
    for (const [name, value] of block.declarations) light.set(name, value);
  }
}
const comfortable = mapFor(
  (s) => /\[data-density=['"]comfortable['"]\]/.test(s) || appliesBare(s),
);
const compact = mapFor((s) => /\[data-density=['"]compact['"]\]/.test(s));

function resolve(tokens: Map<string, string>, value: string, depth = 0): string {
  if (depth > 20) throw new Error(`var() chain too deep: ${value}`);
  const match = /^var\(\s*(--[\w-]+)\s*(?:,\s*([\s\S]+))?\)$/.exec(value.trim());
  if (!match) return value.trim();
  const referenced = tokens.get(match[1] as string);
  if (referenced !== undefined) return resolve(tokens, referenced, depth + 1);
  if (match[2] !== undefined) return resolve(tokens, match[2], depth + 1);
  throw new Error(`unresolved token ${match[1]}`);
}

const STATUSES = ['accepted', 'candidate', 'qualified', 'contested', 'stale', 'private'];
const FEEDBACK = ['success', 'error', 'warning', 'info'];
const TYPE_ROLES = [
  'display',
  'h1',
  'h2',
  'h3',
  'h4',
  'lead',
  'ui',
  'body',
  'body-sm',
  'label',
  'mono',
];

const REQUIRED_SEMANTIC = [
  ...['canvas', 'pane', 'raised', 'paper', 'inverse', 'subtle', 'selected', 'scrim'].map(
    (n) => `--rh-surface-${n}`,
  ),
  ...['subtle', 'default', 'strong'].map((n) => `--rh-border-${n}`),
  ...['primary', 'secondary', 'muted', 'inverse', 'link', 'on-accent'].map(
    (n) => `--rh-text-${n}`,
  ),
  '--rh-accent',
  '--rh-accent-hover',
  '--rh-accent-subtle',
  '--rh-accent-fg',
  '--rh-focus-ring',
  '--rh-focus-ring-width',
  '--rh-focus-ring-offset',
  ...STATUSES.flatMap((s) => [
    `--rh-status-${s}-fg`,
    `--rh-status-${s}-bg`,
    `--rh-status-${s}-border`,
  ]),
  ...FEEDBACK.flatMap((f) => [
    `--rh-feedback-${f}-fg`,
    `--rh-feedback-${f}-bg`,
    `--rh-feedback-${f}-border`,
  ]),
  '--rh-highlight-on-paper',
  '--rh-highlight-on-paper-border',
  '--rh-highlight-on-paper-anchor',
  '--rh-highlight-on-paper-anchor-border',
  '--rh-highlight-on-paper-match',
  '--rh-highlight-on-paper-match-border',
];

const REQUIRED_FOUNDATION = [
  '--rh-font-sans',
  '--rh-font-serif',
  '--rh-font-mono',
  ...TYPE_ROLES.flatMap((role) => [
    `--rh-type-${role}-size`,
    `--rh-type-${role}-lh`,
    `--rh-type-${role}-ls`,
    `--rh-type-${role}-weight`,
  ]),
  ...[1, 2, 3, 4, 5, 6, 8, 10, 12, 16].map((n) => `--rh-space-${n}`),
  ...['control', 'nav', 'card', 'pill'].map((n) => `--rh-radius-${n}`),
  '--rh-duration-fast',
  '--rh-duration-base',
  '--rh-duration-slow',
  '--rh-ease-standard',
  '--rh-scale-hover',
  '--rh-scale-press',
];

describe('token contract', () => {
  it.each(REQUIRED_SEMANTIC)('defines %s in both themes', (token) => {
    expect(dark.has(token), `${token} missing from the dark theme`).toBe(true);
    expect(light.has(token), `${token} missing from the light theme`).toBe(true);
  });

  it.each(REQUIRED_FOUNDATION)('defines %s', (token) => {
    expect(base.has(token), `${token} is not declared`).toBe(true);
  });

  it('resolves every semantic token to a literal in both themes', () => {
    for (const token of REQUIRED_SEMANTIC) {
      expect(resolve(dark, dark.get(token) as string)).not.toMatch(/^var\(/);
      expect(resolve(light, light.get(token) as string)).not.toMatch(/^var\(/);
    }
  });

  it('makes dark the default, with no attribute required', () => {
    const bare = allBlocks.filter((b) =>
      b.selector.split(',').some((s) => s.trim() === ':root'),
    );
    const canvasFromBareRoot = bare.some((b) => b.declarations.has('--rh-surface-canvas'));
    expect(canvasFromBareRoot).toBe(true);
    expect(resolve(dark, dark.get('--rh-surface-canvas') as string)).toBe(
      resolve(base, base.get('--rh-surface-canvas') as string),
    );
  });

  it('gives light different surfaces from dark', () => {
    for (const token of ['--rh-surface-canvas', '--rh-surface-pane', '--rh-text-primary']) {
      expect(resolve(light, light.get(token) as string)).not.toBe(
        resolve(dark, dark.get(token) as string),
      );
    }
  });

  it('keeps the reading surface near-white in both themes', () => {
    for (const theme of [dark, light]) {
      const paper = resolve(theme, theme.get('--rh-surface-paper') as string);
      const channels = /^#(..)(..)(..)$/.exec(paper);
      expect(channels, `paper should be a six-digit hex, got ${paper}`).not.toBeNull();
      for (const channel of (channels ?? []).slice(1)) {
        expect(parseInt(channel, 16)).toBeGreaterThan(0xf0);
      }
    }
  });

  it('sets both density modes', () => {
    expect(comfortable.get('--rh-density-row')).toBe('36px');
    expect(compact.get('--rh-density-row')).toBe('28px');
    for (const token of ['--rh-density-gap', '--rh-density-pad', '--rh-density-font-scale']) {
      expect(comfortable.has(token)).toBe(true);
      expect(compact.has(token)).toBe(true);
    }
  });

  it('collapses motion under prefers-reduced-motion', () => {
    const motion = read('tokens/motion.css');
    expect(motion).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    const reduced = motion.slice(motion.indexOf('@media'));
    expect(reduced).toMatch(/--rh-scale-hover:\s*1;/);
    expect(reduced).toMatch(/--rh-scale-press:\s*1;/);
    expect(reduced).toMatch(/--rh-duration-base:\s*1ms;/);
  });

  it('ships system font stacks and fetches nothing', () => {
    for (const file of [...TOKEN_FILES, 'base.css', 'styles.css']) {
      // Comments are stripped: this rule is about what the browser executes, and the
      // typography file explains the no-CDN rule using the very words it forbids.
      const css = read(file).replace(/\/\*[\s\S]*?\*\//g, '');
      expect(css, `${file} must not use @font-face`).not.toMatch(/@font-face/);
      expect(css, `${file} must not reach a CDN`).not.toMatch(/https?:\/\//);
      expect(css, `${file} must not load a remote asset`).not.toMatch(/url\(\s*['"]?\/\//);
    }
  });

  it('keeps every raw colour inside tokens/ and themes/', () => {
    const literal = /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b|\brgba?\(|\boklab\(/;
    expect(literal.test(read('base.css'))).toBe(false);
    expect(literal.test(read('styles.css'))).toBe(false);
    expect(literal.test(read('tokens/palette.css'))).toBe(true);
  });

  it('matches the resolved dark palette', () => {
    expect(snapshotOf(dark)).toMatchSnapshot();
  });

  it('matches the resolved light palette', () => {
    expect(snapshotOf(light)).toMatchSnapshot();
  });

  it('matches the density scales', () => {
    expect({
      comfortable: Object.fromEntries(
        [...comfortable].filter(([name]) => name.startsWith('--rh-density')),
      ),
      compact: Object.fromEntries([...compact]),
    }).toMatchSnapshot();
  });
});

function snapshotOf(tokens: Map<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const token of [...REQUIRED_SEMANTIC, '--rh-accent-text', '--rh-text-on-paper'].sort()) {
    const value = tokens.get(token);
    if (value === undefined) continue;
    out[token] = resolve(tokens, value);
  }
  return out;
}

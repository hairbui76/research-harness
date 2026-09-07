import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { HOST_TOKENS, tokenCensus } from '../scripts/token-usage.mjs';

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
  // `on-accent` is gone: it was an alias of `--rh-accent-fg` that nothing ever read, and
  // two names for one ink is how a theme comes to disagree with itself (token-usage.mjs).
  ...['primary', 'secondary', 'muted', 'inverse', 'link'].map((n) => `--rh-text-${n}`),
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
  // Two durations. `--rh-duration-slow` was declared, reset under reduced motion, and read
  // by nothing; a third speed nobody chose is not part of the contract (token-usage.mjs).
  '--rh-duration-fast',
  '--rh-duration-base',
  '--rh-ease-standard',
  '--rh-scale-hover',
  '--rh-scale-press',
  '--rh-type-reading-min-size',
  '--rh-control-target-min',
  '--rh-border-width',
  '--rh-border-width-strong',
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

/**
 * The type scale, the reading floor and the pointer-target floor.
 *
 * These are the invariants a heading, a caption or a control cannot be allowed to break
 * silently: one ramp with a deliberate ratio, no heading set smaller than the body it
 * introduces, no reading text below 12px on any surface at any density, and no control
 * whose box falls under the 24px pointer target (WCAG 2.2 SC 2.5.8). They are asserted
 * against the token source for the same reason the rest of this file is: jsdom resolves
 * no `var()`, so the stylesheet is the only honest place to read them.
 */
function px(tokens: Map<string, string>, token: string): number {
  const value = resolve(tokens, tokens.get(token) as string);
  const match = /^(-?[\d.]+)px$/.exec(value.trim());
  expect(match, `${token} should be a px length, got ${value}`).not.toBeNull();
  return Number(match?.[1]);
}

function ratio(tokens: Map<string, string>, bigger: string, smaller: string): number {
  return px(tokens, `--rh-type-${bigger}-size`) / px(tokens, `--rh-type-${smaller}-size`);
}

/** Every token that applies when `data-density="compact"` is set, base values included. */
const compactAll = new Map([...comfortable, ...compact]);

const HEADING_STEPS: readonly [string, string][] = [
  ['display', 'h1'],
  ['h1', 'h2'],
  ['h2', 'h3'],
  ['h3', 'h4'],
];

describe('the type scale', () => {
  it.each(HEADING_STEPS)('steps from %s to %s by a product ratio', (bigger, smaller) => {
    const step = ratio(base, bigger, smaller);
    // Operate mode: 1.125-1.2. A wider ratio is a marketing ramp, and there are more type
    // roles on a research page than on a landing page, so exaggerated contrast is noise.
    expect(step, `${bigger}/${smaller} is ${step.toFixed(3)}`).toBeGreaterThanOrEqual(1.125);
    expect(step, `${bigger}/${smaller} is ${step.toFixed(3)}`).toBeLessThanOrEqual(1.2);
  });

  it('never sets a heading smaller than the body text it introduces', () => {
    const body = px(base, '--rh-type-body-size');
    for (const role of ['display', 'h1', 'h2', 'h3', 'h4']) {
      expect(
        px(base, `--rh-type-${role}-size`),
        `${role} must not be smaller than body`,
      ).toBeGreaterThanOrEqual(body);
    }
  });

  it('separates the smallest heading from body by weight, since size no longer can', () => {
    expect(px(base, '--rh-type-h4-size')).toBe(px(base, '--rh-type-body-size'));
    expect(Number(base.get('--rh-type-h4-weight'))).toBeGreaterThan(
      Number(base.get('--rh-type-body-weight')),
    );
  });
});

describe('the reading floor', () => {
  it('declares one floor for every size a researcher reads', () => {
    expect(px(base, '--rh-type-reading-min-size')).toBe(12);
  });

  it('keeps body and dense body above it', () => {
    const floor = px(base, '--rh-type-reading-min-size');
    expect(px(base, '--rh-type-body-size')).toBeGreaterThan(floor);
    expect(px(base, '--rh-type-body-sm-size')).toBeGreaterThan(floor);
  });

  it('keeps dense body above it after the compact density has scaled it', () => {
    const floor = px(compactAll, '--rh-type-reading-min-size');
    const scale = Number(resolve(compactAll, compactAll.get('--rh-density-font-scale') as string));
    const scaled = px(compactAll, '--rh-type-body-sm-size') * scale;
    expect(scaled, `compact body-sm renders at ${scaled.toFixed(2)}px`).toBeGreaterThanOrEqual(
      floor,
    );
  });
});

/*
 * The floor holds where density does the multiplying, too.
 *
 * `density.css` states the rule — "whatever it multiplies must still land at or above
 * `--rh-type-reading-min-size` for anything a researcher reads" — and until the browser
 * detector measured it, nothing held a stylesheet to it. `.rh-badge--sm` computed
 * 11px x 0.929 = 10.2px inside every `data-density="compact"` subtree.
 *
 * A badge is the case the rule is about. Its whole content is one word of one of the
 * daemon's controlled vocabularies — "Accepted", "Stale", "Partially supported" — read off
 * the screen and acted on, which is reading text however small the box around it is. The
 * other roles density scales are ids, timestamps and code: `mono` and `label` live below
 * the floor by design, and the ramp says so. So this holds the badge, at both densities,
 * the way `browser-tests/typography.spec.ts` measures it in Chromium.
 */
describe('a badge is a word, not a chip of metadata', () => {
  it('keeps every badge size at or above the reading floor in both densities', () => {
    const floor = px(compactAll, '--rh-type-reading-min-size');
    const scale = Number(resolve(compactAll, compactAll.get('--rh-density-font-scale') as string));
    const css = readFileSync(join(src, 'primitives/Badge/Badge.css'), 'utf8').replace(
      /\/\*[\s\S]*?\*\//g,
      '',
    );
    const measured: string[] = [];
    const offenders: string[] = [];

    for (const rule of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const selector = (rule[1] ?? '').trim();
      const declaration = /font-size\s*:\s*([^;}]+)/.exec(rule[2] ?? '');
      if (declaration === null) continue;
      const value = (declaration[1] ?? '').trim();
      const role = /var\(\s*(--rh-type-[\w-]+-size)\s*\)/.exec(value);
      if (role === null) continue;
      const declared = px(compactAll, role[1] as string);
      const floored = /max\(/.test(value) && /--rh-type-reading-min-size/.test(value);
      const dense = /var\(--rh-density-font-scale\)/.test(value) ? declared * scale : declared;
      const rendered = floored ? Math.max(floor, dense) : dense;
      measured.push(selector);
      if (rendered + 0.001 < floor) {
        offenders.push(`${selector} renders ${rendered.toFixed(2)}px in a compact subtree`);
      }
    }

    // The guard on the guard: a renamed class must not turn this into a test of nothing.
    expect(measured).toContain('.rh-badge--sm');
    expect(offenders).toEqual([]);
  });
});

describe('the pointer-target floor', () => {
  it('declares the 24px minimum from WCAG 2.2 SC 2.5.8', () => {
    expect(px(base, '--rh-control-target-min')).toBe(24);
  });

  it.each([
    ['comfortable', comfortable],
    ['compact', compactAll],
  ])('keeps every control height at or above it in %s density', (_density, tokens) => {
    const floor = px(tokens, '--rh-control-target-min');
    for (const token of ['--rh-control-height-sm', '--rh-control-height-md']) {
      expect(px(tokens, token)).toBeGreaterThanOrEqual(floor);
    }
  });
});

describe('border widths', () => {
  it('names the hairline and the one emphatic width above it', () => {
    expect(px(base, '--rh-border-width')).toBe(1);
    expect(px(base, '--rh-border-width-strong')).toBe(2);
  });

  it('ships no third width: every stylesheet states its borders in tokens', () => {
    const literals: string[] = [];
    for (const root of [src, join(src, '..', '..', 'web', 'src')]) {
      for (const file of cssFilesUnder(root)) {
        const css = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
        for (const [index, line] of css.split('\n').entries()) {
          if (/^\s*(?:border|outline)[a-z-]*\s*:/.test(line) && /\b\d+px\b/.test(line)) {
            if (/border-radius/.test(line)) continue;
            literals.push(`${relative(src, file)}:${index + 1}: ${line.trim()}`);
          }
        }
      }
    }
    expect(literals).toEqual([]);
  });

  /*
   * The sweep above reads `border` and `outline`, which is where a rule is normally drawn —
   * and an inset `box-shadow` draws exactly the same rule without using either word. That is
   * how a 2px accent stripe stood down the start edge of the combobox's active option: a
   * side border by every measure except the property it was written in. The strong width is
   * spent on the selected tab's marker and the rule beside quoted matter, so a shadow that
   * draws a stripe is held to the hairline like anything else.
   */
  it('draws no thicker stripe through an inset shadow, which is a border by another name', () => {
    const stripes: string[] = [];
    for (const root of [src, join(src, '..', '..', 'web', 'src')]) {
      for (const file of cssFilesUnder(root)) {
        const css = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
        for (const [index, line] of css.split('\n').entries()) {
          if (!/^\s*box-shadow\s*:/.test(line) || !/\binset\b/.test(line)) continue;
          const above =
            [...line.matchAll(/(\d+(?:\.\d+)?)px/g)].some((match) => Number(match[1]) > 1) ||
            /--rh-border-width-strong/.test(line);
          if (above) stripes.push(`${relative(src, file)}:${index + 1}: ${line.trim()}`);
        }
      }
    }
    expect(stripes).toEqual([]);
  });
});

/**
 * The kicker ban, held mechanically.
 *
 * Every state component names its kind in words, which is right: colour is never the only
 * signal. What the craft floor refuses is naming it *as a label above the heading* — an
 * 11px uppercase wide-tracked word set before the sentence it belongs to. The lead-in that
 * replaced it is the first words of the title, so it carries no case, tracking or size of
 * its own; if one comes back, this fails.
 */
describe('the states name their kind without a kicker', () => {
  const LEAD_INS = ['__kind', '__tone-label'];
  const KICKER_PROPERTIES = ['text-transform', 'letter-spacing', 'font-size'];

  it('leaves the lead-in in the title’s own case, tracking and size', () => {
    const offenders: string[] = [];
    for (const root of [src, join(src, '..', '..', 'web', 'src')]) {
      for (const file of cssFilesUnder(root)) {
        const css = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
        for (const rule of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
          const selector = rule[1]!.trim();
          if (!LEAD_INS.some((suffix) => selector.includes(suffix))) continue;
          for (const property of KICKER_PROPERTIES) {
            if (new RegExp(`(?:^|[;\\s])${property}\\s*:`).test(rule[2]!)) {
              offenders.push(`${relative(src, file)}: ${selector} sets ${property}`);
            }
          }
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

/**
 * A heading is read, so it is set at a size a person reads.
 *
 * `--rh-type-label-size` is 11px, under the 12px reading floor 2F declared, and
 * `.rh-text-label` also sets mono, uppercase and 0.08em tracking: it is the treatment for a
 * metadata chip beside a value — a `<dt>`, a menu group, a `WORK`/`TYPE`/`STRENGTH` key —
 * and never for the heading of a section a researcher reads their way through. `h4` is the
 * smallest heading in the scale and is body-sized; its weight is what makes it a heading.
 */
describe('headings are not label chips', () => {
  it('sets no heading element in the metadata label treatment', () => {
    const offenders: string[] = [];
    for (const root of [src, join(src, '..', '..', 'web', 'src')]) {
      for (const file of sourceFilesUnder(root)) {
        const source = readFileSync(file, 'utf8');
        for (const [index, line] of source.split('\n').entries()) {
          if (/<h[1-6][^>]*\brh-text-label\b/.test(line)) {
            offenders.push(`${relative(src, file)}:${index + 1}: ${line.trim()}`);
          }
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

/**
 * A tab strip that admits it is narrower than its tabs has to look like one.
 *
 * The overflow fade is a mask, so jsdom neither applies it nor resolves the `var()` inside
 * it; the ramp is read off the source the way every other geometry assertion here is. Over
 * one space it is about one character wide, which is not a fade — "Review inbox" ended as
 * "nbox" against a hard edge beside the chevron and read as a rendering fault rather than
 * as more to scroll to.
 */
describe('the tab strip’s overflow fade', () => {
  it('dissolves the label it clips over about two spaces', () => {
    const css = read('primitives/Tabs/Tabs.css');
    const ramps = [...css.matchAll(/mask-image:[^;]*var\(--rh-space-(\d+)\)/g)].map((match) =>
      Number(match[1]),
    );
    expect(ramps).not.toHaveLength(0);
    for (const step of ramps) expect(step).toBeGreaterThanOrEqual(10);
  });
});

/**
 * A notification lands on chrome, never on what is being read or reached for.
 *
 * Wave one moved the viewport off the review screen's decision controls and under the app
 * shell's bar. At 768px that is not enough: the top corner is the page's own header there,
 * and a toast over the `h1` and the sentence under it covers something the researcher has
 * not read yet. The narrow rule clears the measured page header as well, and stays at the
 * top — the bottom of a narrow review screen is wherever the decision controls happen to
 * have been scrolled to.
 */
describe('the toast viewport', () => {
  const css = read('primitives/Toast/Toast.css');

  it('starts below the shell bar and below the page header, at every width', () => {
    const rule = /\.rh-toast-viewport\[data-placement\^='top'\]\s*\{([^}]*)\}/.exec(css);
    expect(rule, 'Toast.css declares no top-placement rule').not.toBeNull();
    expect(rule![1]).toContain('--rh-app-shell-bar-height');
    expect(rule![1]).toContain('--rh-page-header-bottom');
  });

  it('takes the width at a narrow one, and still stays at the top', () => {
    const narrow = /@media \(max-width: 768px\)\s*\{([\s\S]*?)\n\}/.exec(css);
    expect(narrow, 'Toast.css declares no narrow-width rule').not.toBeNull();
    expect(narrow![1]).toContain('width: 100%');
    // Still the top: bottom is where a narrow review screen's decision controls can be.
    expect(narrow![1]).not.toContain("[data-placement^='bottom']");
  });
});

/**
 * `body-sm` is for rows, cells and chips; a sentence is `body`.
 *
 * 13px, and 12.08px once the compact density has scaled it, is the right size for a table
 * cell or a badge's hint — text that is scanned beside something else. It is the wrong size
 * for a sentence a researcher has to read before they can act: what a state means, what a
 * notice is about, why a decision cannot be recorded, what is wrong with a field.
 */
describe('the sentences a researcher reads before acting', () => {
  const READING: readonly [string, string][] = [
    ['states/AsyncState.css', '.rh-state__description'],
    ['states/ErrorNotice.css', '.rh-error-notice__description'],
    ['research/ReviewDecisionBar/ReviewDecisionBar.css', '.rh-review-decision-bar__reason'],
    ['primitives/field.css', '.rh-field__error'],
  ];

  it.each(READING)('sets %s %s at reading size, not at row size', (file, selector) => {
    const css = read(file);
    const rule = new RegExp(`\\${selector}\\s*\\{([^}]*)\\}`).exec(css);
    expect(rule, `${file} declares no ${selector} rule`).not.toBeNull();
    expect(rule![1]).toContain('--rh-type-body-size');
    expect(rule![1]).not.toContain('--rh-type-body-sm-size');
  });
});

function filesUnder(root: string, ends: (name: string) => boolean): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === 'dist' || entry.name.startsWith('.')) {
      continue;
    }
    const full = join(root, entry.name);
    if (entry.isDirectory()) out.push(...filesUnder(full, ends));
    else if (ends(entry.name)) out.push(full);
  }
  return out;
}

function sourceFilesUnder(root: string): string[] {
  return filesUnder(root, (name) => name.endsWith('.tsx'));
}

function cssFilesUnder(root: string): string[] {
  return filesUnder(root, (name) => name.endsWith('.css'));
}

/**
 * The census.
 *
 * A token is a promise that a name means something, and a token nothing reads is not a
 * promise — it survives palette changes because nothing breaks when it drifts, and it sits
 * in autocomplete beside the name that is real. `scripts/token-usage.mjs` reads every
 * `--rh-*` declared under `src/tokens` and `src/themes` and every `var()` under
 * `design/src` and `web/src`; tests, snapshots and specimens are not consumers, because a
 * token whose only reader is the test asserting it exists is exactly the case being looked
 * for.
 *
 * `HOST_TOKENS` is the allow-list, and its bar is not "we might want it one day": each
 * entry must name a set the README publishes as an interface, where a host reads the name
 * and shipping only part of the set would be wrong.
 */
describe('the token census', () => {
  it('declares no token that nothing reads', () => {
    const { unexplained } = tokenCensus();
    expect(unexplained.map((token) => `${token.name} (${token.file}:${token.line})`)).toEqual([]);
  });

  it('gives every host-facing exception a written reason', () => {
    const { dead } = tokenCensus();
    for (const token of dead) {
      const reason = HOST_TOKENS[token.name];
      expect(reason, `${token.name} has no consumer and no reason`).toBeTruthy();
      expect((reason ?? '').length, `${token.name}'s reason is not a sentence`).toBeGreaterThan(40);
    }
  });

  it('allows nothing it does not have to', () => {
    const { dead } = tokenCensus();
    const names = new Set(dead.map((token) => token.name));
    for (const token of Object.keys(HOST_TOKENS)) {
      expect(names.has(token), `${token} is read after all; drop it from HOST_TOKENS`).toBe(true);
    }
  });
});

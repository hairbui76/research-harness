/*
 * WCAG 2.2 contrast gate for the semantic token contract.
 *
 * Parses the palette, the shared semantic tokens and both themes, resolves every var()
 * chain down to a colour literal, and computes the contrast ratio for each text/surface
 * pair the system declares. Text pairs must reach 4.5:1; focus rings, component
 * boundaries and large text must reach 3:1.
 *
 * A pair may declare that one of its two colours is painted with `mix-blend-mode:
 * multiply` over a third (`fgOver` / `bgOver`). The PDF evidence highlights are drawn that
 * way over the reading surface, so the colour a researcher actually sees is the per-channel
 * product, not the token — and gating the token alone is what let a dark-canvas tint
 * multiply down to near-black over paper and take the page ink with it.
 *
 * The check runs in `pnpm --filter @research-harness/design lint`. It fails the build, so
 * a token change that makes muted text illegible on a raised surface cannot be committed
 * and discovered later by a researcher squinting at a review queue.
 *
 * Usage: node scripts/check-contrast.mjs [--json]
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');

const FILES = [
  join(src, 'tokens', 'palette.css'),
  join(src, 'tokens', 'semantic.css'),
  join(src, 'themes', 'dark.css'),
  join(src, 'themes', 'light.css'),
];

/* --- CSS custom property extraction ------------------------------------------------- */

/** Strip /* *\/ comments so a commented-out declaration never reaches the parser. */
function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

/** Every `selector { ... }` block, in source order. */
function blocks(css) {
  const out = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let match;
  while ((match = re.exec(css)) !== null) {
    out.push({ selector: match[1].trim(), body: match[2] });
  }
  return out;
}

/** `--name: value` declarations of one block. */
function declarations(body) {
  const out = new Map();
  for (const part of body.split(';')) {
    const index = part.indexOf(':');
    if (index === -1) continue;
    const name = part.slice(0, index).trim();
    if (!name.startsWith('--')) continue;
    out.set(name, part.slice(index + 1).trim());
  }
  return out;
}

/**
 * The token maps for both themes.
 *
 * `:root` (and any bare `[data-theme="dark"]`) is the dark default; the light map starts
 * as a copy of it and takes the `[data-theme="light"]` overrides on top, which is exactly
 * how the cascade resolves it in the browser.
 */
function readThemes() {
  const dark = new Map();
  const lightOverrides = new Map();
  for (const file of FILES) {
    const css = stripComments(readFileSync(file, 'utf8'));
    for (const { selector, body } of blocks(css)) {
      if (selector.startsWith('@')) continue;
      const isLight = /\[data-theme=['"]light['"]\]/.test(selector);
      const target = isLight ? lightOverrides : dark;
      for (const [name, value] of declarations(body)) target.set(name, value);
    }
  }
  const light = new Map(dark);
  for (const [name, value] of lightOverrides) light.set(name, value);
  return { dark, light };
}

/** Follow var() chains until a literal falls out. */
function resolve(tokens, value, depth = 0) {
  if (depth > 20) throw new Error(`var() chain too deep at: ${value}`);
  const trimmed = String(value).trim();
  const match = /^var\(\s*(--[\w-]+)\s*(?:,\s*([\s\S]+))?\)$/.exec(trimmed);
  if (!match) return trimmed;
  const referenced = tokens.get(match[1]);
  if (referenced !== undefined) return resolve(tokens, referenced, depth + 1);
  if (match[2] !== undefined) return resolve(tokens, match[2], depth + 1);
  throw new Error(`unresolved token ${match[1]}`);
}

/* --- Colour --------------------------------------------------------------------------- */

function parseColour(input) {
  const value = input.trim().toLowerCase();
  const hex = /^#([0-9a-f]{3,8})$/.exec(value);
  if (hex) {
    const digits = hex[1];
    const expand = (s) => parseInt(s.length === 1 ? s + s : s, 16);
    if (digits.length === 3 || digits.length === 4) {
      return {
        r: expand(digits[0]),
        g: expand(digits[1]),
        b: expand(digits[2]),
        a: digits.length === 4 ? expand(digits[3]) / 255 : 1,
      };
    }
    if (digits.length === 6 || digits.length === 8) {
      return {
        r: expand(digits.slice(0, 2)),
        g: expand(digits.slice(2, 4)),
        b: expand(digits.slice(4, 6)),
        a: digits.length === 8 ? expand(digits.slice(6, 8)) / 255 : 1,
      };
    }
  }
  const rgb = /^rgba?\(([^)]+)\)$/.exec(value);
  if (rgb) {
    const parts = rgb[1].split(/[,/\s]+/).filter(Boolean).map(Number);
    if (parts.length >= 3 && parts.slice(0, 3).every((n) => Number.isFinite(n))) {
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
    }
  }
  throw new Error(`cannot parse colour: ${input}`);
}

/** Flatten a translucent colour onto an opaque one. */
function composite(fg, bg) {
  if (fg.a >= 1) return fg;
  return {
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1,
  };
}

/** `mix-blend-mode: multiply`, per channel: a·b/255. Both operands are opaque here. */
function multiply(source, backdrop) {
  return {
    r: (source.r * backdrop.r) / 255,
    g: (source.g * backdrop.g) / 255,
    b: (source.b * backdrop.b) / 255,
    a: 1,
  };
}

/** Straight-line distance in RGB. Used for the design invariants, not for contrast. */
function rgbDistance(a, b) {
  return Math.round(Math.hypot(a.r - b.r, a.g - b.g, a.b - b.b));
}

function luminance({ r, g, b }) {
  const channel = (v) => {
    const c = v / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(fg, bg) {
  const a = luminance(composite(fg, bg));
  const b = luminance(bg);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

/* --- The pairs the system declares ---------------------------------------------------- */

const STATUSES = ['accepted', 'candidate', 'qualified', 'contested', 'stale', 'private'];
const FEEDBACK = ['success', 'error', 'warning', 'info'];

/**
 * The three PDF evidence highlights, drawn over the reading surface: a SyncTeX target
 * (the default), an accepted source anchor, and a search hit. Each is a fill multiplied
 * over `--rh-surface-paper` with a hairline of its own.
 */
const HIGHLIGHTS = [
  { kind: 'sync', fill: '--rh-highlight-on-paper', border: '--rh-highlight-on-paper-border' },
  {
    kind: 'anchor',
    fill: '--rh-highlight-on-paper-anchor',
    border: '--rh-highlight-on-paper-anchor-border',
  },
  {
    kind: 'match',
    fill: '--rh-highlight-on-paper-match',
    border: '--rh-highlight-on-paper-match-border',
  },
];

const TEXT_MIN = 4.5;
const UI_MIN = 3;
/** Both design invariants below are the same distance the statuses keep from the accent. */
const SEPARATION_MIN = 90;

function pairs() {
  const out = [];
  const text = (fg, bg, note) => out.push({ fg, bg, min: TEXT_MIN, kind: 'text', note });
  const ui = (fg, bg, note) => out.push({ fg, bg, min: UI_MIN, kind: 'non-text', note });
  // Reported but not gated: decorative hairlines and status chip edges. WCAG 1.4.11 asks
  // for 3:1 on what identifies a component or its state — a separator identifies nothing,
  // and a status chip is identified by its glyph and its label, both of which are gated
  // above. Holding decoration to a control's standard would flatten the warm palette into
  // a wireframe for no accessibility gain.
  const info = (fg, bg, note) => out.push({ fg, bg, min: null, kind: 'decorative', note });

  // `subtle` and `selected` are surfaces too: a row a researcher hovers or has selected
  // repaints under text that did not change, and muted ink on a selected row is where this
  // gate found a 3.99:1 pair that axe then confirmed in a real browser.
  for (const surface of ['canvas', 'pane', 'raised', 'subtle', 'selected']) {
    for (const ink of ['primary', 'secondary', 'muted']) {
      text(`--rh-text-${ink}`, `--rh-surface-${surface}`, 'body text');
    }
    text('--rh-text-link', `--rh-surface-${surface}`, 'link');
    text('--rh-accent-text', `--rh-surface-${surface}`, 'accent ink');
  }

  // `paper` is near-white in both themes and carries its own ink.
  for (const ink of ['', '-secondary', '-muted']) {
    text(`--rh-text-on-paper${ink}`, '--rh-surface-paper', 'reading surface');
  }

  // A highlight is a fill multiplied over paper, so the page ink has to stay readable
  // through the product — and the hairline that says where the highlight starts and stops
  // is what identifies it (WCAG 1.4.11), so it is gated at 3:1 against the page. The
  // border multiplies too: it is part of the same blended element.
  for (const { kind, fill, border } of HIGHLIGHTS) {
    out.push({
      fg: '--rh-text-on-paper',
      bg: fill,
      bgOver: '--rh-surface-paper',
      min: TEXT_MIN,
      kind: 'text',
      note: `page ink through the ${kind} highlight`,
    });
    out.push({
      fg: border,
      fgOver: '--rh-surface-paper',
      bg: '--rh-surface-paper',
      min: UI_MIN,
      kind: 'non-text',
      note: `${kind} highlight edge`,
    });
  }

  text('--rh-text-inverse', '--rh-surface-inverse', 'inverse band');
  text('--rh-accent-fg', '--rh-accent', 'ink on the accent fill');
  text('--rh-accent-text', '--rh-accent-subtle', 'accent chip');

  for (const status of STATUSES) {
    text(`--rh-status-${status}-fg`, `--rh-status-${status}-bg`, 'scientific status');
  }
  for (const tone of FEEDBACK) {
    text(`--rh-feedback-${tone}-fg`, `--rh-feedback-${tone}-bg`, 'feedback');
  }

  // Non-text: the focus indicator and the boundary of a control must reach 3:1.
  ui('--rh-focus-ring', '--rh-surface-canvas', 'focus ring');
  ui('--rh-focus-ring', '--rh-surface-pane', 'focus ring');
  ui('--rh-focus-ring', '--rh-surface-raised', 'focus ring');
  ui('--rh-border-strong', '--rh-surface-pane', 'control boundary');
  ui('--rh-border-strong', '--rh-surface-raised', 'control boundary');
  ui('--rh-border-strong', '--rh-surface-canvas', 'control boundary');
  ui('--rh-accent', '--rh-surface-canvas', 'accent fill boundary');

  info('--rh-border-default', '--rh-surface-pane', 'separator');
  info('--rh-border-subtle', '--rh-surface-pane', 'separator');
  for (const status of STATUSES) {
    info(`--rh-status-${status}-border`, `--rh-status-${status}-bg`, 'status chip edge');
  }
  return out;
}

/**
 * The six scientific statuses must not read as the AI/action accent. This is a design
 * invariant, not an accessibility one: an orange chip means a model did something, and a
 * status chip means something is true, so they may not converge.
 */
function accentSeparation(tokens) {
  const accent = parseColour(resolve(tokens, tokens.get('--rh-accent')));
  const rows = [];
  for (const status of STATUSES) {
    const fg = parseColour(resolve(tokens, tokens.get(`--rh-status-${status}-fg`)));
    rows.push({
      status,
      distance: rgbDistance(fg, accent),
      ok: rgbDistance(fg, accent) >= SEPARATION_MIN,
    });
  }
  return rows;
}

/**
 * The same invariant, one surface down. A researcher reading a PDF has to tell a search
 * hit from an accepted anchor from the place SyncTeX just jumped to, so the three marks
 * must stay apart as they are *rendered* — multiplied over paper — and the accepted anchor
 * must not converge on the accent, which means a model did something, not that something
 * is true.
 */
function highlightSeparation(tokens) {
  const paper = parseColour(resolve(tokens, tokens.get('--rh-surface-paper')));
  const drawn = new Map(
    HIGHLIGHTS.map(({ kind, fill }) => [
      kind,
      multiply(parseColour(resolve(tokens, tokens.get(fill))), paper),
    ]),
  );
  const rows = [];
  const kinds = [...drawn.keys()];
  for (let i = 0; i < kinds.length; i += 1) {
    for (let j = i + 1; j < kinds.length; j += 1) {
      const distance = rgbDistance(drawn.get(kinds[i]), drawn.get(kinds[j]));
      rows.push({ status: `${kinds[i]}/${kinds[j]}`, distance, ok: distance >= SEPARATION_MIN });
    }
  }
  const accent = parseColour(resolve(tokens, tokens.get('--rh-accent')));
  const distance = rgbDistance(drawn.get('anchor'), accent);
  rows.push({ status: 'anchor/accent', distance, ok: distance >= SEPARATION_MIN });
  return rows;
}

/* --- Run ------------------------------------------------------------------------------ */

function run() {
  const themes = readThemes();
  const results = [];
  for (const [themeName, tokens] of Object.entries(themes)) {
    for (const pair of pairs()) {
      const fgValue = tokens.get(pair.fg);
      const bgValue = tokens.get(pair.bg);
      if (fgValue === undefined) throw new Error(`${themeName}: ${pair.fg} is not defined`);
      if (bgValue === undefined) throw new Error(`${themeName}: ${pair.bg} is not defined`);
      const blend = (colour, over) => {
        if (over === undefined) return colour;
        const backdrop = tokens.get(over);
        if (backdrop === undefined) throw new Error(`${themeName}: ${over} is not defined`);
        return multiply(colour, parseColour(resolve(tokens, backdrop)));
      };
      const bg = blend(parseColour(resolve(tokens, bgValue)), pair.bgOver);
      const fg = blend(parseColour(resolve(tokens, fgValue)), pair.fgOver);
      const ratio = contrast(fg, bg);
      results.push({
        theme: themeName,
        ...pair,
        ratio: Math.round(ratio * 100) / 100,
        pass: pair.min === null ? true : ratio >= pair.min,
      });
    }
  }

  const separation = {
    dark: accentSeparation(themes.dark),
    light: accentSeparation(themes.light),
  };
  const highlights = {
    dark: highlightSeparation(themes.dark),
    light: highlightSeparation(themes.light),
  };

  if (process.argv.includes('--json')) {
    process.stdout.write(JSON.stringify({ results, separation, highlights }, null, 2) + '\n');
  } else {
    report(results, separation, highlights);
  }

  const failures = results.filter((r) => !r.pass);
  const collisions = [
    ...separation.dark,
    ...separation.light,
    ...highlights.dark,
    ...highlights.light,
  ].filter((r) => !r.ok);
  if (failures.length > 0 || collisions.length > 0) {
    console.error(
      `\ncheck-contrast: ${failures.length} contrast failure(s), ` +
        `${collisions.length} colour collision(s).`,
    );
    process.exit(1);
  }
  const gated = results.filter((r) => r.min !== null).length;
  console.log(
    `\ncheck-contrast: ${gated} gated pairs pass WCAG 2.2 AA ` +
      `(${results.length - gated} decorative pairs reported only).`,
  );
}

/** `a on b`, with `x paper` marking a colour that is multiplied over another. */
function pairLabel(row) {
  const blended = (token, over) => (over === undefined ? token : `${token} x ${short(over)}`);
  return `${blended(row.fg, row.fgOver)} on ${blended(row.bg, row.bgOver)}`;
}

const short = (token) => token.replace('--rh-surface-', '').replace('--rh-', '');

function report(results, separation, highlights) {
  const width = Math.max(...results.map((r) => pairLabel(r).length));
  for (const theme of ['dark', 'light']) {
    console.log(`\n${theme.toUpperCase()} theme`);
    console.log(
      `  ${'pair'.padEnd(width)}  ${'ratio'.padStart(7)}  ${'min'.padStart(4)}  result`,
    );
    for (const row of results.filter((r) => r.theme === theme)) {
      const label = pairLabel(row).padEnd(width);
      const ratio = `${row.ratio.toFixed(2)}:1`.padStart(7);
      const min = row.min === null ? '  --' : String(row.min).padStart(4);
      const verdict = row.min === null ? 'info' : row.pass ? 'pass' : 'FAIL';
      console.log(`  ${label}  ${ratio}  ${min}  ${verdict}` + (row.pass ? '' : `  <- ${row.note}`));
    }
    const lowest = results
      .filter((r) => r.theme === theme && r.min !== null)
      .sort((a, b) => a.ratio - b.ratio)
      .slice(0, 3)
      .map((r) => `${r.fg.replace('--rh-', '')} ${r.ratio.toFixed(2)}:1`)
      .join(', ');
    console.log(`  lowest: ${lowest}`);
    const spread = (rows) =>
      rows.map((s) => `${s.status} ${s.distance}${s.ok ? '' : ' TOO CLOSE'}`).join(', ');
    console.log(`  status/accent separation: ${spread(separation[theme])}`);
    console.log(`  highlight separation (over paper): ${spread(highlights[theme])}`);
  }
}

run();

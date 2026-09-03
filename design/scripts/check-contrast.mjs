/*
 * WCAG 2.2 contrast gate for the semantic token contract.
 *
 * Parses the palette, the shared semantic tokens and both themes, resolves every var()
 * chain down to a colour literal, and computes the contrast ratio for each text/surface
 * pair the system declares. Text pairs must reach 4.5:1; focus rings, component
 * boundaries and large text must reach 3:1.
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
const TEXT_MIN = 4.5;
const UI_MIN = 3;

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

  for (const surface of ['canvas', 'pane', 'raised']) {
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
    const distance = Math.round(
      Math.hypot(fg.r - accent.r, fg.g - accent.g, fg.b - accent.b),
    );
    rows.push({ status, distance, ok: distance >= 90 });
  }
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
      const bg = parseColour(resolve(tokens, bgValue));
      const fg = parseColour(resolve(tokens, fgValue));
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

  if (process.argv.includes('--json')) {
    process.stdout.write(JSON.stringify({ results, separation }, null, 2) + '\n');
  } else {
    report(results, separation);
  }

  const failures = results.filter((r) => !r.pass);
  const collisions = [...separation.dark, ...separation.light].filter((r) => !r.ok);
  if (failures.length > 0 || collisions.length > 0) {
    console.error(
      `\ncheck-contrast: ${failures.length} contrast failure(s), ` +
        `${collisions.length} status/accent collision(s).`,
    );
    process.exit(1);
  }
  const gated = results.filter((r) => r.min !== null).length;
  console.log(
    `\ncheck-contrast: ${gated} gated pairs pass WCAG 2.2 AA ` +
      `(${results.length - gated} decorative pairs reported only).`,
  );
}

function report(results, separation) {
  const width = Math.max(...results.map((r) => `${r.fg} on ${r.bg}`.length));
  for (const theme of ['dark', 'light']) {
    console.log(`\n${theme.toUpperCase()} theme`);
    console.log(
      `  ${'pair'.padEnd(width)}  ${'ratio'.padStart(7)}  ${'min'.padStart(4)}  result`,
    );
    for (const row of results.filter((r) => r.theme === theme)) {
      const label = `${row.fg} on ${row.bg}`.padEnd(width);
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
    console.log(
      `  status/accent separation: ` +
        separation[theme]
          .map((s) => `${s.status} ${s.distance}${s.ok ? '' : ' TOO CLOSE'}`)
          .join(', '),
    );
  }
}

run();

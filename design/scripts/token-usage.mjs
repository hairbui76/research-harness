/*
 * Token census: every `--rh-*` this package declares, and who reads it.
 *
 * A design token is a promise that a name means something. A token nothing reads is not a
 * promise, it is a leftover: it survives palette changes because nothing breaks when it
 * drifts, it turns up in autocomplete beside the name that is real, and it makes the
 * contract in `README.md` longer than the system it describes. The critique found three of
 * them by hand; this finds all of them, every time.
 *
 * What counts as a declaration: a `--rh-*` custom property assigned under `src/tokens` or
 * `src/themes`. Those two directories are the contract; a component that declares a local
 * custom property is declaring an implementation detail, not a token.
 *
 * What counts as a consumer: a `var(--rh-*)` anywhere under `design/src` or `web/src`, or
 * the name written as a string (`getPropertyValue('--rh-…')`). Tests, snapshots and
 * specimens are excluded on purpose — a token whose only reader is the test that asserts it
 * exists has no consumer, and that is exactly the case this is looking for. A reference
 * from inside `tokens/` or `themes/` does count: that is how the raw palette is consumed,
 * and a ramp step the themes pick from is being used for the thing it is for.
 *
 * Usage:
 *   node scripts/token-usage.mjs           # the table, and a non-zero exit if any is dead
 *   node scripts/token-usage.mjs --json    # the same census, for tooling
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const designSrc = join(here, '..', 'src');
const webSrc = join(here, '..', '..', 'web', 'src');

/** The two directories that hold the contract. Everything else declares its own details. */
const DECLARING_DIRECTORIES = [`tokens${sep}`, `themes${sep}`];

const SCANNED = /\.(css|ts|tsx|js|jsx|mjs)$/;

/** A file whose only job is to talk about tokens is not a consumer of them. */
const NOT_A_CONSUMER = /(\.test\.|\.spec\.|specimen|__snapshots__)/;

/**
 * Tokens that are allowed to have no consumer inside this repository, and why.
 *
 * The bar is not "we might want it one day". It is that the token is part of a set the
 * README publishes as an interface, where a host reads the name and the package would be
 * wrong to have only some of it. Each entry names the set.
 */
export const HOST_TOKENS = Object.freeze({
  '--rh-density-gap':
    'One of the four values that make the published density contract ' +
    '(--rh-density-{row,gap,pad,font-scale}, README "Themes and density"). A host laying ' +
    'out its own dense row reads the gap the packaged components get from the space scale.',
  '--rh-z-base':
    'The floor of the published stacking scale (--rh-z-{base,sticky,overlay,popover,toast}, ' +
    'tokens/semantic.css). A host layer that must sit under everything the package draws ' +
    'names it rather than writing a bare 0 that nothing connects to the scale.',
});

function walk(root) {
  const files = [];
  const visit = (dir) => {
    let entries;
    try {
      entries = readdirSync(dir);
    } catch {
      return;
    }
    for (const entry of entries) {
      if (entry === 'node_modules' || entry === 'dist' || entry.startsWith('.')) continue;
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) visit(full);
      else if (SCANNED.test(entry)) files.push(full);
    }
  };
  visit(root);
  return files;
}

/** Every `--rh-*` assigned under `tokens/` or `themes/`, with where it was first declared. */
function declarations() {
  const found = new Map();
  for (const file of walk(designSrc)) {
    const rel = relative(designSrc, file);
    if (!DECLARING_DIRECTORIES.some((prefix) => rel.startsWith(prefix))) continue;
    // Comments go, but their line breaks stay, so the reported line is the real one.
    const lines = readFileSync(file, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, ''))
      .split('\n');
    lines.forEach((line, index) => {
      const match = /^\s*(--rh-[\w-]+)\s*:/.exec(line);
      if (!match) return;
      const name = match[1];
      if (found.has(name)) return;
      found.set(name, { name, file: `design/src/${rel}`, line: index + 1 });
    });
  }
  return found;
}

/** Every token name read by a `var()` or written as a string, outside tests and specimens. */
function consumers() {
  const read = new Set();
  const roots = [designSrc, webSrc];
  for (const root of roots) {
    for (const file of walk(root)) {
      if (NOT_A_CONSUMER.test(file)) continue;
      const text = readFileSync(file, 'utf8');
      for (const match of text.matchAll(/var\(\s*(--rh-[\w-]+)/g)) read.add(match[1]);
      for (const match of text.matchAll(/['"`](--rh-[\w-]+)['"`]/g)) read.add(match[1]);
    }
  }
  return read;
}

/**
 * The census: what is declared, what nothing reads, and which of those is unexplained.
 *
 * `unexplained` is the failing set — a dead token with no entry in `HOST_TOKENS`.
 */
export function tokenCensus() {
  const declared = [...declarations().values()].sort((a, b) => a.name.localeCompare(b.name));
  const read = consumers();
  const dead = declared.filter((token) => !read.has(token.name));
  const unexplained = dead.filter((token) => !(token.name in HOST_TOKENS));
  return { declared, dead, unexplained };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const census = tokenCensus();
  if (process.argv.includes('--json')) {
    console.log(JSON.stringify(census, null, 2));
  } else {
    console.log(`token-usage: ${census.declared.length} tokens declared.`);
    for (const token of census.dead) {
      const reason = HOST_TOKENS[token.name];
      console.log(
        `  ${token.name} — no consumer (${token.file}:${token.line})` +
          (reason ? `\n    kept for hosts: ${reason}` : ''),
      );
    }
    if (census.dead.length === 0) console.log('token-usage: every token has a consumer.');
  }
  if (census.unexplained.length > 0) {
    console.error(
      `\ntoken-usage: ${census.unexplained.length} token(s) nothing reads. Remove them, or ` +
        'add them to HOST_TOKENS with the published set they belong to:\n' +
        census.unexplained.map((token) => `  ${token.name}`).join('\n'),
    );
    process.exit(1);
  }
}

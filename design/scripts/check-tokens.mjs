/*
 * Raw-palette lint.
 *
 * Colour in this system comes from semantic tokens. A literal (`#hex`, `rgb()`, `hsl()`,
 * `oklab()`, `oklch()`, or a `color-mix()` over literals) may appear only in
 * `design/src/tokens` and `design/src/themes` — the two files where the palette is
 * defined and the two theme files that map it onto semantic names. Everywhere else a
 * literal forks the theme: it looks right in dark and wrong in light, or it survives a
 * palette change that everything around it followed.
 *
 * A visualisation sometimes genuinely needs a fixed colour (a chart series, a PDF
 * highlight). Say so on the line:
 *
 *     stroke: #65b5ff; /* raw-colour-ok: chart series 2, fixed across themes *\/
 *
 * The same rule is applied to `web/src`, and it fails there too: every cockpit route is on
 * the package, so a literal in the Web client is the same fork it would be here.
 *
 * The second, smaller check enforces the no-CDN rule: nothing under `design/src` may
 * reference a remote stylesheet, font or image.
 *
 * Usage: node scripts/check-tokens.mjs
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const designSrc = join(here, '..', 'src');
const webSrc = join(here, '..', '..', 'web', 'src');

const SCANNED_EXTENSIONS = /\.(css|ts|tsx|js|jsx|mjs)$/;

/** Where raw palette literals are allowed to live, relative to a scanned root. */
const TOKEN_DIRECTORIES = [`tokens${sep}`, `themes${sep}`];

const ESCAPE_HATCH = /raw-colour-ok:/;

const COLOUR_PATTERNS = [
  { name: 'hex literal', re: /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/ },
  { name: 'rgb()', re: /\brgba?\(/ },
  { name: 'hsl()', re: /\bhsla?\(/ },
  { name: 'oklab()', re: /\boklab\(/ },
  { name: 'oklch()', re: /\boklch\(/ },
  { name: 'lab()/lch()', re: /\bl(?:ab|ch)\(/ },
];

/** `color-mix()` is fine over tokens; it is only a violation when it mixes literals. */
const COLOUR_MIX = /\bcolor-mix\(([^)]*)\)/g;

const REMOTE_ASSET = /(?:@import\s+(?:url\()?["']?|url\(\s*["']?)(?:https?:)?\/\//i;

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
      else if (SCANNED_EXTENSIONS.test(entry)) files.push(full);
    }
  };
  visit(root);
  return files;
}

function isTokenFile(root, file) {
  const rel = relative(root, file);
  return TOKEN_DIRECTORIES.some((prefix) => rel.startsWith(prefix));
}

function scan(root, { checkRemoteAssets }) {
  const violations = [];
  const files = walk(root);
  for (const file of files) {
    const allowLiterals = isTokenFile(root, file);
    const lines = readFileSync(file, 'utf8').split('\n');
    lines.forEach((line, index) => {
      const where = { file, line: index + 1, text: line.trim() };
      if (checkRemoteAssets && REMOTE_ASSET.test(line)) {
        violations.push({ ...where, rule: 'remote asset (no CDN)' });
      }
      if (allowLiterals || ESCAPE_HATCH.test(line)) return;
      for (const { name, re } of COLOUR_PATTERNS) {
        if (re.test(line)) {
          violations.push({ ...where, rule: name });
          return;
        }
      }
      COLOUR_MIX.lastIndex = 0;
      let mix;
      while ((mix = COLOUR_MIX.exec(line)) !== null) {
        if (COLOUR_PATTERNS.some(({ re }) => re.test(mix[1]))) {
          violations.push({ ...where, rule: 'color-mix() over literals' });
          return;
        }
      }
    });
  }
  return { files, violations };
}

function print(label, root, violations, level) {
  if (violations.length === 0) {
    console.log(`check-tokens: ${label} clean.`);
    return;
  }
  console.log(`\ncheck-tokens: ${violations.length} ${level} in ${label}:`);
  for (const v of violations) {
    console.log(`  ${relative(root, v.file)}:${v.line}  ${v.rule}`);
    console.log(`    ${v.text}`);
  }
}

const design = scan(designSrc, { checkRemoteAssets: true });
print(`design/src (${design.files.length} files)`, designSrc, design.violations, 'violation(s)');

const web = scan(webSrc, { checkRemoteAssets: false });
print(`web/src (${web.files.length} files)`, webSrc, web.violations, 'violation(s)');

const total = design.violations.length + web.violations.length;
if (total > 0) {
  console.error(
    `\ncheck-tokens: ${total} violation(s) under design/src and web/src. ` +
      'Use a semantic token, or annotate the line with /* raw-colour-ok: <reason> */.',
  );
  process.exit(1);
}

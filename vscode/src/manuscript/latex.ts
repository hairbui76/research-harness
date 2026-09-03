/**
 * A minimal port of `research_harness/manuscript/latex.py`, for one open editor buffer.
 *
 * The harness is the authority on what a manuscript sentence is: the anchor a Claim hangs
 * on is `<file>#sha256(normalize_sentence(text))`, and that hash is computed server-side
 * whenever the CLI or an audit runs. This module exists only so the editor can answer
 * "which sentence is the cursor in?" without a round trip, and so `Research: Attach Claim`
 * can send the daemon an anchor whose fingerprint the daemon will recognise.
 *
 * It is therefore a *port*, not a reimplementation: the normalization, the fingerprint, the
 * abbreviation list, and the boundary rules are copied from the Python module, and
 * `src/test/latex.test.ts` asserts they reproduce fingerprints exported from Python by
 * `scripts/export_fixtures.py`. Where the port is deliberately narrower than Python it is
 * marked NARROWER below; every such case ends in a fingerprint the daemon does not know,
 * which `attachClaim` detects and reports rather than leaving a silent bad anchor.
 *
 * NARROWER: one file at a time. Python's `LatexProject` expands `\input`/`\include` and
 * carries section state across files. The editor only has the buffer in front of it, so
 * includes end a sentence (as they do in Python, which splits the parent into segments
 * there) and `section_path` is not tracked at all - the fingerprint does not use it.
 *
 * NARROWER: offsets are UTF-16 code units, because that is what a `TextDocument` counts,
 * while Python counts code points. The two agree for every BMP character; a manuscript with
 * astral characters before a sentence gets the same fingerprint but a `char_start` a few
 * units off, which revalidation reads as "moved", never as "changed".
 */

import { createHash } from "node:crypto";

/** Sentence-ending punctuation. */
const TERMINATORS = ".?!";

/** Closers that may follow a terminator and still belong to the same sentence. */
const CLOSERS = ")]'\"\u201d\u2019";

/** Characters that may open the next sentence without being a capital letter. */
const SENTENCE_STARTERS = "\\$`\"([\u201c";

/**
 * Compared case-insensitively against the text ending at a candidate `.`; a match means
 * the period abbreviates rather than terminates. Copied from `latex.py`.
 */
export const SENTENCE_ABBREVIATIONS: readonly string[] = [
  "e.g.",
  "i.e.",
  "et al.",
  "al.",
  "approx.",
  "cf.",
  "ca.",
  "dr.",
  "eq.",
  "eqs.",
  "fig.",
  "figs.",
  "no.",
  "prof.",
  "ref.",
  "refs.",
  "resp.",
  "sec.",
  "tab.",
  "viz.",
  "vs.",
];

/** Environments whose body is never prose; a trailing `*` is ignored when matching. */
const BLOCK_ENVIRONMENTS = new Set([
  "align",
  "eqnarray",
  "equation",
  "gather",
  "multline",
  "displaymath",
  "figure",
  "table",
  "array",
  "tabular",
  "tabularx",
  "verbatim",
  "lstlisting",
  "minted",
]);

const SECTION_LEVELS = new Set([
  "part",
  "chapter",
  "section",
  "subsection",
  "subsubsection",
  "paragraph",
]);

/** Invisible markup: skipped with its group, without ending the surrounding sentence. */
const INLINE_SKIP_WITH_GROUP = new Set(["hspace", "index", "label", "nocite", "vspace"]);

/** Commands that end the surrounding sentence and take no group. */
const BLOCK_SKIP = new Set([
  "appendix",
  "bigskip",
  "centering",
  "clearpage",
  "hline",
  "item",
  "linebreak",
  "maketitle",
  "medskip",
  "midrule",
  "newline",
  "newpage",
  "noindent",
  "pagebreak",
  "par",
  "printbibliography",
  "smallskip",
  "tableofcontents",
  "toprule",
  "bottomrule",
]);

/** Preamble-ish commands that end the surrounding sentence and take a group. */
const BLOCK_SKIP_WITH_GROUP = new Set([
  "addbibresource",
  "author",
  "bibliography",
  "bibliographystyle",
  "date",
  "documentclass",
  "title",
  "usepackage",
]);

/** Font wrappers unwrapped by `normalizeSentence`. */
const STYLE_WRAPPERS = [
  "emph",
  "textbf",
  "textit",
  "textrm",
  "textsc",
  "textsf",
  "texttt",
  "underline",
  "mbox",
  "text",
];

/** Citation macros (natbib, biblatex, plain LaTeX), longest first so `citep` beats `cite`. */
const CITATION_COMMANDS = [
  "autocite",
  "citealp",
  "citealt",
  "citeauthor",
  "citep",
  "citet",
  "citeyear",
  "cite",
  "footcite",
  "parencite",
  "textcite",
];

function alternation(names: readonly string[]): string {
  return [...names]
    .sort((a, b) => b.length - a.length)
    .map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");
}

/** `\citep[see][p.~3]{a,b}` - optional bracket arguments, then one brace group of keys. */
export const CITATION_PATTERN = `\\\\(?:${alternation(CITATION_COMMANDS)})\\*?(?:\\s*\\[[^\\[\\]]*\\])*\\s*\\{([^{}]*)\\}`;

const CITATION_RE = new RegExp(CITATION_PATTERN, "g");
const BEGIN_RE = /\\begin\s*\{([^{}]*)\}/y;
const END_RE = /\\end\s*\{([^{}]*)\}/y;
const INCLUDE_RE = /\\(input|include)\s*\{([^{}]*)\}/g;
const SECTION_RE = new RegExp(
  `\\\\(${[...SECTION_LEVELS].join("|")})\\*?\\s*(?:\\[[^\\[\\]]*\\])?\\s*\\{`,
  "y",
);
const COMMAND_RE = /\\([A-Za-z]+)\*?|\\[\s\S]/y;
const OPTIONAL_ARGS_RE = /\s*(?:\[[^[\]]*\])*\s*/y;
const STYLE_WRAPPER_RE = new RegExp(`\\\\(?:${STYLE_WRAPPERS.join("|")})\\s*\\{([^{}]*)\\}`, "g");
const DROPPED_RE = /\\(?:label|index|nocite)\s*\{[^{}]*\}/g;
const UNESCAPE_RE = /\\([%&#_])/g;
const SPACE_BEFORE_PUNCTUATION_RE = /\s+([,.;:!?)\]])/g;
const DOCUMENT_BEGIN_RE = /\\begin\s*\{document\}/;
const DOCUMENT_END_RE = /\\end\s*\{document\}/;

// -- text normalization ------------------------------------------------------

/** Half-open spans of `%` comments (excluding the newline); `\%` is not one. */
function commentSpans(text: string): Array<[number, number]> {
  const spans: Array<[number, number]> = [];
  let index = 0;
  while (index < text.length) {
    const char = text[index];
    if (char === "\\") {
      index += 2;
      continue;
    }
    if (char === "%") {
      const found = text.indexOf("\n", index);
      const end = found === -1 ? text.length : found;
      spans.push([index, end]);
      index = end;
      continue;
    }
    index += 1;
  }
  return spans;
}

/** Blank every comment body to spaces, keeping length so offsets still index `text`. */
export function maskComments(text: string): string {
  if (!text.includes("%")) {
    return text;
  }
  const spans = commentSpans(text);
  if (spans.length === 0) {
    return text;
  }
  let out = "";
  let cursor = 0;
  for (const [start, end] of spans) {
    out += text.slice(cursor, start) + " ".repeat(end - start);
    cursor = end;
  }
  return out + text.slice(cursor);
}

/**
 * Reduce a sentence to the form whose hash identifies it across cosmetic edits.
 *
 * Citations are removed (their keys are tracked separately), invisible markup is dropped,
 * font wrappers are unwrapped, `--`/`---` become dashes, `\%` and friends are unescaped,
 * and whitespace collapses. Math, numbers, and units survive verbatim, because they are
 * exactly what a style pass must not change (Product 30.4).
 */
export function normalizeSentence(text: string): string {
  let out = text.replace(CITATION_RE, " ");
  out = out.replace(DROPPED_RE, " ");
  for (let round = 0; round < 4; round += 1) {
    const unwrapped = out.replace(STYLE_WRAPPER_RE, "$1");
    if (unwrapped === out) {
      break;
    }
    out = unwrapped;
  }
  out = out.split("---").join("\u2014").split("--").join("\u2013");
  out = out.replace(UNESCAPE_RE, "$1");
  out = out.split("~").join(" ");
  out = out.split(/\s+/).filter((part) => part.length > 0).join(" ");
  return out.replace(SPACE_BEFORE_PUNCTUATION_RE, "$1");
}

/** `sha256:<hex>` over `normalizeSentence(text)` - the anchor identity. */
export function sentenceFingerprint(text: string): string {
  const digest = createHash("sha256").update(normalizeSentence(text), "utf8").digest("hex");
  return `sha256:${digest}`;
}

/** Citation keys cited in `text`, in order of first appearance, deduplicated. */
export function citationKeys(text: string): string[] {
  const keys: string[] = [];
  for (const match of text.matchAll(CITATION_RE)) {
    for (const raw of (match[1] ?? "").split(",")) {
      const key = raw.trim();
      if (key && !keys.includes(key)) {
        keys.push(key);
      }
    }
  }
  return keys;
}

// -- sentences ---------------------------------------------------------------

/** One manuscript sentence of one file, addressable the way an anchor is. */
export interface LocalSentence {
  /** Project-relative POSIX path, as the anchor records it. */
  file: string;
  /** 1-based, inclusive, as the harness reports lines. */
  lineStart: number;
  lineEnd: number;
  /** Half-open offsets into the raw file text. */
  charStart: number;
  charEnd: number;
  /** LaTeX source with comment bodies blanked to spaces. */
  text: string;
  normalizedText: string;
  fingerprint: string;
  citationKeys: string[];
}

function isSpace(char: string): boolean {
  return /\s/.test(char);
}

function isDigit(char: string): boolean {
  return char >= "0" && char <= "9";
}

function isUpper(char: string): boolean {
  return char !== char.toLowerCase() && char === char.toUpperCase();
}

function baseEnvironment(name: string): string {
  return name.replace(/\*+$/, "");
}

function stickyMatch(re: RegExp, text: string, index: number): RegExpExecArray | null {
  re.lastIndex = index;
  return re.exec(text);
}

function findAfter(text: string, closer: string, start: number, end: number): number {
  const found = text.indexOf(closer, start);
  return found === -1 || found >= end ? end : found + closer.length;
}

function environmentEnd(text: string, start: number, name: string, end: number): number | null {
  const pattern = new RegExp(`\\\\(begin|end)\\s*\\{${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\}`, "g");
  pattern.lastIndex = start;
  let depth = 0;
  let match = pattern.exec(text);
  while (match !== null && match.index < end) {
    depth += match[1] === "begin" ? 1 : -1;
    if (depth === 0) {
      return match.index + match[0].length;
    }
    match = pattern.exec(text);
  }
  return null;
}

/** Offset just past the `}` closing the group that starts at `start`. */
function groupEnd(text: string, start: number, end: number): number {
  let depth = 1;
  let cursor = start;
  while (cursor < end) {
    const char = text[cursor];
    if (char === "\\") {
      cursor += 2;
      continue;
    }
    if (char === "{") {
      depth += 1;
    } else if (char === "}") {
      depth -= 1;
      if (depth === 0) {
        return cursor + 1;
      }
    }
    cursor += 1;
  }
  return end;
}

/** Skip optional `[...]` arguments and at most one `{...}` group. */
function skipArguments(text: string, start: number, end: number): number {
  const optional = stickyMatch(OPTIONAL_ARGS_RE, text, start);
  const cursor = optional === null ? start : Math.min(start + optional[0].length, end);
  if (cursor < end && text[cursor] === "{") {
    return groupEnd(text, cursor + 1, end);
  }
  return Math.max(start, cursor);
}

/**
 * True when the raw source between two content characters contains an empty line.
 *
 * Blankness is judged on the raw text, so a full-line `%` comment inside a sentence does
 * not split it and does not change its fingerprint.
 */
function hasBlankLine(raw: string, start: number, end: number): boolean {
  const span = raw.slice(start, end);
  const first = span.indexOf("\n");
  const last = span.lastIndexOf("\n");
  if (first === -1 || first === last) {
    return false;
  }
  return span
    .slice(first + 1, last)
    .split("\n")
    .some((part) => part.trim().length === 0);
}

function lineStarts(text: string): number[] {
  const starts = [0];
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === "\n") {
      starts.push(index + 1);
    }
  }
  return starts;
}

/** 1-based line number of `offset`, matching Python's `bisect_right(line_starts, offset)`. */
function lineOf(starts: readonly number[], offset: number): number {
  let low = 0;
  let high = starts.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (offset < (starts[mid] as number)) {
      high = mid;
    } else {
      low = mid + 1;
    }
  }
  return low;
}

class Scanner {
  private readonly starts: number[];
  private start: number | null = null;
  private depth = 0;

  readonly sentences: LocalSentence[] = [];

  constructor(
    private readonly file: string,
    private readonly raw: string,
    private readonly masked: string,
  ) {
    this.starts = lineStarts(raw);
  }

  run(segments: Array<[number, number]>): void {
    for (const [start, end] of segments) {
      if (end <= start) {
        continue;
      }
      this.start = null;
      this.depth = 0;
      this.scan(start, end);
      this.flush(end);
    }
  }

  private scan(begin: number, end: number): void {
    const text = this.masked;
    let index = begin;
    while (index < end) {
      const char = text[index] as string;
      if (char === "\\") {
        index = this.command(index, end);
      } else if (char === "$") {
        index = this.dollar(index, end);
      } else if (char === "{") {
        this.open(index);
        this.depth += 1;
        index += 1;
      } else if (char === "}") {
        this.depth = Math.max(0, this.depth - 1);
        index += 1;
      } else if (isSpace(char)) {
        index = this.whitespace(index, end);
      } else if (TERMINATORS.includes(char)) {
        this.open(index);
        const stop = this.boundary(index, end);
        if (stop === null) {
          index += 1;
        } else {
          this.flush(stop);
          index = stop;
        }
      } else {
        this.open(index);
        index += 1;
      }
    }
  }

  private command(index: number, end: number): number {
    const text = this.masked;
    const begin = stickyMatch(BEGIN_RE, text, index);
    if (begin !== null) {
      return this.beginEnvironment(begin, end);
    }
    const closing = stickyMatch(END_RE, text, index);
    if (closing !== null) {
      this.flush(index);
      return index + closing[0].length;
    }
    if (text.startsWith("\\[", index)) {
      return this.displayMath(index, end, "\\]");
    }
    if (text.startsWith("\\(", index)) {
      this.open(index);
      return findAfter(text, "\\)", index + 2, end);
    }
    const heading = stickyMatch(SECTION_RE, text, index);
    if (heading !== null) {
      this.flush(index);
      return groupEnd(text, index + heading[0].length, end);
    }
    const command = stickyMatch(COMMAND_RE, text, index);
    if (command === null) {
      this.open(index);
      return index + 1;
    }
    const commandEnd = index + command[0].length;
    const name = command[1] ?? "";
    if (INLINE_SKIP_WITH_GROUP.has(name)) {
      return skipArguments(text, commandEnd, end);
    }
    if (BLOCK_SKIP.has(name)) {
      this.flush(index);
      return commandEnd;
    }
    if (BLOCK_SKIP_WITH_GROUP.has(name)) {
      this.flush(index);
      return skipArguments(text, commandEnd, end);
    }
    this.open(index);
    return commandEnd;
  }

  private beginEnvironment(match: RegExpExecArray, end: number): number {
    const name = (match[1] ?? "").trim();
    this.flush(match.index);
    if (!BLOCK_ENVIRONMENTS.has(baseEnvironment(name))) {
      return match.index + match[0].length;
    }
    return environmentEnd(this.masked, match.index, name, end) ?? end;
  }

  private displayMath(index: number, end: number, closer: string): number {
    this.flush(index);
    return findAfter(this.masked, closer, index + 2, end);
  }

  private dollar(index: number, end: number): number {
    if (this.masked.startsWith("$$", index)) {
      this.flush(index);
      return findAfter(this.masked, "$$", index + 2, end);
    }
    this.open(index);
    let cursor = index + 1;
    while (cursor < end) {
      if (this.masked[cursor] === "\\") {
        cursor += 2;
        continue;
      }
      if (this.masked[cursor] === "$") {
        return cursor + 1;
      }
      cursor += 1;
    }
    return end;
  }

  private whitespace(index: number, end: number): number {
    let cursor = index;
    while (cursor < end && isSpace(this.masked[cursor] as string)) {
      cursor += 1;
    }
    if (this.start !== null && hasBlankLine(this.raw, index, cursor)) {
      this.flush(index);
    }
    return cursor;
  }

  private open(index: number): void {
    if (this.start === null) {
      this.start = index;
    }
  }

  private flush(end: number): void {
    const start = this.start;
    this.start = null;
    if (start === null || end <= start) {
      return;
    }
    const raw = this.masked.slice(start, end).replace(/\s+$/u, "");
    if (!raw) {
      return;
    }
    const normalized = normalizeSentence(raw);
    if (!normalized) {
      return;
    }
    const stop = start + raw.length;
    this.sentences.push({
      file: this.file,
      lineStart: lineOf(this.starts, start),
      lineEnd: lineOf(this.starts, stop - 1),
      charStart: start,
      charEnd: stop,
      text: raw,
      normalizedText: normalized,
      fingerprint: sentenceFingerprint(normalized),
      citationKeys: citationKeys(raw),
    });
  }

  /** Offset just past a sentence-ending `.`/`?`/`!`, or `null`. */
  private boundary(index: number, end: number): number | null {
    const text = this.masked;
    if (this.depth > 0) {
      return null;
    }
    if (text[index] === ".") {
      const after = index + 1 < end ? (text[index + 1] as string) : "";
      if (index > 0 && isDigit(text[index - 1] as string) && isDigit(after)) {
        return null;
      }
      const window = text.slice(Math.max(0, index - 16), index + 1).toLowerCase();
      if (SENTENCE_ABBREVIATIONS.some((abbreviation) => window.endsWith(abbreviation))) {
        return null;
      }
    }
    let stop = index + 1;
    while (stop < end && CLOSERS.includes(text[stop] as string)) {
      stop += 1;
    }
    if (stop >= end) {
      return stop;
    }
    if (!isSpace(text[stop] as string)) {
      return null;
    }
    let cursor = stop;
    while (cursor < end && isSpace(text[cursor] as string)) {
      cursor += 1;
    }
    if (cursor >= end || text.slice(stop, cursor).includes("\n")) {
      return stop;
    }
    const following = text[cursor] as string;
    if (isUpper(following) || isDigit(following) || SENTENCE_STARTERS.includes(following)) {
      return stop;
    }
    return null;
  }
}

/**
 * Every sentence of one LaTeX buffer, in document order.
 *
 * `file` is the project-relative POSIX path an anchor records; it is carried through rather
 * than derived, because only the caller knows where the manuscript root is.
 */
export function sentencesOf(file: string, raw: string): LocalSentence[] {
  const masked = maskComments(raw);
  const begin = DOCUMENT_BEGIN_RE.exec(masked);
  const start = begin === null ? 0 : begin.index + begin[0].length;
  const closing = DOCUMENT_END_RE.exec(masked.slice(start));
  const end = closing === null ? masked.length : start + closing.index;

  // `\input`/`\include` splice another file in; the editor cannot follow them, so they end
  // the sentence they interrupt exactly as a segment boundary does in Python.
  const segments: Array<[number, number]> = [];
  let cursor = start;
  INCLUDE_RE.lastIndex = start;
  let match = INCLUDE_RE.exec(masked);
  while (match !== null && match.index < end) {
    segments.push([cursor, match.index]);
    cursor = match.index + match[0].length;
    match = INCLUDE_RE.exec(masked);
  }
  segments.push([cursor, end]);

  const scanner = new Scanner(file, raw, masked);
  scanner.run(segments);
  return scanner.sentences;
}

/** The sentence covering a 1-based `line`, or `undefined` when the line carries none. */
export function sentenceAtLine(
  sentences: readonly LocalSentence[],
  line: number,
): LocalSentence | undefined {
  return sentences.find((item) => item.lineStart <= line && line <= item.lineEnd);
}

/** The sentence covering a raw-text `offset`, or `undefined`. */
export function sentenceAtOffset(
  sentences: readonly LocalSentence[],
  offset: number,
): LocalSentence | undefined {
  return sentences.find((item) => item.charStart <= offset && offset < item.charEnd);
}

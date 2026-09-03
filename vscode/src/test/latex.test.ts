/**
 * The TypeScript segmentation must agree with `manuscript/latex.py`, sentence for sentence.
 *
 * `fixtures/manuscript.json` is written by `scripts/export_fixtures.py` from the real Python
 * module, so these are not assertions about what the port ought to do - they are the
 * harness's own answers. A fingerprint mismatch here is the failure that would otherwise
 * appear as an anchor the daemon never recognises.
 */

import { describe, expect, it } from "vitest";

import {
  citationKeys,
  maskComments,
  normalizeSentence,
  sentenceAtLine,
  sentenceAtOffset,
  sentenceFingerprint,
  sentencesOf,
} from "../manuscript/latex";
import manuscript from "./fixtures/manuscript.json";

interface FixtureSentence {
  file: string;
  line_start: number;
  line_end: number;
  char_start: number;
  char_end: number;
  normalized_text: string;
  fingerprint: string;
  citation_keys: string[];
}

const expected = manuscript.sentences as FixtureSentence[];
const parsed = sentencesOf("main.tex", manuscript.source);

describe("segmentation parity with manuscript/latex.py", () => {
  it("finds the same sentences the harness finds", () => {
    expect(parsed.map((item) => item.normalizedText)).toEqual(
      expected.map((item) => item.normalized_text),
    );
  });

  it("computes the fingerprint every anchor is keyed on", () => {
    expect(parsed.map((item) => item.fingerprint)).toEqual(
      expected.map((item) => item.fingerprint),
    );
  });

  it("reports the same line ranges, which is how a finding is placed", () => {
    expect(parsed.map((item) => [item.lineStart, item.lineEnd])).toEqual(
      expected.map((item) => [item.line_start, item.line_end]),
    );
  });

  it("reports the same character span, which is what a diagnostic underlines", () => {
    expect(parsed.map((item) => [item.charStart, item.charEnd])).toEqual(
      expected.map((item) => [item.char_start, item.char_end]),
    );
  });

  it("extracts the same citation keys", () => {
    expect(parsed.map((item) => item.citationKeys)).toEqual(
      expected.map((item) => item.citation_keys),
    );
  });
});

describe("boundary rules", () => {
  it("does not split a decimal", () => {
    const sentences = sentencesOf("a.tex", "Recall reaches 94.32 percent on the held-out split.\n");
    expect(sentences).toHaveLength(1);
    expect(sentences[0]?.normalizedText).toContain("94.32");
  });

  it("does not split on an abbreviation", () => {
    const sentences = sentencesOf("a.tex", "Surveys, e.g. the 2024 review, report no figure.\n");
    expect(sentences).toHaveLength(1);
  });

  it("does not split on et al.", () => {
    const sentences = sentencesOf("a.tex", "Hale et al. report a drop under sustained load.\n");
    expect(sentences).toHaveLength(1);
  });

  it("splits on a terminator followed by a capital", () => {
    const sentences = sentencesOf("a.tex", "The first claim holds. The second does not.\n");
    expect(sentences.map((item) => item.normalizedText)).toEqual([
      "The first claim holds.",
      "The second does not.",
    ]);
  });

  it("splits on a paragraph break even without a terminator", () => {
    const sentences = sentencesOf("a.tex", "A trailing fragment\n\nA second paragraph\n");
    expect(sentences.map((item) => item.normalizedText)).toEqual([
      "A trailing fragment",
      "A second paragraph",
    ]);
  });

  it("keeps a sentence whole across a line break and a full-line comment", () => {
    const sentences = sentencesOf(
      "a.tex",
      "The measured value holds\n% an aside that must not split anything\nunder load.\n",
    );
    expect(sentences).toHaveLength(1);
    expect(sentences[0]?.normalizedText).toBe("The measured value holds under load.");
  });

  it("excludes a display environment from the sentence stream", () => {
    const sentences = sentencesOf(
      "a.tex",
      "Before the display.\n\n\\begin{equation}\n  x = 1.\n\\end{equation}\n\nAfter the display.\n",
    );
    expect(sentences.map((item) => item.normalizedText)).toEqual([
      "Before the display.",
      "After the display.",
    ]);
  });

  it("excludes a section heading, which carries no research assertion", () => {
    const sentences = sentencesOf("a.tex", "\\section{Introduction}\n\nProse follows here.\n");
    expect(sentences.map((item) => item.normalizedText)).toEqual(["Prose follows here."]);
  });
});

describe("normalization", () => {
  it("removes citation commands but keeps their keys separately", () => {
    const raw = "Load matters \\citep[see][p.~3]{a2024,b2025}.";
    expect(normalizeSentence(raw)).toBe("Load matters.");
    expect(citationKeys(raw)).toEqual(["a2024", "b2025"]);
  });

  it("unwraps font commands and unescapes protected punctuation", () => {
    expect(normalizeSentence("A \\textbf{bold} gain of 5\\% held.")).toBe(
      "A bold gain of 5% held.",
    );
  });

  it("is idempotent, so re-hashing a stored sentence gives the same fingerprint", () => {
    const once = normalizeSentence("Recall  rose\nby 5--7 points \\citep{x}.");
    expect(normalizeSentence(once)).toBe(once);
    expect(sentenceFingerprint(once)).toBe(sentenceFingerprint(normalizeSentence(once)));
  });

  it("blanks comment bodies without moving any offset", () => {
    const text = "keep % drop\nkeep";
    const masked = maskComments(text);
    expect(masked).toHaveLength(text.length);
    expect(masked).toBe("keep       \nkeep");
  });
});

describe("the sentence under the cursor", () => {
  it("finds the sentence covering the first line of its range", () => {
    const found = sentenceAtLine(parsed, expected[1]?.line_start ?? 1);
    expect(found?.fingerprint).toBe(expected[1]?.fingerprint);
  });

  it("finds it from the last line too, since a sentence spans line breaks", () => {
    const found = sentenceAtLine(parsed, expected[1]?.line_end ?? 1);
    expect(found?.fingerprint).toBe(expected[1]?.fingerprint);
  });

  it("returns undefined on a line that carries no sentence", () => {
    // Line 1 is a comment; line 12 is the blank line before the first paragraph.
    expect(sentenceAtLine(parsed, 1)).toBeUndefined();
    expect(sentenceAtLine(parsed, 12)).toBeUndefined();
  });

  it("finds the sentence by character offset, the way a selection reports one", () => {
    const target = expected[2];
    const middle = Math.floor(((target?.char_start ?? 0) + (target?.char_end ?? 0)) / 2);
    expect(sentenceAtOffset(parsed, middle)?.fingerprint).toBe(target?.fingerprint);
  });

  it("returns undefined for an offset between sentences", () => {
    const gap = (expected[0]?.char_end ?? 0) + 1;
    expect(sentenceAtOffset(parsed, gap)).toBeUndefined();
  });
});

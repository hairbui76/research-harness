/**
 * The mapping layer, on its own.
 *
 * These are the places where a wrong answer would be invisible in the interface: a tree
 * assembled from the wrong path segments, a stale PDF presented as current, a compiler
 * count borrowed by the audit list, a SyncTeX rectangle flipped the wrong way, or a
 * candidate whose Apply is enabled because the blocking reason was dropped.
 */
import { describe, expect, it } from 'vitest';
import type { BuildView, ManuscriptFile, SuggestionCandidate } from '../../api/dto';
import {
  auditFindingsFrom,
  blockedReasonOf,
  buildModelFrom,
  buildStatusOf,
  candidateDiffFrom,
  diagnosticsFrom,
  fileKindOf,
  fileTreeFrom,
  hunkHeader,
  manuscriptReference,
  synctexReasonOf,
  toSynctexPoint,
  toUserSpaceRect,
  whereOf,
} from './mappers';
import succeeded from '../../test/fixtures/manuscript-workspace/build-succeeded.json';
import failed from '../../test/fixtures/manuscript-workspace/build-failed.json';
import unavailable from '../../test/fixtures/manuscript-workspace/build-unavailable.json';
import tree from '../../test/fixtures/manuscript-workspace/files.json';
import candidateJson from '../../test/fixtures/manuscript-workspace/candidate.json';
import blockedJson from '../../test/fixtures/manuscript-workspace/candidate-blocked.json';

const SUCCEEDED = succeeded as unknown as BuildView;
const FAILED = failed as unknown as BuildView;
const UNAVAILABLE = unavailable as unknown as BuildView;
const FILES = tree.files as unknown as ManuscriptFile[];
const CANDIDATE = candidateJson as unknown as SuggestionCandidate;
const BLOCKED = blockedJson as unknown as SuggestionCandidate;

describe('the file tree', () => {
  it('grows the directories out of the flat list the daemon answers with', () => {
    const nodes = fileTreeFrom(FILES);

    expect(nodes.map((node) => node.path)).toEqual(['sections', 'main.tex', 'references.bib']);
    const sections = nodes[0]!;
    expect(sections.kind).toBe('dir');
    expect(sections.children?.map((child) => child.path)).toEqual(['sections/intro.tex']);
  });

  it('marks the file a researcher has unsaved work in, and the folder holding it', () => {
    const nodes = fileTreeFrom(FILES, { 'sections/intro.tex': { dirty: true } });

    const sections = nodes.find((node) => node.path === 'sections')!;
    expect(sections.dirty).toBe(true);
    expect(sections.children?.[0]?.dirty).toBe(true);
    expect(nodes.find((node) => node.path === 'main.tex')?.dirty).toBeUndefined();
  });

  it('gives a compiled figure the PDF glyph the daemon files under `image`', () => {
    expect(fileKindOf({ path: 'figures/plot.pdf', kind: 'image' })).toBe('pdf');
    expect(fileKindOf({ path: 'figures/plot.png', kind: 'image' })).toBe('image');
  });
});

describe('the build model', () => {
  it('reads `unavailable` off the toolchain rather than off a refused compile', () => {
    expect(buildStatusOf(UNAVAILABLE, false)).toBe('unavailable');
    expect(buildStatusOf(UNAVAILABLE, true)).toBe('running');
    expect(buildStatusOf(null, false)).toBe('idle');
    expect(buildStatusOf(SUCCEEDED, false)).toBe('succeeded');
    expect(buildStatusOf(FAILED, false)).toBe('failed');
  });

  it('carries the setup guidance when there is no engine, and no PDF of any kind', () => {
    const model = buildModelFrom(UNAVAILABLE, { compiling: false });

    expect(model.status).toBe('unavailable');
    expect(model.setupGuidance).toContain('No LaTeX engine is installed');
    expect(model.pdf).toBeUndefined();
    expect(model.lastGood).toBeUndefined();
  });

  it('shows a successful build as its own, current PDF', () => {
    const model = buildModelFrom(SUCCEEDED, { compiling: false, pdfUrl: '/pdf/b-0002' });

    expect(model.pdf).toEqual({
      url: '/pdf/b-0002',
      stale: false,
      producedAt: '2026-09-03T10:00:04Z',
    });
    expect(model.engine).toBe('latexmk -norc -pdf -interaction=nonstopmode -file-line-error -synctex=1');
  });

  it('keeps the last good PDF, and only the last good PDF, after a failure', () => {
    const model = buildModelFrom(FAILED, { compiling: false, lastGoodUrl: '/pdf/last-good' });

    // No `pdf` and a `lastGood` is exactly what makes `PdfPreview` draw its stale banner.
    expect(model.pdf).toBeUndefined();
    expect(model.lastGood).toEqual({
      url: '/pdf/last-good',
      producedAt: '2026-09-03T10:00:04Z',
    });
    expect(model.status).toBe('failed');
  });

  it('quotes the daemon on why SyncTeX is unavailable instead of inventing a reason', () => {
    expect(synctexReasonOf(SUCCEEDED)).toBeUndefined();
    expect(synctexReasonOf(FAILED)).toBe(
      'no SyncTeX file at main.synctex.gz; the engine produced none',
    );
    expect(buildModelFrom(FAILED, { compiling: false }).synctex).toBe('unavailable');
  });
});

describe('the two lists', () => {
  it('keeps the compiler’s messages and the audit’s findings apart', () => {
    const diagnostics = diagnosticsFrom(FAILED);
    const findings = auditFindingsFrom(FAILED.audit_findings);

    expect(diagnostics).toHaveLength(2);
    expect(diagnostics.every((row) => row.source === 'compiler')).toBe(true);
    expect(findings).toHaveLength(1);
    expect(findings.every((row) => row.source === 'audit')).toBe(true);
    // Different vocabularies on purpose: nothing sums 2 and 1 into 3.
    expect(diagnostics[0]).toMatchObject({
      severity: 'error',
      file: 'sections/intro.tex',
      line: 7,
      code: 'Undefined control sequence',
    });
  });

  it('places a finding by its own structured location and names its Claim', () => {
    const [finding] = auditFindingsFrom(SUCCEEDED.audit_findings);

    expect(finding).toMatchObject({
      kind: 'over_strong_wording',
      severity: 'error',
      file: 'sections/intro.tex',
      line: 4,
      claim: { id: 'C0001' },
      anchor: { id: 'sections/intro.tex:4' },
    });
  });

  /**
   * A finding card opens with the manuscript's own sentence, so the sentence has to reach
   * it. An anchored finding carries it through the anchor; one raised against a sentence
   * attached to nothing carries no anchor at all and answers with its own field.
   */
  it('carries the manuscript sentence each finding is about', () => {
    const [anchored, unattached] = auditFindingsFrom(SUCCEEDED.audit_findings);

    expect(anchored?.sentence).toBe(
      'All existing traffic classifiers degrade under sustained load, and no prior work ' +
        'reports the size of the gap \\cite{kraus2019}.',
    );
    expect(unattached?.sentence).toBe(
      'No prior work reports the size of the gap \\cite{kraus2019}.',
    );
  });

  /**
   * The auditor writes `"<file>:<line>: "` in front of every message and keeps it there on
   * purpose, as the fallback for a client older than `location`. The cockpit draws the
   * position from `location`, so the card would otherwise say where twice.
   */
  it('drops the position the message repeats, and only where it matches', () => {
    const [anchored] = auditFindingsFrom(SUCCEEDED.audit_findings);
    expect(anchored?.message).toBe(
      'sentence reads above C0001: the Claim allows corpus-level wording, the sentence ' +
        'asserts it universally',
    );

    const unprefixed = auditFindingsFrom([
      {
        kind: 'stale_claim',
        severity: 'warning',
        message: 'C0001 needs review before this sentence ships',
        location: { file: 'sections/intro.tex', line_start: 9, line_end: 9 },
      },
    ]);
    expect(unprefixed[0]?.message).toBe('C0001 needs review before this sentence ships');
  });

  it('says so plainly when no sentence produced a finding', () => {
    expect(whereOf({ kind: 'stale_claim', severity: 'warning', message: 'x' })).toBe(
      'whole project',
    );
    expect(whereOf(SUCCEEDED.audit_findings[0]!)).toBe('sections/intro.tex:4-5');
    expect(whereOf(SUCCEEDED.audit_findings[1]!)).toBe('sections/intro.tex:5');
  });
});

describe('a candidate diff', () => {
  it('marks the protected span on the line that carries it', () => {
    const diff = candidateDiffFrom(CANDIDATE);

    const lines = diff.hunks[0]!.lines;
    const cited = lines.filter((line) => line.protected !== undefined);
    expect(cited).toHaveLength(2);
    expect(cited[0]?.protected).toEqual({
      kind: 'citation',
      reason: 'A protected citation: the rewrite has to keep it exactly as it is.',
    });
    expect(diff.hunks[0]?.header).toBe(hunkHeader(CANDIDATE.hunks[0]!));
  });

  it('leaves Apply unblocked for a candidate the daemon passed', () => {
    expect(blockedReasonOf(CANDIDATE)).toBeUndefined();
    expect(candidateDiffFrom(CANDIDATE).auditStatus).toBe('passed');
  });

  it('carries the daemon’s own blocking reason, and says the span was changed', () => {
    const diff = candidateDiffFrom(BLOCKED);

    expect(diff.auditStatus).toBe('failed');
    expect(diff.blockedReason).toContain('a style pass may change wording');
    const changed = diff.hunks[0]!.lines.find((line) => line.protected !== undefined);
    expect(changed?.protected?.reason).toContain('changed a protected citation');
  });

  it('summarises the movement of a weakened proposition, not only its new words', () => {
    const diff = candidateDiffFrom(BLOCKED);

    expect(diff.semanticSummary.weakened[0]).toContain('→');
    expect(diff.semanticSummary.weakened[0]).toContain('\\cite{kraus2019}');
  });

  it('refuses a rewrite that proposed nothing, which the wire does not phrase', () => {
    const unchanged: SuggestionCandidate = {
      ...CANDIDATE,
      proposed_text: CANDIDATE.original_text,
    };

    expect(blockedReasonOf(unchanged)).toContain('proposed no change');
    expect(blockedReasonOf({ ...CANDIDATE, applied: true })).toContain('already been applied');
  });
});

describe('coordinates and references', () => {
  it('flips a SyncTeX box into the user space pdf.js draws in', () => {
    // Top-left origin: 24pt tall, 180pt down a 792pt page -> 588..612 up from the bottom.
    expect(toUserSpaceRect({ page: 1, x: 72, y: 180, width: 468, height: 24 }, 792)).toEqual([
      72, 588, 540, 612,
    ]);
  });

  it('flips a pdf.js point back into the space SyncTeX is asked in', () => {
    expect(toSynctexPoint(72, 588, 792)).toEqual({ x: 72, y: 204 });
  });

  it('writes the reference W1 and W3 paste into a conversation', () => {
    expect(manuscriptReference('sections/intro.tex', 4)).toBe(
      'rh://manuscript/sections/intro.tex?line=4',
    );
    expect(manuscriptReference('a b/c.tex', 12)).toBe('rh://manuscript/a%20b/c.tex?line=12');
  });
});

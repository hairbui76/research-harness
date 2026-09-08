/**
 * Fixtures shared by the manuscript specimens. Not part of the published package —
 * `tsconfig.build.json` excludes `src/**\/*.specimen*` from `dist`.
 */
import type {
  AuditFindingModel,
  BuildModel,
  CandidateDiffModel,
  DiagnosticModel,
  FileNode,
} from './models';

export const files: FileNode[] = [
  {
    path: 'manuscript',
    name: 'manuscript',
    kind: 'dir',
    children: [
      { path: 'manuscript/main.tex', name: 'main.tex', kind: 'tex', dirty: true },
      { path: 'manuscript/refs.bib', name: 'refs.bib', kind: 'bib' },
      {
        path: 'manuscript/sections',
        name: 'sections',
        kind: 'dir',
        children: [
          { path: 'manuscript/sections/intro.tex', name: 'intro.tex', kind: 'tex' },
          {
            path: 'manuscript/sections/results.tex',
            name: 'results.tex',
            kind: 'tex',
            conflict: true,
          },
        ],
      },
      {
        path: 'manuscript/figures',
        name: 'figures',
        kind: 'dir',
        children: [
          { path: 'manuscript/figures/tolerance.png', name: 'tolerance.png', kind: 'image' },
        ],
      },
      { path: 'manuscript/main.pdf', name: 'main.pdf', kind: 'pdf' },
    ],
  },
  { path: 'README.md', name: 'README.md', kind: 'other' },
];

export const succeededBuild: BuildModel = {
  buildId: 'B0007',
  status: 'succeeded',
  engine: 'latexmk -pdf -interaction=nonstopmode',
  startedAt: '2026-09-03T09:59:48Z',
  finishedAt: '2026-09-03T10:00:12Z',
  pdf: { url: '/builds/B0007/pdf', stale: false, producedAt: '2026-09-03T10:00:12Z' },
  synctex: 'available',
};

export const failedBuild: BuildModel = {
  ...succeededBuild,
  buildId: 'B0008',
  status: 'failed',
  startedAt: '2026-09-03T10:04:02Z',
  finishedAt: '2026-09-03T10:04:09Z',
  pdf: { url: '/builds/B0007/pdf', stale: true, producedAt: '2026-09-03T10:00:12Z' },
  lastGood: { url: '/builds/B0007/pdf', producedAt: '2026-09-03T10:00:12Z' },
  synctex: 'unavailable',
  synctexReason: 'the failing run wrote no .synctex.gz',
};

export const noToolchainBuild: BuildModel = {
  status: 'unavailable',
  synctex: 'unavailable',
  setupGuidance:
    'No allowlisted LaTeX engine was found. Install tectonic or latexmk and add it to research.yaml.',
};

export const diagnostics: DiagnosticModel[] = [
  {
    id: 'D1',
    severity: 'error',
    file: 'manuscript/main.tex',
    line: 120,
    column: 3,
    message: 'Undefined control sequence \\includegraph.',
    code: 'Undefined control sequence',
    source: 'compiler',
  },
  {
    id: 'D2',
    severity: 'warning',
    file: 'manuscript/main.tex',
    line: 210,
    message: 'Overfull \\hbox (12.4pt too wide) in paragraph at lines 208--212.',
    source: 'compiler',
  },
  {
    id: 'D3',
    severity: 'info',
    file: 'manuscript/refs.bib',
    line: 8,
    message: 'Entry "smith2024" has no year field.',
    source: 'compiler',
  },
];

/*
 * Four findings the auditor actually raises, in its own kinds and its own words.
 *
 * Each carries the manuscript sentence it is about, because that is what a finding card
 * opens with; the messages are the auditor's, with the `"<file>:<line>: "` prefix the
 * cockpit removes already off, since the card draws the position itself.
 */
export const findings: AuditFindingModel[] = [
  {
    id: 'A1',
    kind: 'unregistered_claim',
    severity: 'warning',
    file: 'manuscript/sections/results.tex',
    line: 88,
    sentence:
      'The pretrained encoder improves F1 by 2.57 points over the strongest baseline, and the gain is concentrated in the two rarest attack families.',
    message: 'substantive sentence is attached to no Claim',
    source: 'audit',
  },
  {
    id: 'A2',
    kind: 'over_strong_wording',
    severity: 'warning',
    file: 'manuscript/sections/results.tex',
    line: 91,
    sentence: 'This proves that pretraining transfers to every rare family.',
    message:
      "sentence reads L4 universal or absence via 'every', but C0041 allows only L2 corpus pattern; the defensible wording is 'in the two families we measured'",
    claim: { id: 'C0041' },
    source: 'audit',
  },
  {
    id: 'A3',
    kind: 'citation_mismatch',
    severity: 'error',
    file: 'manuscript/main.tex',
    line: 44,
    sentence: 'Earlier sweeps report the same ordering on held-out traffic~\\cite{smith2024}.',
    message: "citation key 'smith2024' is not defined in the bibliography",
    source: 'audit',
  },
  {
    id: 'A4',
    kind: 'invalid_evidence_anchor',
    severity: 'info',
    sentence: 'The held-out split is the only evidence that the encoder generalises.',
    message:
      'E0482 no longer opens at its source, so C0005 is unprovenanced: anchor validation reports stale - the artifact bytes changed',
    claim: { id: 'C0005' },
    anchor: { id: 'manuscript/main.tex:12' },
    source: 'audit',
  },
];

export const candidate: CandidateDiffModel = {
  id: 'CD0001',
  originMessageId: 'M0042',
  contextPackId: 'CP0007',
  file: 'manuscript/main.tex',
  hunks: [
    {
      header: '@@ -88,5 +88,5 @@',
      lines: [
        { kind: 'context', text: 'We measured the response under sustained load.' },
        { kind: 'removed', text: 'The effect proves the mechanism.' },
        { kind: 'added', text: 'The effect is consistent with the mechanism.' },
        {
          kind: 'context',
          text: '\\cite{smith2024}',
          protected: { kind: 'citation', reason: 'A candidate may not reword a citation.' },
        },
        {
          kind: 'context',
          text: '$T_{\\max} = 34.2\\,^{\\circ}\\mathrm{C}$',
          protected: {
            kind: 'equation',
            reason: 'Equations, numbers and units are protected spans.',
          },
        },
      ],
    },
  ],
  semanticSummary: {
    added: [],
    removed: [],
    weakened: ['"proves the mechanism" becomes "is consistent with the mechanism"'],
    strengthened: [],
  },
  auditStatus: 'passed',
};

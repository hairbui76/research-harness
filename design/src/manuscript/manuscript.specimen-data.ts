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

export const findings: AuditFindingModel[] = [
  {
    id: 'A1',
    kind: 'unsupported_statement',
    severity: 'error',
    file: 'manuscript/main.tex',
    line: 88,
    message: 'No accepted Evidence supports "the effect doubles under load".',
    source: 'audit',
  },
  {
    id: 'A2',
    kind: 'wording_stronger_than_claim',
    severity: 'warning',
    file: 'manuscript/main.tex',
    line: 91,
    message: '"proves" overstates C0041, which is qualified to one dataset.',
    claim: { id: 'C0041' },
    source: 'audit',
  },
  {
    id: 'A3',
    kind: 'citation_mismatch',
    severity: 'warning',
    file: 'manuscript/main.tex',
    line: 44,
    message: 'The key "smith2024" is cited but missing from refs.bib.',
    source: 'audit',
  },
  {
    id: 'A4',
    kind: 'invalid_anchor',
    severity: 'info',
    message: 'The anchor recorded for E0482 no longer resolves in A0017-3.',
    anchor: { id: 'AN0012' },
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

/**
 * Sample research view models.
 *
 * One set of fixtures shared by the specimens and the tests, so the gallery shows exactly
 * what the suite asserts. It is data only — no test imports — and it is deliberately not
 * part of the package's public API.
 */
import type {
  ClaimModel,
  ConflictNoticeModel,
  ContextReceiptModel,
  EntityRefModel,
  EvidenceModel,
  IdentityChoice,
  ProvenancePathModel,
  SourceAnchorModel,
} from './models';

export const SAMPLE_WORK: EntityRefModel = {
  id: 'W0017',
  kind: 'work',
  label: 'Hydrogel stiffness and neurite outgrowth',
  authority: 'accepted',
  resolution: 'resolved',
  href: 'rh://work/W0017',
};

export const SAMPLE_EVIDENCE_REF: EntityRefModel = {
  id: 'E0482',
  kind: 'evidence',
  label: 'Storage modulus at 24 h',
  authority: 'accepted',
  resolution: 'resolved',
  href: 'rh://evidence/E0482',
};

export const SAMPLE_CLAIM_REF: EntityRefModel = {
  id: 'C0041',
  kind: 'claim',
  label: 'Stiffer gels shorten neurites',
  authority: 'qualified',
  resolution: 'resolved',
};

export const SAMPLE_STALE_REF: EntityRefModel = {
  id: 'A0017-3',
  kind: 'artifact',
  label: 'Preprint v3',
  authority: 'stale',
  resolution: 'stale',
};

export const SAMPLE_PRIVATE_REF: EntityRefModel = {
  id: 'CS0004',
  kind: 'session',
  label: 'Grant notes',
  authority: 'private',
  resolution: 'private',
};

export const SAMPLE_BROKEN_REF: EntityRefModel = {
  id: 'E9999',
  kind: 'evidence',
  resolution: 'broken',
};

export const SAMPLE_UNRESOLVED_REF: EntityRefModel = {
  id: 'C0099',
  kind: 'claim',
  resolution: 'unresolved',
};

export const SAMPLE_MESSAGE_REF: EntityRefModel = {
  id: 'M0042',
  kind: 'message',
  label: 'Assistant, 3 September',
  resolution: 'resolved',
};

export const SAMPLE_ANCHOR: SourceAnchorModel = {
  artifactId: 'A0017-3',
  page: 6,
  block: 'B0081',
  span: { start: 1204, end: 1361 },
  quote:
    'Storage modulus rose from 1.2 to 8.4 kPa over 24 h, with no measurable change in swelling ratio.',
  href: 'rh://artifact/A0017-3?page=6&block=B0081',
};

export const SAMPLE_STALE_ANCHOR: SourceAnchorModel = {
  ...SAMPLE_ANCHOR,
  stale: true,
};

export const SAMPLE_EVIDENCE: EvidenceModel = {
  id: 'E0482',
  workId: 'W0017',
  workLabel: 'Hydrogel stiffness and neurite outgrowth (2024)',
  quote:
    'Storage modulus rose from 1.2 to 8.4 kPa over 24 h, with no measurable change in swelling ratio.',
  field: 'materials',
  evidenceType: 'measurement',
  strength: 'direct',
  origin: 'researcher',
  authority: 'accepted',
  anchor: SAMPLE_ANCHOR,
  numeric: { value: '8.4', unit: 'kPa', metric: 'storage modulus', dataset: '24 h timepoint' },
};

export const SAMPLE_CLAIM: ClaimModel = {
  id: 'C0041',
  text: 'Increasing hydrogel stiffness above 5 kPa shortens mean neurite length in cortical cultures.',
  claimType: 'causal',
  scope: 'rat cortical neurons, 3D culture, 24-72 h',
  status: 'under review',
  authority: 'qualified',
  support: { supports: 4, contradicts: 1, qualifies: 2 },
  wordingCeiling:
    'The evidence supports "associated with shorter neurites", not "causes shorter neurites".',
};

export const SAMPLE_PROVENANCE: ProvenancePathModel = {
  steps: [
    { ref: SAMPLE_CLAIM_REF },
    { ref: SAMPLE_EVIDENCE_REF, relation: 'supports' },
    { ref: SAMPLE_STALE_REF, relation: 'anchored_at' },
  ],
};

export const SAMPLE_RECEIPT: ContextReceiptModel = {
  packId: 'CP0007',
  provider: 'Anthropic',
  model: 'claude-opus-5',
  egressClass: 'external',
  tokenBudget: 32000,
  allocation: [
    { cls: 'policy', tokens: 420 },
    { cls: 'accepted_state', tokens: 6800 },
    { cls: 'current_session', tokens: 9100 },
    { cls: 'prior_sessions', tokens: 2400 },
    { cls: 'attachments', tokens: 3000 },
    { cls: 'corpus_blocks', tokens: 5100 },
  ],
  included: [
    { ref: SAMPLE_CLAIM_REF, cls: 'accepted_state', authority: 'qualified', tokens: 310 },
    {
      ref: SAMPLE_EVIDENCE_REF,
      cls: 'accepted_state',
      authority: 'accepted',
      tokens: 260,
      sourcePointer: 'A0017-3#B0081',
    },
    {
      ref: SAMPLE_MESSAGE_REF,
      cls: 'current_session',
      tokens: 1840,
      sourcePointer: 'CS0001/messages.jsonl#M0042',
    },
  ],
  omitted: [
    {
      ref: SAMPLE_PRIVATE_REF,
      cls: 'prior_sessions',
      authority: 'private',
      reason: 'privacy_policy',
      detail: 'The session is marked private and the selected provider is external.',
    },
    {
      ref: SAMPLE_STALE_REF,
      cls: 'corpus_blocks',
      reason: 'stale',
    },
  ],
};

export const SAMPLE_CONFLICT: ConflictNoticeModel = {
  chat: {
    ref: SAMPLE_MESSAGE_REF,
    excerpt: 'Earlier we agreed the threshold was 2 kPa.',
  },
  accepted: {
    ref: SAMPLE_CLAIM_REF,
    excerpt: 'The reviewed threshold is 5 kPa, qualified to 3D cultures.',
  },
  explanation:
    'A message in this session contradicts an accepted claim. The accepted claim was sent to the model; the message was not.',
};

export const SAMPLE_IDENTITY_CHOICES: IdentityChoice[] = [
  {
    kind: 'existing_artifact',
    label: 'Already in the corpus as A0017-3',
    detail: 'The same bytes are already stored under this artifact.',
    work: SAMPLE_WORK,
    artifact: SAMPLE_STALE_REF,
  },
  {
    kind: 'existing_work_new_version',
    label: 'New version of W0017',
    detail: 'Same title and authors, later revision date.',
    work: SAMPLE_WORK,
  },
  {
    kind: 'new_work',
    label: 'Create a new work',
    detail: 'No existing work matched the metadata.',
  },
];

/**
 * Sample conversation view models, shared by the specimens and the tests. Data only.
 */
import {
  SAMPLE_CLAIM_REF,
  SAMPLE_EVIDENCE_REF,
  SAMPLE_STALE_REF,
  SAMPLE_PRIVATE_REF,
  SAMPLE_UNRESOLVED_REF,
  SAMPLE_WORK,
} from '../research/samples';
import type { EntityRefModel } from '../research/models';
import type { AttachmentModel, MessageModel, ModelOption, SessionSummary } from './models';

export const SAMPLE_IMAGE: AttachmentModel = {
  id: 'SA0002',
  name: 'figure-3-stiffness-sweep.png',
  mediaType: 'image/png',
  size: 482_000,
  state: 'session_only',
  thumbnailUrl: 'data:image/gif;base64,R0lGODlhAQABAAAAACw=',
  previewUrl: 'data:image/gif;base64,R0lGODlhAQABAAAAACw=',
  downloadUrl: 'data:image/gif;base64,R0lGODlhAQABAAAAACw=',
};

export const SAMPLE_IMAGE_2: AttachmentModel = {
  ...SAMPLE_IMAGE,
  id: 'SA0004',
  name: 'figure-4-neurite-length.png',
};

export const SAMPLE_PDF: AttachmentModel = {
  id: 'SA0003',
  name: 'lee-2024-hydrogel-preprint.pdf',
  mediaType: 'application/pdf',
  size: 3_400_000,
  state: 'ready',
  pageCount: 14,
  downloadUrl: 'data:application/pdf;base64,',
};

export const SAMPLE_BLOCKED_ATTACHMENT: AttachmentModel = {
  id: 'SA0005',
  name: 'raw-traces.h5',
  mediaType: 'application/x-hdf5',
  size: 91_000_000,
  state: 'ready',
  sendability: {
    ok: false,
    reason: 'The selected model cannot read HDF5 files.',
    suggestedModel: 'a local analysis tool',
  },
};

export const SAMPLE_FAILED_ATTACHMENT: AttachmentModel = {
  ...SAMPLE_PDF,
  id: 'SA0006',
  name: 'scan-broken.pdf',
  state: 'failed',
};

export const SAMPLE_USER_MESSAGE: MessageModel = {
  id: 'M0041',
  role: 'user',
  createdAt: '2026-09-03T14:20:11Z',
  status: 'complete',
  blocks: [
    {
      kind: 'text',
      text: 'Does the stiffness sweep in this preprint support C0041, or only the weaker wording?',
    },
    { kind: 'reference', ref: SAMPLE_CLAIM_REF },
    { kind: 'attachment', attachment: SAMPLE_PDF },
  ],
};

export const SAMPLE_ASSISTANT_MESSAGE: MessageModel = {
  id: 'M0042',
  role: 'assistant',
  createdAt: '2026-09-03T14:20:38Z',
  status: 'complete',
  attempt: 2,
  attempts: 2,
  contextPackId: 'CP0007',
  provider: 'Anthropic',
  model: 'claude-opus-5',
  blocks: [
    {
      kind: 'text',
      text: 'The sweep supports an association, not the causal wording. E0482 measures modulus, not neurite length.',
    },
    { kind: 'reference', ref: SAMPLE_EVIDENCE_REF },
  ],
};

export const SAMPLE_STREAMING_MESSAGE: MessageModel = {
  ...SAMPLE_ASSISTANT_MESSAGE,
  id: 'M0043',
  status: 'streaming',
  attempt: undefined,
  attempts: undefined,
  blocks: [{ kind: 'text', text: 'Reading the accepted evidence for C0041' }],
};

export const SAMPLE_INCOMPLETE_MESSAGE: MessageModel = {
  ...SAMPLE_ASSISTANT_MESSAGE,
  id: 'M0044',
  status: 'incomplete',
  blocks: [{ kind: 'text', text: 'The three measurements that bear on this are' }],
};

export const SAMPLE_FAILED_MESSAGE: MessageModel = {
  ...SAMPLE_ASSISTANT_MESSAGE,
  id: 'M0045',
  status: 'failed',
  blocks: [
    { kind: 'error', message: 'The provider did not respond after 30 s.', retryable: true },
  ],
};

export const SAMPLE_MODELS: ModelOption[] = [
  {
    id: 'claude-opus-5',
    label: 'Claude Opus 5',
    provider: 'Anthropic',
    egressClass: 'external',
    vision: true,
    contextTokens: 200_000,
    available: true,
  },
  {
    id: 'local-llama',
    label: 'Llama 3.1 70B',
    provider: 'Ollama (local)',
    egressClass: 'local',
    vision: false,
    contextTokens: 32_000,
    available: true,
  },
  {
    id: 'gpt-vision',
    label: 'Vision preview',
    provider: 'OpenAI',
    egressClass: 'external',
    vision: true,
    contextTokens: 128_000,
    available: false,
    unavailableReason: 'No API key is configured for this provider.',
  },
];

export const SAMPLE_SESSIONS: SessionSummary[] = [
  {
    id: 'CS0001',
    title: 'Stiffness threshold for C0041',
    updatedAt: '2026-09-03T14:20:38Z',
    messageCount: 24,
    visibility: 'project',
    preview: 'The sweep supports an association, not the causal wording.',
  },
  {
    id: 'CS0004',
    title: 'Grant notes',
    updatedAt: '2026-08-28T09:02:00Z',
    messageCount: 6,
    visibility: 'private',
  },
  {
    id: 'CS0007',
    title: 'Taxonomy clean-up',
    updatedAt: '2026-08-19T17:44:00Z',
    messageCount: 41,
    visibility: 'project',
  },
];

export const SAMPLE_REFERENCE_RESULTS: EntityRefModel[] = [
  SAMPLE_WORK,
  SAMPLE_EVIDENCE_REF,
  SAMPLE_CLAIM_REF,
  SAMPLE_UNRESOLVED_REF,
  SAMPLE_STALE_REF,
  SAMPLE_PRIVATE_REF,
];

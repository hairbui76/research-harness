/**
 * The DTO → view-model mapping, on its own.
 *
 * These are the places a rename on either side would show up first: the id prefixes that
 * decide what an `@` token *is*, the retry chain that decides what one turn is, and the
 * receipt's included/omitted lists, whose words a researcher reads when they have to
 * explain what the model saw.
 */
import { describe, expect, it } from 'vitest';
import contextPack from '../../test/fixtures/conversation/context-pack.json';
import transcript from '../../test/fixtures/conversation/transcript.json';
import incomplete from '../../test/fixtures/conversation/transcript-incomplete.json';
import scan from '../../test/fixtures/providers/cli-scan.json';
import sessions from '../../test/fixtures/conversation/sessions.json';
import type {
  CliRuntimeStatus,
  CliScanReport,
  ContextPackView,
  ConversationMessage,
  ConversationSession,
  SessionTranscript,
} from '../../api/dto';
import {
  bindingWords,
  entityKindOf,
  entityRefFor,
  groupAttempts,
  messagesReferencing,
  parseRuntimeOptionId,
  reasoningChoicesFor,
  routeForDeepLink,
  routeForEntity,
  runtimeOptionId,
  toContextReceiptModel,
  toMessageModel,
  toProjectDefaultOption,
  toRuntimeGroup,
  toSessionSummary,
  PROJECT_DEFAULT_OPTION,
} from './mappers';
import { parseDeepLink } from '../../render';

const PAGE = transcript as unknown as SessionTranscript;
const INTERRUPTED = incomplete as unknown as SessionTranscript;
const PACK = contextPack as unknown as ContextPackView;
const SCAN = scan as unknown as CliScanReport;
const SESSIONS = sessions.sessions as unknown as ConversationSession[];

describe('stable ids', () => {
  it('dispatches on the longest prefix, as the domain does', () => {
    // `CS` must beat `C`, and `SA` must beat `S`, or a session reads as a claim.
    expect(entityKindOf('CS0001')).toBe('session');
    expect(entityKindOf('C0041')).toBe('claim');
    expect(entityKindOf('SA0003')).toBe('attachment');
    expect(entityKindOf('S0002')).toBe('synthesis');
    expect(entityKindOf('RQ0002')).toBe('question');
    expect(entityKindOf('E0482')).toBe('evidence');
    expect(entityKindOf('A0017-3')).toBe('artifact');
    expect(entityKindOf('file:main.tex')).toBe('manuscript_file');
  });

  it('names no kind for an id whose prefix names none', () => {
    // `CP` is a real id and not a graph node kind; guessing one would mislabel it.
    expect(entityKindOf('CP0007')).toBeNull();
    expect(entityKindOf('not-an-id')).toBeNull();
  });

  it('routes a work-scoped id to the Work it belongs to', () => {
    expect(routeForEntity('artifact', 'A0017-3')).toBe('/corpus/W0017');
    expect(routeForEntity('evidence', 'E0482')).toBe('/evidence/E0482');
    expect(routeForEntity('session', 'CS0001')).toBe('/?session=CS0001');
    expect(routeForEntity('message', 'M0042', { session: 'CS0001' })).toBe(
      '/?session=CS0001&message=M0042',
    );
    // A message with no session named has no address; saying so beats guessing one.
    expect(routeForEntity('message', 'M0042')).toBeNull();
  });

  it('resolves the deep links of plan §0.1', () => {
    const link = parseDeepLink('rh://session/CS0001?message=M0042');
    expect(link && routeForDeepLink(link)).toBe('/?session=CS0001&message=M0042');
    const claim = parseDeepLink('rh://claim/C0041');
    expect(claim && routeForDeepLink(claim)).toBe('/claims/C0041');
    const manuscript = parseDeepLink('rh://manuscript/main.tex?line=120');
    expect(manuscript && routeForDeepLink(manuscript)).toBe('/manuscript');
  });

  it('gives a reference the cockpit route as its href', () => {
    expect(entityRefFor('E0482', { label: 'a quote' })).toEqual({
      id: 'E0482',
      kind: 'evidence',
      resolution: 'resolved',
      label: 'a quote',
      href: '/evidence/E0482',
    });
  });
});

describe('turns and attempts', () => {
  it('collapses a retry chain into one turn, keeping every attempt', () => {
    const turns = groupAttempts(INTERRUPTED.messages);
    expect(turns).toHaveLength(1);
    expect(turns[0]?.attempts.map((message) => message.id)).toEqual(['M0043', 'M0044']);
  });

  it('reports an interrupted attempt as incomplete, not as an answer', () => {
    const [interruptedMessage] = INTERRUPTED.messages;
    const model = toMessageModel(interruptedMessage as ConversationMessage);
    expect(model.status).toBe('incomplete');
    // Everything that arrived is kept.
    expect(model.blocks[0]).toEqual({
      kind: 'text',
      text: 'Under batching the tail flattens, but the',
    });
  });

  it('marks an unresolved token on the message that used it', () => {
    const [userMessage] = PAGE.messages;
    const model = toMessageModel(userMessage as ConversationMessage, {
      unresolved: new Set(['E0482']),
    });
    const reference = model.blocks.find((block) => block.kind === 'reference');
    expect(reference?.kind === 'reference' && reference.ref.resolution).toBe('unresolved');
  });

  it('appends live text to the message the run is writing', () => {
    const [, assistant] = PAGE.messages;
    const model = toMessageModel(assistant as ConversationMessage, {
      streaming: true,
      streamingText: '…and the corpus agrees.',
    });
    expect(model.status).toBe('streaming');
    expect(model.blocks.at(-1)).toEqual({ kind: 'text', text: '…and the corpus agrees.' });
  });

  it('finds every message that referenced an id', () => {
    expect(messagesReferencing(PAGE.messages, 'E0482').map((m) => m.id)).toEqual(['M0041']);
    expect(messagesReferencing(PAGE.messages, 'E9999')).toEqual([]);
  });
});

describe('the context receipt', () => {
  const receipt = toContextReceiptModel(PACK);

  it('carries the provider, model and egress class the pack recorded', () => {
    expect(receipt.packId).toBe('CP0007');
    expect(receipt.provider).toBe('local');
    expect(receipt.model).toBe('local-small');
    expect(receipt.egressClass).toBe('local');
    expect(receipt.tokenBudget).toBe(8000);
  });

  it('lists accepted state and the prior-session excerpt that was included', () => {
    const included = receipt.included.map((item) => `${item.cls}:${item.ref.id}`);
    expect(included).toContain('accepted_state:E0482');
    expect(included).toContain('prior_sessions:M0009');
  });

  it('keeps the omission reason, and marks a privacy omission as private', () => {
    const omitted = receipt.omitted.find((item) => item.reason === 'privacy_policy');
    expect(omitted?.ref.resolution).toBe('private');
    expect(omitted?.detail).toContain('external');
    expect(receipt.omitted.map((item) => item.reason)).toContain('token_budget');
  });

  it('draws an item with no stable id under the class it was packed in', () => {
    const policy = receipt.included.find((item) => item.cls === 'policy');
    expect(policy?.ref.id).toBe('Research assistant policy');
    expect(policy?.sourcePointer).toBe('policy/system.md');
  });
});

/* -- the session binding (plan ruling 4, ruling 6) ------------------------ */

describe('the session binding', () => {
  it('composes the binding words in the fixed format the CLI uses', () => {
    expect(
      bindingWords({ model: { provider: 'local_cli:codex', model: 'gpt-5.5' }, reasoning: 'high' }),
    ).toBe('session:codex/gpt-5.5 (reasoning high)');
    expect(bindingWords({ model: { provider: 'local_cli:claude', model: 'default' } })).toBe(
      'session:claude/default',
    );
    expect(bindingWords({ model: { provider: 'entry', model: 'codex-sub' } })).toBe(
      'entry codex-sub',
    );
    expect(bindingWords({ model: { provider: 'fast', model: 'fast' } })).toBe('entry fast');
    expect(bindingWords({ model: null })).toBeNull();
  });

  it('round-trips a runtime option id', () => {
    expect(parseRuntimeOptionId(runtimeOptionId('codex', 'gpt-5.5'))).toEqual({
      runtime: 'codex',
      model: 'gpt-5.5',
    });
    expect(parseRuntimeOptionId('codex-sub')).toBeNull();
  });

  it('puts the binding words on the session row, and nothing on the project default', () => {
    const bound = SESSIONS.find((session) => session.id === 'CS0002');
    const unbound = SESSIONS.find((session) => session.id === 'CS0001');
    expect(toSessionSummary(bound as ConversationSession).binding).toBe(
      'session:codex/gpt-5.5 (reasoning high)',
    );
    expect(toSessionSummary({ ...(unbound as ConversationSession), defaults: {} }).binding).toBe(
      undefined,
    );
  });

  it('offers the scan\'s models under a routable runtime, with the daemon\'s source word', () => {
    const codex = SCAN.runtimes.find((item) => item.runtime === 'codex');
    const group = toRuntimeGroup(codex as (typeof SCAN)['runtimes'][number]);
    expect(group.label).toBe('Codex CLI 0.150.1');
    expect(group.options.map((option) => option.id)).toEqual([
      'runtime:codex:default',
      'runtime:codex:gpt-5.5',
      'runtime:codex:gpt-5.4-mini',
    ]);
    const model = group.options.find((option) => option.id === 'runtime:codex:gpt-5.5');
    expect(model?.label).toBe('gpt-5.5 (live)');
    expect(model?.contextTokens).toBe(272000);
    expect(model?.available).toBe(true);
  });

  it('shows a runtime the daemon will not route to as one row with its reason', () => {
    const cursor = SCAN.runtimes.find((item) => item.runtime === 'cursor-agent');
    const group = toRuntimeGroup(cursor as (typeof SCAN)['runtimes'][number]);
    expect(group.label).toBe('Cursor Agent 1.4.0');
    expect(group.options).toHaveLength(1);
    expect(group.options[0]?.available).toBe(false);
    expect(group.options[0]?.unavailableReason).toBe(
      'cursor-agent 1.4.0 has no tested bounded (no-tools, read-only) mode',
    );
  });
});

/* -- clearing, and the effort levels one model offers ---------------------- */

describe('the project default row', () => {
  const codex = SCAN.runtimes.find((item) => item.runtime === 'codex') as CliRuntimeStatus;
  const claude = SCAN.runtimes.find((item) => item.runtime === 'claude') as CliRuntimeStatus;

  it('names the entry the daemon marked default, and claims nothing of its own', () => {
    const entry = {
      id: 'fast',
      label: 'fast/gpt-5.4-mini',
      provider: 'openai',
      egressClass: 'external' as const,
      vision: false,
      contextTokens: 272000,
      available: true,
    };
    const option = toProjectDefaultOption(entry);
    expect(option.id).toBe(PROJECT_DEFAULT_OPTION);
    expect(option.label).toBe('Project default (fast/gpt-5.4-mini)');
    // Where it goes is where that entry goes; nothing is re-decided here.
    expect(option.provider).toBe('openai');
    expect(option.egressClass).toBe('external');
    expect(option.contextTokens).toBe(272000);
    expect(option.available).toBe(true);
  });

  it('says only that the router decides when the daemon named no default', () => {
    const option = toProjectDefaultOption(null);
    expect(option.label).toBe('Project default');
    expect(option.available).toBe(true);
  });

  it('offers the effort levels of the model, and the runtime\'s only as the fallback', () => {
    // `gpt-5.5` publishes its own list; `gpt-5.4-mini` publishes none.
    expect(reasoningChoicesFor(codex, 'gpt-5.5')).toEqual(['low', 'medium', 'high', 'xhigh']);
    expect(reasoningChoicesFor(codex, 'gpt-5.4-mini')).toEqual([
      'low',
      'medium',
      'high',
      'xhigh',
    ]);
    expect(reasoningChoicesFor(claude, 'sonnet')).toEqual([
      'low',
      'medium',
      'high',
      'xhigh',
      'max',
    ]);
  });

  it('lets a model narrow the runtime\'s list rather than widening it', () => {
    // The same exported runtime row, with the one model publishing a shorter list — which
    // is the case the fallback must not paper over.
    const narrowed: CliRuntimeStatus = {
      ...codex,
      models: codex.models.map((model) =>
        model.id === 'gpt-5.4-mini' ? { ...model, reasoning: ['low'] } : model,
      ),
    };
    expect(reasoningChoicesFor(narrowed, 'gpt-5.4-mini')).toEqual(['low']);
    expect(reasoningChoicesFor(narrowed, 'gpt-5.5')).toEqual(['low', 'medium', 'high', 'xhigh']);
  });
});

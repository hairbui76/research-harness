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
import type { ContextPackView, ConversationMessage, SessionTranscript } from '../../api/dto';
import {
  entityKindOf,
  entityRefFor,
  groupAttempts,
  messagesReferencing,
  routeForDeepLink,
  routeForEntity,
  toContextReceiptModel,
  toMessageModel,
} from './mappers';
import { parseDeepLink } from '../../render';
import { projectHref } from '../../app/projectPaths';

const PAGE = transcript as unknown as SessionTranscript;
const INTERRUPTED = incomplete as unknown as SessionTranscript;
const PACK = contextPack as unknown as ContextPackView;

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

/**
 * The same routes, under the multi-project host.
 *
 * Nothing here decides which host it is talking to: the caller passes the transform it got
 * from `useProjectPaths()`, and these tests state the two answers it can be — the identity
 * (`research serve`) and `projectHref` (`research app`) — plus the one rule that keeps them
 * honest, which is that the transform is applied once per route and never to a null.
 */
describe('routes under a project prefix', () => {
  const inProject = (path: string) => projectHref('prj_abc', path);

  it('keeps every entity route inside the active project, query and all', () => {
    expect(routeForEntity('claim', 'C0001', {}, inProject)).toBe('/projects/prj_abc/claims/C0001');
    expect(routeForEntity('artifact', 'A0017-3', {}, inProject)).toBe(
      '/projects/prj_abc/corpus/W0017',
    );
    expect(routeForEntity('evidence', 'E0482', {}, inProject)).toBe(
      '/projects/prj_abc/evidence/E0482',
    );
    expect(routeForEntity('question', 'RQ0002', {}, inProject)).toBe('/projects/prj_abc/questions');
    expect(routeForEntity('session', 'CS0001', {}, inProject)).toBe(
      '/projects/prj_abc/?session=CS0001',
    );
    expect(routeForEntity('message', 'M0042', { session: 'CS0001' }, inProject)).toBe(
      '/projects/prj_abc/?session=CS0001&message=M0042',
    );
  });

  it('leaves a route it has none of alone: null is not a path to prefix', () => {
    expect(routeForEntity('message', 'M0042', {}, inProject)).toBeNull();
  });

  it('applies the transform exactly once to each route', () => {
    let calls = 0;
    const once = (path: string): string => {
      calls += 1;
      return `/p${path}`;
    };

    expect(routeForEntity('claim', 'C0001', {}, once)).toBe('/p/claims/C0001');
    expect(calls).toBe(1);

    calls = 0;
    const claim = parseDeepLink('rh://claim/C0041');
    expect(claim && routeForDeepLink(claim, once)).toBe('/p/claims/C0041');
    expect(calls).toBe(1);
  });

  it('prefixes a deep link and keeps the query that addresses the exact place', () => {
    const session = parseDeepLink('rh://session/CS0001?message=M0042');
    expect(session && routeForDeepLink(session, inProject)).toBe(
      '/projects/prj_abc/?session=CS0001&message=M0042',
    );
    const manuscript = parseDeepLink('rh://manuscript/main.tex?line=120');
    expect(manuscript && routeForDeepLink(manuscript, inProject)).toBe(
      '/projects/prj_abc/manuscript',
    );
  });

  it('gives a reference chip the project route as its href', () => {
    expect(entityRefFor('E0482', { label: 'a quote', href: inProject }).href).toBe(
      '/projects/prj_abc/evidence/E0482',
    );
    // Without one, the chip is exactly the chip it has always been.
    expect(entityRefFor('E0482', { label: 'a quote' }).href).toBe('/evidence/E0482');
  });

  it('routes a whole receipt through the project it was read in', () => {
    const receipt = toContextReceiptModel(PACK, inProject);
    const hrefs = [...receipt.included, ...receipt.omitted]
      .map((item) => item.ref.href)
      .filter((href): href is string => href !== undefined);

    expect(hrefs.length).toBeGreaterThan(0);
    expect(hrefs.every((href) => href.startsWith('/projects/prj_abc/'))).toBe(true);
    // And the legacy receipt is unchanged.
    expect(
      toContextReceiptModel(PACK)
        .included.map((item) => item.ref.href)
        .some((href) => href?.startsWith('/projects/')),
    ).toBe(false);
  });

  it('gives every reference in a message the project route', () => {
    const message = PAGE.messages.find((entry) =>
      entry.blocks.some((block) => block.kind === 'reference'),
    ) as ConversationMessage;
    const model = toMessageModel(message, { href: inProject });
    const refs = model.blocks.filter(
      (block): block is Extract<typeof block, { kind: 'reference' }> => block.kind === 'reference',
    );

    expect(refs.length).toBeGreaterThan(0);
    expect(refs.every((block) => block.ref.href?.startsWith('/projects/prj_abc/'))).toBe(true);
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

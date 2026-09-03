/**
 * Task 11.1: the client shapes every call the cockpit makes exactly as the daemon's
 * request models expect, and every mutation goes through `POST /capabilities/<name>`.
 *
 * The request bodies are asserted whole rather than field by field: a silently added key
 * is refused by the daemon's `extra="forbid"` models, so a test that only checked the keys
 * it knows about would pass while the real call failed.
 */
import { describe, expect, it } from 'vitest';
import type { vi } from 'vitest';
import { CapabilityError, HarnessClient } from './client';
import { CAPABILITIES } from './capabilities.gen';
import { fakeDaemon, FIXTURES } from '../test/harness';

/** One `ReviewOutcome`, as every candidate-keyed review action answers. */
function outcome(evidence: string | null, status = 'reviewed') {
  return { candidate_id: 'cand_1', action: 'accept', status, evidence, mutation: null };
}

function client(daemon = fakeDaemon({ capabilities: {} })) {
  return {
    daemon,
    client: new HarnessClient({
      baseUrl: 'http://daemon.test',
      token: 'local-token',
      fetchImpl: daemon.fetch,
    }),
  };
}

describe('capability calls', () => {
  it('sends the review queue request `review.inbox` declares', async () => {
    const daemon = fakeDaemon({ capabilities: { 'review.inbox': FIXTURES.reviewInbox } });
    const queue = await client(daemon).client.reviewInbox();

    expect(daemon.capabilityCalls()).toEqual([{ name: 'review.inbox', request: {} }]);
    expect(queue.count).toBe(3);
  });

  it('accepts one candidate by its staging id and nothing else', async () => {
    const daemon = fakeDaemon({ capabilities: { 'review.accept': outcome('E0001') } });

    const result = await client(daemon).client.acceptCandidate('cand_1');

    expect(daemon.capabilityCalls()).toEqual([
      { name: 'review.accept', request: { candidate_id: 'cand_1' } },
    ]);
    expect(result.evidence).toBe('E0001');
    expect(result.status).toBe('reviewed');
  });

  it('carries the qualification, and still only the staging id', async () => {
    const daemon = fakeDaemon({ capabilities: { 'review.qualify': outcome('E0002') } });

    await client(daemon).client.qualifyCandidate(
      'cand_1',
      'holds for the CICIDS2017 capture only',
    );

    expect(daemon.capabilityCalls()[0]!).toEqual({
      name: 'review.qualify',
      request: {
        candidate_id: 'cand_1',
        qualification: 'holds for the CICIDS2017 capture only',
      },
    });
  });

  it('sends the corrected object under `edited`, never the candidate back', async () => {
    const daemon = fakeDaemon({ capabilities: { 'review.edit': outcome('E0003') } });

    await client(daemon).client.editCandidate('cand_1', {
      id: 'E0000',
      corrected: true,
    } as never);

    expect(daemon.capabilityCalls()[0]!).toEqual({
      name: 'review.edit',
      request: { candidate_id: 'cand_1', edited: { id: 'E0000', corrected: true } },
    });
  });

  it('records the reason with a rejection, keyed by the staging id', async () => {
    const daemon = fakeDaemon({ capabilities: { 'review.reject': outcome(null, 'rejected') } });

    await client(daemon).client.rejectCandidate('cand_1', 'the span describes the encoder');

    expect(daemon.capabilityCalls()[0]!).toEqual({
      name: 'review.reject',
      request: { candidate_id: 'cand_1', reason: 'the span describes the encoder' },
    });
  });

  it('defers with a note and leaves the candidate in the queue', async () => {
    const daemon = fakeDaemon({ capabilities: { 'review.defer': outcome(null, 'deferred') } });

    const result = await client(daemon).client.deferCandidate('cand_1', 'waiting for the appendix');

    expect(daemon.capabilityCalls()[0]!).toEqual({
      name: 'review.defer',
      request: { candidate_id: 'cand_1', note: 'waiting for the appendix' },
    });
    expect(result.mutation).toBeNull();
  });

  it('asks for more evidence through the capability that captures it durably', async () => {
    const daemon = fakeDaemon({
      capabilities: { 'review.request_more': outcome(null, 'more_evidence_requested') },
    });

    await client(daemon).client.requestMoreEvidence('cand_1', 'which capture window?');

    expect(daemon.capabilityCalls()[0]!).toEqual({
      name: 'review.request_more',
      request: { candidate_id: 'cand_1', note: 'which capture window?' },
    });
  });

  it('still closes a conflict record through `review.resolve_conflict`', async () => {
    const daemon = fakeDaemon({
      capabilities: { 'review.resolve_conflict': { candidate_id: 'cand_1', choice: 'accept' } },
    });

    await client(daemon).client.resolveCandidate('cand_1', 'accept', 'read on page 4');

    expect(daemon.capabilityCalls()[0]!).toEqual({
      name: 'review.resolve_conflict',
      request: { candidate_id: 'cand_1', choice: 'accept', reason: 'read on page 4' },
    });
  });

  it('lets the daemon name a new Claim rather than guessing its id', async () => {
    const daemon = fakeDaemon({
      capabilities: { 'claim.create': { capability: 'claim.create', objects: ['C0007'] } },
    });

    const created = await client(daemon).client.createClaim({ statement: 'a claim' } as never);

    expect(daemon.capabilityCalls()[0]!).toEqual({
      name: 'claim.create',
      request: { claim: { statement: 'a claim' } },
    });
    expect(daemon.capabilityCalls()[0]!.request.claim).not.toHaveProperty('id');
    expect(created.id).toBe('C0007');
  });

  it('reads one list at a time through the capability, not the whole index', async () => {
    const daemon = fakeDaemon({
      capabilities: {
        'claim.list': { count: 1, claims: [{ id: 'C0001' }] },
        'work.list': { count: 0, works: [] },
        'question.list': { count: 0, questions: [] },
        'decision.list': { count: 0, decisions: [] },
        'anchor.list': { count: 0, anchors: [] },
        'evidence.list': { count: 0, evidence: [] },
        'state.index': FIXTURES.index,
      },
    });
    const { client: harness } = client(daemon);

    await harness.claims({ status: 'supported' });
    await harness.works();
    await harness.questions('open');
    await harness.decisions('C0001');
    await harness.anchors();
    await harness.evidence('W0001', 'accepted');
    await harness.index();

    expect(daemon.capabilityCalls()).toEqual([
      { name: 'claim.list', request: { status: 'supported' } },
      { name: 'work.list', request: {} },
      { name: 'question.list', request: { status: 'open' } },
      { name: 'decision.list', request: { claim: 'C0001' } },
      { name: 'anchor.list', request: {} },
      { name: 'evidence.list', request: { work: 'W0001', status: 'accepted' } },
      { name: 'state.index', request: {} },
    ]);
  });

  it('narrows a manuscript audit only when it was given the file the range is in', async () => {
    const daemon = fakeDaemon({
      capabilities: { 'manuscript.audit': { findings: [], sentences_checked: 0 } },
    });
    const { client: harness } = client(daemon);

    await harness.auditManuscript(null, 'main.tex');
    await harness.auditManuscript('/paper', 'main.tex', {
      file: 'main.tex',
      lineStart: 20,
      lineEnd: 24,
    });

    expect(daemon.capabilityCalls()).toEqual([
      { name: 'manuscript.audit', request: { project_root: null, main_tex: 'main.tex' } },
      {
        name: 'manuscript.audit',
        request: {
          project_root: '/paper',
          main_tex: 'main.tex',
          file: 'main.tex',
          line_start: 20,
          line_end: 24,
        },
      },
    ]);
  });

  it('reads and records anchors through the two capabilities that own them', async () => {
    const daemon = fakeDaemon({
      capabilities: {
        'manuscript.anchors': { count: 0, anchors: [], verdicts: [] },
        'manuscript.revalidate': { dry_run: false, checked: 0, applied: [] },
        'manuscript.trace': { file: 'main.tex', line: 23, sentence: 'x' },
      },
    });
    const { client: harness } = client(daemon);

    await harness.manuscriptAnchors(null);
    await harness.revalidateManuscript(null);
    await harness.traceManuscript('main.tex', 23);

    expect(daemon.capabilityCalls()).toEqual([
      { name: 'manuscript.anchors', request: { project_root: null, main_tex: 'main.tex' } },
      {
        name: 'manuscript.revalidate',
        request: { project_root: null, main_tex: 'main.tex', dry_run: false },
      },
      {
        name: 'manuscript.trace',
        request: { project_root: null, main_tex: 'main.tex', file: 'main.tex', line: 23 },
      },
    ]);
  });

  it('relates evidence as one ClaimEvidenceRelation object', async () => {
    const daemon = fakeDaemon({ capabilities: { 'claim.relate': { objects: ['C0001'] } } });

    await client(daemon).client.relateEvidence('C0001', 'E0001', 'supports');

    expect(daemon.capabilityCalls()[0]!).toEqual({
      name: 'claim.relate',
      request: { claim_id: 'C0001', relation: { evidence: 'E0001', relation: 'supports' } },
    });
  });

  it('sends an audit as status, allowed strength, and the wording it permits', async () => {
    const daemon = fakeDaemon({ capabilities: { 'claim.audit': { objects: ['C0001'] } } });

    await client(daemon).client.auditClaim('C0001', {
      status: 'supported',
      allowedStrength: 'individual',
      wording: 'one system on one held-out split',
    });

    expect(daemon.capabilityCalls()[0]!).toEqual({
      name: 'claim.audit',
      request: {
        claim_id: 'C0001',
        status: 'supported',
        allowed_strength: 'individual',
        maximum_defensible_wording: 'one system on one held-out split',
      },
    });
  });

  it('makes an override a Decision before it is a claim edit, and lets the daemon name it', async () => {
    const daemon = fakeDaemon({
      capabilities: {
        'decision.accept': { objects: ['D0001'] },
        'claim.override_strength': { objects: ['C0001'] },
      },
    });

    await client(daemon).client.overrideClaimStrength('C0001', {
      selected: 'observed_subset',
      auditorRecommendation: 'individual',
      rationale: 'the split covers both captures',
      actor: 'human',
    });

    const [accepted, applied] = daemon.capabilityCalls() as [
      { name: string; request: any },
      { name: string; request: any },
    ];
    expect(accepted.name).toBe('decision.accept');
    expect(accepted.request.decision).not.toHaveProperty('id');
    expect(accepted.request.decision).toMatchObject({
      type: 'epistemic_override',
      status: 'proposed',
      claim: 'C0001',
      auditor_recommendation: 'individual',
      researcher_selected: 'observed_subset',
    });
    expect(applied).toEqual({
      name: 'claim.override_strength',
      request: { claim_id: 'C0001', decision_id: 'D0001' },
    });
  });

  it('never reads `next_decision_id` to write a Decision', async () => {
    const daemon = fakeDaemon({
      capabilities: {
        'decision.accept': { objects: ['D0002'] },
        'claim.override_strength': { objects: ['C0001'] },
      },
    });

    await client(daemon).client.overrideClaimStrength('C0001', {
      selected: 'observed_subset',
      auditorRecommendation: 'individual',
      rationale: 'the split covers both captures',
    });

    expect(daemon.calls.map((call) => call.path)).not.toContain('/overview');
    expect(daemon.capabilityCalls()[1]!.request).toEqual({
      claim_id: 'C0001',
      decision_id: 'D0002',
    });
  });

  it('names only capabilities the daemon actually publishes', () => {
    for (const name of [
      'review.inbox',
      'review.candidate',
      'review.accept',
      'review.qualify',
      'review.edit',
      'review.reject',
      'review.defer',
      'review.request_more',
      'review.resolve_conflict',
      'claim.create',
      'claim.list',
      'claim.relate',
      'claim.audit',
      'claim.override_strength',
      'claim.find_support',
      'decision.accept',
      'decision.list',
      'question.list',
      'work.list',
      'evidence.list',
      'anchor.list',
      'state.index',
      'state.stale',
      'synthesis.compare',
      'manuscript.audit',
      'manuscript.anchors',
      'manuscript.revalidate',
      'manuscript.trace',
      'work.get',
    ] as const) {
      expect(CAPABILITIES[name]).toBeDefined();
    }
  });

  it('marks every accepted-state capability the cockpit calls as human-only', () => {
    for (const name of [
      'review.accept',
      'review.qualify',
      'review.edit',
      'review.reject',
      'claim.audit',
      'claim.override_strength',
      'manuscript.revalidate',
    ] as const) {
      expect(CAPABILITIES[name].humanOnly).toBe(true);
      expect(CAPABILITIES[name].permission).toBe('mutate');
    }
  });

  it('knows the two review actions that stage rather than mutate, and still need a human', () => {
    for (const name of ['review.defer', 'review.request_more'] as const) {
      expect(CAPABILITIES[name].permission).toBe('stage');
      expect(CAPABILITIES[name].humanOnly).toBe(true);
    }
  });

  it('reads through capabilities that write nothing', () => {
    for (const name of [
      'claim.list',
      'work.list',
      'question.list',
      'decision.list',
      'evidence.list',
      'anchor.list',
      'state.index',
      'review.candidate',
      'manuscript.anchors',
      'manuscript.trace',
    ] as const) {
      expect(CAPABILITIES[name].permission).toBe('read');
      expect(CAPABILITIES[name].humanOnly).toBe(false);
    }
  });
});

describe('reads and refusals', () => {
  it('sends the bearer token on a read and asks for the routes the daemon publishes', async () => {
    const daemon = fakeDaemon();
    await client(daemon).client.overview();

    expect(daemon.calls).toEqual([{ method: 'GET', path: '/overview', body: null }]);
    const [, init] = (daemon.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [
      unknown,
      RequestInit,
    ];
    expect(init.headers).toEqual({ Authorization: 'Bearer local-token' });
  });

  it('sends no Authorization header without a token, which makes it an agent host', async () => {
    const daemon = fakeDaemon();
    const anonymous = new HarnessClient({
      baseUrl: 'http://daemon.test',
      token: null,
      fetchImpl: daemon.fetch,
    });
    expect(anonymous.authenticated).toBe(false);

    await anonymous.overview();
    const [, init] = (daemon.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [
      unknown,
      RequestInit,
    ];
    expect(init.headers).toEqual({});
  });

  it('turns a capability refusal into an error carrying the daemon’s stable code', async () => {
    const daemon = fakeDaemon({
      capabilities: {
        'review.accept': {
          capability: 'review.accept',
          ok: false,
          error: { code: 'permission_denied', message: 'an agent host may not accept' },
        },
      },
    });

    await expect(client(daemon).client.acceptCandidate('cand_1')).rejects.toThrow(CapabilityError);
    await expect(client(daemon).client.acceptCandidate('cand_1')).rejects.toMatchObject({
      code: 'permission_denied',
    });
  });

  it('points the source pane at the artifact bytes route', () => {
    const { client: harness } = client();
    expect(harness.artifactBytesUrl('A0001-1')).toBe(
      'http://daemon.test/artifacts/A0001-1/bytes?token=local-token',
    );
  });
});

describe('subscription-backed CLI providers', () => {
  it('scans through provider.cli.scan and forwards rescan', async () => {
    const daemon = fakeDaemon({ capabilities: { 'provider.cli.scan': { scanned_at: 't', count: 0, runtimes: [], configured: [], notice: 'n' } } });
    const client = new HarnessClient({ baseUrl: 'http://daemon.test', token: 't', fetchImpl: daemon.fetch });
    const report = await client.providerCliScan(true);
    expect(report.count).toBe(0);
    expect(daemon.capabilityCalls()).toEqual([{ name: 'provider.cli.scan', request: { rescan: true } }]);
  });

  it('configures, tests, and removes by name', async () => {
    const daemon = fakeDaemon({
      capabilities: {
        'provider.cli.configure': { entry: { name: 'codex-sub' }, created: true, file: 'research.yaml' },
        'provider.cli.test': { name: 'codex-sub', ok: true, message: 'ok' },
        'provider.cli.remove': { name: 'codex-sub', file: 'research.yaml' },
      },
    });
    const client = new HarnessClient({ baseUrl: 'http://daemon.test', token: 't', fetchImpl: daemon.fetch });
    await client.providerCliConfigure({ name: 'codex-sub', runtime: 'codex', model: 'gpt-5.5', priority: 10 });
    await client.providerCliTest('codex-sub');
    await client.providerCliRemove('codex-sub');
    expect(daemon.capabilityCalls().map((call) => call.name)).toEqual(['provider.cli.configure', 'provider.cli.test', 'provider.cli.remove']);
    expect(daemon.capabilityCalls()[0]!.request).toEqual({ name: 'codex-sub', runtime: 'codex', model: 'gpt-5.5', priority: 10 });
    expect(daemon.capabilityCalls()[2]!.request).toEqual({ name: 'codex-sub' });
  });

  it('surfaces a refusal as a CapabilityError', async () => {
    const daemon = fakeDaemon({ capabilities: { 'provider.cli.configure': { capability: 'provider.cli.configure', ok: false, error: { code: 'permission_denied', message: 'human only' } } } });
    const client = new HarnessClient({ baseUrl: 'http://daemon.test', token: null, fetchImpl: daemon.fetch });
    await expect(client.providerCliConfigure({ name: 'x', runtime: 'codex' })).rejects.toThrow('human only');
  });
});

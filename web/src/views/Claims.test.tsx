/**
 * Task 11.4: the claim explorer shows what was asked for beside what the evidence allows,
 * and every act on a claim is a capability call.
 *
 * Product 42 G is the invariant behind this screen: a claim with incomplete coverage must
 * not quietly escalate its wording. The cockpit's part of that is to always show the two
 * strengths together, and to make the override a visible Decision rather than an edit.
 */
import { describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { ClaimDetailPage, ClaimsPage } from './Claims';
import { FIXTURES, fakeDaemon, renderView } from '../test/harness';

const CLAIM = 'C0001';

function daemonFor(overview: unknown = FIXTURES.overview) {
  return fakeDaemon({
    gets: {
      '/overview': overview,
      [`/objects/${CLAIM}`]: FIXTURES.claim,
    },
    capabilities: {
      // One list per read, through the capability every host shares.
      'claim.list': { count: FIXTURES.index.claims.length, claims: FIXTURES.index.claims },
      'decision.list': { count: FIXTURES.index.decisions.length, decisions: FIXTURES.index.decisions },
      'anchor.list': { count: FIXTURES.index.anchors.length, anchors: FIXTURES.index.anchors },
      'claim.find_support': FIXTURES.claimSupport,
      'claim.audit': { capability: 'claim.audit', objects: [CLAIM] },
      'claim.relate': { capability: 'claim.relate', objects: [CLAIM] },
      'decision.accept': { capability: 'decision.accept', objects: ['D0001'] },
      'claim.override_strength': { capability: 'claim.override_strength', objects: [CLAIM] },
    },
  });
}

function renderDetail(daemon = daemonFor(), token: string | null = 'local-token') {
  return renderView(<ClaimDetailPage />, {
    daemon,
    token,
    route: `/claims/${CLAIM}`,
    path: '/claims/:claimId',
  });
}

describe('the claim list', () => {
  it('shows requested strength beside allowed strength for every claim', async () => {
    renderView(<ClaimsPage />, { daemon: daemonFor(), route: '/claims', path: '/claims' });

    await waitFor(() => expect(screen.getByText('Requested')).toBeInTheDocument());
    expect(screen.getByText('Allowed')).toBeInTheDocument();
    expect(screen.getByText('observed_subset')).toBeInTheDocument();
    expect(screen.getByText('individual')).toBeInTheDocument();
  });

  it('reads the one list it shows, not the whole workspace index', async () => {
    const daemon = daemonFor();
    renderView(<ClaimsPage />, { daemon, route: '/claims', path: '/claims' });

    await waitFor(() => expect(screen.getByText('Requested')).toBeInTheDocument());
    expect(daemon.capabilityCalls()).toEqual([{ name: 'claim.list', request: {} }]);
    expect(daemon.calls.map((call) => call.path)).not.toContain('/index');
  });
});

describe('the claim detail', () => {
  it('reports what was asked for, what is allowed, and the wording that permits', async () => {
    renderDetail();

    await waitFor(() => expect(screen.getByText('Requested strength')).toBeInTheDocument());
    expect(screen.getAllByText('Allowed strength').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Maximum defensible wording').length).toBeGreaterThan(0);
    expect(screen.getByText('one system on one held-out split')).toBeInTheDocument();
    expect(screen.getByText(/relevant\s*works examined/)).toBeInTheDocument();
  });

  it('lists the supporting evidence with the span it was accepted from', async () => {
    renderDetail();

    await waitFor(() => expect(screen.getByText(/Supporting \(1\)/)).toBeInTheDocument());
    const link = screen.getByRole('link', { name: 'E0001' });
    expect(link).toHaveAttribute('href', '/evidence/E0001');
  });

  it('records an audit through `claim.audit` with the status and strength chosen', async () => {
    const daemon = daemonFor();
    renderDetail(daemon);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Record the audit' })).toBeEnabled(),
    );
    fireEvent.change(screen.getByLabelText('Status the evidence supports'), {
      target: { value: 'qualified' },
    });
    fireEvent.change(screen.getByLabelText('Allowed strength'), {
      target: { value: 'observed_subset' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Record the audit' }));

    await waitFor(() => {
      const call = daemon.capabilityCalls().find((entry) => entry.name === 'claim.audit');
      expect(call?.request).toMatchObject({
        claim_id: CLAIM,
        status: 'qualified',
        allowed_strength: 'observed_subset',
      });
    });
  });

  it('shows the coverage the audit recorded, without recomputing any of it', async () => {
    renderDetail();

    await waitFor(() => expect(screen.getByText('Search runs')).toBeInTheDocument());
    expect(screen.getByText(/overturn risk/)).toBeInTheDocument();
  });

  it('makes an override an accepted Decision first, then applies it', async () => {
    const daemon = daemonFor();
    renderDetail(daemon);

    await waitFor(() =>
      expect(screen.getByLabelText(/Scope you are choosing instead of/)).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText(/Scope you are choosing instead of/), {
      target: { value: 'observed_subset' },
    });
    fireEvent.change(screen.getByLabelText('Rationale'), {
      target: { value: 'the held-out split covers both captures' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Accept the override' }));

    await waitFor(() => {
      const names = daemon.capabilityCalls().map((call) => call.name);
      expect(names).toContain('decision.accept');
      expect(names.indexOf('decision.accept')).toBeLessThan(
        names.indexOf('claim.override_strength'),
      );
    });
    // The daemon names the Decision under the workspace lock; the cockpit uses what it got
    // back rather than the id `GET /overview` announced before anything was written.
    const accepted = daemon.capabilityCalls().find((call) => call.name === 'decision.accept');
    expect(accepted?.request.decision).not.toHaveProperty('id');
    const applied = daemon
      .capabilityCalls()
      .find((call) => call.name === 'claim.override_strength');
    expect(applied?.request).toEqual({ claim_id: CLAIM, decision_id: 'D0001' });
  });

  it('relates evidence as one directed edge', async () => {
    const daemon = daemonFor();
    renderDetail(daemon);

    await waitFor(() => expect(screen.getByLabelText('Evidence id')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Evidence id'), { target: { value: 'E0002' } });
    fireEvent.click(screen.getByRole('button', { name: 'Relate' }));

    await waitFor(() => {
      const call = daemon.capabilityCalls().find((entry) => entry.name === 'claim.relate');
      expect(call?.request).toEqual({
        claim_id: CLAIM,
        relation: { evidence: 'E0002', relation: 'supports' },
      });
    });
  });

  it('disables auditing and overriding for an agent host', async () => {
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    renderDetail(daemonFor(asHost), null);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Record the audit' })).toBeDisabled(),
    );
    expect(screen.getByRole('button', { name: 'Accept the override' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Relate' })).toBeDisabled();
  });
});

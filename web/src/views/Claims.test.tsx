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
import userEvent from '@testing-library/user-event';
import { ClaimDetailPage, ClaimsPage } from './Claims';
import { ProjectPathProvider } from '../app/projectPaths';
import { FIXTURES, expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const CLAIM = 'C0001';

/**
 * The project's accepted evidence, as `evidence.list` reports it. Hand-declared like the
 * `EvidenceSummary` interface itself, whose names the daemon's contract test asserts.
 */
const ACCEPTED = [
  {
    id: 'E0001',
    work: 'W0001',
    artifact: 'A0001-1',
    field: 'metric_result',
    status: 'accepted',
    origin: 'source_observed',
    evidence_type: 'experimental_result',
    strength: 'direct',
    review_tier: 2,
    verdict: 'supported',
    exact_text: 'TrafficLM reaches an F1 of 94.32 on CICIDS2017',
    qualification: null,
    stale: 'fresh',
  },
  {
    id: 'E0002',
    work: 'W0002',
    artifact: 'A0002-1',
    field: 'method_summary',
    status: 'accepted',
    origin: 'source_observed',
    evidence_type: 'method_description',
    strength: 'direct',
    review_tier: 1,
    verdict: 'supported',
    exact_text: 'The encoder is a twelve layer transformer',
    qualification: null,
    stale: 'fresh',
  },
];

function daemonFor(
  overview: unknown = FIXTURES.overview,
  extraCapabilities: Record<string, unknown> = {},
) {
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
      'evidence.list': { count: ACCEPTED.length, evidence: ACCEPTED },
      'claim.audit': { capability: 'claim.audit', objects: [CLAIM] },
      'claim.relate': { capability: 'claim.relate', objects: [CLAIM] },
      'decision.accept': { capability: 'decision.accept', objects: ['D0001'] },
      'claim.override_strength': { capability: 'claim.override_strength', objects: [CLAIM] },
      ...extraCapabilities,
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
    expect(screen.getByText('L1 Observed subset')).toBeInTheDocument();
    expect(screen.getByText('L0 Individual')).toBeInTheDocument();
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

  it('relates evidence picked out of the project’s own accepted evidence', async () => {
    const user = userEvent.setup();
    const daemon = daemonFor();
    renderDetail(daemon);

    const picker = await screen.findByRole('combobox', { name: 'Accepted evidence' });
    // Nothing is relatable until something real has been chosen: an id typed from memory
    // is the one input on this screen that cannot be checked before the button is pressed.
    expect(screen.getByRole('button', { name: 'Relate' })).toBeDisabled();

    await user.type(picker, 'transformer');
    const option = await screen.findByRole('option', { name: /E0002/ });
    expect(option).toHaveTextContent('Method summary');
    expect(option).toHaveTextContent('W0002');
    await user.click(option);
    await user.click(screen.getByRole('button', { name: 'Relate' }));

    await waitFor(() => {
      const call = daemon.capabilityCalls().find((entry) => entry.name === 'claim.relate');
      expect(call?.request).toEqual({
        claim_id: CLAIM,
        relation: { evidence: 'E0002', relation: 'supports' },
      });
    });
  });

  it('still takes an id in full, for a researcher who knows it', async () => {
    const user = userEvent.setup();
    const daemon = daemonFor();
    renderDetail(daemon);

    const picker = await screen.findByRole('combobox', { name: 'Accepted evidence' });
    await user.type(picker, 'E0001');
    expect(await screen.findByRole('option', { name: /E0001/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Relate' }));

    await waitFor(() => {
      const call = daemon.capabilityCalls().find((entry) => entry.name === 'claim.relate');
      expect(call?.request).toEqual({
        claim_id: CLAIM,
        relation: { evidence: 'E0001', relation: 'supports' },
      });
    });
  });

  it('says the vocabulary in words, never as the daemon’s identifiers', async () => {
    const { container } = renderDetail();

    await waitFor(() => expect(screen.getByText('Requested strength')).toBeInTheDocument());
    const text = container.textContent ?? '';
    for (const token of ['observed_subset', 'field_generalization', 'metric_result']) {
      expect(text).not.toContain(token);
    }
    expect(text).toContain('L1 Observed subset');
  });

  it('disables auditing and overriding for an agent host', async () => {
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    renderDetail(daemonFor(asHost), null);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Record the audit' })).toBeDisabled(),
    );
    expect(screen.getByRole('button', { name: 'Accept the override' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Relate' })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'Accepted evidence' })).toBeDisabled();
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = renderDetail();

    await waitFor(() => expect(screen.getByText('Requested strength')).toBeInTheDocument());
    await expectNoAxeViolations(container);
  });
});

/**
 * The claim screens under `research app`, where a workspace path is not the URL.
 *
 * The Claim → Evidence → Work chain is the navigation this screen exists for, so every
 * step of it has to stay inside the project: a middle-clicked `E0001` that landed on the
 * legacy `/evidence/E0001` would leave the project entirely.
 */
describe('the claim screens inside a project', () => {
  it('points each row of the list at the project’s own claim page', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <ClaimsPage />
      </ProjectPathProvider>,
      { daemon: daemonFor(), route: '/projects/prj_abc/claims', path: '/projects/prj_abc/claims' },
    );

    await waitFor(() => expect(screen.getByText('Requested')).toBeInTheDocument());
    const hrefs = screen.getAllByRole('link').map((link) => link.getAttribute('href'));
    expect(hrefs).toContain(`/projects/prj_abc/claims/${CLAIM}`);
    expect(hrefs.every((href) => href?.startsWith('/projects/prj_abc/'))).toBe(true);
  });

  it('keeps every step of the provenance chain inside the project', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <ClaimDetailPage />
      </ProjectPathProvider>,
      {
        daemon: daemonFor(),
        route: `/projects/prj_abc/claims/${CLAIM}`,
        path: '/projects/prj_abc/claims/:claimId',
      },
    );

    await waitFor(() => expect(screen.getByText(/Supporting \(1\)/)).toBeInTheDocument());
    expect(screen.getByRole('link', { name: 'E0001' })).toHaveAttribute(
      'href',
      '/projects/prj_abc/evidence/E0001',
    );
    const hrefs = screen.getAllByRole('link').map((link) => link.getAttribute('href'));
    expect(hrefs).toContain(`/projects/prj_abc/claims/${CLAIM}`);
    expect(hrefs).toContain('/projects/prj_abc/corpus/W0001');
  });

  it('leaves the legacy chain exactly where it was', async () => {
    renderDetail();

    await waitFor(() => expect(screen.getByText(/Supporting \(1\)/)).toBeInTheDocument());
    expect(screen.getByRole('link', { name: 'E0001' })).toHaveAttribute(
      'href',
      '/evidence/E0001',
    );
  });
});

/**
 * The claim screens in the states that are not "here is the claim".
 *
 * Both used to return the state instead of the page, which took the `h1` — the claim's own
 * id — off the screen exactly when a researcher needed to know which claim had failed to
 * load. The frame is asserted first in each of these, the state second.
 */
const CLAIM_REFUSAL = 'the workspace lock is held by another process';

/** A daemon that has not answered yet, so the page stays in its loading state. */
function pendingDaemon(): FakeDaemon {
  return {
    fetch: (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

describe('the claim list before, without, and after its read', () => {
  it('keeps its heading and draws table rows while the read is in flight', () => {
    const { container } = renderView(<ClaimsPage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Claims' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the claims…');
    expect(
      container.querySelectorAll('.rh-skeleton-group[data-direction="row"]').length,
    ).toBeGreaterThan(1);
    expect(container.textContent).not.toMatch(/\d+ registered/);
  });

  it('keeps its heading when the read is refused, and offers the retry', async () => {
    renderView(<ClaimsPage />, {
      daemon: fakeDaemon({
        capabilities: {
          'claim.list': {
            capability: 'claim.list',
            ok: false,
            error: { code: 'unavailable', message: CLAIM_REFUSAL },
          },
        },
      }),
    });

    await waitFor(() => expect(screen.getByText(CLAIM_REFUSAL)).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Claims' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('says what a claim is and where one comes from when there are none', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <ClaimsPage />
      </ProjectPathProvider>,
      {
        daemon: fakeDaemon({ capabilities: { 'claim.list': { count: 0, claims: [] } } }),
        route: '/projects/prj_abc/claims',
        path: '/projects/prj_abc/claims',
      },
    );

    await waitFor(() => expect(screen.getByText('No claims registered yet')).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Claims' })).toBeInTheDocument();
    expect(screen.getByText(/held against the strength its evidence allows/)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Open the conversation to promote a claim' }),
    ).toHaveAttribute('href', '/projects/prj_abc/');
    await expectNoAxeViolations(container);
  });
});

describe('one claim that could not be read', () => {
  it('keeps the claim id as the heading and offers the retry', async () => {
    renderView(<ClaimDetailPage />, {
      daemon: fakeDaemon({
        capabilities: {
          'claim.find_support': FIXTURES.claimSupport,
          'decision.list': { count: 0, decisions: [] },
          'anchor.list': { count: 0, anchors: [] },
        },
        gets: { [`/objects/${CLAIM}`]: undefined as never },
      }),
      route: `/claims/${CLAIM}`,
      path: '/claims/:claimId',
    });

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument(),
    );
    expect(screen.getByRole('heading', { level: 1, name: CLAIM })).toBeInTheDocument();
  });

  it('teaches nothing it cannot know: no evidence relation is reported as absent', async () => {
    const noSupport = { supporting: [], qualifying: [], contradicting: [], other: [] };
    renderView(<ClaimDetailPage />, {
      daemon: daemonFor(FIXTURES.overview, { 'claim.find_support': noSupport }),
      route: `/claims/${CLAIM}`,
      path: '/claims/:claimId',
    });

    await waitFor(() => expect(screen.getByText(/Supporting \(0\)/)).toBeInTheDocument());
    expect(
      screen.getByText('No evidence is related to this claim as supporting.'),
    ).toBeInTheDocument();
  });
});

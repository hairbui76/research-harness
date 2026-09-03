/**
 * The Manuscript view reads the manuscript capabilities and recomputes none of them.
 *
 * Three properties are asserted here. A finding is placed by its own `location`, not by
 * parsing the prose the auditor wrote (Product 30.3). An anchor's current verdict comes
 * from `manuscript.anchors`, which is a read. And Revalidate — the one control on this
 * screen that writes — is disabled without the local token, because recording that a
 * reworded sentence has gone stale is a researcher's judgement (ADR-008, Product 29).
 *
 * The fixtures are real responses, exported by `web/scripts/export_backend_json.py` from
 * the same fixture manuscript the VS Code extension is tested against.
 */
import { describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import type { ManuscriptAuditFinding } from '../api/dto';
import { ManuscriptPage, whereOf } from './Manuscript';
import { FIXTURES, expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';

const FINDINGS = FIXTURES.manuscriptAudit.findings as unknown as ManuscriptAuditFinding[];

function daemonFor(overview: unknown = FIXTURES.overview) {
  return fakeDaemon({
    gets: { '/overview': overview },
    capabilities: {
      'manuscript.anchors': FIXTURES.manuscriptAnchors,
      'manuscript.audit': FIXTURES.manuscriptAudit,
      'manuscript.trace': FIXTURES.manuscriptTrace,
      'manuscript.revalidate': {
        dry_run: false,
        checked: 3,
        valid: 3,
        relocated: 0,
        stale: 0,
        missing: 0,
        applied: [],
        results: [],
        mutations: [],
      },
    },
  });
}

function renderManuscript(daemon = daemonFor(), token: string | null = 'local-token') {
  return renderView(<ManuscriptPage />, { daemon, token, route: '/manuscript', path: '/manuscript' });
}

describe('a finding’s location', () => {
  it('comes from the structured field rather than the message prefix', () => {
    const finding = FINDINGS[0]!;
    expect(finding.location).toBeDefined();
    expect(whereOf(finding)).toBe(
      `${finding.location!.file}:${finding.location!.line_start}-${finding.location!.line_end}`,
    );
  });

  it('says so plainly when no sentence produced the finding', () => {
    expect(whereOf({ kind: 'stale_claim', severity: 'warning', message: 'x' })).toBe(
      'whole project',
    );
  });

  it('collapses a one-line span rather than printing it twice', () => {
    expect(
      whereOf({
        kind: 'unregistered_claim',
        severity: 'info',
        message: 'x',
        location: { file: 'main.tex', line_start: 23, line_end: 23 },
      }),
    ).toBe('main.tex:23');
  });
});

describe('the anchors panel', () => {
  it('lists every stored anchor with the verdict `manuscript.anchors` computed', async () => {
    const daemon = daemonFor();
    renderManuscript(daemon);

    await waitFor(() => expect(screen.getByText(/Anchors \(3\)/)).toBeInTheDocument());
    expect(screen.getByText('main.tex:14')).toBeInTheDocument();
    expect(
      screen.getAllByText(/sentence unchanged at the recorded span/).length,
    ).toBeGreaterThan(0);
    expect(daemon.capabilityCalls().map((call) => call.name)).toContain('manuscript.anchors');
    expect(daemon.calls.map((call) => call.path)).not.toContain('/index');
  });

  it('traces one sentence down to its Claim through `manuscript.trace`', async () => {
    const daemon = daemonFor();
    renderManuscript(daemon);

    await waitFor(() => expect(screen.getAllByText('Trace this sentence').length).toBe(3));
    fireEvent.click(screen.getAllByText('Trace this sentence')[1]!);

    await waitFor(() => {
      const call = daemon.capabilityCalls().find((entry) => entry.name === 'manuscript.trace');
      expect(call?.request).toMatchObject({ file: 'main.tex', line: 17 });
    });
    await waitFor(() => expect(screen.getByText(/Trace — main.tex:17/)).toBeInTheDocument());
  });
});

describe('the audit', () => {
  it('renders each finding where the daemon said it was raised', async () => {
    renderManuscript();

    fireEvent.click(screen.getByRole('button', { name: 'Audit the manuscript' }));

    await waitFor(() => expect(screen.getByText('Sentences checked')).toBeInTheDocument());
    const first = FINDINGS[0]!;
    expect(screen.getAllByText(whereOf(first)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(first.kind).length).toBeGreaterThan(0);
  });
});

describe('revalidating', () => {
  it('records the verdicts through the mutation and reports what it wrote', async () => {
    const daemon = daemonFor();
    renderManuscript(daemon);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Revalidate anchors' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Revalidate anchors' }));

    await waitFor(() => {
      const call = daemon.capabilityCalls().find((entry) => entry.name === 'manuscript.revalidate');
      expect(call?.request).toEqual({
        project_root: null,
        main_tex: 'main.tex',
        dry_run: false,
      });
    });
    await waitFor(() => expect(screen.getByText(/3 anchors re-found/)).toBeInTheDocument());
  });

  it('is disabled for an agent host, and says why', async () => {
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    const daemon = daemonFor(asHost);
    renderManuscript(daemon, null);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Revalidate anchors' })).toBeDisabled(),
    );
    expect(screen.getByTestId('revalidate-blocked').textContent).toContain('agent host');
    fireEvent.click(screen.getByRole('button', { name: 'Revalidate anchors' }));
    expect(daemon.capabilityCalls().map((call) => call.name)).not.toContain(
      'manuscript.revalidate',
    );
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = renderManuscript();

    await waitFor(() => expect(screen.getByText(/Anchors \(3\)/)).toBeInTheDocument());
    await expectNoAxeViolations(container);
  });
});

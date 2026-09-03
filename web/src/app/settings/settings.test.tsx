/**
 * The Models & providers settings: what the daemon says, rendered, and nothing decided here.
 *
 * Every state word in these expectations is a string the fixtures carry — the reasons, the
 * diagnostics, the test report, the egress notice. When one of them changes on the daemon,
 * this file has to change with it, which is the point.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations, fakeDaemon, renderView, FIXTURES } from '../../test/harness';
import scan from '../../test/fixtures/providers/cli-scan.json';
import scanEmpty from '../../test/fixtures/providers/cli-scan-empty.json';
import configured from '../../test/fixtures/providers/cli-configured.json';
import removed from '../../test/fixtures/providers/cli-removed.json';
import testOk from '../../test/fixtures/providers/cli-test-ok.json';
import testFailed from '../../test/fixtures/providers/cli-test-failed.json';
import apiProviders from '../../test/fixtures/providers/api-providers.json';
import { SettingsDialog } from '../SettingsDialog';

function answers(extra: Record<string, unknown> = {}) {
  return {
    'provider.cli.scan': scan,
    'provider.list': apiProviders,
    'provider.cli.configure': configured,
    'provider.cli.remove': removed,
    'provider.cli.test': testOk,
    ...extra,
  };
}

function open(daemon: ReturnType<typeof fakeDaemon>, token: string | null = 'local-token') {
  return renderView(<SettingsDialog open onOpenChange={() => undefined} />, { daemon, token });
}

/** The daemon's answer for a window connected without the local token (PRODUCT §29). */
const AS_HOST = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };

async function providersTab() {
  await userEvent.click(screen.getByRole('tab', { name: 'Models & providers' }));
  return screen.getByRole('tabpanel', { name: 'Models & providers' });
}

describe('the two tabs', () => {
  it('renders Local CLIs and API providers as separate tabs', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    const panel = await providersTab();
    expect(within(panel).getByRole('tab', { name: 'Local CLIs' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(within(panel).getByRole('tab', { name: 'API providers' })).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole('tab', { name: 'API providers' }));
    expect(await screen.findByText('fast/gpt-5.4-mini')).toBeInTheDocument();
    expect(screen.getByText(/API keys are read from environment variables/)).toBeInTheDocument();
  });

  it('lists the API providers the daemon named, and leaves the CLI entries to the other tab', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    const panel = await providersTab();
    await userEvent.click(within(panel).getByRole('tab', { name: 'API providers' }));
    const rows = await screen.findAllByRole('listitem');
    expect(rows.map((row) => row.textContent)).toEqual([
      'fast/gpt-5.4-mini · openai · external · available',
    ]);
    expect(screen.queryByText(/codex-sub\/gpt-5\.5/)).not.toBeInTheDocument();
  });

  it('moves between tabs with the arrow keys', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    const panel = await providersTab();
    within(panel).getByRole('tab', { name: 'Local CLIs' }).focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(within(panel).getByRole('tab', { name: 'API providers' })).toHaveFocus();
  });
});

/** A daemon whose CLI scan does not answer until the test lets it. */
function gatedScan(): { daemon: ReturnType<typeof fakeDaemon>; release: () => void } {
  const base = fakeDaemon({ capabilities: answers() });
  let release = () => undefined as void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).includes('provider.cli.scan')) await gate;
    return base.fetch(input, init);
  }) as typeof fetch;
  return { daemon: { ...base, fetch: fetchImpl }, release: () => release() };
}

describe('the Local CLIs tab', () => {
  it('says it is scanning while the daemon is still looking', async () => {
    const { daemon, release } = gatedScan();
    open(daemon);
    await providersTab();
    expect(screen.getByText(/Reading the local CLI scan/)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Installed' })).not.toBeInTheDocument();
    release();
    expect(await screen.findByRole('region', { name: 'Installed' })).toBeInTheDocument();
  });

  it('shows the installed and unavailable groups', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    await providersTab();
    const installed = await screen.findByRole('region', { name: 'Installed' });
    expect(
      within(installed)
        .getAllByRole('heading', { level: 4 })
        .map((heading) => heading.textContent),
    ).toEqual(['Codex CLI', 'Claude Code', 'Cursor Agent', 'OpenCode']);
    const unavailable = screen.getByRole('region', { name: 'Not installed' });
    expect(
      within(unavailable)
        .getAllByRole('heading', { level: 4 })
        .map((heading) => heading.textContent),
    ).toEqual(['Amp', 'DeepSeek Harness', 'Pi']);
    expect(screen.getByText(scan.notice)).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('renders the daemon states: logged out, unsafe, version warning, with its own words', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    await providersTab();
    const claude = await screen.findByRole('article', { name: 'Claude Code' });
    expect(within(claude).getByText('Not logged in')).toBeInTheDocument();
    expect(within(claude).getByText('run `claude auth login`')).toBeInTheDocument();
    expect(
      within(claude).getByText('claude is not logged in: run `claude auth login`'),
    ).toBeInTheDocument();

    const cursor = screen.getByRole('article', { name: 'Cursor Agent' });
    expect(within(cursor).getByText('No bounded mode')).toBeInTheDocument();
    expect(within(cursor).getByText('Untested 1.4.0')).toBeInTheDocument();
    expect(within(cursor).getByText(/no deny-tools flag is documented/)).toBeInTheDocument();
    expect(
      within(cursor).getByText('cursor-agent 1.4.0 has no tested bounded (no-tools, read-only) mode'),
    ).toBeInTheDocument();
    expect(within(cursor).getByRole('button', { name: 'Add provider' })).toBeDisabled();
  });

  it('keeps an installed but unroutable CLI in the installed group, with the daemon reason', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    await providersTab();
    const opencode = await screen.findByRole('article', { name: 'OpenCode' });
    expect(within(opencode).getByText('Bounded mode unproven')).toBeInTheDocument();
    expect(
      within(opencode).getByText(
        'opencode: the environment-injected bounded posture is unproven on this version (no recorded fixtures)',
      ),
    ).toBeInTheDocument();
    expect(
      within(opencode).getByText('opencode 1.18.0 could not prove a bounded (no-tools, read-only) mode'),
    ).toBeInTheDocument();
    expect(within(opencode).getByRole('button', { name: 'Add provider' })).toBeDisabled();
  });

  it('says so when nothing is installed and offers a rescan', async () => {
    const daemon = fakeDaemon({ capabilities: answers({ 'provider.cli.scan': scanEmpty }) });
    open(daemon);
    await providersTab();
    expect(await screen.findByText(/No supported CLI is installed/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Rescan' }));
    await waitFor(() =>
      expect(daemon.capabilityCalls().filter((call) => call.name === 'provider.cli.scan')).toHaveLength(2),
    );
    expect(daemon.capabilityCalls().at(-1)?.request).toEqual({ rescan: true });
  });

  it('reports a failed scan and keeps the rescan control', async () => {
    const daemon = fakeDaemon({
      capabilities: answers({
        'provider.cli.scan': {
          capability: 'provider.cli.scan',
          ok: false,
          error: { code: 'internal_error', message: 'scan blew up' },
        },
      }),
    });
    open(daemon);
    await providersTab();
    expect(await screen.findByText(/scan blew up/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rescan' })).toBeEnabled();
  });

  it('adds a provider with the chosen model and reasoning, after the egress warning', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    await providersTab();
    const claude = await screen.findByRole('article', { name: 'Claude Code' });
    expect(within(claude).getByRole('button', { name: 'Add provider' })).toBeDisabled();

    const codex = screen.getByRole('article', { name: 'Codex CLI' });
    expect(within(codex).getByText(/leave the machine/)).toBeInTheDocument();
    await userEvent.selectOptions(within(codex).getByLabelText('Model'), 'gpt-5.5');
    await userEvent.selectOptions(within(codex).getByLabelText('Reasoning'), 'high');
    await userEvent.clear(within(codex).getByLabelText('Entry name'));
    await userEvent.type(within(codex).getByLabelText('Entry name'), 'codex-work');
    await userEvent.click(within(codex).getByRole('button', { name: 'Update provider' }));
    await waitFor(() =>
      expect(daemon.capabilityCalls().some((call) => call.name === 'provider.cli.configure')).toBe(true),
    );
    expect(daemon.capabilityCalls().find((call) => call.name === 'provider.cli.configure')?.request).toEqual({
      name: 'codex-work',
      runtime: 'codex',
      model: 'gpt-5.5',
      priority: 10,
      reasoning: 'high',
    });
  });

  it('tests a configured entry and renders the daemon report', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    await providersTab();
    const codex = await screen.findByRole('article', { name: 'Codex CLI' });
    await userEvent.click(within(codex).getByRole('button', { name: 'Test' }));
    expect(await within(codex).findByRole('status')).toHaveTextContent(
      'Codex CLI answered through the subscription login in 2140 ms',
    );
    expect(daemon.capabilityCalls().find((call) => call.name === 'provider.cli.test')?.request).toEqual({
      name: 'codex-sub',
    });
  });

  it('renders a failed test with the daemon message and its diagnostic', async () => {
    const daemon = fakeDaemon({ capabilities: answers({ 'provider.cli.test': testFailed }) });
    open(daemon);
    await providersTab();
    const codex = await screen.findByRole('article', { name: 'Codex CLI' });
    await userEvent.click(within(codex).getByRole('button', { name: 'Test' }));
    expect(
      await within(codex).findByText(/not logged in; run `codex login`/),
    ).toBeInTheDocument();
    expect(within(codex).getByText('login_missing')).toBeInTheDocument();
  });

  it('removes a configured entry', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    await providersTab();
    const codex = await screen.findByRole('article', { name: 'Codex CLI' });
    expect(
      within(codex).getByText('Configured as codex-sub (gpt-5.5, priority 10) — available'),
    ).toBeInTheDocument();
    await userEvent.click(within(codex).getByRole('button', { name: 'Remove' }));
    await waitFor(() =>
      expect(daemon.capabilityCalls().some((call) => call.name === 'provider.cli.remove')).toBe(true),
    );
    expect(daemon.capabilityCalls().find((call) => call.name === 'provider.cli.remove')?.request).toEqual({
      name: 'codex-sub',
    });
  });

  it('offers no mutation to a window that may only read', async () => {
    const daemon = fakeDaemon({ gets: { '/overview': AS_HOST }, capabilities: answers() });
    open(daemon, null);
    await providersTab();
    const codex = await screen.findByRole('article', { name: 'Codex CLI' });
    for (const name of ['Update provider', 'Test', 'Remove']) {
      expect(within(codex).getByRole('button', { name })).toBeDisabled();
    }
    expect(within(codex).getByText(/agent host/)).toBeInTheDocument();
    expect(daemon.capabilityCalls().some((call) => call.name === 'provider.cli.configure')).toBe(false);
  });
});

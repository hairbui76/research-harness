/**
 * Test scaffolding: a fake daemon, and the cockpit rendered against it.
 *
 * The fixtures under `fixtures/` are real responses, exported from a real workspace by
 * `uv run python web/scripts/export_backend_json.py`. A test that hand-wrote its payloads
 * would pass against an API that no longer exists.
 */
import type { ReactElement } from 'react';
import axe from 'axe-core';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import { ThemeProvider, ToastProvider } from '@research-harness/design';
import { HarnessClient } from '../api/client';
import { SessionProvider } from '../app/session';

import blocks from './fixtures/blocks.json';
import candidate from './fixtures/candidate.json';
import claim from './fixtures/claim.json';
import claimSupport from './fixtures/claim-support.json';
import index from './fixtures/index.json';
import manuscriptAnchors from './fixtures/manuscript-anchors.json';
import manuscriptAudit from './fixtures/manuscript-audit.json';
import manuscriptTrace from './fixtures/manuscript-trace.json';
import overview from './fixtures/overview.json';
import reviewInbox from './fixtures/review-inbox.json';

export const FIXTURES = {
  blocks,
  candidate,
  claim,
  claimSupport,
  index,
  manuscriptAnchors,
  manuscriptAudit,
  manuscriptTrace,
  overview,
  reviewInbox,
};

export interface RecordedCall {
  method: string;
  path: string;
  body: unknown;
}

export interface FakeDaemon {
  fetch: typeof fetch;
  calls: RecordedCall[];
  /** Every `POST /capabilities/<name>` made so far, in order. */
  capabilityCalls(): { name: string; request: any }[];
}

/**
 * A fake daemon.
 *
 * `gets` maps a path to its JSON body; `capabilities` maps a capability name to the
 * `result` it answers with, or to a full envelope when a test needs a refusal.
 */
export function fakeDaemon(options: {
  gets?: Record<string, unknown>;
  capabilities?: Record<string, unknown>;
} = {}): FakeDaemon {
  const calls: RecordedCall[] = [];
  const gets: Record<string, unknown> = {
    '/overview': FIXTURES.overview,
    '/index': FIXTURES.index,
    ...options.gets,
  };

  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://daemon.test');
    const path = url.pathname;
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, path, body });

    if (method === 'POST' && path.startsWith('/capabilities/')) {
      const name = path.slice('/capabilities/'.length);
      const answer = options.capabilities?.[name];
      if (answer === undefined) {
        return jsonResponse({
          capability: name,
          ok: false,
          error: { code: 'capability_not_found', message: `no fake answer for ${name}` },
        });
      }
      if (isEnvelope(answer)) return jsonResponse(answer);
      return jsonResponse({ capability: name, ok: true, result: answer });
    }

    if (path in gets) return jsonResponse(gets[path]);
    return new Response('not found', { status: 404 });
  });

  return {
    fetch: fetchImpl as unknown as typeof fetch,
    calls,
    capabilityCalls: () =>
      calls
        .filter((call) => call.method === 'POST' && call.path.startsWith('/capabilities/'))
        .map((call) => ({ name: call.path.slice('/capabilities/'.length), request: call.body })),
  };
}

/**
 * A whole `CapabilityResponse`, rather than the `result` a caller wrote out bare.
 *
 * `ok` alone cannot tell the two apart: `provider.cli.test` answers a report whose own
 * verdict field is `ok`, and reading that as an envelope would find no `result` and turn a
 * success into a refusal. The daemon names the capability on every envelope it sends and
 * on nothing else, so that is the discriminator.
 */
function isEnvelope(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  return 'ok' in (value as object) && 'capability' in (value as object);
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

export interface RenderOptions {
  daemon: FakeDaemon;
  token?: string | null;
  route?: string;
  path?: string;
}

/**
 * Render one view inside the session and the router, against a fake daemon.
 *
 * The two Design System providers are the same ones `main.tsx` mounts: `ThemeProvider`
 * (with `storageKey={null}`, so a test never writes an appearance preference into the
 * shared jsdom `localStorage`) and `ToastProvider`, which every mutation surface reports
 * through.
 */
export function renderView(ui: ReactElement, options: RenderOptions) {
  const client = new HarnessClient({
    baseUrl: 'http://daemon.test',
    token: options.token ?? 'local-token',
    fetchImpl: options.daemon.fetch,
  });
  const route = options.route ?? '/';
  const path = options.path ?? route;
  return render(
    <ThemeProvider defaultTheme="dark" storageKey={null}>
      <ToastProvider>
        <MemoryRouter
          initialEntries={[route]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <SessionProvider client={client}>
            <Routes>
              <Route path={path} element={ui} />
            </Routes>
          </SessionProvider>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

/**
 * The accessibility gate every migrated view runs (DS spec §6, §12.5).
 *
 * The rules that need a layout engine or a whole document are off: jsdom computes no
 * geometry, so `color-contrast` cannot run here — the Design System verifies contrast
 * against the token values instead (`design/scripts/check-contrast.mjs`) — and page-level
 * landmark rules do not apply to a view rendered without its shell.
 */
const DISABLED_RULES = [
  'color-contrast',
  'region',
  'page-has-heading-one',
  'landmark-one-main',
  'html-has-lang',
  'document-title',
  'bypass',
];

/** Fails with the offending rule ids and target selectors when anything is violated. */
export async function expectNoAxeViolations(
  target: Element | Document = document.body,
  extraDisabledRules: readonly string[] = [],
): Promise<void> {
  const rules: axe.RuleObject = {};
  for (const rule of [...DISABLED_RULES, ...extraDisabledRules]) rules[rule] = { enabled: false };
  const results = await axe.run(target as axe.ElementContext, { rules });
  if (results.violations.length > 0) {
    const summary = results.violations
      .map(
        (violation) =>
          `${violation.id}: ${violation.help} -> ${violation.nodes
            .map((node) => node.target.join(' '))
            .join(', ')}`,
      )
      .join('\n');
    throw new Error(`Expected no accessibility violations, found:\n${summary}`);
  }
}

/**
 * Test scaffolding: a fake daemon, and the cockpit rendered against it.
 *
 * The fixtures under `fixtures/` are real responses, exported from a real workspace by
 * `uv run python web/scripts/export_backend_json.py`. A test that hand-wrote its payloads
 * would pass against an API that no longer exists.
 */
import type { ReactElement } from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
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

function isEnvelope(value: unknown): boolean {
  return typeof value === 'object' && value !== null && 'ok' in (value as object);
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

/** Render one view inside the session and the router, against a fake daemon. */
export function renderView(ui: ReactElement, options: RenderOptions) {
  const client = new HarnessClient({
    baseUrl: 'http://daemon.test',
    token: options.token ?? 'local-token',
    fetchImpl: options.daemon.fetch,
  });
  const route = options.route ?? '/';
  const path = options.path ?? route;
  return render(
    <MemoryRouter
      initialEntries={[route]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <SessionProvider client={client}>
        <Routes>
          <Route path={path} element={ui} />
        </Routes>
      </SessionProvider>
    </MemoryRouter>,
  );
}

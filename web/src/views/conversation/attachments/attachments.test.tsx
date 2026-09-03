/**
 * Attachments in the conversation workspace, against a fake daemon.
 *
 * Each `describe` is one of the acceptance scenarios of the attachments design §9, driven
 * the way a researcher drives it: through the real route table, the real shell and the real
 * client. The only fakes are `fetch` — which here also answers the byte intake route and
 * the two byte reads — and pdf.js, because jsdom has no PDF engine and no canvas.
 *
 * Two things these tests are strict about, because they are the design's own promises.
 * Attaching a file writes session-only bytes and **calls no corpus capability**: the
 * `attachment.*` calls a test makes are asserted, in order, against what actually happened.
 * And nothing a researcher typed or attached is ever collateral damage: a blocked send, a
 * refused upload and a failed promotion each leave the draft and the other files exactly
 * where they were.
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@research-harness/design';
import { HarnessClient } from '../../../api/client';
import { SessionProvider } from '../../../app/session';
import { AppRoutes } from '../../../app/routes';
import { FIXTURES, expectNoAxeViolations, fakeDaemon } from '../../../test/harness';
import type { FakeDaemon } from '../../../test/harness';
import contextPack from '../../../test/fixtures/conversation/context-pack.json';
import sendStarted from '../../../test/fixtures/conversation/send-started.json';
import sessions from '../../../test/fixtures/conversation/sessions.json';
import transcript from '../../../test/fixtures/conversation/transcript.json';
import attachmentTranscript from '../../../test/fixtures/conversation/transcript-attachment.json';
import providers from '../../../test/fixtures/attachments/providers.json';
import imageReady from '../../../test/fixtures/attachments/image-ready.json';
import pdfReady from '../../../test/fixtures/attachments/pdf-ready.json';
import notesReady from '../../../test/fixtures/attachments/notes-ready.json';
import checkOk from '../../../test/fixtures/attachments/check-ok.json';
import checkBlocked from '../../../test/fixtures/attachments/check-blocked.json';
import identityExistingWork from '../../../test/fixtures/attachments/identity-existing-work.json';
import identityDuplicate from '../../../test/fixtures/attachments/identity-duplicate.json';
import promotionVersion from '../../../test/fixtures/attachments/promotion-version.json';
import promotionDuplicate from '../../../test/fixtures/attachments/promotion-duplicate.json';

/* -- pdf.js, scripted -------------------------------------------------------
 *
 * The page viewer is W0's `usePdfDocument` + `PdfPage`, and what matters here is that a
 * page of the *attachment's own bytes* reaches it. The engine itself is mocked exactly as
 * `src/pdf/pdf.test.tsx` mocks it. */

const engine = vi.hoisted(() => ({ documentParams: [] as Record<string, unknown>[] }));

vi.mock('pdfjs-dist', () => {
  const viewport = {
    scale: 1,
    width: 612,
    height: 792,
    convertToPdfPoint: (x: number, y: number) => [x, 792 - y],
    convertToViewportRectangle: (rect: number[]) => rect,
  };
  return {
    GlobalWorkerOptions: { workerSrc: '' },
    getDocument(params: Record<string, unknown>) {
      engine.documentParams.push(params);
      return {
        promise: Promise.resolve({
          numPages: 14,
          getPage: () =>
            Promise.resolve({
              getViewport: () => viewport,
              render: () => ({ promise: Promise.resolve(), cancel: () => undefined }),
              getTextContent: () => Promise.resolve({ items: [], styles: {} }),
            }),
        }),
        destroy: () => Promise.resolve(),
      };
    },
    TextLayer: class {
      render() {
        return Promise.resolve();
      }
    },
  };
});

/* -- the fake daemon, with bytes ------------------------------------------ */

const SESSION = 'CS0001';
const ROUTE = `/?session=${SESSION}`;

/** What one upload answers with: a record, or an HTTP refusal of the request itself. */
type UploadAnswer = Record<string, unknown> | { status: number; detail: unknown };

interface AttachmentScript {
  /** Keyed by the `?filename=` the intake sends. */
  uploads?: Record<string, UploadAnswer>;
}

function isRefusal(answer: UploadAnswer): answer is { status: number; detail: unknown } {
  return 'status' in answer && typeof (answer as { status: unknown }).status === 'number';
}

/**
 * The fake daemon plus the three attachment routes and the run stream.
 *
 * They are layered here rather than added to the shared harness for the same reason
 * `withRun` is: the byte routes are not capabilities, and a scripted upload belongs to the
 * test that scripts it.
 */
function withAttachments(daemon: FakeDaemon, script: AttachmentScript = {}): FakeDaemon {
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(String(input), 'http://daemon.test');
    const method = init?.method ?? 'GET';

    if (method === 'POST' && /^\/sessions\/[^/]+\/attachments$/.test(url.pathname)) {
      const filename = url.searchParams.get('filename') ?? '';
      daemon.calls.push({ method, path: `${url.pathname}?filename=${filename}`, body: null });
      const answer = script.uploads?.[filename];
      if (answer === undefined) {
        return new Response(JSON.stringify({ detail: `no scripted upload for ${filename}` }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (isRefusal(answer)) {
        return new Response(JSON.stringify({ detail: answer.detail }), {
          status: answer.status,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify(answer), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    if (/\/attachments\/[^/]+\/(bytes|preview)$/.test(url.pathname)) {
      daemon.calls.push({ method, path: url.pathname, body: null });
      // Enough bytes to make an object URL out of; nothing reads them but pdf.js, mocked.
      return new Response(new Uint8Array([0x25, 0x50, 0x44, 0x46]), { status: 200 });
    }

    if (url.pathname.startsWith('/runs/') && url.pathname.endsWith('/events')) {
      daemon.calls.push({ method: 'GET', path: url.pathname, body: null });
      const frame =
        'event: status\ndata: ' +
        JSON.stringify({
          run_id: 'run_5f3c1a',
          state: 'succeeded',
          message_id: 'M0043',
          attempt: 1,
          context_pack_id: 'CP0008',
        }) +
        '\n\n';
      return new Response(frame, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      });
    }

    return daemon.fetch(input, init);
  };
  return { ...daemon, fetch: fetchImpl as unknown as typeof fetch };
}

interface Answers {
  [capability: string]: unknown;
}

/**
 * A send check, wrapped in its capability envelope.
 *
 * `AttachmentSendCheck` has an `ok` field of its own — "may the send proceed" — and the
 * shared fake daemon reads a top-level `ok` as the *envelope's*. Wrapping it here keeps the
 * fixture in the daemon's exact response shape and still answers `ok: true` for the call.
 */
function check(result: unknown): unknown {
  return { capability: 'attachment.check_send', ok: true, result };
}

function answers(extra: Answers = {}): Answers {
  return {
    'session.list': sessions,
    'session.get': transcript,
    'session.search': { count: 0, matches: [] },
    'provider.list': providers,
    'context.get': contextPack,
    'context.preview': contextPack,
    'state.index': FIXTURES.index,
    'evidence.list': { count: 0, evidence: [] },
    'claim.list': { count: 0, claims: [] },
    'review.inbox': FIXTURES.reviewInbox,
    'state.stale': { count: 0, marks: [] },
    ...extra,
  };
}

function renderConversation(options: {
  daemon: FakeDaemon;
  token?: string | null;
  route?: string;
}) {
  const client = new HarnessClient({
    baseUrl: 'http://daemon.test',
    token: options.token === undefined ? 'local-token' : options.token,
    fetchImpl: options.daemon.fetch,
  });
  return render(
    <ThemeProvider defaultTheme="dark" storageKey={null}>
      <ToastProvider>
        <MemoryRouter
          initialEntries={[options.route ?? ROUTE]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <SessionProvider client={client}>
            <AppRoutes />
          </SessionProvider>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

async function workspaceReady(): Promise<HTMLElement> {
  return screen.findByRole('textbox', { name: 'Message' }, { timeout: 3000 });
}

/** The drop target the composer's tray lives in. */
function intake(): HTMLElement {
  const node = document.querySelector('.rh-web-attachments');
  if (!node) throw new Error('the attachment intake is not on screen');
  return node as HTMLElement;
}

function fileOf(name: string, type: string, size = 1024): File {
  const file = new File([new Uint8Array(8)], name, { type });
  // jsdom computes `size` from the blob parts; the tray shows the daemon's number anyway,
  // and a pending row should show something honest before the record arrives.
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

/** Drop files onto the composer's intake, the way a researcher does. */
async function drop(...files: File[]): Promise<void> {
  fireEvent.dragOver(intake(), { dataTransfer: { files, types: ['Files'] } });
  fireEvent.drop(intake(), { dataTransfer: { files, types: ['Files'] } });
  await waitFor(() => expect(screen.queryByText('Checking')).not.toBeInTheDocument());
}

const IMAGE = () => fileOf('figure-3-latency.png', 'image/png', 184320);
const PDF = () => fileOf('lee-2024-hydrogel-preprint.pdf', 'application/pdf', 3400000);

beforeAll(() => {
  // jsdom has no object URLs; the tray degrades to names and states without them, and
  // these tests are about the previews, so they are provided.
  if (typeof URL.createObjectURL !== 'function') {
    URL.createObjectURL = vi.fn(() => 'blob:attachment') as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  }
});

beforeEach(() => {
  window.localStorage.clear();
  engine.documentParams.length = 0;
});

/* -- §9.1 attach and preview, with no corpus mutation --------------------- */

describe('attaching an image and a PDF', () => {
  it('previews both and calls no corpus capability', async () => {
    const daemon = withAttachments(
      fakeDaemon({ capabilities: answers({ 'attachment.check_send': check(checkBlocked) }) }),
      {
        uploads: {
          'figure-3-latency.png': imageReady,
          'lee-2024-hydrogel-preprint.pdf': pdfReady,
        },
      },
    );
    renderConversation({ daemon });
    await workspaceReady();

    await drop(IMAGE(), PDF());

    // Both files are listed, by name, with the daemon's own state as a word.
    expect(await screen.findByText('figure-3-latency.png')).toBeInTheDocument();
    expect(screen.getByText('lee-2024-hydrogel-preprint.pdf')).toBeInTheDocument();
    expect(screen.getAllByText('Ready').length).toBeGreaterThan(0);
    // The PDF's facts, which is what a researcher checks before sending.
    expect(screen.getByText('14 pages')).toBeInTheDocument();
    // The image has a thumbnail, drawn from the daemon's own bytes.
    expect(screen.getByRole('button', { name: 'Open figure-3-latency.png' })).toBeInTheDocument();

    // The bytes went through the one documented non-capability write, once per file.
    const uploads = daemon.calls.filter((call) => call.path.includes('/attachments?filename='));
    expect(uploads).toHaveLength(2);

    // Nothing that could create corpus state was called.
    const called = daemon.capabilityCalls().map((call) => call.name);
    expect(called).not.toContain('attachment.save_to_corpus');
    expect(called).not.toContain('attachment.resolve_identity');
    expect(called).not.toContain('ingest.local');
  });

  it('opens the PDF page viewer over the attachment bytes, and says a preview is not ingestion', async () => {
    const daemon = withAttachments(
      fakeDaemon({ capabilities: answers({ 'attachment.check_send': check(checkOk) }) }),
      { uploads: { 'lee-2024-hydrogel-preprint.pdf': pdfReady } },
    );
    const user = userEvent.setup();
    renderConversation({ daemon });
    await workspaceReady();
    await drop(PDF());

    await user.click(
      await screen.findByRole('button', { name: 'Preview lee-2024-hydrogel-preprint.pdf' }),
    );
    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).getByText(/does not add it to the corpus and does not create evidence/),
    ).toBeInTheDocument();

    // The page came from the attachment's own bytes, not from a server-rendered picture.
    await waitFor(() => expect(engine.documentParams.length).toBeGreaterThan(0));
    expect(engine.documentParams[0]).toHaveProperty('data');
    expect(await within(dialog).findByRole('img', { name: 'page 1' })).toBeInTheDocument();
    expect(within(dialog).getByText('Page 1 of 14')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Next page' }));
    expect(within(dialog).getByText('Page 2 of 14')).toBeInTheDocument();
  });

  it('keeps an unsupported file visible, with the model that would take it', async () => {
    const daemon = withAttachments(
      fakeDaemon({ capabilities: answers({ 'attachment.check_send': check(checkBlocked) }) }),
      { uploads: { 'figure-3-latency.png': imageReady } },
    );
    renderConversation({ daemon });
    await workspaceReady();
    await drop(IMAGE());

    // The row itself carries the reason and the suggestion, so the researcher never has to
    // find the composer's notice to learn which file is the problem.
    const row = within(intake());
    expect(await row.findByText('figure-3-latency.png')).toBeInTheDocument();
    expect(row.getByText(/local-small\/text-1 does not accept image\/png/)).toBeInTheDocument();
    expect(row.getByText(/Try vendor-vision\/vision-1\./)).toBeInTheDocument();
    // Visible, not dropped: the file is still there, still ready, still removable.
    expect(row.getByText('Ready')).toBeInTheDocument();
  });

  it('removes one file without touching the draft or the others', async () => {
    const daemon = withAttachments(
      fakeDaemon({
        capabilities: answers({
          'attachment.check_send': check(checkOk),
          'attachment.remove': { session: SESSION, attachment: 'SA0001', removed: true },
        }),
      }),
      {
        uploads: {
          'figure-3-latency.png': imageReady,
          'lee-2024-hydrogel-preprint.pdf': pdfReady,
        },
      },
    );
    const user = userEvent.setup();
    renderConversation({ daemon });
    const box = await workspaceReady();
    await user.type(box, 'Two files, one of them wrong.');
    await drop(IMAGE(), PDF());

    // The picker is offered to a researcher, beside the drop target.
    expect(screen.getByRole('button', { name: 'Attach files' })).toBeInTheDocument();

    await user.click(await screen.findByRole('button', { name: 'Remove figure-3-latency.png' }));
    await waitFor(() =>
      expect(screen.queryByText('figure-3-latency.png')).not.toBeInTheDocument(),
    );
    const removed = daemon.capabilityCalls().find((call) => call.name === 'attachment.remove');
    expect(removed?.request).toMatchObject({ session: SESSION, attachment: 'SA0001' });
    // The other file and the words survive it.
    expect(screen.getByText('lee-2024-hydrogel-preprint.pdf')).toBeInTheDocument();
    expect(box).toHaveValue('Two files, one of them wrong.');
  });

  it('keeps the other files when one upload is refused, and retries the one that failed', async () => {
    const uploads: Record<string, UploadAnswer> = {
      'figure-3-latency.png': imageReady,
      'sweep-notes.md': { status: 413, detail: 'attachment upload exceeds the 64-byte limit' },
      'lee-2024-hydrogel-preprint.pdf': pdfReady,
    };
    const daemon = withAttachments(
      fakeDaemon({ capabilities: answers({ 'attachment.check_send': check(checkOk) }) }),
      { uploads },
    );
    const user = userEvent.setup();
    renderConversation({ daemon });
    await workspaceReady();

    await drop(IMAGE(), fileOf('sweep-notes.md', 'text/markdown', 2048), PDF());

    // Two ready, one failed — and the failed one is still on screen with its reason.
    expect(await screen.findByText('figure-3-latency.png')).toBeInTheDocument();
    expect(screen.getByText('lee-2024-hydrogel-preprint.pdf')).toBeInTheDocument();
    expect(screen.getByText('sweep-notes.md')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(
      screen.getByText(/attachment upload exceeds the 64-byte limit/),
    ).toBeInTheDocument();

    // The bytes were never discarded, so the retry re-uploads exactly what was chosen.
    uploads['sweep-notes.md'] = notesReady;
    await user.click(screen.getByRole('button', { name: 'Retry sweep-notes.md' }));
    await waitFor(() => expect(screen.queryByText('Failed')).not.toBeInTheDocument());
    expect(within(intake()).getAllByText('Ready')).toHaveLength(3);
  });
});

/* -- §9.2 send with a compatible model ------------------------------------ */

describe('sending with a compatible model', () => {
  it('carries both attachment ids in `session.send`', async () => {
    const daemon = withAttachments(
      fakeDaemon({
        capabilities: answers({
          'attachment.check_send': check(checkOk),
          'session.send': sendStarted,
        }),
      }),
      {
        uploads: {
          'figure-3-latency.png': imageReady,
          'lee-2024-hydrogel-preprint.pdf': pdfReady,
        },
      },
    );
    const user = userEvent.setup();
    renderConversation({ daemon });
    const box = await workspaceReady();
    await drop(IMAGE(), PDF());

    await user.type(box, 'Read the sweep in these two.');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => {
      const send = daemon.capabilityCalls().find((call) => call.name === 'session.send');
      expect(send?.request.attachments).toEqual(['SA0001', 'SA0002']);
    });

    // The check ran against the selected model before the message was written.
    const checks = daemon.capabilityCalls().filter((call) => call.name === 'attachment.check_send');
    expect(checks.length).toBeGreaterThan(0);
    expect(checks[checks.length - 1]?.request.attachments).toEqual(['SA0001', 'SA0002']);
  });

  it('lists sent, converted and omitted attachments in `Context used`', async () => {
    const withAttachmentLines = {
      ...contextPack,
      pack: {
        ...contextPack.pack,
        receipt: {
          included: [
            ...contextPack.pack.receipt.included,
            {
              context_class: 'attachments',
              source: 'rh://attachment/SA0001',
              id: 'SA0001',
              authority: 'private',
              label: 'figure-3-latency.png (image/png, 184320 bytes) — sent',
              tokens: 0,
            },
          ],
          omitted: [
            ...contextPack.pack.receipt.omitted,
            {
              context_class: 'attachments',
              source: 'rh://attachment/SA0002',
              id: 'SA0002',
              authority: 'private',
              label: 'lee-2024-hydrogel-preprint.pdf (application/pdf, 3400000 bytes, 14 pages) — omitted',
              tokens: 0,
              reason: 'unsupported_media',
              detail: 'local-small/text-1 does not accept application/pdf; vendor-vision/vision-1 would accept it',
            },
          ],
        },
      },
    };
    const daemon = withAttachments(
      fakeDaemon({
        capabilities: answers({
          'context.get': withAttachmentLines,
          'attachment.check_send': check(checkOk),
        }),
      }),
    );
    const user = userEvent.setup();
    renderConversation({ daemon });
    await screen.findByText(/records the accepted claim/, undefined, { timeout: 3000 });

    await user.click(await screen.findByRole('button', { name: /Context used/ }));

    expect(
      await screen.findByText(/figure-3-latency\.png \(image\/png, 184320 bytes\) — sent/),
    ).toBeInTheDocument();
    expect(screen.getByText(/14 pages\) — omitted/)).toBeInTheDocument();
    expect(
      screen.getByText(/vendor-vision\/vision-1 would accept it/),
    ).toBeInTheDocument();
  });
});

/* -- §9.3 an incompatible model blocks the send --------------------------- */

describe('choosing an incompatible model', () => {
  it('blocks Send with a reason per item and a suggestion, and touches nothing', async () => {
    const daemon = withAttachments(
      fakeDaemon({
        capabilities: answers({
          'attachment.check_send': check(checkBlocked),
          'session.send': sendStarted,
        }),
      }),
      {
        uploads: {
          'figure-3-latency.png': imageReady,
          'lee-2024-hydrogel-preprint.pdf': pdfReady,
        },
      },
    );
    const user = userEvent.setup();
    renderConversation({ daemon });
    const box = await workspaceReady();

    await user.type(box, 'Does the sweep hold?');
    await drop(IMAGE(), PDF());

    // Every blocked item, named, with the model the daemon suggests instead.
    expect(await screen.findByText(/This message cannot be sent yet/)).toBeInTheDocument();
    expect(
      screen.getByText(/figure-3-latency\.png: local-small\/text-1 does not accept image\/png/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /lee-2024-hydrogel-preprint\.pdf: local-small\/text-1 does not accept application\/pdf/,
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Try vendor-vision\/vision-1\./).length).toBeGreaterThan(0);

    // Send is disabled, and nothing was written.
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(daemon.capabilityCalls().some((call) => call.name === 'session.send')).toBe(false);

    // The draft and both attachments are exactly as they were.
    expect(box).toHaveValue('Does the sweep hold?');
    expect(screen.getByText('figure-3-latency.png')).toBeInTheDocument();
    expect(screen.getByText('lee-2024-hydrogel-preprint.pdf')).toBeInTheDocument();
    expect(within(intake()).getAllByText('Ready')).toHaveLength(2);
  });

  it('re-asks the daemon when the model changes, and lets the send through', async () => {
    const capabilities = answers({
      'attachment.check_send': check(checkBlocked),
      'session.send': sendStarted,
    });
    const daemon = withAttachments(fakeDaemon({ capabilities }), {
      uploads: { 'figure-3-latency.png': imageReady },
    });
    const user = userEvent.setup();
    renderConversation({ daemon });
    const box = await workspaceReady();
    await user.type(box, 'What is in this figure?');
    await drop(IMAGE());
    await screen.findByText(/This message cannot be sent yet/);

    // A model that takes images. The check is asked again, naming the chosen entry.
    capabilities['attachment.check_send'] = check(checkOk);
    await user.click(screen.getByRole('button', { name: /^Model:/ }));
    await user.click(await screen.findByRole('menuitem', { name: /vendor-vision/ }));

    await waitFor(() =>
      expect(screen.queryByText(/This message cannot be sent yet/)).not.toBeInTheDocument(),
    );
    const asked = daemon
      .capabilityCalls()
      .filter((call) => call.name === 'attachment.check_send')
      .pop();
    expect(asked?.request.provider).toBe('vendor-vision');

    await user.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => {
      const send = daemon.capabilityCalls().find((call) => call.name === 'session.send');
      expect(send?.request.attachments).toEqual(['SA0001']);
      expect(send?.request.model).toBe('vendor-vision');
    });
  });
});

/* -- §9.4–9.7 Save to corpus ---------------------------------------------- */

describe('saving a PDF to the corpus', () => {
  function savingDaemon(extra: Answers = {}, script: AttachmentScript = {}) {
    return withAttachments(
      fakeDaemon({
        capabilities: answers({
          'session.get': attachmentTranscript,
          'attachment.check_send': check(checkOk),
          ...extra,
        }),
      }),
      script,
    );
  }

  async function openTheSaveDialog(user: ReturnType<typeof userEvent.setup>) {
    const buttons = await screen.findAllByRole('button', { name: /Save .* to corpus/ });
    await user.click(buttons[0] as HTMLElement);
    return screen.findByRole('dialog', { name: /Save .* to the corpus/ });
  }

  it('resolves identity, waits for a confirmation, then links a new Version and Artifact', async () => {
    const daemon = savingDaemon({
      'attachment.resolve_identity': identityExistingWork,
      'attachment.save_to_corpus': promotionVersion,
    });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await screen.findByText('lee-2024-hydrogel-preprint.pdf');

    const dialog = await openTheSaveDialog(user);
    // Resolution is a read, and nothing has been saved by opening the dialog.
    expect(
      daemon.capabilityCalls().some((call) => call.name === 'attachment.resolve_identity'),
    ).toBe(true);
    expect(
      daemon.capabilityCalls().some((call) => call.name === 'attachment.save_to_corpus'),
    ).toBe(false);

    // Nothing is preselected: the researcher chooses.
    const confirm = within(dialog).getByRole('button', { name: 'Confirm and save' });
    expect(confirm).toBeDisabled();
    await user.click(within(dialog).getByRole('radio', { name: /Hydrogel swelling/ }));
    await user.click(confirm);

    await waitFor(() => {
      const save = daemon.capabilityCalls().find((call) => call.name === 'attachment.save_to_corpus');
      expect(save?.request).toMatchObject({ session: SESSION, attachment: 'SA0003' });
    });
    expect((await screen.findAllByText('In corpus')).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Registered as a new version V0007-2 of W0007, artifact A0007-3/),
    ).toBeInTheDocument();
  });

  it('says that no evidence was created', async () => {
    const daemon = savingDaemon({
      'attachment.resolve_identity': identityExistingWork,
      'attachment.save_to_corpus': promotionVersion,
    });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await screen.findByText('lee-2024-hydrogel-preprint.pdf');

    const dialog = await openTheSaveDialog(user);
    await user.click(within(dialog).getByRole('radio', { name: /Hydrogel swelling/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Confirm and save' }));

    expect(
      await screen.findByText(
        /No evidence was created: extraction still goes through candidate, verification and review/,
      ),
    ).toBeInTheDocument();
  });

  it('resolves the same bytes to the existing Artifact instead of duplicating it', async () => {
    const daemon = savingDaemon({
      'attachment.resolve_identity': identityDuplicate,
      'attachment.save_to_corpus': promotionDuplicate,
    });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await screen.findByText('lee-2024-hydrogel-preprint.pdf');

    const dialog = await openTheSaveDialog(user);
    // The duplicate is offered as what it is, and named.
    expect(within(dialog).getByText('Existing artifact')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('radio', { name: /already/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Confirm and save' }));

    expect(
      await screen.findByText(
        /These exact bytes were already in the corpus, so the existing artifact A0007-3 was linked and nothing was copied/,
      ),
    ).toBeInTheDocument();
  });

  it('keeps the session copy usable when the promotion fails, and the retry succeeds', async () => {
    const capabilities = answers({
      'session.get': attachmentTranscript,
      'attachment.check_send': check(checkOk),
      'attachment.resolve_identity': identityExistingWork,
      'attachment.save_to_corpus': {
        capability: 'attachment.save_to_corpus',
        ok: false,
        error: {
          code: 'capability_error',
          message: 'save to corpus failed: the corpus index is locked by another process',
        },
      },
    });
    const daemon = withAttachments(fakeDaemon({ capabilities }));
    const user = userEvent.setup();
    renderConversation({ daemon });
    await screen.findByText('lee-2024-hydrogel-preprint.pdf');

    const dialog = await openTheSaveDialog(user);
    await user.click(within(dialog).getByRole('radio', { name: /Hydrogel swelling/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Confirm and save' }));

    // The daemon's own words, and the promise that the file survived them.
    expect(
      await screen.findByText(/the corpus index is locked by another process/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/The session copy of lee-2024-hydrogel-preprint\.pdf is unchanged/),
    ).toBeInTheDocument();
    // Still listed, still previewable.
    expect(screen.getByText('lee-2024-hydrogel-preprint.pdf')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Preview lee-2024-hydrogel-preprint.pdf' }),
    ).toBeInTheDocument();

    // The retry is the same save again, not a re-attach.
    capabilities['attachment.save_to_corpus'] = promotionVersion;
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect((await screen.findAllByText('In corpus')).length).toBeGreaterThan(0);
    const saves = daemon
      .capabilityCalls()
      .filter((call) => call.name === 'attachment.save_to_corpus');
    expect(saves).toHaveLength(2);
    expect(saves[1]?.request).toMatchObject({ attachment: 'SA0003' });
  });
});

/* -- PRODUCT §29: an agent host may read and not attach -------------------- */

describe('an agent host', () => {
  const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };

  it('sees the intake closed with the daemon’s reason, and no attach control', async () => {
    const daemon = withAttachments(
      fakeDaemon({ gets: { '/overview': asHost }, capabilities: answers() }),
    );
    renderConversation({ daemon, token: null });
    await workspaceReady();

    expect(await screen.findByText(/Files cannot be attached from this window/)).toBeInTheDocument();
    expect(screen.getByText(/it may read and propose/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Attach files' })).not.toBeInTheDocument();

    // A drop is not a way around the refusal.
    fireEvent.drop(intake(), { dataTransfer: { files: [IMAGE()], types: ['Files'] } });
    await waitFor(() =>
      expect(daemon.calls.some((call) => call.path.includes('/attachments?'))).toBe(false),
    );
  });
});

/* -- accessibility -------------------------------------------------------- */

describe('accessibility', () => {
  it('has no automatically detectable violation in the tray or the save dialog', async () => {
    const daemon = withAttachments(
      fakeDaemon({
        capabilities: answers({
          'session.get': attachmentTranscript,
          'attachment.check_send': check(checkBlocked),
          'attachment.resolve_identity': identityExistingWork,
        }),
      }),
      { uploads: { 'figure-3-latency.png': imageReady } },
    );
    const user = userEvent.setup();
    renderConversation({ daemon });
    await workspaceReady();
    await drop(IMAGE());
    await screen.findByText('figure-3-latency.png');
    await expectNoAxeViolations(document.body);

    const buttons = await screen.findAllByRole('button', { name: /Save .* to corpus/ });
    await user.click(buttons[0] as HTMLElement);
    await screen.findByRole('dialog', { name: /Save .* to the corpus/ });
    await expectNoAxeViolations(document.body);
  });

  it('opens the image viewer and moves through it from the keyboard', async () => {
    const daemon = withAttachments(
      fakeDaemon({ capabilities: answers({ 'attachment.check_send': check(checkOk) }) }),
      { uploads: { 'figure-3-latency.png': imageReady } },
    );
    const user = userEvent.setup();
    renderConversation({ daemon });
    await workspaceReady();
    await drop(IMAGE());

    const thumb = await screen.findByRole('button', { name: 'Open figure-3-latency.png' });
    thumb.focus();
    await user.keyboard('{Enter}');
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/figure-3-latency\.png · 100%/)).toBeInTheDocument();

    await user.keyboard('{+}');
    expect(within(dialog).getByText(/125%/)).toBeInTheDocument();
    await user.keyboard('0');
    expect(within(dialog).getByText(/100%/)).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: /Download original/ })).toBeInTheDocument();
  });
});

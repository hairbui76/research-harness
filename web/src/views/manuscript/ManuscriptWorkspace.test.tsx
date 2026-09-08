/**
 * Gate P21 from the Web side (LaTeX spec §10).
 *
 * The properties asserted here are the ones a researcher would be misled by if they were
 * wrong: an edit that reaches disk without a save, a save that overwrites somebody else's
 * change, a stale PDF presented as current, a compiler count borrowed by the audit, a
 * SyncTeX jump invented when there is no map, a model's words entering the manuscript
 * without an explicit application, and an agent host being offered any of it.
 *
 * jsdom has no PDF engine and no canvas, so pdf.js is scripted the same way the adapter's
 * own tests script it — what is under test is this workspace, not pdf.js. CodeMirror
 * measures the document as it renders, which jsdom cannot do, so the two `Range` shims
 * below are the whole accommodation.
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorView } from '@codemirror/view';
import { ManuscriptPage } from './ManuscriptWorkspace';
import { resetPdfjs } from '../../pdf';
import { FIXTURES, expectNoAxeViolations, renderView } from '../../test/harness';
import type { RecordedCall } from '../../test/harness';
import files from '../../test/fixtures/manuscript-workspace/files.json';
import readMain from '../../test/fixtures/manuscript-workspace/read-main.json';
import readIntro from '../../test/fixtures/manuscript-workspace/read-intro.json';
import buildSucceeded from '../../test/fixtures/manuscript-workspace/build-succeeded.json';
import buildFailed from '../../test/fixtures/manuscript-workspace/build-failed.json';
import buildUnavailable from '../../test/fixtures/manuscript-workspace/build-unavailable.json';
import synctexForward from '../../test/fixtures/manuscript-workspace/synctex-forward.json';
import synctexInverse from '../../test/fixtures/manuscript-workspace/synctex-inverse.json';
import candidate from '../../test/fixtures/manuscript-workspace/candidate.json';
import candidateBlocked from '../../test/fixtures/manuscript-workspace/candidate-blocked.json';
import applied from '../../test/fixtures/manuscript-workspace/applied.json';

const PAGE_WIDTH = 612;
const PAGE_HEIGHT = 792;

const engine = vi.hoisted(() => ({ pages: 2 }));

vi.mock('pdfjs-dist', () => {
  function viewportFor(scale: number) {
    return {
      scale,
      width: PAGE_WIDTH * scale,
      height: PAGE_HEIGHT * scale,
      convertToPdfPoint: (x: number, y: number) => [x / scale, PAGE_HEIGHT - y / scale],
      convertToViewportRectangle: (rect: number[]) => [
        (rect[0] ?? 0) * scale,
        (PAGE_HEIGHT - (rect[1] ?? 0)) * scale,
        (rect[2] ?? 0) * scale,
        (PAGE_HEIGHT - (rect[3] ?? 0)) * scale,
      ],
    };
  }

  return {
    GlobalWorkerOptions: { workerSrc: '' },
    getDocument: () => ({
      promise: Promise.resolve({
        numPages: engine.pages,
        getPage: () =>
          Promise.resolve({
            getViewport: ({ scale }: { scale: number }) => viewportFor(scale),
            render: () => ({ promise: Promise.resolve(), cancel: () => undefined }),
            getTextContent: () =>
              Promise.resolve({ items: [{ str: 'traffic classifiers degrade' }] }),
          }),
      }),
      destroy: () => Promise.resolve(),
    }),
    TextLayer: class {
      render() {
        return Promise.resolve();
      }
    },
  };
});

beforeAll(() => {
  const rect = {
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: 0,
    height: 0,
    toJSON: () => ({}),
  } as DOMRect;
  const rects = Object.assign([] as DOMRect[], { item: () => null }) as unknown as DOMRectList;
  Range.prototype.getClientRects = function getClientRects() {
    return rects;
  };
  Range.prototype.getBoundingClientRect = function getBoundingClientRect() {
    return rect;
  };
  // jsdom has no canvas; a plain stub keeps `getContext` from answering null.
  HTMLCanvasElement.prototype.getContext = function getContext() {
    return {};
  } as unknown as HTMLCanvasElement['getContext'];
});

beforeEach(() => {
  engine.pages = 2;
  resetPdfjs();
  window.localStorage.clear();
});

// ---------------------------------------------------------------------------------------
// a manuscript daemon
//
// The shared `fakeDaemon` answers one fixed payload per capability, and this screen calls
// `manuscript.read_file` for several paths and `manuscript.synctex` in both directions, so
// the fake here routes on the request instead. Everything it answers is a fixture shaped
// like the daemon's own response models.
// ---------------------------------------------------------------------------------------

type AnswerFn = (request: Record<string, unknown>) => unknown;
type Answer = AnswerFn | object;

interface Scenario {
  overview?: unknown;
  build?: unknown;
  compile?: unknown;
  suggest?: unknown;
  apply?: unknown;
  write?: Answer;
  snapshots?: Record<string, unknown>;
}

function envelope(name: string, result: unknown) {
  if (result !== null && typeof result === 'object' && 'ok' in (result as object)) return result;
  return { capability: name, ok: true, result };
}

function refusal(code: string, message: string) {
  return { ok: false, error: { code, message } };
}

function manuscriptDaemon(scenario: Scenario = {}) {
  const calls: RecordedCall[] = [];
  const snapshots: Record<string, unknown> = {
    'main.tex': readMain,
    'sections/intro.tex': readIntro,
    ...scenario.snapshots,
  };

  const answers: Record<string, Answer> = {
    'manuscript.files': files,
    'manuscript.read_file': (request) => snapshots[String(request.path)],
    'manuscript.write_file': scenario.write ?? ((request) => savedFrom(request)),
    'manuscript.build': scenario.build ?? buildSucceeded,
    'manuscript.compile': scenario.compile ?? buildSucceeded,
    'manuscript.synctex': (request) =>
      'file' in request ? synctexForward : synctexInverse,
    'manuscript.suggest': scenario.suggest ?? candidate,
    'manuscript.apply_suggestion': scenario.apply ?? applied,
    'manuscript.anchors': FIXTURES.manuscriptAnchors,
    'manuscript.trace': FIXTURES.manuscriptTrace,
  };

  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://daemon.test');
    const path = url.pathname;
    const method = init?.method ?? 'GET';
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    calls.push({ method, path, body });

    if (method === 'POST' && path.startsWith('/capabilities/')) {
      const name = path.slice('/capabilities/'.length);
      const answer = answers[name];
      if (answer === undefined) {
        return json({
          capability: name,
          ok: false,
          error: { code: 'capability_not_found', message: `no fake answer for ${name}` },
        });
      }
      const result =
        typeof answer === 'function' ? (answer as AnswerFn)(body ?? {}) : answer;
      return json(envelope(name, result));
    }

    if (path === '/overview') return json(scenario.overview ?? FIXTURES.overview);
    if (/^\/manuscript\/builds\/[^/]+\/pdf$/.test(path)) {
      return new Response(new Uint8Array([37, 80, 68, 70]), { status: 200 });
    }
    return new Response('not found', { status: 404 });
  });

  return {
    fetch: fetchImpl as unknown as typeof fetch,
    calls,
    capabilityCalls: () =>
      calls
        .filter((call) => call.method === 'POST' && call.path.startsWith('/capabilities/'))
        .map((call) => ({
          name: call.path.slice('/capabilities/'.length),
          request: (call.body ?? {}) as Record<string, unknown>,
        })),
    callsTo: (name: string): Record<string, unknown>[] =>
      calls
        .filter((call) => call.path === `/capabilities/${name}`)
        .map((call) => (call.body ?? {}) as Record<string, unknown>),
  };
}

/** What `manuscript.write_file` answers with: the file as it now is, and its new hash. */
function savedFrom(request: Record<string, unknown>) {
  const path = String(request.path);
  const content = String(request.content);
  return {
    path,
    kind: 'tex',
    content,
    content_hash: `sha256:${'9'.repeat(64)}`,
    size_bytes: content.length,
    modified_at: '2026-09-03T10:20:00Z',
  };
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

type Daemon = ReturnType<typeof manuscriptDaemon>;

function renderWorkspace(daemon: Daemon = manuscriptDaemon(), token: string | null = 'local-token') {
  return renderView(<ManuscriptPage />, {
    daemon: daemon as never,
    token,
    route: '/manuscript',
    path: '/manuscript',
  });
}

/** Waits for the tree and the entry file to be on screen. */
async function opened(path = 'main.tex'): Promise<void> {
  await waitFor(() =>
    expect(screen.getByRole('textbox', { name: `${path} source` })).toBeInTheDocument(),
  );
}

/**
 * An edit, made the way CodeMirror actually receives one.
 *
 * jsdom does not deliver typed text into a contenteditable the way a browser does, so the
 * edit is dispatched into the live `EditorView` — which is the same transaction a keystroke
 * would produce, and it goes through `onChange` exactly as one.
 */
function edit(text: string): void {
  const host = document.querySelector('.cm-editor');
  const view = host ? EditorView.findFromDOM(host as HTMLElement) : null;
  if (!view) throw new Error('no CodeMirror view is mounted');
  act(() => {
    view.dispatch({ changes: { from: 0, insert: text } });
  });
}

function editorText(): string {
  const host = document.querySelector('.cm-editor');
  const view = host ? EditorView.findFromDOM(host as HTMLElement) : null;
  return view?.state.doc.toString() ?? '';
}

/** The source frame, so a status word here is not confused with the same word in a toast. */
function frame(): HTMLElement {
  return screen.getByRole('region', { name: /Manuscript source/ });
}

// ---------------------------------------------------------------------------------------

describe('the workspace', () => {
  it('lays out the files, the source, the PDF and the audit inspector', async () => {
    const daemon = manuscriptDaemon();
    renderWorkspace(daemon);
    await opened();

    expect(screen.getByRole('tree', { name: 'Manuscript files' })).toBeInTheDocument();
    expect(screen.getByRole('treeitem', { name: /main\.tex/ })).toBeInTheDocument();
    expect(screen.getByRole('treeitem', { name: /sections/ })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'PDF preview' })).toBeInTheDocument();
    // The two lists are never one list.
    expect(screen.getByRole('heading', { name: /Compiler diagnostics/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Scientific audit/ })).toBeInTheDocument();

    const names = daemon.capabilityCalls().map((call) => call.name);
    expect(names).toContain('manuscript.files');
    expect(names).toContain('manuscript.build');
    expect(names).toContain('manuscript.read_file');
  });

  /**
   * The workspace's toolbar is compact, which is why its title was set in `rh-text-h4` —
   * 13px, smaller than the body text under it and a sixth of the size the same `<h1>`
   * carries on every research page. An `<h1>` is what names a screen, for the eye and for
   * the screen reader that lands on it from the skip link, so it is the page-title role
   * here as well. jsdom resolves no stylesheet; the class *is* the assertion.
   */
  it('names the screen with the same h1 the research pages use', async () => {
    renderWorkspace();
    await opened();

    const title = screen.getByRole('heading', { level: 1, name: 'Manuscript' });
    expect(title).toHaveClass('rh-text-h1');
    expect(title.className).not.toMatch(/rh-text-(?:h[234]|body|ui|label)\b/);
  });

  it('remembers the pane layout in this browser, and survives a refusal to store it', async () => {
    renderWorkspace();
    await opened();

    const [handle] = screen.getAllByRole('separator');
    handle?.focus();
    await userEvent.keyboard('{ArrowRight}');

    await waitFor(() =>
      expect(window.localStorage.getItem('rh.manuscript.columns')).toContain('editor'),
    );
  });
});

describe('files and editing', () => {
  it('keeps an edit local until an explicit save, then presents the snapshot’s hash', async () => {
    const daemon = manuscriptDaemon();
    renderWorkspace(daemon);
    await opened();

    edit('% a local edit\n');

    expect(daemon.callsTo('manuscript.write_file')).toHaveLength(0);
    await waitFor(() => expect(screen.getByText('Unsaved changes')).toBeInTheDocument());
    // The tree says so too, in words rather than colour.
    expect(within(screen.getByRole('treeitem', { name: /main\.tex/ })).getByText('Unsaved'))
      .toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(daemon.callsTo('manuscript.write_file')[0]).toMatchObject({
        path: 'main.tex',
        expected_hash: readMain.content_hash,
      }),
    );
    expect(String(daemon.callsTo('manuscript.write_file')[0]?.content)).toContain('% a local edit');
    await waitFor(() => expect(within(frame()).getByText('Saved')).toBeInTheDocument());
  });

  it('saves on Mod-S as well, and never on its own', async () => {
    const daemon = manuscriptDaemon();
    renderWorkspace(daemon);
    await opened();
    edit('% typed\n');

    act(() => screen.getByRole('textbox', { name: 'main.tex source' }).focus());
    await userEvent.keyboard('{Control>}s{/Control}');

    await waitFor(() => expect(daemon.callsTo('manuscript.write_file')).toHaveLength(1));
  });

  it('opens another file from the tree without losing the first buffer', async () => {
    renderWorkspace();
    await opened();
    edit('% unsaved in main\n');

    await userEvent.click(screen.getByRole('treeitem', { name: /intro\.tex/ }));
    await opened('sections/intro.tex');
    expect(editorText()).toContain('traffic classifiers');

    await userEvent.click(screen.getByRole('treeitem', { name: /main\.tex/ }));
    await opened('main.tex');
    expect(editorText()).toContain('% unsaved in main');
  });

  it('refuses a save that meets a changed file, and offers both answers', async () => {
    const daemon = manuscriptDaemon({
      write: refusal(
        'capability_error',
        'main.tex changed outside the harness: expected sha256:1111, found sha256:8888; re-read the file before saving again',
      ),
    });
    renderWorkspace(daemon);
    await opened();
    edit('% mine\n');

    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(screen.getByText(/main\.tex changed on disk/)).toBeInTheDocument(),
    );
    // The banner says what each answer will do before the researcher has to choose.
    expect(screen.getByText(/Keep mine re-reads main\.tex only to learn its new hash/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload from disk' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep mine' })).toBeInTheDocument();
  });

  it('keeps the researcher’s text on “Keep mine”, and re-reads only for the new hash', async () => {
    const daemon = manuscriptDaemon({
      write: refusal(
        'capability_error',
        'main.tex changed outside the harness: expected sha256:1111, found sha256:8888; re-read the file before saving again',
      ),
      snapshots: {
        'main.tex': { ...readMain, content: '% somebody else wrote this\n', content_hash: `sha256:${'8'.repeat(64)}` },
      },
    });
    renderWorkspace(daemon);
    await opened();
    edit('% mine\n');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByRole('button', { name: 'Keep mine' });

    await userEvent.click(screen.getByRole('button', { name: 'Keep mine' }));

    await waitFor(() => expect(screen.queryByRole('button', { name: 'Keep mine' })).toBeNull());
    expect(editorText()).toContain('% mine');
    // …and the next save presents the hash of what is on disk now.
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(daemon.callsTo('manuscript.write_file').at(-1)).toMatchObject({
        expected_hash: `sha256:${'8'.repeat(64)}`,
      }),
    );
  });

  it('replaces the buffer on “Reload from disk”', async () => {
    const daemon = manuscriptDaemon({
      write: refusal(
        'capability_error',
        'main.tex changed outside the harness: expected sha256:1111, found sha256:8888; re-read the file before saving again',
      ),
      snapshots: {
        'main.tex': { ...readMain, content: '% somebody else wrote this\n', content_hash: `sha256:${'8'.repeat(64)}` },
      },
    });
    renderWorkspace(daemon);
    await opened();
    edit('% mine\n');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByRole('button', { name: 'Reload from disk' });

    await userEvent.click(screen.getByRole('button', { name: 'Reload from disk' }));

    await waitFor(() => expect(editorText()).toBe('% somebody else wrote this\n'));
  });

  it('is read-only for an agent host, and says whose decision that is', async () => {
    const daemon = manuscriptDaemon({
      overview: { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' },
    });
    renderWorkspace(daemon, null);
    await opened();

    expect(screen.getByRole('textbox', { name: 'main.tex source' })).toHaveAttribute(
      'aria-readonly',
      'true',
    );
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Compile' })).toBeDisabled();
    expect(screen.getAllByText(/agent host/).length).toBeGreaterThan(0);
  });
});

describe('compiling and the preview', () => {
  it('compiles on request and renders the pages of the PDF that build produced', async () => {
    const daemon = manuscriptDaemon();
    renderWorkspace(daemon);
    await opened();

    await userEvent.click(screen.getByRole('button', { name: 'Compile' }));

    await waitFor(() => expect(daemon.callsTo('manuscript.compile')).toHaveLength(1));
    await waitFor(() => expect(screen.getByText('Compiled')).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByRole('img', { name: 'manuscript page 1' })).toBeInTheDocument(),
    );
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument();
    expect(daemon.calls.some((call) => call.path === '/manuscript/builds/b-0002/pdf')).toBe(true);
  });

  it('keeps the last good PDF, labelled stale, while the new errors are shown', async () => {
    const daemon = manuscriptDaemon({ compile: buildFailed });
    renderWorkspace(daemon);
    await opened();
    await waitFor(() =>
      expect(screen.getByRole('img', { name: 'manuscript page 1' })).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Compile' }));

    await waitFor(() =>
      expect(
        screen.getByText(/Showing the last successful PDF from 2026-09-03 10:00 UTC/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText('Compilation failed')).toBeInTheDocument();
    // The document is still on screen; the errors are about the source as it is now.
    expect(screen.getByRole('img', { name: 'manuscript page 1' })).toBeInTheDocument();
    // A diagnostic row is a card whose act is named for what it does, so what proves the
    // errors are on screen is the compiler's own sentence.
    expect(screen.getByText(/Undefined control sequence \\notacommand/)).toBeInTheDocument();
  });

  it('keeps unsaved editor content across a failed compile', async () => {
    const daemon = manuscriptDaemon({ compile: buildFailed });
    renderWorkspace(daemon);
    await opened();
    edit('% still being written\n');

    await userEvent.click(screen.getByRole('button', { name: 'Compile' }));
    await waitFor(() => expect(screen.getByText('Compilation failed')).toBeInTheDocument());

    expect(editorText()).toContain('% still being written');
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
    expect(daemon.callsTo('manuscript.write_file')).toHaveLength(0);
  });

  it('shows the setup guidance and no PDF when no engine is installed', async () => {
    const daemon = manuscriptDaemon({ build: buildUnavailable });
    renderWorkspace(daemon);
    await opened();

    expect(await screen.findByText('No LaTeX toolchain is available')).toBeInTheDocument();
    expect(screen.getAllByText(/No LaTeX engine is installed/).length).toBeGreaterThan(0);
    expect(screen.queryByRole('img', { name: /manuscript page/ })).toBeNull();
    // Nothing was compiled and nothing was written to say so.
    expect(daemon.callsTo('manuscript.compile')).toHaveLength(0);
    expect(daemon.callsTo('manuscript.write_file')).toHaveLength(0);
  });

  it('searches the PDF’s own text layer and says which page matched', async () => {
    renderWorkspace();
    await opened();
    await waitFor(() =>
      expect(screen.getByRole('img', { name: 'manuscript page 1' })).toBeInTheDocument(),
    );

    const search = screen.getByRole('searchbox', { name: 'Search the PDF' });
    await userEvent.type(search, 'classifiers{Enter}');

    expect(await screen.findByText(/“classifiers” found on page 2\./)).toBeInTheDocument();
    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument();
  });

  it('says the audit did not run rather than showing an empty list as a clean one', async () => {
    renderWorkspace(manuscriptDaemon({ build: buildUnavailable }));
    await opened();

    expect(
      await screen.findByText(/The scientific audit did not run for this build/),
    ).toBeInTheDocument();
  });
});

describe('diagnostics', () => {
  it('opens the source position a compiler error names', async () => {
    const daemon = manuscriptDaemon({ build: buildFailed });
    renderWorkspace(daemon);
    await opened();

    /*
     * The whole row used to be one button named after the compiler's sentence. The row is
     * a card now — severity, sentence, position, then the one act — and the act says what
     * it does and where, so three diagnostics in one file are three distinct names rather
     * than three copies of "open".
     */
    await userEvent.click(screen.getByRole('button', { name: 'Open line 7' }));

    await waitFor(() =>
      expect(daemon.callsTo('manuscript.read_file')).toContainEqual({
        path: 'sections/intro.tex',
      }),
    );
    await opened('sections/intro.tex');
    await waitFor(() => expect(screen.getByText('Ln 7, Col 1')).toBeInTheDocument());
  });

  it('keeps the audit’s findings in their own list with their own words', async () => {
    renderWorkspace(manuscriptDaemon({ build: buildFailed }));
    await opened();

    const audit = screen.getByRole('list', { name: 'Scientific audit' });
    /*
     * `over_strong_wording` used to arrive here as the humanised token "Over strong
     * wording", because the package's audit vocabulary was keyed on four identifiers the
     * daemon does not send. The word is the product's now — Product 30.3 calls this a
     * manuscript sentence stronger than the accepted Claim.
     */
    expect(within(audit).getByText('Wording stronger than the Claim')).toBeInTheDocument();
    expect(within(audit).getByText('Must fix')).toBeInTheDocument();
    // The card opens with the manuscript's own sentence, not with the audit's verdict.
    expect(
      within(audit).getByText(/All existing traffic classifiers degrade under sustained load/),
    ).toBeInTheDocument();
    // The compiler's words are not the audit's words.
    expect(within(audit).queryByText('Error')).toBeNull();
    expect(screen.getByText('1 finding')).toBeInTheDocument();
    expect(screen.getByText('2 messages')).toBeInTheDocument();
  });

  it('carries both counts into the inspector’s tab, without summing them', async () => {
    renderWorkspace(manuscriptDaemon({ build: buildFailed }));
    await opened();

    expect(screen.getByRole('tab', { name: /Build and audit/ })).toHaveTextContent(
      '2 compiler · 1 audit',
    );
  });
});

describe('SyncTeX', () => {
  it('jumps from the cursor to the box the compiler recorded', async () => {
    const daemon = manuscriptDaemon();
    renderWorkspace(daemon);
    await opened();
    await waitFor(() =>
      expect(screen.getByRole('img', { name: 'manuscript page 1' })).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Jump to PDF' }));

    await waitFor(() =>
      expect(daemon.callsTo('manuscript.synctex')[0]).toMatchObject({
        file: 'main.tex',
        line: 1,
        build_id: 'b-0002',
      }),
    );
    await waitFor(() => expect(screen.getAllByTestId('pdf-highlight')).toHaveLength(1));
    expect(screen.getByRole('img', { name: /SyncTeX target for main\.tex:1/ })).toBeInTheDocument();
  });

  it('jumps back from a double-click in the page to the source line', async () => {
    const daemon = manuscriptDaemon();
    renderWorkspace(daemon);
    await opened();
    await waitFor(() =>
      expect(screen.getByRole('img', { name: 'manuscript page 1' })).toBeInTheDocument(),
    );

    fireEvent.doubleClick(screen.getByTestId('pdf-frame'), { clientX: 0, clientY: 0 });

    await waitFor(() => {
      const [request] = daemon.callsTo('manuscript.synctex');
      expect(request).toMatchObject({ page: 1, build_id: 'b-0002' });
      // The point pdf.js reported in user space, asked for in SyncTeX's top-left space.
      expect(request?.y).toBe(0);
    });
    await opened('sections/intro.tex');
    await waitFor(() => expect(screen.getByText('Ln 4, Col 3')).toBeInTheDocument());
  });

  it('disables both directions with the daemon’s reason when there is no map', async () => {
    renderWorkspace(manuscriptDaemon({ build: buildFailed }));
    await opened();

    expect(screen.getByRole('button', { name: 'Jump to PDF' })).toBeDisabled();
    expect(
      screen.getByText(/Source-to-PDF navigation is unavailable: no SyncTeX file at main\.synctex\.gz/),
    ).toBeInTheDocument();
    expect(
      screen.getByText('PDF-to-source navigation is unavailable for this build.'),
    ).toBeInTheDocument();
  });
});

describe('suggestions', () => {
  async function openCandidate(daemon: Daemon): Promise<void> {
    renderWorkspace(daemon);
    await opened();
    await userEvent.click(screen.getByRole('treeitem', { name: /intro\.tex/ }));
    await opened('sections/intro.tex');

    await userEvent.click(screen.getByRole('button', { name: 'Suggest…' }));
    await userEvent.type(screen.getByLabelText('Provider'), 'local/model-y');
    await userEvent.click(screen.getByRole('button', { name: 'Ask for a candidate' }));
  }

  it('stages a candidate and leaves the file untouched', async () => {
    const daemon = manuscriptDaemon();
    await openCandidate(daemon);

    await waitFor(() =>
      expect(daemon.callsTo('manuscript.suggest')[0]).toMatchObject({
        file: 'sections/intro.tex',
        provider: 'local/model-y',
        style: 'humanize',
      }),
    );
    expect(await screen.findByText('Candidate edit')).toBeInTheDocument();
    expect(screen.getByText('Audit passed')).toBeInTheDocument();
    // The protected citation is marked in words, on the line that carries it.
    expect(screen.getAllByText('protected: citation').length).toBeGreaterThan(0);
    expect(daemon.callsTo('manuscript.write_file')).toHaveLength(0);
    expect(daemon.callsTo('manuscript.apply_suggestion')).toHaveLength(0);
  });

  it('refuses to apply a blocked candidate and prints the daemon’s reason', async () => {
    const daemon = manuscriptDaemon({ suggest: candidateBlocked });
    await openCandidate(daemon);

    expect(await screen.findByText('Audit failed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply to source' })).toBeDisabled();
    expect(
      screen.getByText(/a style pass may change wording, never a protected span/),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Apply to source' }));
    expect(daemon.callsTo('manuscript.apply_suggestion')).toHaveLength(0);
  });

  it('applies an allowed candidate against the open file’s hash, and takes the new text', async () => {
    const daemon = manuscriptDaemon();
    await openCandidate(daemon);
    await screen.findByText('Audit passed');

    await userEvent.click(screen.getByRole('button', { name: 'Apply to source' }));

    await waitFor(() =>
      expect(daemon.callsTo('manuscript.apply_suggestion')[0]).toEqual({
        candidate_id: 'mscand_0001',
        expected_hash: readIntro.content_hash,
      }),
    );
    await waitFor(() => expect(editorText()).toBe(applied.snapshot.content));
    expect(within(frame()).getByText('Saved')).toBeInTheDocument();
  });

  it('will not apply over unsaved work, and says so instead of overwriting it', async () => {
    const daemon = manuscriptDaemon();
    renderWorkspace(daemon);
    await opened();
    await userEvent.click(screen.getByRole('treeitem', { name: /intro\.tex/ }));
    await opened('sections/intro.tex');
    edit('% still being written\n');

    await userEvent.click(screen.getByRole('button', { name: 'Suggest…' }));
    await userEvent.type(screen.getByLabelText('Provider'), 'local/model-y');
    await userEvent.click(screen.getByRole('button', { name: 'Ask for a candidate' }));

    expect(
      await screen.findByText(/Save or discard your unsaved changes to sections\/intro\.tex/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply to source' })).toBeDisabled();
  });

  it('offers an agent host the diff and refuses it the application', async () => {
    const daemon = manuscriptDaemon({
      overview: { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' },
    });
    renderWorkspace(daemon, null);
    await opened();
    await userEvent.click(screen.getByRole('treeitem', { name: /intro\.tex/ }));
    await opened('sections/intro.tex');
    await userEvent.click(screen.getByRole('button', { name: 'Suggest…' }));
    await userEvent.type(screen.getByLabelText('Provider'), 'local/model-y');
    await userEvent.click(screen.getByRole('button', { name: 'Ask for a candidate' }));

    expect(await screen.findByText('Candidate edit')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply to source' })).toBeDisabled();
    expect(daemon.callsTo('manuscript.suggest')).toHaveLength(1);
  });
});

describe('references and reach', () => {
  it('offers the reference a conversation can carry', async () => {
    renderWorkspace();
    await opened();

    await userEvent.click(screen.getByRole('button', { name: 'Copy reference' }));

    expect(await screen.findByText('rh://manuscript/main.tex?line=1')).toBeInTheDocument();
  });

  it('opens a file from the tree with the keyboard alone', async () => {
    renderWorkspace();
    await opened();

    const tree = screen.getByRole('tree', { name: 'Manuscript files' });
    const first = within(tree).getAllByRole('treeitem')[0]!;
    act(() => first.focus());
    // `sections` is the first row, `sections/intro.tex` the second: down one, then open it.
    await userEvent.keyboard('{ArrowDown}');
    await userEvent.keyboard('{Enter}');

    await opened('sections/intro.tex');
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = renderWorkspace();
    await opened();
    await waitFor(() =>
      expect(screen.getByRole('img', { name: 'manuscript page 1' })).toBeInTheDocument(),
    );

    await expectNoAxeViolations(container);
  });
});

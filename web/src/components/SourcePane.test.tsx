/**
 * Which tint the span on the page is drawn in, and what it is called.
 *
 * The pane draws one rectangle over the source, and that rectangle carries a scientific
 * status colour: `anchor` is the accepted tint. So the pane may never choose it for itself.
 * Its two callers are in different states — the review screen is looking at a proposal in
 * staging, and the source route is opened by a reference whose standing is the daemon's to
 * report — and both are asserted here, because a status colour on a decision nobody has
 * made is the failure this test exists to catch.
 *
 * jsdom has no PDF engine and no canvas, so pdf.js is scripted the way `pdf.test.tsx`
 * scripts it: the arithmetic is the real viewport's, and what is read back is the overlay
 * the pane asked for.
 */
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import type { ReviewItem } from '../api/dto';
import { EvidenceReviewPage } from '../views/EvidenceReview';
import { ArtifactSourcePage } from '../views/conversation/references';
import { CommandsProvider } from '../app/commands';
import { FIXTURES, fakeDaemon, renderView } from '../test/harness';

const PAGE_HEIGHT = 792;

vi.mock('pdfjs-dist', () => {
  function viewportFor(scale: number) {
    return {
      scale,
      width: 612 * scale,
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
        numPages: 5,
        getPage: () =>
          Promise.resolve({
            getViewport: ({ scale }: { scale: number }) => viewportFor(scale),
            render: () => ({ promise: Promise.resolve(), cancel: () => undefined }),
            getTextContent: () => Promise.resolve({ items: [], styles: {} }),
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
  HTMLCanvasElement.prototype.getContext = function getContext() {
    return {};
  } as unknown as HTMLCanvasElement['getContext'];
});

const QUEUE = FIXTURES.reviewInbox as unknown as { items: ReviewItem[] };
const ITEM = QUEUE.items[0]!;
const ARTIFACT = ITEM.artifact;
const BLOCK = FIXTURES.blocks as unknown as { blocks: { id: string; page: number }[] };
const ANCHORED = BLOCK.blocks[3]!;

/** The bytes read the pane makes before it can render anything at all. */
const BYTES = { [`/artifacts/${ARTIFACT}/bytes`]: {} };

function withShell(ui: ReactElement): ReactElement {
  return <CommandsProvider>{ui}</CommandsProvider>;
}

/** The one rectangle the pane drew, once the scripted engine has rendered the page. */
async function span(): Promise<HTMLElement> {
  return waitFor(() => {
    const drawn = screen.getByTestId('pdf-highlight');
    expect(drawn).toBeInTheDocument();
    return drawn;
  });
}

describe('the review screen’s span', () => {
  it('is a proposal, in the accent, on a candidate nobody has decided', async () => {
    const daemon = fakeDaemon({
      gets: {
        '/overview': FIXTURES.overview,
        [`/candidates/${ITEM.candidate_id}`]: FIXTURES.candidate,
        [`/blocks/${ARTIFACT}`]: FIXTURES.blocks,
        ...BYTES,
      },
      capabilities: { 'review.inbox': FIXTURES.reviewInbox },
    });

    renderView(withShell(<EvidenceReviewPage />), {
      daemon,
      route: `/review/${ITEM.candidate_id}`,
      path: '/review/:candidateId',
    });

    const drawn = await span();
    expect(drawn).toHaveAttribute('data-kind', 'sync');
    expect(drawn).toHaveAccessibleName('Proposed span');
    expect(screen.queryByRole('img', { name: 'Accepted span' })).not.toBeInTheDocument();
  });
});

describe('the source route’s span', () => {
  function sourceDaemon(resolved: unknown) {
    return fakeDaemon({
      gets: { [`/blocks/${ARTIFACT}`]: FIXTURES.blocks, ...BYTES },
      ...(resolved === undefined ? {} : { capabilities: { 'graph.resolve': resolved } }),
    });
  }

  function renderSource(resolved: unknown) {
    return renderView(<ArtifactSourcePage />, {
      daemon: sourceDaemon(resolved),
      route: `/source/${ARTIFACT}?page=${ANCHORED.page}&block=${ANCHORED.id}`,
      path: '/source/:artifactId',
    });
  }

  const resolvedAs = (authority: string, extra: Record<string, unknown> = {}) => ({
    reference: `rh://artifact/${ARTIFACT}?block=${ANCHORED.id}`,
    project: 'demo',
    exists: true,
    authority,
    visibility: 'project',
    fresh: true,
    node: null,
    problems: [],
    ...extra,
  });

  it('takes the accepted tint only when the daemon says the reference is accepted', async () => {
    renderSource(resolvedAs('accepted'));

    const drawn = await span();
    expect(drawn).toHaveAttribute('data-kind', 'anchor');
    expect(drawn).toHaveAccessibleName('Accepted span');
  });

  it('is a proposal when the reference carries any other authority', async () => {
    renderSource(resolvedAs('candidate'));

    const drawn = await span();
    expect(drawn).toHaveAttribute('data-kind', 'sync');
    expect(drawn).toHaveAccessibleName('Proposed span');
  });

  it('is a proposal when the anchor no longer holds, whatever the authority says', async () => {
    renderSource(resolvedAs('accepted', { fresh: false, problems: ['the block moved'] }));

    const drawn = await span();
    expect(drawn).toHaveAttribute('data-kind', 'sync');
    expect(drawn).toHaveAccessibleName('Proposed span');
  });

  it('never assumes accepted when the authority could not be read at all', async () => {
    renderSource(undefined);

    const drawn = await span();
    expect(drawn).toHaveAttribute('data-kind', 'sync');
    expect(drawn).toHaveAccessibleName('Proposed span');
  });
});

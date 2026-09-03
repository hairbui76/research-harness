/**
 * The pdf.js adapter, against a scripted engine.
 *
 * jsdom has no PDF engine and no canvas, so pdf.js is mocked — the same way the review
 * screen's tests mock it. What is being tested here is not pdf.js: it is the two
 * coordinate crossings the manuscript workspace depends on (a double click reported in PDF
 * user space, a highlight given in PDF user space and drawn in CSS pixels), the page cache,
 * and the promise that a failed engine degrades to text instead of an empty frame.
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { PdfPage } from './PdfPage';
import { usePdfDocument } from './usePdfDocument';
import type { PdfDocumentState } from './usePdfDocument';
import { resetPdfjs } from './worker';

/** The page box of the fixture, in points: US Letter, as PDF user space measures it. */
const PAGE_WIDTH = 612;
const PAGE_HEIGHT = 792;

const engine = vi.hoisted(() => ({
  numPages: 3,
  failWith: null as string | null,
  loads: 0,
  destroys: 0,
  pageRequests: [] as number[],
  renders: [] as unknown[],
  documentParams: [] as Record<string, unknown>[],
  textLayers: [] as { container: HTMLElement }[],
}));

vi.mock('pdfjs-dist', () => {
  /** A viewport with the real one's arithmetic: y flipped, everything times the scale. */
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
    getDocument(params: Record<string, unknown>) {
      engine.loads += 1;
      engine.documentParams.push(params);
      const failure = engine.failWith;
      return {
        promise: failure
          ? Promise.reject(new Error(failure))
          : Promise.resolve({
              numPages: engine.numPages,
              getPage(page: number) {
                engine.pageRequests.push(page);
                return Promise.resolve({
                  getViewport: ({ scale }: { scale: number }) => viewportFor(scale),
                  render(options: unknown) {
                    engine.renders.push(options);
                    return { promise: Promise.resolve(), cancel: () => undefined };
                  },
                  getTextContent: () => Promise.resolve({ items: [], styles: {} }),
                });
              },
            }),
        destroy() {
          engine.destroys += 1;
          return Promise.resolve();
        },
      };
    },
    TextLayer: class {
      private readonly container: HTMLElement;
      constructor(options: { container: HTMLElement }) {
        this.container = options.container;
        engine.textLayers.push(options);
      }
      render() {
        const span = window.document.createElement('span');
        span.textContent = 'a line of the page';
        this.container.appendChild(span);
        return Promise.resolve();
      }
    },
  };
});

beforeAll(() => {
  // jsdom has no canvas; a plain stub keeps `getContext` from returning null. It is not a
  // spy on purpose — `restoreMocks` would empty it after the first test.
  HTMLCanvasElement.prototype.getContext = function getContext() {
    return {};
  } as unknown as HTMLCanvasElement['getContext'];
});

beforeEach(() => {
  engine.numPages = 3;
  engine.failWith = null;
  engine.loads = 0;
  engine.destroys = 0;
  engine.pageRequests = [];
  engine.renders = [];
  engine.documentParams = [];
  engine.textLayers = [];
  resetPdfjs();
});

describe('usePdfDocument', () => {
  it('loads a document from a url and answers with its page count', async () => {
    const { result } = renderHook(() => usePdfDocument('/manuscript/builds/B1/pdf'));

    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.numPages).toBe(3);
    expect(result.current.error).toBeNull();
    expect(engine.documentParams[0]).toMatchObject({ url: '/manuscript/builds/B1/pdf' });
  });

  it('asks the engine for each page once and keeps the same `getPage` identity', async () => {
    const { result, rerender } = renderHook(() => usePdfDocument('/pdf'));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const getPage = result.current.getPage;

    await result.current.getPage(2);
    await result.current.getPage(2);
    rerender();

    expect(engine.pageRequests).toEqual([2]);
    // A stable identity is what stops `PdfPage` re-rendering the page on every state tick.
    expect(result.current.getPage).toBe(getPage);
  });

  it('refuses a page outside the document', async () => {
    const { result } = renderHook(() => usePdfDocument('/pdf'));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    await expect(result.current.getPage(9)).rejects.toThrow('outside this document');
  });

  it('copies the bytes it is given, because pdf.js detaches the buffer it is handed', async () => {
    const source = new Uint8Array([37, 80, 68, 70]);
    const { result } = renderHook(() => usePdfDocument(source));
    await waitFor(() => expect(result.current.status).toBe('ready'));

    const data = engine.documentParams[0]?.data as Uint8Array;
    expect(Array.from(data)).toEqual([37, 80, 68, 70]);
    expect(data).not.toBe(source);
    expect(source.byteLength).toBe(4);
  });

  it('reports a failed load as text, and reloads on request', async () => {
    engine.failWith = 'no PDF engine here';
    const { result } = renderHook(() => usePdfDocument('/pdf'));

    await waitFor(() => expect(result.current.status).toBe('unavailable'));
    expect(result.current.error).toBe('no PDF engine here');

    engine.failWith = null;
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(engine.loads).toBe(2);
  });

  it('is idle with no source, and tears the document down on unmount', async () => {
    const { result, unmount } = renderHook(() => usePdfDocument('/pdf'));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    unmount();
    await waitFor(() => expect(engine.destroys).toBe(1));

    const idle = renderHook(() => usePdfDocument(null));
    expect(idle.result.current.status).toBe('idle');
    expect(idle.result.current.numPages).toBe(0);
  });
});

/** The document a `PdfPage` is given, driven by the hook. */
function useDocument(source: string | null = '/pdf'): PdfDocumentState {
  return usePdfDocument(source);
}

function Harness(props: {
  scale?: number;
  index?: number;
  textLayer?: boolean;
  highlights?: { rect: [number, number, number, number]; label?: string; kind?: 'anchor' }[];
  onDoubleClick?: (page: number, x: number, y: number) => void;
}) {
  const document = useDocument();
  return (
    <PdfPage
      document={document}
      index={props.index ?? 1}
      scale={props.scale ?? 1}
      textLayer={props.textLayer ?? false}
      highlights={props.highlights}
      onDoubleClick={props.onDoubleClick}
    />
  );
}

describe('PdfPage', () => {
  it('renders the page onto a canvas at the requested scale', async () => {
    render(<Harness scale={2} index={2} />);

    const canvas = (await screen.findByRole('img', { name: 'page 2' })) as HTMLCanvasElement;
    await waitFor(() => expect(engine.renders).toHaveLength(1));
    expect(engine.pageRequests).toEqual([2]);
    expect(canvas.style.width).toBe(`${PAGE_WIDTH * 2}px`);
    expect(canvas.style.height).toBe(`${PAGE_HEIGHT * 2}px`);
  });

  it('clamps a page number to the document rather than failing', async () => {
    render(<Harness index={99} />);
    await waitFor(() => expect(engine.pageRequests).toEqual([3]));
    expect(await screen.findByRole('img', { name: 'page 3' })).toBeInTheDocument();
  });

  it('reports a double click in PDF user space, for a SyncTeX inverse lookup', async () => {
    const onDoubleClick = vi.fn();
    render(<Harness scale={2} onDoubleClick={onDoubleClick} />);
    await screen.findByRole('img', { name: 'page 1' });
    await waitFor(() => expect(engine.renders).toHaveLength(1));

    // jsdom gives the frame a zero-origin box, so the client point is the point on the
    // canvas: (100, 200) CSS px at scale 2 is (50, 792 − 100) in PDF coordinates.
    fireEvent.doubleClick(screen.getByTestId('pdf-frame'), { clientX: 100, clientY: 200 });

    expect(onDoubleClick).toHaveBeenCalledWith(1, 50, PAGE_HEIGHT - 100);
  });

  it('draws a highlight given in PDF coordinates', async () => {
    render(
      <Harness
        scale={2}
        highlights={[{ rect: [72, 692, 172, 712], label: 'SyncTeX target, line 120', kind: 'anchor' }]}
      />,
    );
    await screen.findByRole('img', { name: 'page 1' });

    const highlight = await screen.findByTestId('pdf-highlight');
    // y flips: the top of the box is (792 − 712) × 2, and it is 20pt tall × 2.
    expect(highlight.style.left).toBe('144px');
    expect(highlight.style.top).toBe(`${(PAGE_HEIGHT - 712) * 2}px`);
    expect(highlight.style.width).toBe('200px');
    expect(highlight.style.height).toBe('40px');
    expect(highlight).toHaveAttribute('data-kind', 'anchor');
    expect(highlight).toHaveAccessibleName('SyncTeX target, line 120');
  });

  it('renders the text layer only when it is asked for', async () => {
    const { unmount } = render(<Harness />);
    await screen.findByRole('img', { name: 'page 1' });
    await waitFor(() => expect(engine.renders).toHaveLength(1));
    expect(engine.textLayers).toHaveLength(0);
    unmount();

    render(<Harness textLayer />);
    await waitFor(() => expect(engine.textLayers).toHaveLength(1));
    expect(await screen.findByText('a line of the page')).toBeInTheDocument();
  });

  it('falls back to text when the document could not be loaded', async () => {
    engine.failWith = 'this browser could not start the PDF engine';
    render(<Harness />);

    const message = await screen.findByRole('status');
    expect(message).toHaveTextContent('could not be rendered');
    expect(message).toHaveTextContent('this browser could not start the PDF engine');
  });

  it('falls back to a caller-supplied message when the page itself fails', async () => {
    const broken: PdfDocumentState = {
      status: 'unavailable',
      numPages: 0,
      error: 'the build has no PDF yet',
      getPage: () => Promise.reject(new Error('no document')),
      reload: () => undefined,
    };
    render(<PdfPage document={broken} index={1} fallback={<>No PDF for this build yet.</>} />);

    expect(await screen.findByRole('status')).toHaveTextContent('No PDF for this build yet.');
  });
});

/**
 * The PDF pane: the Design System's preview frame around this client's pdf.js adapter.
 *
 * Three things happen here that neither side can do alone.
 *
 * *The coordinate crossing.* SyncTeX answers in PDF points from the page's **top** left;
 * `PdfPage` draws and reports in PDF user space, whose origin is the **bottom** left. The
 * flip is about the page's real height, read back from pdf.js rather than assumed, so a
 * highlight lands in the same place on A4 and on US Letter.
 *
 * *The double click.* `PdfPage` reports it already converted, so the inner handler does the
 * work and the frame's own surface handler only exists so the footer can truthfully say
 * that PDF-to-source navigation is available; a click that missed a rendered page is
 * ignored rather than guessed at.
 *
 * *Searching.* The query runs over pdf.js's own extracted text, page by page from the one
 * being read, and reports which page matched — or that nothing did. The pane never claims
 * to have found something it did not.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { PdfPreview } from '@research-harness/design';
import type { BuildModel } from '@research-harness/design';
import { PdfPage, usePdfDocument } from '../../pdf';
import type { PdfHighlight } from '../../pdf';
import type { PdfLocation, SourceLocation } from '../../api/dto';
import { toSynctexPoint, toUserSpaceRect } from './mappers';

export interface PreviewPaneProps {
  build: BuildModel;
  /** The bytes of the PDF to show; held steady by the caller for `usePdfDocument`. */
  bytes: ArrayBuffer | null;
  loading?: boolean;
  /** Why there are no bytes — a 404 from the byte route, say. */
  error?: string | null;
  /** A link that opens the same PDF unchanged, for when this pane cannot render it. */
  fileUrl?: string;
  /** SyncTeX forward hits, in PDF points from the page's top left. */
  locations: readonly PdfLocation[];
  /** The page a forward lookup landed on; the pane turns to it. */
  syncPage: number | null;
  /** What the last forward lookup was asked about, for the highlight's accessible name. */
  syncLabel?: string;
  /** Enabled only when the daemon reported a SyncTeX map for this build. */
  inverseEnabled: boolean;
  onInverseSync: (page: number, x: number, y: number) => Promise<SourceLocation | null>;
}

/** Padding the frame puts around the page, so "Fit page" leaves the page inside the pane. */
const SURFACE_PADDING_PX = 32;

export function PreviewPane({
  build,
  bytes,
  loading = false,
  error = null,
  fileUrl,
  locations,
  syncPage,
  syncLabel,
  inverseEnabled,
  onInverseSync,
}: PreviewPaneProps) {
  const pdf = usePdfDocument(bytes);
  const [page, setPage] = useState(1);
  const [scale, setScale] = useState(1);
  const [pageSize, setPageSize] = useState<{ width: number; height: number } | null>(null);
  const [paneWidth, setPaneWidth] = useState(0);
  const [searchNote, setSearchNote] = useState<string | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  // Set by the page's own double-click handler, which fires first; the frame's surface
  // handler then knows the click was already answered in PDF user space.
  const handledInner = useRef(false);

  // A forward lookup turns the page. Nothing else moves it, so a researcher reading page 4
  // stays on page 4 across a recompile. `locations` is a fresh array per lookup, so asking
  // twice for the same line brings the reader back to it.
  useEffect(() => {
    if (syncPage !== null) setPage(syncPage);
  }, [locations, syncPage]);

  useEffect(() => {
    if (pdf.numPages > 0 && page > pdf.numPages) setPage(pdf.numPages);
  }, [page, pdf.numPages]);

  // The page's real size in points, which is what the SyncTeX flip is about.
  useEffect(() => {
    if (pdf.status !== 'ready') {
      setPageSize(null);
      return;
    }
    let live = true;
    pdf
      .getPage(page)
      .then((rendered) => {
        if (!live) return;
        const viewport = rendered.getViewport({ scale: 1 });
        setPageSize({ width: viewport.width, height: viewport.height });
      })
      .catch(() => {
        if (live) setPageSize(null);
      });
    return () => {
      live = false;
    };
  }, [pdf.status, pdf.getPage, page]);

  useLayoutEffect(() => {
    const measure = (): void => setPaneWidth(hostRef.current?.clientWidth ?? 0);
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [pdf.status]);

  const fitScale =
    pageSize && paneWidth > SURFACE_PADDING_PX
      ? (paneWidth - SURFACE_PADDING_PX) / pageSize.width
      : 1;

  const highlights = useMemo<PdfHighlight[]>(() => {
    const height = pageSize?.height;
    if (height === undefined) return [];
    return locations
      .filter((location) => location.page === page)
      .map((location, index) => ({
        id: `synctex-${index}`,
        rect: toUserSpaceRect(location, height),
        kind: 'sync' as const,
        label: syncLabel ? `SyncTeX target for ${syncLabel}` : 'SyncTeX target',
      }));
  }, [locations, page, pageSize?.height, syncLabel]);

  const handleDoubleClick = useCallback(
    (pdfPage: number, x: number, y: number): void => {
      handledInner.current = true;
      const height = pageSize?.height;
      if (!inverseEnabled || height === undefined) return;
      const point = toSynctexPoint(x, y, height);
      void onInverseSync(pdfPage, point.x, point.y);
    },
    [inverseEnabled, onInverseSync, pageSize?.height],
  );

  /**
   * The frame's own surface double-click.
   *
   * It exists so the frame's footer states the truth about this build. The page handler
   * above has already answered any click that landed on a rendered page; anything else was
   * a click on the surface around it, and is not a place in the document.
   */
  const handleSurfaceDoubleClick = useCallback((): void => {
    handledInner.current = false;
  }, []);

  const search = useCallback(
    (query: string): void => {
      const needle = query.trim().toLowerCase();
      if (!needle) {
        setSearchNote(null);
        return;
      }
      if (pdf.status !== 'ready') return;
      void (async () => {
        const total = pdf.numPages;
        for (let offset = 0; offset < total; offset += 1) {
          const candidate = ((page - 1 + offset + 1) % total) + 1;
          const text = await textOf(pdf.getPage, candidate);
          if (text.toLowerCase().includes(needle)) {
            setPage(candidate);
            setSearchNote(`“${query}” found on page ${candidate}.`);
            return;
          }
        }
        setSearchNote(`“${query}” is not in this PDF's text.`);
      })();
    },
    [page, pdf.getPage, pdf.numPages, pdf.status],
  );

  const renderPage = useCallback(
    (index: number, currentScale: number): ReactNode => (
      <>
        {searchNote ? (
          <p className="rh-text-secondary" role="status">
            {searchNote}
          </p>
        ) : null}
        {loading ? (
          <p className="rh-text-secondary" role="status">
            Loading the compiled PDF…
          </p>
        ) : null}
        {error ? (
          <p className="rh-text-secondary" role="status">
            {`The compiled PDF could not be read (${error}).`}
            {fileUrl ? (
              <>
                {' '}
                <a href={fileUrl} target="_blank" rel="noreferrer">
                  Open it directly
                </a>
                .
              </>
            ) : null}
          </p>
        ) : (
          <PdfPage
            document={pdf}
            index={index}
            scale={currentScale}
            textLayer
            highlights={highlights}
            onDoubleClick={handleDoubleClick}
            label={`manuscript page ${index}`}
            fallback={
              <>
                This page could not be rendered here.
                {fileUrl ? (
                  <>
                    {' '}
                    <a href={fileUrl} target="_blank" rel="noreferrer">
                      The compiled PDF
                    </a>{' '}
                    opens unchanged.
                  </>
                ) : null}
              </>
            }
          />
        )}
      </>
    ),
    [error, fileUrl, handleDoubleClick, highlights, loading, pdf, searchNote],
  );

  return (
    // A measuring wrapper, and nothing else: "Fit page" needs the pane's width, and the
    // frame owns its own surface. The inline rule only passes the pane's height through, so
    // no colour and no spacing is decided outside the package.
    <div
      ref={hostRef}
      style={{ display: 'flex', flexDirection: 'column', flex: '1 1 auto', minHeight: 0, minWidth: 0 }}
    >
      <PdfPreview
        build={build}
        {...(pdf.numPages > 0 ? { pageCount: pdf.numPages } : {})}
        page={page}
        onPageChange={setPage}
        scale={scale}
        onScaleChange={setScale}
        fitScale={fitScale}
        onSearch={pdf.status === 'ready' ? search : undefined}
        renderPage={renderPage}
        {...(inverseEnabled ? { onInverseSync: handleSurfaceDoubleClick } : {})}
      />
    </div>
  );
}

/** One page's extracted text, from pdf.js's own text layer content. */
async function textOf(
  getPage: (page: number) => Promise<{ getTextContent: () => Promise<unknown> }>,
  page: number,
): Promise<string> {
  try {
    const rendered = await getPage(page);
    const content = (await rendered.getTextContent()) as { items?: unknown[] } | null;
    return (content?.items ?? [])
      .map((item) =>
        typeof item === 'object' && item !== null && 'str' in item
          ? String((item as { str: unknown }).str)
          : '',
      )
      .join(' ');
  } catch {
    return '';
  }
}

/**
 * One rendered page, with the two coordinate crossings the manuscript workspace needs.
 *
 * LaTeX spec §6 asks for navigation in both directions: a source cursor jumps to a place
 * in the PDF, and a place in the PDF jumps back to source. Both halves are coordinate
 * conversions, and both are done here in *PDF user space* — origin at the bottom left,
 * units of 1/72 inch — because that is the space SyncTeX speaks:
 *
 * - `onDoubleClick(page, x, y)` reports where the pointer landed in PDF user space, by
 *   inverting the viewport transform (`viewport.convertToPdfPoint`). That is what
 *   `manuscript.synctex` takes for an inverse lookup.
 * - `highlights` are rectangles in the same space, drawn by applying the transform
 *   forwards. A forward SyncTeX lookup answers in PDF coordinates, so nothing has to be
 *   scaled by the caller when the zoom changes.
 *
 * When pdf.js cannot render — no engine, a corrupt file, a build that failed — the page
 * says so in words. LaTeX spec §9: an unavailable preview is a state to explain, not a
 * blank rectangle.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, MouseEvent, ReactNode } from 'react';
import type { PageViewport, RenderTask } from 'pdfjs-dist';
import type { PdfDocumentState } from './usePdfDocument';
import { loadPdfjs } from './worker';
import './pdf.css';

/** A rectangle in PDF user space: `[x0, y0, x1, y1]`, origin bottom left. */
export type PdfRect = readonly [number, number, number, number];

export interface PdfHighlight {
  rect: PdfRect;
  /** Stable key; falls back to the rectangle itself. */
  id?: string;
  /** Named for assistive technology — "SyncTeX target, line 120". */
  label?: string;
  /** `sync` a SyncTeX target, `anchor` an accepted source anchor, `match` a search hit. */
  kind?: 'sync' | 'anchor' | 'match';
}

export interface PdfPageProps {
  /** The document this page belongs to, from `usePdfDocument`. */
  document: PdfDocumentState;
  /** 1-based page number. Out-of-range values are clamped to the document. */
  index: number;
  /** 1 renders at the page's natural size. */
  scale?: number;
  /** Render pdf.js's selectable text layer over the canvas. Off by default. */
  textLayer?: boolean;
  /** Rectangles in PDF user space, drawn over the page. */
  highlights?: readonly PdfHighlight[];
  /** Where the pointer landed, in PDF user space, for a SyncTeX inverse lookup. */
  onDoubleClick?: (page: number, x: number, y: number) => void;
  className?: string;
  /** Accessible name for the rendered page. */
  label?: string;
  /** Shown instead of the canvas when the page cannot be rendered. */
  fallback?: ReactNode;
}

type PageStatus = 'idle' | 'rendering' | 'ready' | 'unavailable';

export function PdfPage({
  document: pdf,
  index,
  scale = 1,
  textLayer = false,
  highlights,
  onDoubleClick,
  className,
  label,
  fallback,
}: PdfPageProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const textLayerRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<PageViewport | null>(null);
  const [status, setStatus] = useState<PageStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);

  const page = pdf.numPages > 0 ? Math.min(Math.max(1, index), pdf.numPages) : Math.max(1, index);

  useEffect(() => {
    if (pdf.status === 'idle') {
      setStatus('idle');
      return;
    }
    if (pdf.status === 'unavailable') {
      setStatus('unavailable');
      setError(pdf.error);
      return;
    }
    if (pdf.status !== 'ready') return;

    const canvas = canvasRef.current;
    if (!canvas) return;

    let live = true;
    let task: RenderTask | null = null;
    setStatus('rendering');
    setError(null);

    (async () => {
      const rendered = await pdf.getPage(page);
      const viewport = rendered.getViewport({ scale });
      if (!live) return;

      // A device pixel ratio above 1 draws more pixels than CSS asks for; the canvas keeps
      // its CSS size so that every coordinate below stays in CSS pixels.
      const ratio = Math.max(1, Math.min(globalThis.devicePixelRatio || 1, 3));
      const width = Math.floor(viewport.width);
      const height = Math.floor(viewport.height);
      canvas.width = Math.floor(width * ratio);
      canvas.height = Math.floor(height * ratio);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      const canvasContext = canvas.getContext('2d');
      if (!canvasContext) throw new Error('this browser gave no 2d canvas context');

      task = rendered.render({
        canvasContext,
        viewport,
        ...(ratio === 1 ? {} : { transform: [ratio, 0, 0, ratio, 0, 0] }),
      });
      await task.promise;
      if (!live) return;

      viewportRef.current = viewport;
      setSize({ width, height });
      setStatus('ready');

      const container = textLayerRef.current;
      if (textLayer && container) {
        const { TextLayer } = await loadPdfjs();
        const textContentSource = await rendered.getTextContent();
        if (!live) return;
        container.textContent = '';
        // pdf.js positions text-layer spans against this custom property.
        container.style.setProperty('--scale-factor', String(scale));
        await new TextLayer({ textContentSource, container, viewport }).render();
      }
    })().catch((cause: unknown) => {
      if (!live || isCancellation(cause)) return;
      setError(cause instanceof Error ? cause.message : String(cause));
      setStatus('unavailable');
    });

    return () => {
      live = false;
      task?.cancel();
    };
  }, [pdf.status, pdf.error, pdf.getPage, page, scale, textLayer]);

  const handleDoubleClick = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      const viewport = viewportRef.current;
      if (!onDoubleClick || !viewport) return;
      const box = event.currentTarget.getBoundingClientRect();
      const [x, y] = viewport.convertToPdfPoint(event.clientX - box.left, event.clientY - box.top);
      onDoubleClick(page, x as number, y as number);
    },
    [onDoubleClick, page],
  );

  const viewport = viewportRef.current;
  const name = label ?? `page ${page}`;

  return (
    <div className={className ? `rh-pdf ${className}` : 'rh-pdf'} data-status={status}>
      <div className="rh-pdf__frame" onDoubleClick={handleDoubleClick} data-testid="pdf-frame">
        <canvas ref={canvasRef} className="rh-pdf__canvas" role="img" aria-label={name} />
        {textLayer ? (
          <div ref={textLayerRef} className="rh-pdf__text-layer" aria-hidden="true" />
        ) : null}
        {status === 'ready' && viewport && size
          ? (highlights ?? []).map((highlight, position) => (
              <span
                key={highlight.id ?? `${highlight.rect.join(',')}:${position}`}
                className="rh-pdf__highlight"
                data-testid="pdf-highlight"
                data-kind={highlight.kind ?? 'sync'}
                style={overlayStyle(viewport, highlight.rect)}
                {...(highlight.label ? { role: 'img', 'aria-label': highlight.label } : {})}
              />
            ))
          : null}
      </div>

      {status === 'unavailable' ? (
        <p className="rh-pdf__fallback" role="status">
          {fallback ?? (
            <>
              This page could not be rendered{error ? ` (${error})` : ''}. The PDF itself is
              unchanged.
            </>
          )}
        </p>
      ) : null}
    </div>
  );
}

/**
 * A PDF rectangle in CSS pixels over the canvas.
 *
 * `convertToViewportRectangle` applies the page's rotation and flips the y axis, so the
 * corners can come back in either order; the box is whatever those two corners span.
 */
function overlayStyle(viewport: PageViewport, rect: PdfRect): CSSProperties {
  const [x0, y0, x1, y1] = viewport.convertToViewportRectangle([
    rect[0],
    rect[1],
    rect[2],
    rect[3],
  ]) as [number, number, number, number];
  return {
    left: `${Math.min(x0, x1)}px`,
    top: `${Math.min(y0, y1)}px`,
    width: `${Math.abs(x1 - x0)}px`,
    height: `${Math.abs(y1 - y0)}px`,
  };
}

/** A render cancelled by a re-render is not a failure to report. */
function isCancellation(cause: unknown): boolean {
  return (
    typeof cause === 'object' &&
    cause !== null &&
    'name' in cause &&
    (cause as { name?: string }).name === 'RenderingCancelledException'
  );
}

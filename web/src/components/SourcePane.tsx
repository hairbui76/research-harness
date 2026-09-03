/**
 * The left half of the review screen: the page the evidence was read off, with the span
 * drawn on it.
 *
 * Product 25 and 42 D: a researcher must never be asked to trust a candidate summary
 * without the source in front of them. The page is rendered from the artifact's own bytes
 * with pdf.js, and the highlight comes from the block geometry the parse stored — the same
 * geometry the anchor was made against, not a re-derivation.
 *
 * pdf.js is imported lazily so that the rest of the cockpit (and its tests) never pay for
 * a PDF engine they are not using. When it cannot load, the pane falls back to the exact
 * block text, which is still the source and still beside the decision.
 */
import { useEffect, useRef, useState } from 'react';
import type { ArtifactBlocks, BlockView, SourceContext } from '../api/dto';
import { useSession } from '../app/session';

export interface SourcePaneProps {
  artifact: string;
  context: SourceContext;
  /** The stored parse, when the caller already read it; otherwise this pane reads it. */
  blocks?: ArtifactBlocks | null;
  blockId?: string | null;
}

export function SourcePane({ artifact, context, blocks, blockId }: SourcePaneProps) {
  const { client } = useSession();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [status, setStatus] = useState<'idle' | 'rendering' | 'ready' | 'unavailable'>('idle');
  const [detail, setDetail] = useState<string | null>(null);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);

  const page = context.page ?? 1;
  const highlight = context.bbox ?? bboxOf(blocks, blockId);

  useEffect(() => {
    let live = true;
    const canvas = canvasRef.current;
    if (!canvas) return;
    setStatus('rendering');

    (async () => {
      const pdfjs = await import('pdfjs-dist');
      pdfjs.GlobalWorkerOptions.workerSrc = new URL(
        'pdfjs-dist/build/pdf.worker.min.mjs',
        import.meta.url,
      ).toString();
      const data = await client.artifactBytes(artifact);
      const document = await pdfjs.getDocument({ data }).promise;
      const rendered = await document.getPage(Math.min(page, document.numPages));
      const viewport = rendered.getViewport({ scale: 1.4 });
      if (!live) return;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      setSize({ width: viewport.width, height: viewport.height });
      const canvasContext = canvas.getContext('2d');
      if (!canvasContext) throw new Error('this browser gave no 2d canvas context');
      await rendered.render({ canvasContext, viewport }).promise;
      if (live) setStatus('ready');
    })().catch((cause: unknown) => {
      if (!live) return;
      setDetail(cause instanceof Error ? cause.message : String(cause));
      setStatus('unavailable');
    });

    return () => {
      live = false;
    };
  }, [artifact, client, page]);

  return (
    <div className="source-pane">
      <header>
        <strong>{artifact}</strong>
        <span className="muted">
          page {page}
          {context.section_path.length ? ` · ${context.section_path.join(' › ')}` : ''}
        </span>
      </header>

      <div className="page-frame">
        <canvas ref={canvasRef} aria-label={`page ${page} of ${artifact}`} />
        {status === 'ready' && highlight && size ? (
          <span
            className="span-highlight"
            data-testid="span-highlight"
            style={overlayStyle(highlight, size)}
          />
        ) : null}
      </div>

      {status === 'unavailable' ? (
        <p className="muted">
          The page could not be rendered here ({detail}). The exact source text is below, and{' '}
          <a href={client.artifactBytesUrl(artifact)} target="_blank" rel="noreferrer">
            the original file
          </a>{' '}
          opens unchanged.
        </p>
      ) : null}

      <section className="source-text">
        <h3>Source text</h3>
        <p className="block-text">
          {splitAround(context.block_text, context.exact_text).map((part, index) =>
            part.match ? (
              <mark key={index}>{part.text}</mark>
            ) : (
              <span key={index}>{part.text}</span>
            ),
          )}
        </p>
        {context.neighbors.length ? (
          <details>
            <summary>Blocks either side</summary>
            {context.neighbors.map((text, index) => (
              <p key={index} className="muted">
                {text}
              </p>
            ))}
          </details>
        ) : null}
      </section>
    </div>
  );
}

/** The parse's geometry for one block, when the anchor did not carry its own. */
function bboxOf(blocks: ArtifactBlocks | null | undefined, blockId: string | null | undefined) {
  if (!blocks || !blockId) return null;
  const found = blocks.blocks.find((block: BlockView) => block.id === blockId);
  return found?.bbox ?? null;
}

/**
 * Where to draw the highlight. Parser coordinates share pdf.js's origin (top left) and its
 * unit, so the box only needs the render scale applied — which is exactly the ratio between
 * the rendered canvas and the page it came from.
 */
function overlayStyle(bbox: readonly number[], size: { width: number; height: number }) {
  const [x0, y0, x1, y1] = bbox as [number, number, number, number];
  return {
    left: `${(x0 / PAGE_WIDTH_PT) * size.width}px`,
    top: `${(y0 / PAGE_HEIGHT_PT) * size.height}px`,
    width: `${((x1 - x0) / PAGE_WIDTH_PT) * size.width}px`,
    height: `${((y1 - y0) / PAGE_HEIGHT_PT) * size.height}px`,
  };
}

/** US Letter in points, the fixture's page box; a wrong guess misplaces a rectangle only. */
const PAGE_WIDTH_PT = 612;
const PAGE_HEIGHT_PT = 792;

/** The block text split around the exact span, so the quote is visibly *in* its source. */
export function splitAround(block: string, exact: string): { text: string; match: boolean }[] {
  if (!exact) return [{ text: block, match: false }];
  const at = block.indexOf(exact);
  if (at < 0) return [{ text: block, match: false }];
  return [
    { text: block.slice(0, at), match: false },
    { text: exact, match: true },
    { text: block.slice(at + exact.length), match: false },
  ].filter((part) => part.text.length > 0);
}

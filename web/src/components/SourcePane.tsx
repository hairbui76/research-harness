/**
 * The left half of the review screen: the page the evidence was read off, with the span
 * drawn on it.
 *
 * PRODUCT §25 and §42 D: a researcher must never be asked to trust a candidate summary
 * without the source in front of them. The page is rendered from the artifact's own bytes,
 * and the highlight comes from the block geometry the parse stored — the same geometry the
 * anchor was made against, not a re-derivation.
 *
 * The mark itself is never this pane's judgement. `authority` says whether the rectangle is
 * an accepted anchor or a proposal, and the caller answers it, because the accepted tint is
 * a scientific status colour and a staged candidate has no status yet.
 *
 * pdf.js lives behind `src/pdf`: `usePdfDocument` loads the document lazily (a researcher
 * who never opens a PDF never pays for a PDF engine) and `PdfPage` renders one page and
 * draws the rectangles. The worker is configured in exactly one place, `src/pdf/worker.ts`,
 * which is what keeps the no-CDN rule true at runtime. When the engine cannot run, the pane
 * falls back to the exact block text, which is still the source and still beside the
 * decision.
 */
import { useMemo } from 'react';
import { SourceAnchor } from '@research-harness/design';
import type { ArtifactBlocks, BlockView, SourceContext } from '../api/dto';
import { PdfPage, usePdfDocument } from '../pdf';
import type { PdfRect } from '../pdf';
import { useSession } from '../app/session';
import { useAsync } from '../app/useAsync';

/**
 * What standing the span drawn on the page has.
 *
 * The mark carries a scientific status colour, so the caller says which one applies and
 * this pane never decides: `accepted` is the accepted-status tint of an anchor a decision
 * was written against, and `candidate` is the accent every model proposal wears. A caller
 * that does not know is not offered a third word — it says `candidate`, because a status
 * colour on a decision nobody made is the one reading this pane must never allow.
 */
export type SpanAuthority = 'accepted' | 'candidate';

/** How each standing is drawn and what it is called, for the page and for a screen reader. */
const SPAN: Record<SpanAuthority, { kind: 'anchor' | 'sync'; label: string }> = {
  accepted: { kind: 'anchor', label: 'Accepted span' },
  candidate: { kind: 'sync', label: 'Proposed span' },
};

export interface SourcePaneProps {
  artifact: string;
  context: SourceContext;
  /** Whether the span drawn on the page is an accepted anchor or a proposal. */
  authority: SpanAuthority;
  /** The stored parse, when the caller already read it; otherwise this pane reads it. */
  blocks?: ArtifactBlocks | null;
  blockId?: string | null;
}

export function SourcePane({ artifact, context, authority, blocks, blockId }: SourcePaneProps) {
  const { client } = useSession();
  // One authenticated read of the immutable file. `useAsync` holds the bytes steady, which
  // is what `usePdfDocument` compares its source by.
  const bytes = useAsync(() => client.artifactBytes(artifact), [client, artifact]);
  const pdf = usePdfDocument(bytes.data);

  const page = context.page ?? 1;
  const box = context.bbox ?? bboxOf(blocks, blockId);
  const highlights = useMemo(
    () => (box ? [{ id: 'span', rect: toPdfSpace(box), ...SPAN[authority] }] : []),
    [box, authority],
  );

  /*
   * What the page block says when it is not a page.
   *
   * Both halves are the block's own caption rather than a note printed beside it: an empty
   * rectangle beside an explanation is still an empty rectangle, and on this screen — where
   * the whole promise is the source beside the decision — a reader cannot tell one from a
   * source that simply has nothing on it (design critique, minor).
   */
  const unavailable = bytes.error ?? (pdf.status === 'unavailable' ? pdf.error : null);
  const fallback = (
    <>
      This source has no page image{unavailable ? ` (${unavailable})` : ''}. The exact source
      text is below, and{' '}
      <a href={client.artifactBytesUrl(artifact)} target="_blank" rel="noreferrer">
        the original file
      </a>{' '}
      opens unchanged.
    </>
  );

  return (
    <div className="rh-web-source rh-web-stack rh-web-stack--tight">
      <header className="rh-web-source__header">
        <SourceAnchor
          variant="inline"
          anchor={{ artifactId: artifact, page, ...(blockId ? { block: blockId } : {}) }}
        />
        {context.section_path.length ? (
          <span className="rh-text-secondary">{context.section_path.join(' › ')}</span>
        ) : null}
      </header>

      {bytes.error ? (
        <p className="rh-text-secondary" role="status">
          {fallback}
        </p>
      ) : (
        <PdfPage
          document={pdf}
          index={page}
          scale={1.4}
          highlights={highlights}
          label={`page ${page} of ${artifact}`}
          caption={`Page ${page} of the source, rendering…`}
          fallback={fallback}
        />
      )}

      <section className="rh-web-stack rh-web-stack--tight">
        {/* h2: the source pane is a top-level section of the page, beside the decision. */}
        <h2 className="rh-text-h4">Source text</h2>
        <p className="rh-web-quote">
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
              <p key={index} className="rh-text-secondary">
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
 * The parse's rectangle in PDF user space.
 *
 * The parser records boxes with the origin at the *top* left, in points — PyMuPDF's
 * convention. `PdfPage` draws in PDF user space, whose origin is the *bottom* left, because
 * that is the space SyncTeX and pdf.js both answer in. The conversion is therefore a flip
 * about the page height, and the page height is assumed to be US Letter, exactly as this
 * pane assumed before: a wrong guess misplaces a rectangle, and the exact text below it is
 * unaffected.
 */
function toPdfSpace(bbox: readonly number[]): PdfRect {
  const [x0, y0, x1, y1] = bbox as [number, number, number, number];
  return [x0, PAGE_HEIGHT_PT - y1, x1, PAGE_HEIGHT_PT - y0];
}

/** US Letter in points, the fixture's page box. */
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

import { forwardRef, useRef, useState } from 'react';
import type {
  FormEvent,
  HTMLAttributes,
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  ReactNode,
} from 'react';
import { cx } from '../../utils/cx';
import { useControllable } from '../../utils/useControllable';
import { useId } from '../../hooks/useId';
import { IconButton } from '../../primitives/IconButton';
import { Icon } from '../../primitives/Icon';
import { Input } from '../../primitives/Input';
import { AsyncState } from '../../states/AsyncState';
import { formatTimestamp } from '../models';
import type { BuildModel } from '../models';

const MIN_SCALE = 0.25;
const MAX_SCALE = 4;
const SCALE_STEP = 0.25;

export interface PdfPreviewProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onSelect'> {
  build: BuildModel;
  /** Number of pages in the document being shown. */
  pageCount?: number;
  /** Controlled 1-based page number. */
  page?: number;
  defaultPage?: number;
  onPageChange?: (page: number) => void;
  /** Controlled zoom, where 1 is 100%. */
  scale?: number;
  defaultScale?: number;
  onScaleChange?: (scale: number) => void;
  /** Zoom used by "Fit page". Default 1. */
  fitScale?: number;
  onSearch?: (query: string) => void;
  /**
   * Renders one page. `index` is the 1-based page number shown in the toolbar, matching
   * `onInverseSync`. pdf.js stays in the application; this component only frames it.
   */
  renderPage?: (index: number, scale: number) => ReactNode;
  /** Double-click in the page surface. `x` and `y` are fractions of the page box, 0-1. */
  onInverseSync?: (page: number, x: number, y: number) => void;
  label?: string;
}

function clampScale(value: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.round(value * 100) / 100));
}

/**
 * The PDF pane of the manuscript workspace.
 *
 * It never renders a page itself — pdf.js is an application adapter — and it never claims
 * a PDF is current when it is not: a failed build keeps the last good PDF on screen under
 * a banner that names the time it was produced, and a missing toolchain shows the host's
 * setup guidance instead of a blank pane.
 */
export const PdfPreview = forwardRef<HTMLDivElement, PdfPreviewProps>(function PdfPreview(
  {
    build,
    pageCount,
    page,
    defaultPage = 1,
    onPageChange,
    scale,
    defaultScale = 1,
    onScaleChange,
    fitScale = 1,
    onSearch,
    renderPage,
    onInverseSync,
    label = 'PDF preview',
    className,
    id,
    ...rest
  },
  ref,
) {
  const baseId = useId(id, 'rh-pdfpreview');
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const [query, setQuery] = useState('');
  const [currentPage, setCurrentPage] = useControllable<number>({
    value: page,
    defaultValue: defaultPage,
    onChange: onPageChange,
  });
  const [currentScale, setCurrentScale] = useControllable<number>({
    value: scale,
    defaultValue: defaultScale,
    onChange: onScaleChange,
  });

  const total = pageCount ?? 0;
  const shown = build.pdf ?? build.lastGood;
  const stale = build.pdf ? build.pdf.stale : Boolean(build.lastGood);
  const hasDocument = shown !== undefined;

  const goTo = (next: number): void => {
    const bounded = total > 0 ? Math.min(Math.max(next, 1), total) : Math.max(next, 1);
    if (bounded !== currentPage) setCurrentPage(bounded);
  };

  const onSurfaceKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>): void => {
    switch (event.key) {
      case 'PageDown':
      case 'ArrowRight':
        event.preventDefault();
        goTo(currentPage + 1);
        return;
      case 'PageUp':
      case 'ArrowLeft':
        event.preventDefault();
        goTo(currentPage - 1);
        return;
      case 'Home':
        event.preventDefault();
        goTo(1);
        return;
      case 'End':
        if (total > 0) {
          event.preventDefault();
          goTo(total);
        }
        return;
      default:
    }
  };

  const onSurfaceDoubleClick = (event: ReactMouseEvent<HTMLDivElement>): void => {
    if (!onInverseSync) return;
    const box = surfaceRef.current?.getBoundingClientRect();
    if (!box || box.width === 0 || box.height === 0) {
      onInverseSync(currentPage, 0, 0);
      return;
    }
    onInverseSync(
      currentPage,
      (event.clientX - box.left) / box.width,
      (event.clientY - box.top) / box.height,
    );
  };

  const onSubmitSearch = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    onSearch?.(query);
  };

  const unavailable =
    build.status === 'unavailable' ? (
      <AsyncState
        kind="blocked"
        title="No LaTeX toolchain is available"
        description={
          build.setupGuidance ??
          'Install a LaTeX engine and add it to the allowlist in research.yaml to compile this manuscript.'
        }
        safety={{ draft: 'safe', source: 'safe' }}
      />
    ) : null;

  const empty =
    !hasDocument && !unavailable ? (
      <AsyncState
        kind={build.status === 'failed' || build.status === 'timed_out' ? 'fatal' : 'empty'}
        title={
          build.status === 'failed' || build.status === 'timed_out'
            ? 'No PDF has been produced yet'
            : 'Nothing compiled yet'
        }
        description={
          build.status === 'failed' || build.status === 'timed_out'
            ? 'The first build did not finish, so there is no previous PDF to fall back on. The compiler errors are listed beside this pane.'
            : 'Compile the manuscript to see its pages here.'
        }
        safety={{ draft: 'safe', source: 'safe' }}
      />
    ) : null;

  return (
    <section
      ref={ref}
      id={baseId}
      aria-label={label}
      className={cx('rh-pdf-preview', className)}
      data-stale={stale ? '' : undefined}
      data-status={build.status}
      {...rest}
    >
      <div className="rh-pdf-preview__toolbar">
        <div className="rh-pdf-preview__pager">
          <IconButton
            size="sm"
            icon="chevron-left"
            label="Previous page"
            disabled={!hasDocument || currentPage <= 1}
            onClick={() => goTo(currentPage - 1)}
          />
          <p className="rh-pdf-preview__page-count" aria-live="polite">
            {total > 0 ? `Page ${currentPage} of ${total}` : `Page ${currentPage}`}
          </p>
          <IconButton
            size="sm"
            icon="chevron-right"
            label="Next page"
            disabled={!hasDocument || (total > 0 && currentPage >= total)}
            onClick={() => goTo(currentPage + 1)}
          />
        </div>

        <div className="rh-pdf-preview__zoom">
          <IconButton
            size="sm"
            icon="zoom-out"
            label="Zoom out"
            disabled={currentScale <= MIN_SCALE}
            onClick={() => setCurrentScale(clampScale(currentScale - SCALE_STEP))}
          />
          <p className="rh-pdf-preview__scale">{Math.round(currentScale * 100)}%</p>
          <IconButton
            size="sm"
            icon="zoom-in"
            label="Zoom in"
            disabled={currentScale >= MAX_SCALE}
            onClick={() => setCurrentScale(clampScale(currentScale + SCALE_STEP))}
          />
          <IconButton
            size="sm"
            icon="maximize"
            label="Fit page"
            onClick={() => setCurrentScale(clampScale(fitScale))}
          />
        </div>

        <form className="rh-pdf-preview__search" onSubmit={onSubmitSearch}>
          <Input
            size="sm"
            type="search"
            label="Search the PDF"
            hideLabel
            iconStart="search"
            placeholder="Search the PDF"
            value={query}
            disabled={!onSearch || !hasDocument}
            onChange={(event) => setQuery(event.target.value)}
          />
        </form>
      </div>

      {stale && shown ? (
        <p className="rh-pdf-preview__stale" role="status">
          <Icon name="clock" size={14} />
          <span>
            {`Showing the last successful PDF from ${formatTimestamp(shown.producedAt)}; the current build failed.`}
          </span>
        </p>
      ) : null}

      {unavailable ?? empty ?? (
        <div
          ref={surfaceRef}
          className="rh-pdf-preview__surface"
          role="group"
          aria-label={`${label} pages`}
          tabIndex={0}
          onKeyDown={onSurfaceKeyDown}
          onDoubleClick={onSurfaceDoubleClick}
        >
          {renderPage ? (
            renderPage(currentPage, currentScale)
          ) : (
            <div className="rh-pdf-preview__placeholder rh-surface-paper">
              <p>{`Page ${currentPage}`}</p>
            </div>
          )}
        </div>
      )}

      <p className="rh-pdf-preview__footer">
        {onInverseSync
          ? 'Double-click a page to jump to the matching source line.'
          : 'PDF-to-source navigation is unavailable for this build.'}
      </p>
    </section>
  );
});

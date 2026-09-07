import { forwardRef, useLayoutEffect, useRef } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { useId } from '../../hooks/useId';

/**
 * Where the sticky header ends, in the window, published so a fixed overlay can start there.
 *
 * The same problem `--rh-app-shell-bar-height` solves, one level in: the toast viewport is
 * portalled outside this frame, so it cannot read a value scoped to it, and the top of the
 * window is not empty chrome — it is the page's `h1`, the sentence under it and the toolbar
 * beside them, which is content a researcher is reading rather than content they have read.
 *
 * The *bottom edge*, not the height. Between the shell's bar and this header sits whatever
 * the application put there — the project's breadcrumb, on every research page — and an
 * overlay offset by two known heights would still land on the third. A viewport-relative
 * bottom is the whole answer whatever is stacked above it, and the header is sticky, so the
 * number does not move while the page scrolls.
 *
 * Where there is no layout engine and no `ResizeObserver` — jsdom, SSR — nothing is
 * published and the overlay falls back to clearing the shell's bar alone.
 */
const PAGE_HEADER_BOTTOM = '--rh-page-header-bottom';

export interface FullPageWorkspaceProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  /** The page's `h1`. Rich content is allowed, so this is not the DOM `title` attribute. */
  title: ReactNode;
  /** One line under the title: what this page is for, or what it is scoped to. */
  description?: ReactNode;
  /** Filters, view switches, primary actions. Sits in the sticky header beside the title. */
  toolbar?: ReactNode;
  /** Facets, a summary, a detail panel. */
  sidePanel?: ReactNode;
  sidePanelLabel?: string;
  /** Which edge the side panel sits on. Default `end`. */
  sidePanelPosition?: 'start' | 'end';
  footer?: ReactNode;
  /**
   * Whether the body is still waiting for its first content. The frame is unaffected — the
   * heading, description, toolbar and footer stay exactly where they are — and only the
   * content region is marked `aria-busy`, so a page can load without disappearing.
   */
  busy?: boolean;
  children?: ReactNode;
}

/**
 * The frame for the pages that stay pages — Corpus, Claims, Synthesis, Taxonomy — where a
 * wide table or a long comparison is more useful than an inspector.
 *
 * The header is sticky so the page's identity and its actions survive a long scroll, and
 * the title is the page's `h1`, which is what a screen-reader user lands on after the
 * shell's skip link.
 *
 * That is why loading, empty and failure belong *inside* this frame rather than in place
 * of it: a page that returns its state instead of itself has no heading for the skip link
 * to reach, and a researcher who was reading Claims cannot tell that they still are. The
 * body carries the state; `busy` marks the content region while it does.
 */
export const FullPageWorkspace = forwardRef<HTMLElement, FullPageWorkspaceProps>(
  function FullPageWorkspace(
    {
      title,
      description,
      toolbar,
      sidePanel,
      sidePanelLabel = 'Page panel',
      sidePanelPosition = 'end',
      footer,
      busy = false,
      children,
      className,
      id,
      ...rest
    },
    ref,
  ) {
    const baseId = useId(id, 'rh-fullpage');
    const titleId = `${baseId}-title`;
    const headerRef = useRef<HTMLElement | null>(null);

    useLayoutEffect(() => {
      const node = headerRef.current;
      const view = node?.ownerDocument.defaultView;
      const root = node?.ownerDocument.documentElement;
      if (!node || !root || !view) return;
      let published = '';
      const publish = (): void => {
        const value = `${Math.max(0, Math.round(node.getBoundingClientRect().bottom))}px`;
        if (value === published) return;
        published = value;
        root.style.setProperty(PAGE_HEADER_BOTTOM, value);
      };
      publish();
      // Anything that moves the header's bottom edge: its own content reflowing, the window
      // changing shape, and — for a header sticky inside a scroller that is itself inside a
      // scrolled page — a scroll anywhere above it. The write is skipped when the value has
      // not changed, so the scroll listener costs a rect read.
      view.addEventListener('resize', publish);
      view.addEventListener('scroll', publish, true);
      const observer =
        typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(publish);
      observer?.observe(node);
      return () => {
        view.removeEventListener('resize', publish);
        view.removeEventListener('scroll', publish, true);
        observer?.disconnect();
        root.style.removeProperty(PAGE_HEADER_BOTTOM);
      };
    }, []);

    return (
      <section
        ref={ref}
        id={baseId}
        aria-labelledby={titleId}
        className={cx('rh-full-page', className)}
        data-side={sidePanel === undefined ? undefined : sidePanelPosition}
        {...rest}
      >
        <header className="rh-full-page__header" ref={headerRef}>
          <div className="rh-full-page__heading">
            <h1 className="rh-full-page__title" id={titleId}>
              {title}
            </h1>
            {description === undefined ? null : (
              <p className="rh-full-page__description">{description}</p>
            )}
          </div>
          {toolbar === undefined ? null : (
            <div className="rh-full-page__toolbar">{toolbar}</div>
          )}
        </header>

        <div className="rh-full-page__body">
          <div className="rh-full-page__content" aria-busy={busy ? true : undefined}>
            {children}
          </div>
          {sidePanel === undefined ? null : (
            <aside className="rh-full-page__side" aria-label={sidePanelLabel}>
              {sidePanel}
            </aside>
          )}
        </div>

        {footer === undefined ? null : <footer className="rh-full-page__footer">{footer}</footer>}
      </section>
    );
  },
);

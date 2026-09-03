import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { useId } from '../../hooks/useId';

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
  children?: ReactNode;
}

/**
 * The frame for the pages that stay pages — Corpus, Claims, Synthesis, Taxonomy — where a
 * wide table or a long comparison is more useful than an inspector.
 *
 * The header is sticky so the page's identity and its actions survive a long scroll, and
 * the title is the page's `h1`, which is what a screen-reader user lands on after the
 * shell's skip link.
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
      children,
      className,
      id,
      ...rest
    },
    ref,
  ) {
    const baseId = useId(id, 'rh-fullpage');
    const titleId = `${baseId}-title`;

    return (
      <section
        ref={ref}
        id={baseId}
        aria-labelledby={titleId}
        className={cx('rh-full-page', className)}
        data-side={sidePanel === undefined ? undefined : sidePanelPosition}
        {...rest}
      >
        <header className="rh-full-page__header">
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
          <div className="rh-full-page__content">{children}</div>
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

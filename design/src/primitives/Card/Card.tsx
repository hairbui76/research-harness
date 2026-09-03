import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode, Ref } from 'react';
import { cx } from '../../utils/cx';

export type CardSurface = 'raised' | 'pane' | 'paper';
export type CardPadding = 'none' | 'sm' | 'md' | 'lg';
export type CardElement = 'div' | 'section' | 'article' | 'aside' | 'li';

export interface CardProps extends HTMLAttributes<HTMLElement> {
  /** Element to render. Use `section`/`article` when the card is a landmark or a document. */
  as?: CardElement;
  /**
   * `paper` is the neutral reading surface for source and manuscript content and brings
   * its own ink, so dark-theme text stays legible on a near-white page.
   */
  surface?: CardSurface;
  padding?: CardPadding;
  /** Header row: a title, a status badge, and whatever actions belong to the card. */
  header?: ReactNode;
  footer?: ReactNode;
  /** Darken the hairline on hover. Depth in this system is a border, not a shadow. */
  hoverable?: boolean;
  children?: ReactNode;
}

/**
 * A bordered container. Elevation is expressed as a warm hairline plus a surface change,
 * never as a drop shadow — overlays are the one exception, and they are DS1b's.
 */
export const Card = forwardRef<HTMLElement, CardProps>(function Card(
  {
    as = 'div',
    surface = 'raised',
    padding = 'md',
    header,
    footer,
    hoverable = false,
    className,
    children,
    ...rest
  },
  ref,
) {
  // `as` is a closed union of container elements whose attributes are all a superset of
  // HTMLAttributes; the cast keeps JSX checking one concrete element instead of the
  // intersection of every candidate, which nothing can satisfy.
  const Component = as as 'div';
  return (
    <Component
      ref={ref as Ref<HTMLDivElement>}
      className={cx(
        'rh-card',
        `rh-card--${surface}`,
        `rh-card--pad-${padding}`,
        surface === 'paper' && 'rh-surface-paper',
        hoverable && 'rh-card--hoverable',
        className,
      )}
      {...rest}
    >
      {header === undefined ? null : <div className="rh-card__header">{header}</div>}
      {children === undefined ? null : <div className="rh-card__body">{children}</div>}
      {footer === undefined ? null : <div className="rh-card__footer">{footer}</div>}
    </Component>
  );
});

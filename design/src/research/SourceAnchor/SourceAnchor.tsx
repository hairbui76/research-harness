import { forwardRef } from 'react';
import type { HTMLAttributes, MouseEvent as ReactMouseEvent, ReactNode, Ref } from 'react';
import { Badge } from '../../primitives/Badge';
import { Icon } from '../../primitives/Icon';
import { cx } from '../../utils/cx';
import { formatAnchorTarget } from '../models';
import type { SourceAnchorModel } from '../models';

export type SourceAnchorVariant = 'inline' | 'block';

export interface SourceAnchorProps extends Omit<HTMLAttributes<HTMLElement>, 'onClick'> {
  anchor: SourceAnchorModel;
  /** `block` shows the quote under the target; `inline` shows the target alone. */
  variant?: SourceAnchorVariant;
  /** Open the source at this exact place. Suppresses the link's default navigation. */
  onOpen?: (anchor: SourceAnchorModel) => void;
  /** Label for the open control. Defaults to "Open source at …". */
  openLabel?: string;
  /** Show the quote when the model carries one. Default true for `block`. */
  showQuote?: boolean;
  /** Extra content after the target, e.g. the work title. */
  children?: ReactNode;
}

/**
 * Where a quote actually came from: artifact, page, block, table, character span.
 *
 * The target is mono, because every part of it is a machine identity the researcher can
 * paste back into the graph. A stale anchor says `Stale` in words — the document moved
 * under the recorded position, so the highlighted region may no longer be the quoted text.
 * Freshness is decided by the host's resolver; this only reports it.
 */
export const SourceAnchor = forwardRef<HTMLElement, SourceAnchorProps>(function SourceAnchor(
  { anchor, variant = 'inline', onOpen, openLabel, showQuote, className, children, ...rest },
  ref,
) {
  const target = formatAnchorTarget(anchor);
  const withQuote = (showQuote ?? variant === 'block') && anchor.quote !== undefined;
  const label = openLabel ?? `Open source at ${target}`;

  const handleClick = (event: ReactMouseEvent<HTMLElement>): void => {
    if (onOpen === undefined) return;
    event.preventDefault();
    onOpen(anchor);
  };

  const targetBody = (
    <>
      <Icon name="quote" size={14} />
      <span className="rh-source-anchor__target">{target}</span>
    </>
  );

  const targetNode =
    onOpen !== undefined || anchor.href !== undefined ? (
      anchor.href !== undefined ? (
        <a
          className="rh-source-anchor__open"
          href={anchor.href}
          aria-label={label}
          onClick={handleClick}
        >
          {targetBody}
        </a>
      ) : (
        <button
          type="button"
          className="rh-source-anchor__open"
          aria-label={label}
          onClick={handleClick}
        >
          {targetBody}
        </button>
      )
    ) : (
      <span className="rh-source-anchor__open">{targetBody}</span>
    );

  // A quote is flow content, so the wrapper has to be a block element to hold it legally.
  const Root = withQuote ? 'div' : 'span';

  return (
    <Root
      ref={ref as Ref<HTMLDivElement>}
      className={cx('rh-source-anchor', `rh-source-anchor--${variant}`, className)}
      data-stale={anchor.stale === true ? '' : undefined}
      {...rest}
    >
      <span className="rh-source-anchor__row">
        {targetNode}
        {anchor.stale === true ? <Badge status="stale" size="sm" /> : null}
        {children}
      </span>
      {withQuote ? (
        <blockquote className="rh-source-anchor__quote">{anchor.quote}</blockquote>
      ) : null}
    </Root>
  );
});

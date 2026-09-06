import { forwardRef } from 'react';
import type { CSSProperties, HTMLAttributes } from 'react';
import { useReducedMotion } from '../../hooks/useReducedMotion';
import { cx } from '../../utils/cx';

export type SkeletonShape = 'text' | 'block' | 'circle';

/** Which way a group of bars runs. A row stands for a table row; the default stacks. */
export type SkeletonDirection = 'column' | 'row';

export interface SkeletonProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  width?: number | string;
  height?: number | string;
  shape?: SkeletonShape;
  /** Number of text lines; the last one is rendered short. Only for `shape="text"`. */
  lines?: number;
  /**
   * One bar per entry, at exactly these widths — the cells of a table row, the controls of
   * a toolbar. Takes precedence over `lines`, and nothing is shortened: the caller has
   * already said what each bar stands for.
   */
  widths?: readonly (number | string)[];
  /** Which way a group of bars runs. Default `column`. */
  direction?: SkeletonDirection;
}

function toLength(value: number | string | undefined): string | undefined {
  if (value === undefined) return undefined;
  return typeof value === 'number' ? `${value}px` : value;
}

/**
 * A placeholder for content that has not arrived. It is hidden from assistive technology -
 * the surrounding region announces the loading state through `AsyncState` or an
 * `aria-busy` container - and it stops shimmering under `prefers-reduced-motion`.
 *
 * One bar is the default; `lines` stacks a paragraph, and `widths` with `direction="row"`
 * draws the row of a table, so a page that is still loading can be shaped like the page
 * that is about to arrive rather than like a spinner.
 */
export const Skeleton = forwardRef<HTMLDivElement, SkeletonProps>(function Skeleton(
  {
    width,
    height,
    shape = 'text',
    lines = 1,
    widths,
    direction = 'column',
    className,
    style,
    ...rest
  },
  ref,
) {
  const reducedMotion = useReducedMotion();
  const explicit = widths && widths.length > 0 ? widths : null;
  const count = explicit ? explicit.length : shape === 'text' ? Math.max(1, lines) : 1;

  const baseStyle: CSSProperties = {
    ...style,
    width: toLength(width),
    height: toLength(height),
  };

  if (explicit === null && count === 1) {
    return (
      <div
        ref={ref}
        aria-hidden="true"
        data-shape={shape}
        data-motion={reducedMotion ? 'reduced' : 'full'}
        className={cx('rh-skeleton', className)}
        style={baseStyle}
        {...rest}
      />
    );
  }

  return (
    <div
      ref={ref}
      aria-hidden="true"
      data-direction={direction === 'row' ? 'row' : undefined}
      className={cx('rh-skeleton-group', className)}
      style={style}
      {...rest}
    >
      {Array.from({ length: count }, (_unused, index) => (
        <div
          key={index}
          data-shape={shape}
          data-motion={reducedMotion ? 'reduced' : 'full'}
          className="rh-skeleton"
          style={{
            width: explicit
              ? toLength(explicit[index])
              : index === count - 1
                ? '60%'
                : toLength(width),
            height: toLength(height),
          }}
        />
      ))}
    </div>
  );
});

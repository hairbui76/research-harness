import { forwardRef } from 'react';
import type { CSSProperties, HTMLAttributes } from 'react';
import { useReducedMotion } from '../../hooks/useReducedMotion';
import { cx } from '../../utils/cx';

export type SkeletonShape = 'text' | 'block' | 'circle';

export interface SkeletonProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  width?: number | string;
  height?: number | string;
  shape?: SkeletonShape;
  /** Number of text lines; the last one is rendered short. Only for `shape="text"`. */
  lines?: number;
}

function toLength(value: number | string | undefined): string | undefined {
  if (value === undefined) return undefined;
  return typeof value === 'number' ? `${value}px` : value;
}

/**
 * A placeholder for content that has not arrived. It is hidden from assistive technology -
 * the surrounding region announces the loading state through `AsyncState` or an
 * `aria-busy` container - and it stops shimmering under `prefers-reduced-motion`.
 */
export const Skeleton = forwardRef<HTMLDivElement, SkeletonProps>(function Skeleton(
  { width, height, shape = 'text', lines = 1, className, style, ...rest },
  ref,
) {
  const reducedMotion = useReducedMotion();
  const count = shape === 'text' ? Math.max(1, lines) : 1;

  const baseStyle: CSSProperties = {
    ...style,
    width: toLength(width),
    height: toLength(height),
  };

  if (count === 1) {
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
      className={cx('rh-skeleton-group', className)}
      style={style}
      {...rest}
    >
      {Array.from({ length: count }, (_unused, index) => (
        <div
          key={index}
          data-shape="text"
          data-motion={reducedMotion ? 'reduced' : 'full'}
          className="rh-skeleton"
          style={{
            width: index === count - 1 ? '60%' : toLength(width),
            height: toLength(height),
          }}
        />
      ))}
    </div>
  );
});

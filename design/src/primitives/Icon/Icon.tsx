import { forwardRef } from 'react';
import type { SVGProps } from 'react';
import { cx } from '../../utils/cx';
import { icons } from './icons';
import type { IconName } from './icons';

/** The only sizes the system draws. Icons sit on the 2px stroke grid at each of them. */
export const ICON_SIZES = [14, 16, 18, 20, 24] as const;
export type IconSize = (typeof ICON_SIZES)[number];

export interface IconProps
  extends Omit<SVGProps<SVGSVGElement>, 'ref' | 'name' | 'width' | 'height'> {
  /** Registry name, e.g. `chevron-down`. */
  name: IconName;
  /** 14 beside 14px text, 16 in buttons, 18-20 in nav and panel headers, 24 as a mark. */
  size?: IconSize;
  /**
   * Accessible name. Omit it for an icon that only repeats adjacent text: the icon is then
   * hidden from assistive technology. Supply it when the icon is the only carrier of the
   * meaning, and it is announced as an image.
   */
  label?: string;
}

/**
 * The single choke point for iconography. Product code never inlines an `<svg>`, so
 * sizing, colour and the decorative/meaningful distinction stay in one place.
 */
export const Icon = forwardRef<SVGSVGElement, IconProps>(function Icon(
  { name, size = 16, label, className, ...rest },
  ref,
) {
  const Glyph = icons[name];
  const decorative = label === undefined;
  return (
    <Glyph
      ref={ref}
      className={cx('rh-icon', className)}
      width={size}
      height={size}
      aria-hidden={decorative ? true : undefined}
      role={decorative ? undefined : 'img'}
      aria-label={label}
      focusable="false"
      data-icon={name}
      {...rest}
    />
  );
});

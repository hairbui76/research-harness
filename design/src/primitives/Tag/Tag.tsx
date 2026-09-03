import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { useControllable } from '../../utils/useControllable';
import { Icon } from '../Icon';
import type { IconName } from '../Icon';

export type TagSize = 'sm' | 'md';

export interface TagProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'onSelect'> {
  /** Leading glyph, e.g. `tag`, `at-sign`, `file-text`. */
  icon?: IconName;
  /** Controlled pressed state. Requires `onSelect` to be useful. */
  selected?: boolean;
  /** Starting state when the tag keeps its own. */
  defaultSelected?: boolean;
  /** Makes the tag a toggle. Called with the state it is moving to. */
  onSelect?: (selected: boolean) => void;
  /** Renders a remove control. Called when the researcher dismisses the tag. */
  onRemove?: () => void;
  /** Accessible name for the remove control; defaults to `Remove <text>`. */
  removeLabel?: string;
  disabled?: boolean;
  size?: TagSize;
  children: ReactNode;
}

/**
 * A selectable and/or removable chip: filters, `@` references, attachment names.
 *
 * `Badge` is the read-only sibling. The two are kept apart on purpose — a researcher
 * should never have to guess whether a coloured chip is something they can act on.
 */
export const Tag = forwardRef<HTMLSpanElement, TagProps>(function Tag(
  {
    icon,
    selected,
    defaultSelected = false,
    onSelect,
    onRemove,
    removeLabel,
    disabled = false,
    size = 'md',
    className,
    children,
    ...rest
  },
  ref,
) {
  const [isSelected, setSelected] = useControllable<boolean>({
    value: selected,
    defaultValue: defaultSelected,
    onChange: onSelect,
  });
  const iconSize = size === 'sm' ? 14 : 16;
  const classes = cx(
    'rh-tag',
    `rh-tag--${size}`,
    isSelected && 'is-selected',
    disabled && 'is-disabled',
    className,
  );
  const body = (
    <>
      {icon ? <Icon name={icon} size={iconSize} /> : null}
      <span className="rh-tag__label">{children}</span>
    </>
  );

  return (
    <span ref={ref} className={classes} data-selected={isSelected || undefined} {...rest}>
      {onSelect ? (
        <button
          type="button"
          className="rh-tag__body rh-tag__body--button"
          aria-pressed={isSelected}
          disabled={disabled}
          onClick={() => setSelected(!isSelected)}
        >
          {body}
        </button>
      ) : (
        <span className="rh-tag__body">{body}</span>
      )}
      {onRemove ? (
        <button
          type="button"
          className="rh-tag__remove"
          aria-label={removeLabel ?? `Remove ${typeof children === 'string' ? children : 'tag'}`}
          disabled={disabled}
          onClick={onRemove}
        >
          <Icon name="x" size={14} />
        </button>
      ) : null}
    </span>
  );
});

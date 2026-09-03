import { forwardRef } from 'react';
import type { AnchorHTMLAttributes, MouseEvent as ReactMouseEvent, Ref } from 'react';
import { Icon } from '../../primitives/Icon';
import { Tooltip } from '../../primitives/Tooltip';
import { cx } from '../../utils/cx';
import { AuthorityBadge } from '../AuthorityBadge';
import { ENTITY_KIND_META, RESOLUTION_META } from '../models';
import type { EntityRefModel } from '../models';

export type EntityRefElement = 'button' | 'a';
export type EntityRefSize = 'sm' | 'md';

export interface EntityRefProps
  extends Omit<AnchorHTMLAttributes<HTMLElement>, 'children' | 'href' | 'onClick' | 'type'> {
  /** The reference as the resolver reported it. Named `entity` because `ref` is React's. */
  entity: EntityRefModel;
  /**
   * Force the element. The default is `a` when the model carries an `rh://` href and
   * `button` otherwise; with neither an href nor `onOpen` the chip is static text.
   */
  as?: EntityRefElement;
  /**
   * Open the referenced object. When it is set on a link the default navigation is
   * suppressed, so a host that routes `rh://` itself does not also get a page load.
   */
  onOpen?: (entity: EntityRefModel) => void;
  /** Show the human label beside the id. Default true. */
  showLabel?: boolean;
  /** Show the authority badge when the model carries one. Default true. */
  showAuthority?: boolean;
  /** Attach the kind and resolution explanation as a tooltip. Default true. */
  describe?: boolean;
  size?: EntityRefSize;
}

/**
 * An inline reference chip: `@W0017`, `@E0482`, `@CS0001`.
 *
 * The id is set in mono because it is a machine identity a researcher copies and types.
 * Resolution and authority are carried by an icon *and* a word — a chip that is stale,
 * private, unresolved or broken says so in text, so nothing depends on noticing a colour
 * or hovering. The component resolves nothing itself: `resolution` is what the host's
 * resolver returned at render time.
 */
export const EntityRef = forwardRef<HTMLElement, EntityRefProps>(function EntityRef(
  {
    entity,
    as,
    onOpen,
    showLabel = true,
    showAuthority = true,
    describe = true,
    size = 'md',
    className,
    ...rest
  },
  ref,
) {
  const kind = ENTITY_KIND_META[entity.kind];
  const resolution = RESOLUTION_META[entity.resolution];
  const wanted = as ?? (entity.href !== undefined ? 'a' : 'button');
  const interactive = onOpen !== undefined || entity.href !== undefined;
  const element: 'a' | 'button' | 'span' = !interactive
    ? 'span'
    : wanted === 'a' && entity.href === undefined
      ? 'button'
      : wanted;

  const body = (
    <>
      <Icon className="rh-entity-ref__kind" name={kind.icon} size={size === 'sm' ? 14 : 16} />
      <span className="rh-entity-ref__id">{entity.id}</span>
      {showLabel && entity.label !== undefined ? (
        <span className="rh-entity-ref__label">{entity.label}</span>
      ) : null}
      {showAuthority && entity.authority !== undefined ? (
        <AuthorityBadge className="rh-entity-ref__authority" authority={entity.authority} size="sm" />
      ) : null}
      {entity.resolution === 'resolved' ? null : (
        <span className="rh-entity-ref__resolution">
          <Icon name={resolution.icon} size={14} />
          <span>{resolution.label}</span>
        </span>
      )}
    </>
  );

  const classes = cx(
    'rh-entity-ref',
    `rh-entity-ref--${size}`,
    interactive && 'rh-entity-ref--interactive',
    className,
  );
  const shared = {
    className: classes,
    'data-kind': entity.kind,
    'data-resolution': entity.resolution,
    'data-authority': entity.authority,
    ...rest,
  };

  const handleClick = (event: ReactMouseEvent<HTMLElement>): void => {
    if (onOpen === undefined) return;
    event.preventDefault();
    onOpen(entity);
  };

  const chip =
    element === 'span' ? (
      <span ref={ref as Ref<HTMLSpanElement>} {...shared}>
        {body}
      </span>
    ) : element === 'a' ? (
      <a ref={ref as Ref<HTMLAnchorElement>} href={entity.href} onClick={handleClick} {...shared}>
        {body}
      </a>
    ) : (
      <button ref={ref as Ref<HTMLButtonElement>} type="button" onClick={handleClick} {...shared}>
        {body}
      </button>
    );

  if (!describe || element === 'span') return chip;
  return (
    <Tooltip content={`${kind.label}. ${resolution.description}`}>{chip}</Tooltip>
  );
});

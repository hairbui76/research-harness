import { forwardRef } from 'react';
import type { HTMLAttributes } from 'react';
import { Icon } from '../../primitives/Icon';
import { cx } from '../../utils/cx';
import { EntityRef } from '../EntityRef';
import type { EntityRefModel, ProvenancePathModel } from '../models';

export type ProvenancePathOrientation = 'horizontal' | 'vertical';

export interface ProvenancePathProps extends Omit<HTMLAttributes<HTMLElement>, 'children'> {
  path: ProvenancePathModel;
  /** Open any step. Each step is a keyboard-reachable control. */
  onOpen?: (entity: EntityRefModel) => void;
  /** `vertical` stacks the steps, for a narrow inspector pane. */
  orientation?: ProvenancePathOrientation;
  /** Accessible name for the list. Defaults to "Provenance". */
  label?: string;
}

/**
 * Claim → Evidence → Artifact, in the order the project derived it.
 *
 * It is an ordered list, so assistive technology reads "1 of 4" rather than counting
 * arrows, and the relation between two steps (`supports`, `anchored_at`) is written out
 * between them rather than implied by an arrow glyph alone. Every step is an `EntityRef`,
 * so a broken or stale link in the middle of a chain is visible where it breaks.
 */
export const ProvenancePath = forwardRef<HTMLElement, ProvenancePathProps>(function ProvenancePath(
  { path, onOpen, orientation = 'horizontal', label = 'Provenance', className, ...rest },
  ref,
) {
  return (
    <nav
      ref={ref}
      aria-label={label}
      className={cx('rh-provenance-path', `rh-provenance-path--${orientation}`, className)}
      {...rest}
    >
      <ol className="rh-provenance-path__steps">
        {path.steps.map((step, index) => (
          <li key={`${step.ref.id}-${index}`} className="rh-provenance-path__step">
            {index > 0 ? (
              <span className="rh-provenance-path__relation">
                <Icon
                  name={orientation === 'vertical' ? 'arrow-down' : 'arrow-right'}
                  size={14}
                />
                {step.relation !== undefined ? <span>{step.relation}</span> : null}
              </span>
            ) : null}
            <EntityRef entity={step.ref} onOpen={onOpen} size="sm" />
          </li>
        ))}
      </ol>
    </nav>
  );
});

import { forwardRef } from 'react';
import type { HTMLAttributes, ReactElement, ReactNode } from 'react';
import { useControllableState } from '../../hooks/useControllableState';
import { useId } from '../../hooks/useId';
import { Badge } from '../../primitives/Badge';
import { Card } from '../../primitives/Card';
import { Icon } from '../../primitives/Icon';
import { Progress } from '../../primitives/Progress';
import { cx } from '../../utils/cx';
import { AuthorityBadge } from '../AuthorityBadge';
import { EntityRef } from '../EntityRef';
import { CONTEXT_CLASSES, CONTEXT_CLASS_META, EGRESS_META, OMISSION_REASON_META } from '../models';
import type {
  ContextClass,
  ContextItem,
  ContextReceiptModel,
  EntityRefModel,
  OmittedContextItem,
} from '../models';

export interface ContextReceiptProps extends Omit<HTMLAttributes<HTMLElement>, 'children' | 'title'> {
  receipt: ContextReceiptModel;
  /** Controlled expansion. */
  open?: boolean;
  /**
   * Starting expansion. Defaults to open whenever anything was omitted: a receipt whose
   * omissions are folded away is the one thing this component must never be.
   */
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Open any referenced object from the included or omitted list. */
  onOpenRef?: (entity: EntityRefModel) => void;
  /** Heading text. Defaults to "Context used". */
  title?: ReactNode;
}

function groupByClass<T extends ContextItem>(items: readonly T[]): Array<[ContextClass, T[]]> {
  const groups: Array<[ContextClass, T[]]> = [];
  for (const cls of CONTEXT_CLASSES) {
    const matching = items.filter((item) => item.cls === cls);
    if (matching.length > 0) groups.push([cls, matching]);
  }
  return groups;
}

function tokenText(tokens: number | undefined): ReactNode {
  if (tokens === undefined) return null;
  return <span className="rh-context-receipt__tokens">{tokens.toLocaleString('en-US')} tok</span>;
}

interface ItemRowProps {
  item: ContextItem;
  onOpenRef?: (entity: EntityRefModel) => void;
  children?: ReactNode;
}

function ItemRow({ item, onOpenRef, children }: ItemRowProps): ReactElement {
  const authority = item.authority ?? item.ref.authority;
  return (
    <li className="rh-context-receipt__item">
      <EntityRef entity={item.ref} onOpen={onOpenRef} size="sm" showAuthority={false} />
      {authority !== undefined ? <AuthorityBadge authority={authority} size="sm" /> : null}
      {tokenText(item.tokens)}
      {item.sourcePointer !== undefined ? (
        <span className="rh-context-receipt__pointer">{item.sourcePointer}</span>
      ) : null}
      {children}
    </li>
  );
}

/**
 * What one model call did and did not receive.
 *
 * This is the component the product's honesty rests on: it names the provider and the
 * effective egress class, shows how the token budget was spent by context class, lists
 * every included item with its authority and source pointer, and — crucially — lists every
 * omission with the reason it was omitted. The omitted list is never collapsed away by
 * default: a receipt that hides what the model did not see is worse than no receipt.
 *
 * It computes nothing about what *should* have been sent. The pack was assembled by the
 * daemon; this reads it back.
 */
export const ContextReceipt = forwardRef<HTMLElement, ContextReceiptProps>(function ContextReceipt(
  { receipt, open, defaultOpen, onOpenChange, onOpenRef, title = 'Context used', className, ...rest },
  ref,
) {
  const baseId = useId(undefined, 'rh-context-receipt');
  const bodyId = `${baseId}-body`;
  const [isOpen, setOpen] = useControllableState<boolean>({
    value: open,
    defaultValue: defaultOpen ?? receipt.omitted.length > 0,
    onChange: onOpenChange,
  });

  const egress = EGRESS_META[receipt.egressClass];
  const used = receipt.allocation.reduce((total, entry) => total + entry.tokens, 0);
  const included = groupByClass<ContextItem>(receipt.included);
  const omitted = groupByClass<OmittedContextItem>(receipt.omitted);

  return (
    <Card
      ref={ref}
      as="section"
      surface="pane"
      padding="sm"
      className={cx('rh-context-receipt', className)}
      data-egress={receipt.egressClass}
      data-open={isOpen || undefined}
      header={
        <>
          <button
            type="button"
            className="rh-context-receipt__toggle"
            aria-expanded={isOpen}
            aria-controls={bodyId}
            onClick={() => setOpen(!isOpen)}
          >
            <Icon name={isOpen ? 'chevron-down' : 'chevron-right'} size={16} />
            <span>{title}</span>
          </button>
          <span className="rh-context-receipt__summary">
            <span className="rh-context-receipt__pack">{receipt.packId}</span>
            <span>{receipt.provider}</span>
            <span className="rh-context-receipt__model">{receipt.model}</span>
            <Badge
              tone={receipt.egressClass === 'external' ? 'warning' : 'neutral'}
              icon={egress.icon}
              size="sm"
            >
              {egress.label}
            </Badge>
            <span className="rh-context-receipt__tokens">
              {used.toLocaleString('en-US')} / {receipt.tokenBudget.toLocaleString('en-US')} tok
            </span>
            {receipt.omitted.length > 0 ? (
              <Badge tone="warning" icon="alert-triangle" size="sm">
                {receipt.omitted.length} omitted
              </Badge>
            ) : null}
          </span>
        </>
      }
      {...rest}
    >
      <div id={bodyId} className="rh-context-receipt__body" hidden={!isOpen}>
        <p className="rh-context-receipt__egress-note">{egress.hint}</p>

        <section className="rh-context-receipt__section">
          <h3 className="rh-text-label">Token budget by class</h3>
          <ul className="rh-context-receipt__allocation">
            {receipt.allocation.map((entry) => (
              <li key={entry.cls} className="rh-context-receipt__allocation-row">
                <Progress
                  value={entry.tokens}
                  max={receipt.tokenBudget}
                  label={CONTEXT_CLASS_META[entry.cls].label}
                  valueText={`${entry.tokens.toLocaleString('en-US')} of ${receipt.tokenBudget.toLocaleString('en-US')} tokens`}
                  showValue
                  size="sm"
                  tone="neutral"
                />
              </li>
            ))}
          </ul>
        </section>

        <section className="rh-context-receipt__section">
          <h3 className="rh-text-label">
            Included ({receipt.included.length})
          </h3>
          {included.length === 0 ? (
            <p className="rh-context-receipt__none">Nothing was included in this pack.</p>
          ) : (
            included.map(([cls, items]) => (
              <div key={cls} className="rh-context-receipt__group">
                <h4 className="rh-context-receipt__group-label">
                  <Icon name={CONTEXT_CLASS_META[cls].icon} size={14} />
                  <span>{CONTEXT_CLASS_META[cls].label}</span>
                </h4>
                <ul className="rh-context-receipt__items">
                  {items.map((item, index) => (
                    <ItemRow key={`${item.ref.id}-${index}`} item={item} onOpenRef={onOpenRef} />
                  ))}
                </ul>
              </div>
            ))
          )}
        </section>

        <section className="rh-context-receipt__section" data-omitted="">
          <h3 className="rh-text-label">
            Omitted ({receipt.omitted.length})
          </h3>
          {omitted.length === 0 ? (
            <p className="rh-context-receipt__none">Nothing was left out of this pack.</p>
          ) : (
            omitted.map(([cls, items]) => (
              <div key={cls} className="rh-context-receipt__group">
                <h4 className="rh-context-receipt__group-label">
                  <Icon name={CONTEXT_CLASS_META[cls].icon} size={14} />
                  <span>{CONTEXT_CLASS_META[cls].label}</span>
                </h4>
                <ul className="rh-context-receipt__items">
                  {items.map((item, index) => (
                    <ItemRow key={`${item.ref.id}-${index}`} item={item} onOpenRef={onOpenRef}>
                      <span className="rh-context-receipt__reason">
                        <Icon name="alert-triangle" size={14} />
                        <span>{OMISSION_REASON_META[item.reason].label}</span>
                      </span>
                      <span className="rh-context-receipt__detail">
                        {item.detail ?? OMISSION_REASON_META[item.reason].description}
                      </span>
                    </ItemRow>
                  ))}
                </ul>
              </div>
            ))
          )}
        </section>
      </div>
    </Card>
  );
});

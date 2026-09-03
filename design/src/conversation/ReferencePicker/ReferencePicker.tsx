import { forwardRef, useMemo } from 'react';
import type { ReactNode } from 'react';
import { Combobox } from '../../primitives/Combobox';
import type { ComboboxItem } from '../../primitives/Combobox';
import { Icon } from '../../primitives/Icon';
import { AuthorityBadge } from '../../research/AuthorityBadge';
import { ENTITY_KINDS, ENTITY_KIND_META, RESOLUTION_META } from '../../research/models';
import type { EntityRefModel } from '../../research/models';
import { cx } from '../../utils/cx';

export interface ReferencePickerProps {
  /**
   * The matches, already found by the host. Matching is a graph query — prefix completion
   * over `W0017`, fuzzy title search, privacy filtering — and it belongs in the daemon.
   */
  results: readonly EntityRefModel[];
  query: string;
  onQueryChange: (query: string) => void;
  onSelect: (entity: EntityRefModel) => void;
  loading?: boolean;
  /** Accessible name for the text box and the list. */
  label?: string;
  placeholder?: string;
  emptyMessage?: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  autoFocus?: boolean;
  className?: string;
}

/**
 * The `@` reference picker: search the research graph and insert a structured token.
 *
 * Rows are grouped by kind and carry the id in mono, the title, the authority and — this
 * is the point — the resolution state. A broken, stale or private reference is still
 * selectable, because a researcher may well want to write about one; it is simply marked,
 * so nobody inserts a dangling `@E0482` believing it resolved.
 */
export const ReferencePicker = forwardRef<HTMLInputElement, ReferencePickerProps>(
  function ReferencePicker(
    {
      results,
      query,
      onQueryChange,
      onSelect,
      loading = false,
      label = 'Insert a research reference',
      placeholder = 'Search works, evidence, claims…',
      emptyMessage = 'No references match',
      open,
      defaultOpen,
      onOpenChange,
      autoFocus,
      className,
    },
    ref,
  ) {
    // The Combobox groups consecutive runs, so results are ordered by kind first.
    const items = useMemo<ComboboxItem<EntityRefModel>[]>(() => {
      const order = new Map(ENTITY_KINDS.map((kind, index) => [kind, index]));
      return [...results]
        .sort((a, b) => (order.get(a.kind) ?? 0) - (order.get(b.kind) ?? 0))
        .map((entity) => ({
          id: entity.id,
          label: entity.label ?? entity.id,
          value: entity,
          group: ENTITY_KIND_META[entity.kind].plural,
        }));
    }, [results]);

    return (
      <Combobox<EntityRefModel>
        ref={ref}
        className={cx('rh-reference-picker', className)}
        items={items}
        label={label}
        placeholder={placeholder}
        query={query}
        onQueryChange={onQueryChange}
        onChange={(item) => {
          if (item?.value !== undefined) onSelect(item.value);
        }}
        open={open}
        defaultOpen={defaultOpen}
        onOpenChange={onOpenChange}
        loading={loading}
        emptyMessage={emptyMessage}
        selectionBehaviour="clear"
        openOnFocus
        autoFocus={autoFocus}
        renderItem={(item) => {
          const entity = item.value;
          if (entity === undefined) return item.label;
          const resolution = RESOLUTION_META[entity.resolution];
          return (
            <span className="rh-reference-picker__row" data-resolution={entity.resolution}>
              <Icon name={ENTITY_KIND_META[entity.kind].icon} size={14} />
              <span className="rh-reference-picker__id">{entity.id}</span>
              <span className="rh-reference-picker__label">{entity.label ?? entity.id}</span>
              {entity.authority !== undefined ? (
                <AuthorityBadge authority={entity.authority} size="sm" />
              ) : null}
              {entity.resolution === 'resolved' ? null : (
                <span className="rh-reference-picker__resolution">
                  <Icon name={resolution.icon} size={14} />
                  <span>{resolution.label}</span>
                </span>
              )}
            </span>
          );
        }}
      />
    );
  },
);

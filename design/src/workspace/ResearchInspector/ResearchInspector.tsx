import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { useControllable } from '../../utils/useControllable';
import { Button } from '../../primitives/Button';
import { Icon } from '../../primitives/Icon';
import { Tabs } from '../../primitives/Tabs';
import { AsyncState } from '../../states/AsyncState';
import { INSPECTOR_TABS, INSPECTOR_TAB_META, SELECTION_KIND_META } from '../models';
import type { InspectorRef, InspectorSelection, InspectorTab } from '../models';

export interface ResearchInspectorProps extends Omit<HTMLAttributes<HTMLElement>, 'onSelect'> {
  tab?: InspectorTab;
  defaultTab?: InspectorTab;
  onTabChange?: (tab: InspectorTab) => void;
  /** Badge counts per tab. A tab with no entry shows no count. */
  counts?: Partial<Record<InspectorTab, number>>;
  /** Which message, reference, attachment or selection the inspector is following. */
  selection?: InspectorSelection;
  /** Toggle following. Called with the state the inspector is moving to. */
  onFollow?: (following: boolean) => void;
  following?: boolean;
  /** Content per tab. A tab with no content renders an empty state. */
  panels?: Partial<Record<InspectorTab, ReactNode>>;
  /**
   * Two-way navigation: the header's Open button and any reference a panel hands back
   * resolve through the application, which owns deep links and authority checks.
   */
  onNavigate?: (ref: InspectorRef) => void;
  label?: string;
}

/**
 * The right pane: Context, Evidence, Claims, Review inbox, Conflicts and Stale for
 * whatever the researcher is looking at.
 *
 * The header states what the inspector follows in words, so "why am I seeing this?" is
 * never a guess, and `onNavigate` is the other half of the two-way link: a reference in
 * the transcript opens its object here, and the object opens the message it came from.
 * Panels are slots; the inspector owns no research content of its own.
 */
export const ResearchInspector = forwardRef<HTMLElement, ResearchInspectorProps>(
  function ResearchInspector(
    {
      tab,
      defaultTab = 'context',
      onTabChange,
      counts,
      selection,
      onFollow,
      following = true,
      panels,
      onNavigate,
      label = 'Research inspector',
      className,
      ...rest
    },
    ref,
  ) {
    const [currentTab, setTab] = useControllable<InspectorTab>({
      value: tab,
      defaultValue: defaultTab,
      onChange: onTabChange,
    });
    const selectionMeta = selection ? SELECTION_KIND_META[selection.kind] : undefined;

    return (
      <section
        ref={ref}
        aria-label={label}
        className={cx('rh-research-inspector', className)}
        data-tab={currentTab}
        {...rest}
      >
        <header className="rh-research-inspector__header">
          {selection && selectionMeta ? (
            <>
              <p className="rh-research-inspector__following">
                <Icon name={selectionMeta.icon} size={14} />
                <span className="rh-research-inspector__following-kind">
                  {following ? `Following ${selectionMeta.label.toLowerCase()}` : 'Pinned to'}
                </span>
                <span className="rh-research-inspector__following-label">{selection.label}</span>
              </p>
              {selection.detail ? (
                <p className="rh-research-inspector__detail">{selection.detail}</p>
              ) : null}
              <div className="rh-research-inspector__header-actions">
                {selection.ref && onNavigate ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    iconStart="external-link"
                    onClick={() => onNavigate(selection.ref as InspectorRef)}
                  >
                    {`Open ${selectionMeta.label.toLowerCase()}`}
                  </Button>
                ) : null}
                {onFollow ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    iconStart={following ? 'eye-off' : 'eye'}
                    aria-pressed={following}
                    onClick={() => onFollow(!following)}
                  >
                    {following ? 'Stop following' : 'Follow selection'}
                  </Button>
                ) : null}
              </div>
            </>
          ) : (
            <p className="rh-research-inspector__following" data-empty="">
              <Icon name="circle-dashed" size={14} />
              <span>Nothing selected. Choose a message, reference or attachment.</span>
            </p>
          )}
        </header>

        <Tabs
          className="rh-research-inspector__tabs"
          value={currentTab}
          onValueChange={(next) => setTab(next as InspectorTab)}
          activation="manual"
        >
          <Tabs.List aria-label={label}>
            {INSPECTOR_TABS.map((name) => {
              const meta = INSPECTOR_TAB_META[name];
              const count = counts?.[name];
              return (
                <Tabs.Tab key={name} value={name} className="rh-research-inspector__tab">
                  <Icon name={meta.icon} size={14} />
                  <span>{meta.label}</span>
                  {count === undefined ? null : (
                    <span className="rh-research-inspector__tab-count">
                      {count}
                      <span className="rh-visually-hidden">{` ${meta.label} items`}</span>
                    </span>
                  )}
                </Tabs.Tab>
              );
            })}
          </Tabs.List>

          {INSPECTOR_TABS.map((name) => (
            <Tabs.Panel key={name} value={name} className="rh-research-inspector__panel">
              {panels?.[name] ?? (
                <AsyncState
                  kind="empty"
                  compact
                  title={`No ${INSPECTOR_TAB_META[name].label.toLowerCase()} for this selection`}
                  description="Selecting a message, reference or attachment fills this tab."
                />
              )}
            </Tabs.Panel>
          ))}
        </Tabs>
      </section>
    );
  },
);

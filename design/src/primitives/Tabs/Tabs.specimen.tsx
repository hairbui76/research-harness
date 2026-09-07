import type { ReactNode } from 'react';
import { Icon } from '../Icon';
import { Tabs } from './Tabs';

export const title = 'Tabs in a narrow pane';

/** The research inspector's six tabs, at the width the inspector actually gets. */
const INSPECTOR = [
  { value: 'context', label: 'Context', icon: 'list' },
  { value: 'evidence', label: 'Evidence', icon: 'quote' },
  { value: 'claims', label: 'Claims', icon: 'bookmark' },
  { value: 'review', label: 'Review inbox', icon: 'inbox' },
  { value: 'conflicts', label: 'Conflicts', icon: 'alert-triangle' },
  { value: 'stale', label: 'Stale', icon: 'clock' },
] as const;

function Pane({ children }: { children: ReactNode }): ReactNode {
  return (
    <div
      style={{
        inlineSize: 352,
        maxInlineSize: '100%',
        border: 'var(--rh-border-width) solid var(--rh-border-subtle)',
        borderRadius: 'var(--rh-radius-card)',
        background: 'var(--rh-surface-pane)',
        padding: 'var(--rh-space-2)',
      }}
    >
      {children}
    </div>
  );
}

function Strip({ overflow }: { overflow?: 'scroll' | 'wrap' }): ReactNode {
  return (
    <Tabs defaultValue="context" activation="manual">
      <Tabs.List aria-label="Research inspector" overflow={overflow}>
        {INSPECTOR.map((tab) => (
          <Tabs.Tab key={tab.value} value={tab.value}>
            <Icon name={tab.icon} size={14} />
            <span>{tab.label}</span>
          </Tabs.Tab>
        ))}
      </Tabs.List>
      {INSPECTOR.map((tab) => (
        <Tabs.Panel key={tab.value} value={tab.value}>
          {`${tab.label} for this selection.`}
        </Tabs.Panel>
      ))}
    </Tabs>
  );
}

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'Six tabs in a 352px pane — the strip says where the rest are',
    render: () => (
      <Pane>
        <Strip />
      </Pane>
    ),
  },
  {
    name: 'The same six, wrapped, where vertical room is cheaper than a scroller',
    render: () => (
      <Pane>
        <Strip overflow="wrap" />
      </Pane>
    ),
  },
];

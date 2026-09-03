import { useState } from 'react';
import type { ReactElement } from 'react';
import { ThemeProvider, useTheme } from './ThemeProvider';
import { Badge } from '../../primitives/Badge';
import { Button } from '../../primitives/Button';
import { Card } from '../../primitives/Card';

function Readout(): ReactElement {
  const { theme, density, setTheme, setDensity, prefersReducedMotion } = useTheme();
  return (
    <Card
      header={<strong>A scoped appearance</strong>}
      footer={
        <span style={{ color: 'var(--rh-text-muted)' }}>
          {prefersReducedMotion
            ? 'Reduced motion is on: transitions collapse to a single frame.'
            : 'Reduced motion is off.'}
        </span>
      }
    >
      <p style={{ marginTop: 0 }}>{`theme: ${theme} · density: ${density}`}</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Button size="sm" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
          Toggle theme
        </Button>
        <Button
          size="sm"
          onClick={() => setDensity(density === 'comfortable' ? 'compact' : 'comfortable')}
        >
          Toggle density
        </Button>
        <Badge status="private" size="sm" />
      </div>
    </Card>
  );
}

/**
 * A provider scoped to one subtree.
 *
 * `target` is the escape hatch that makes this possible: the attributes land on the
 * wrapper rather than on `document.documentElement`, so this demo can disagree with the
 * gallery's own theme without fighting it. `storageKey: null` keeps it out of the
 * researcher's stored preference as well.
 */
function Scoped(): ReactElement {
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  return (
    <div ref={setHost} style={{ inlineSize: 360, padding: 'var(--rh-space-3)', background: 'var(--rh-surface-canvas)' }}>
      <ThemeProvider target={host} storageKey={null} defaultTheme="light" defaultDensity="compact">
        <Readout />
      </ThemeProvider>
    </div>
  );
}

export const title = 'ThemeProvider';

export const specimens = [
  {
    name: 'Scoped to a subtree — light and compact inside a dark page',
    render: () => <Scoped />,
  },
];

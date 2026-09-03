import { FullPageWorkspace } from './FullPageWorkspace';
import { Badge } from '../../primitives/Badge';
import { Button } from '../../primitives/Button';
import { Input } from '../../primitives/Input';

const rows = [
  { id: 'C0041', text: 'Tolerance rises with acclimation temperature', status: 'accepted' as const },
  { id: 'C0042', text: 'The effect doubles under sustained load', status: 'candidate' as const },
  { id: 'C0043', text: 'Recovery is complete within 48 h', status: 'contested' as const },
];

export const title = 'FullPageWorkspace';

export const specimens = [
  {
    name: 'A research page with a toolbar and a side panel',
    render: () => (
      <div
        className="gallery-block"
        style={{
          blockSize: '30rem',
          border: '1px solid var(--rh-border-subtle)',
          borderRadius: 'var(--rh-radius-card)',
          overflow: 'hidden',
        }}
      >
        <FullPageWorkspace
          title="Claims"
          description="Every claim in this project, with the evidence that supports it."
          toolbar={
            <>
              <Input size="sm" label="Filter" hideLabel iconStart="search" placeholder="Filter claims" />
              <Button size="sm" variant="secondary" iconStart="filter">
                Facets
              </Button>
              <Button size="sm" variant="primary" iconStart="plus">
                New claim
              </Button>
            </>
          }
          sidePanel={
            <div data-density="compact">
              <h3 style={{ marginTop: 0 }}>Authority</h3>
              <ul style={{ margin: 0, paddingInlineStart: '1.2em' }}>
                <li>accepted — 18</li>
                <li>candidate — 7</li>
                <li>contested — 2</li>
              </ul>
            </div>
          }
          sidePanelLabel="Facets"
          footer={<span>27 claims · 3 need review</span>}
        >
          <table style={{ inlineSize: '100%', borderCollapse: 'collapse' }} data-density="compact">
            <thead>
              <tr>
                <th style={{ textAlign: 'start', padding: 'var(--rh-space-2)' }}>Id</th>
                <th style={{ textAlign: 'start', padding: 'var(--rh-space-2)' }}>Claim</th>
                <th style={{ textAlign: 'start', padding: 'var(--rh-space-2)' }}>Authority</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} style={{ borderTop: '1px solid var(--rh-border-subtle)' }}>
                  <td style={{ padding: 'var(--rh-space-2)', fontFamily: 'var(--rh-font-mono)' }}>
                    {row.id}
                  </td>
                  <td style={{ padding: 'var(--rh-space-2)' }}>{row.text}</td>
                  <td style={{ padding: 'var(--rh-space-2)' }}>
                    <Badge status={row.status} size="sm" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </FullPageWorkspace>
      </div>
    ),
  },
  {
    name: 'No side panel',
    render: () => (
      <div
        className="gallery-block"
        style={{
          blockSize: '20rem',
          border: '1px solid var(--rh-border-subtle)',
          borderRadius: 'var(--rh-radius-card)',
          overflow: 'hidden',
        }}
      >
        <FullPageWorkspace title="Synthesis" description="Draft argument over accepted claims.">
          <p>The body of the page.</p>
        </FullPageWorkspace>
      </div>
    ),
  },
];

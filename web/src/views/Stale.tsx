/**
 * Stale (Product 37, ADR-008): what is out of date, highest scientific impact first.
 *
 * A stale object is never silently rewritten, so this list is work to do rather than a
 * failure report. The priority and the reason are `state.stale`'s, not this page's.
 */
import { Empty, ErrorBox, Loading, Panel } from '../components/Feedback';
import { useSession } from '../app/session';
import { useAsync } from '../app/useAsync';

const PRIORITY_LABELS: Record<number, string> = {
  5: 'manuscript anchor',
  4: 'claim',
  3: 'synthesis',
  2: 'classification',
  1: 'index',
};

export function StalePage() {
  const { client } = useSession();
  const state = useAsync(() => client.stale(), [client]);

  if (state.loading) return <Loading what="the stale set" />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data || state.data.count === 0) return <Empty>Nothing is stale.</Empty>;

  return (
    <div className="stale">
      <h1>Stale objects</h1>
      <p className="muted">{state.data.count} marked, highest scientific impact first.</p>
      <Panel title="Marks">
        <table>
          <thead>
            <tr>
              <th>Object</th>
              <th>Impact</th>
              <th>Reason</th>
              <th>Changed by</th>
            </tr>
          </thead>
          <tbody>
            {state.data.marks.map((mark) => (
              <tr key={`${mark.object_id}:${mark.source_change}`}>
                <td>{mark.object_id}</td>
                <td>{PRIORITY_LABELS[mark.priority] ?? mark.priority}</td>
                <td>{mark.reason}</td>
                <td>{mark.source_change}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

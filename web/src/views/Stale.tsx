/**
 * Stale (PRODUCT §37, ADR-008): what is out of date, highest scientific impact first.
 *
 * A stale object is never silently rewritten, so this list is work to do rather than a
 * failure report. The priority and the reason are `state.stale`'s, not this page's.
 */
import { FullPageWorkspace } from '@research-harness/design';
import { DataTable, Empty, ErrorBox, Loading, StatusBadge } from '../components/Feedback';
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
    <FullPageWorkspace
      title="Stale objects"
      description={`${state.data.count} marked, highest scientific impact first.`}
    >
      <DataTable
        label="Stale marks"
        head={
          <tr>
            <th scope="col">Object</th>
            <th scope="col">Impact</th>
            <th scope="col">Reason</th>
            <th scope="col">Changed by</th>
          </tr>
        }
      >
        {state.data.marks.map((mark) => (
          <tr key={`${mark.object_id}:${mark.source_change}`}>
            <th scope="row">
              <code>{mark.object_id}</code> <StatusBadge status="stale" />
            </th>
            <td>{PRIORITY_LABELS[mark.priority] ?? mark.priority}</td>
            <td>{mark.reason}</td>
            <td>
              <code>{mark.source_change}</code>
            </td>
          </tr>
        ))}
      </DataTable>
    </FullPageWorkspace>
  );
}

/**
 * Stale: what is out of date, highest scientific impact first.
 *
 * A stale object is never silently rewritten, so this list is work to do rather than a
 * failure report. The priority and the reason are `state.stale`'s, not this page's.
 *
 * The frame is mounted before the read resolves, so the heading and this page's shape
 * survive loading, a refusal and a project where nothing is stale.
 */
import { Link } from 'react-router-dom';
import { FullPageWorkspace, humaniseResearchTokens } from '@research-harness/design';
import { DataTable, Empty, ErrorBox, Loading, StatusBadge } from '../components/Feedback';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
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
  const { href } = useProjectPaths();
  const state = useAsync(() => client.stale(), [client]);

  const marks = state.data?.marks ?? [];
  const settled = !state.loading && !state.error;
  return (
    <FullPageWorkspace
      busy={state.loading}
      title="Stale objects"
      description={
        settled
          ? `${state.data?.count ?? 0} marked, highest scientific impact first.`
          : 'Highest scientific impact first.'
      }
    >
      {state.loading ? (
        <Loading what="the stale set" shape="table" />
      ) : state.error ? (
        <ErrorBox error={state.error} retry={state.reload} />
      ) : marks.length === 0 ? (
        <Empty
          description="An object is marked stale when something it rests on has changed. Nothing is ever rewritten silently, so this page is a list of work rather than a report of damage — and today it is empty."
          action={<Link to={href('/overview')}>See what else needs attention</Link>}
        >
          Nothing is stale
        </Empty>
      ) : (
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
          {marks.map((mark) => (
            <tr key={`${mark.object_id}:${mark.source_change}`}>
              <th scope="row">
                <code>{mark.object_id}</code> <StatusBadge status="stale" />
              </th>
              <td>{PRIORITY_LABELS[mark.priority] ?? mark.priority}</td>
              <td>{humaniseResearchTokens(mark.reason)}</td>
              <td>
                <code>{mark.source_change}</code>
              </td>
            </tr>
          ))}
        </DataTable>
      )}
    </FullPageWorkspace>
  );
}

/**
 * The cockpit, and the one decision that has to happen before any route exists.
 *
 * `useHost()` says which server answered (`host.tsx`). A legacy `research serve` daemon
 * owns exactly one workspace, so the session is mounted here, around the existing route
 * table, exactly as `main.tsx` used to mount it. A multi-project host has no single
 * workspace to open a session against — Task 10 gives it Project Home and a session per
 * project — so for now it renders the notice below rather than a workspace that would be
 * pointed at nothing.
 */
import { AsyncState, ErrorNotice } from '@research-harness/design';
import { useHost, APP_TOKEN_MISSING_EXPLANATION } from './host';
import { AppRoutes } from './routes';
import { SessionProvider } from './session';

export function App() {
  const host = useHost();

  if (host.mode === 'loading') {
    return (
      <AsyncState
        kind="loading"
        title="Opening Research Harness"
        description="Asking the local application which workspaces it holds."
      />
    );
  }

  if (host.mode === 'error') {
    return (
      <ErrorNotice
        kind="retryable"
        title="Cannot reach Research Harness"
        description={host.error ?? 'The local application did not answer.'}
      />
    );
  }

  if (host.mode === 'legacy') {
    return (
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    );
  }

  return <ProjectHomePlaceholder authRequired={host.authRequired} count={host.projects.length} />;
}

/** Task 10 replaces this with Project Home; until then it states what the host reported. */
function ProjectHomePlaceholder({
  authRequired,
  count,
}: {
  authRequired: boolean;
  count: number;
}) {
  if (authRequired) {
    return (
      <ErrorNotice
        kind="blocked"
        title="Not signed in to the local application"
        description={APP_TOKEN_MISSING_EXPLANATION}
      />
    );
  }
  return (
    <AsyncState
      kind="empty"
      title="Your research projects"
      description={`This application holds ${count} registered ${count === 1 ? 'project' : 'projects'}.`}
    />
  );
}

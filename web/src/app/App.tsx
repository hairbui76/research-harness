/**
 * The cockpit, and the one decision that has to happen before any route exists.
 *
 * `useHost()` says which server answered (`host.tsx`), and that answer selects a whole
 * route tree rather than a flag inside one:
 *
 * * **legacy** — `research serve`, one workspace, no such thing as a project. The session
 *   is mounted here around the existing route table at the paths it has always had.
 * * **multi** — `research app`, a registry of them. `/` is Project Home and every workspace
 *   screen lives below `/projects/{project_id}` (design §4.5), so reloading a page restores
 *   the same project and switching projects cannot silently retarget the one you were in.
 *
 * The two trees mount exactly the same workspace routes (`routes.tsx`). All that differs is
 * the client underneath — a project-scoped `HarnessClient` versus the legacy one — and the
 * `ProjectPathProvider` that tells the views' links which prefix they are under. Neither
 * the routes nor the views branch on host mode.
 */
import { useEffect, useMemo, useRef } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { AsyncState, ErrorNotice } from '@research-harness/design';
import { useHost } from './host';
import { projectHref, ProjectPathProvider, readLastProject, writeLastProject } from './projectPaths';
import { AppRoutes } from './routes';
import { SessionProvider } from './session';
import { ProjectHome } from '../views/projects/ProjectHome';

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

  if (host.mode === 'legacy') return <LegacyWorkspaceRoutes />;
  return <MultiProjectRoutes />;
}

/** Today's tree, at today's paths, with no project prefix anywhere in it. */
export function LegacyWorkspaceRoutes() {
  return (
    <SessionProvider>
      <AppRoutes />
    </SessionProvider>
  );
}

/** Project Home at the root, one workspace tree per project below it. */
export function MultiProjectRoutes() {
  useResumeLastProject();
  return (
    <Routes>
      <Route index element={<ProjectHome />} />
      <Route path="projects/:projectId/*" element={<ProjectWorkspaceRoute />} />
      {/* A legacy bookmark, or a typo: Project Home is always somewhere to land. */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

/**
 * One project's workspace: the same routes as the legacy tree, over a scoped client.
 *
 * The id is validated against the registry the host loaded rather than trusted from the
 * URL, so a stale bookmark reaches Project Home with a notice instead of a client pointed
 * at a project that no longer exists. The scoped client is memoised per id, because a new
 * `HarnessClient` identity would re-run every view's fetch effect on each render.
 */
export function ProjectWorkspaceRoute() {
  const { projectId = null } = useParams();
  const host = useHost();
  const project = host.projects.find((candidate) => candidate.project_id === projectId) ?? null;
  const client = useMemo(
    () => (projectId && host.appClient ? host.appClient.workspaceClient(projectId) : null),
    [host.appClient, projectId],
  );

  const known = project !== null;
  useEffect(() => {
    if (known && projectId) writeLastProject(projectId);
  }, [known, projectId]);

  if (!known || !client) return <ProjectHome notFoundProjectId={projectId} />;

  return (
    <ProjectPathProvider projectId={projectId}>
      <SessionProvider client={client}>
        <AppRoutes />
      </SessionProvider>
    </ProjectPathProvider>
  );
}

/**
 * Reopen the project this browser was last in, once, on the way in.
 *
 * Spec §4.2: with previous projects the app opens the most recently used available one,
 * and Project Home stays reachable. Both halves are in the conditions below — it fires only
 * for a bare `/` on the first render of this tree, so navigating back to Project Home
 * afterwards, or arriving on any other URL, is left alone. A project that is no longer
 * listed, or is not available, is not resumed.
 */
/**
 * True when the query names nothing the researcher chose. The launch URL from
 * `research app` is `/?bootstrap=<nonce>`; the nonce is consumed and stripped by
 * `readBootstrap` before the router sees it, but the router keeps the search it was mounted
 * with, so the entry decision must ignore that one parameter or resumption never fires.
 */
function isBareEntry(search: string): boolean {
  const params = new URLSearchParams(search);
  params.delete('bootstrap');
  return params.toString() === '';
}

function useResumeLastProject(): void {
  const host = useHost();
  const location = useLocation();
  const navigate = useNavigate();
  const resumed = useRef(false);

  useEffect(() => {
    if (resumed.current) return;
    resumed.current = true;
    if (location.pathname !== '/' || !isBareEntry(location.search)) return;
    const remembered = readLastProject();
    if (!remembered) return;
    const project = host.projects.find((candidate) => candidate.project_id === remembered);
    if (!project || project.availability !== 'available') return;
    navigate(projectHref(project.project_id, '/'), { replace: true });
    // Deliberately once per mount: this is an entry decision, not a reaction to the URL.
  }, [host.projects, location.pathname, location.search, navigate]);
}

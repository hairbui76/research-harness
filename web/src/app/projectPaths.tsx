/**
 * Which project this part of the tree belongs to, and where its links point.
 *
 * The multi-project host serves every workspace screen below `/projects/{project_id}`
 * (design §4.5), while `research serve` serves the same screens at the bare paths they
 * have always had. Rather than teach every view about that, the prefix lives in one
 * context: a view asks for `href('/claims/C0001')` and gets whichever of the two is
 * correct for the tree it is mounted in.
 *
 * The default context is the legacy one — no project id, `href` the identity function — so
 * a component rendered outside a `ProjectPathProvider` keeps producing exactly the URLs it
 * produced before this file existed. That is what makes the change safe to apply view by
 * view.
 *
 * The remembered project below is a convenience, not state: it says which project this
 * browser opened last, so relaunching the app lands where the researcher left off (spec
 * §4.2). Nothing scientific depends on it and losing it costs one click.
 */
import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';

/** Where the last-opened project id is remembered, per origin. */
export const LAST_PROJECT_KEY = 'research-harness.last-project';

export interface ProjectPaths {
  /** The active project, or null in a legacy single-workspace window. */
  projectId: string | null;
  /** A workspace-local path, rewritten for whichever host this window is talking to. */
  href: (path: string) => string;
}

/**
 * Prefix one workspace-local path with a project.
 *
 * The path is taken whole, query and all: `/?session=CS0001` becomes
 * `/projects/prj_abc/?session=CS0001`, so a conversation deep link survives the move. A
 * null id returns the path untouched, which is the legacy host's answer.
 */
export function projectHref(projectId: string | null, localPath: string): string {
  if (!projectId) return localPath;
  const path = localPath.startsWith('/') ? localPath : `/${localPath}`;
  return `/projects/${encodeURIComponent(projectId)}${path}`;
}

const LEGACY: ProjectPaths = { projectId: null, href: (path) => path };

const ProjectPathContext = createContext<ProjectPaths>(LEGACY);

export interface ProjectPathProviderProps {
  projectId: string | null;
  children: ReactNode;
}

export function ProjectPathProvider({ projectId, children }: ProjectPathProviderProps) {
  const value = useMemo<ProjectPaths>(
    () => ({ projectId, href: (path: string) => projectHref(projectId, path) }),
    [projectId],
  );
  return <ProjectPathContext.Provider value={value}>{children}</ProjectPathContext.Provider>;
}

/** The active project and its href helper; the legacy identity when there is no provider. */
export function useProjectPaths(): ProjectPaths {
  return useContext(ProjectPathContext);
}

/** The project this browser opened last, or null when it has never opened one. */
export function readLastProject(): string | null {
  try {
    return window.localStorage.getItem(LAST_PROJECT_KEY);
  } catch {
    return null;
  }
}

export function writeLastProject(projectId: string | null): void {
  try {
    if (projectId) window.localStorage.setItem(LAST_PROJECT_KEY, projectId);
    else window.localStorage.removeItem(LAST_PROJECT_KEY);
  } catch {
    /* storage disabled: the app simply opens Project Home every time */
  }
}

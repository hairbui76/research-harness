/**
 * The cockpit shell.
 *
 * `AppShell` is the frame (skip link, rail, main surface, and — for W1 — an inspector);
 * `ProjectRail` is the left pane: which project is open, the PRODUCT §26 research
 * navigation with the counts the daemon reported, settings, and whether this window may
 * accept anything. Below the shell's breakpoint the rail becomes a drawer and `main`
 * stays mounted, so nothing a researcher has typed is lost when they open it.
 *
 * Two slots are deliberately empty here:
 *
 * * `sessionList` — W1 fills it with the conversation history (`SessionList` over
 *   `session.list`). Nothing else about the rail changes when it does.
 * * `inspector` — a full research page carries its own side panel, so the shell mounts no
 *   inspector and the slot stays absent. W1 passes `<ResearchInspector />` here for the
 *   conversation route, with `inspectorOpen` state beside `railOpen` below.
 */
import { useCallback, useMemo, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { AppShell, ProjectRail } from '@research-harness/design';
import type { ProjectModel, ProviderStatus, RailItem } from '@research-harness/design';
import { useSession } from './session';
import { NAVIGATION } from './routes';
import { SettingsDialog } from './SettingsDialog';
import { TokenBar } from './TokenBar';

export function Layout() {
  const { overview, canMutate, error, loading } = useSession();
  const location = useLocation();
  const [railOpen, setRailOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const routeRailClick = useRailRouting();

  const project: ProjectModel = {
    id: overview?.workspace ?? 'unconnected',
    name: overview?.project ?? 'not connected',
    ...(overview?.workspace ? { path: overview.workspace } : {}),
  };

  const items = useMemo<RailItem[]>(
    () =>
      NAVIGATION.map((entry) => {
        // The count the daemon reported for this surface, when it reported one. The
        // cockpit never counts anything itself (PRODUCT §5 P10).
        const group = overview?.attention.find((attention) => attention.route === entry.to);
        const active =
          (entry.end
            ? location.pathname === entry.to
            : location.pathname === entry.to || location.pathname.startsWith(`${entry.to}/`)) ||
          (entry.alsoMatches?.includes(location.pathname) ?? false);
        return {
          id: entry.id,
          label: entry.label,
          to: entry.to,
          icon: entry.icon,
          ...(group && group.count > 0 ? { count: group.count } : {}),
          ...(active ? { active: true } : {}),
        };
      }),
    [location.pathname, overview],
  );

  const providerStatus = principalStatus({ loading, error, canMutate, principal: overview?.principal });

  return (
    <>
      <AppShell
        mainLabel="Research workspace"
        railOpen={railOpen}
        onRailOpenChange={setRailOpen}
        rail={
          // The click handler routes the rail's links; it adds no behaviour of its own,
          // so the interactive elements are still the rail's own buttons and links.
          <div className="rh-web-rail" onClick={routeRailClick}>
            <ProjectRail
              project={project}
              items={items}
              onNavigate={() => setRailOpen(false)}
              onOpenSettings={() => setSettingsOpen(true)}
              {...(providerStatus ? { providerStatus } : {})}
              // W1: the conversation session history goes here.
              // sessionList={<SessionList … />}
            />
          </div>
        }
        main={
          <>
            <TokenBar />
            <div className="rh-web-route">
              <Outlet />
            </div>
          </>
        }
      />
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </>
  );
}

/**
 * What the rail footer says about this connection.
 *
 * It is the daemon's judgement, not the cockpit's: `principal` comes from `GET /overview`
 * and decides whether this window may accept anything (PRODUCT §29, ADR-007). The state
 * name is rendered as words by `ProjectRail`, so it never depends on the colour.
 */
function principalStatus(input: {
  loading: boolean;
  error: string | null;
  canMutate: boolean;
  principal: string | undefined;
}): ProviderStatus | undefined {
  if (input.error) {
    return { label: 'Daemon', state: 'offline', detail: input.error };
  }
  if (input.loading || input.principal === undefined) return undefined;
  if (input.canMutate) {
    return { label: 'Daemon', state: 'ok', detail: 'Researcher — may accept' };
  }
  return {
    label: 'Daemon',
    state: 'degraded',
    detail: `${input.principal} — reads and proposes only`,
  };
}

/**
 * Client-side routing for the rail's links.
 *
 * `ProjectRail` renders a real `<a href>` for every navigation item — which is what makes
 * it middle-clickable, bookmarkable and correct for assistive technology — and the Design
 * System has no router to call. So the cockpit applies the same rule react-router's own
 * `<Link>` does: an unmodified left click becomes a client-side navigation, and every
 * other click (a new tab, a new window, a download) is left to the browser.
 */
function useRailRouting(): (event: ReactMouseEvent<HTMLDivElement>) => void {
  const navigate = useNavigate();
  return useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      if (event.defaultPrevented) return;
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest('a[href]');
      if (!(anchor instanceof HTMLAnchorElement)) return;
      if (anchor.target && anchor.target !== '_self') return;
      if (anchor.origin !== window.location.origin) return;
      event.preventDefault();
      navigate(`${anchor.pathname}${anchor.search}${anchor.hash}`);
    },
    [navigate],
  );
}

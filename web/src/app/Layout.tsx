/**
 * The cockpit shell.
 *
 * `AppShell` is the frame (skip link, rail, main surface, and — for W1 — an inspector);
 * `ProjectRail` is the left pane: which project is open, the PRODUCT §26 research
 * navigation with the counts the daemon reported, settings, and whether this window may
 * accept anything. Below the shell's breakpoint the rail becomes a drawer and `main`
 * stays mounted, so nothing a researcher has typed is lost when they open it.
 *
 * Both of the slots this file used to leave empty are now filled by the conversation
 * workspace (`src/views/conversation`):
 *
 * * `sessionList` — the session history, on every route. The rail owns it everywhere, not
 *   just on `/`, so a researcher reading a claim can still see and reopen the conversation
 *   they were in (workspace design §2).
 * * `inspector` — mounted for the conversation route only. A full research page carries
 *   its own side panel, so on every other route the slot stays absent and `AppShell` draws
 *   two panes. Below the shell's breakpoint the rail *and* the inspector become drawers
 *   while `main` stays mounted, which is what keeps an unsent draft alive when either one
 *   is opened (conversation spec §9).
 *
 * The workspace state itself is a context mounted here rather than props threaded through
 * `Outlet`, because three parts of the tree — rail, route, inspector — share one session.
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
import { InspectorPane } from '../views/conversation/InspectorPane';
import { NewSessionDialog } from '../views/conversation/NewSessionDialog';
import { SessionListPane } from '../views/conversation/SessionListPane';
import { ConversationProvider, useConversation } from '../views/conversation/state';

/** The shell, wrapped in the conversation state its rail and inspector both read. */
export function Layout() {
  return (
    <ConversationProvider>
      <Shell />
    </ConversationProvider>
  );
}

function Shell() {
  const { overview, canMutate, error, loading } = useSession();
  const conversation = useConversation();
  const location = useLocation();
  const [railOpen, setRailOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [newSessionOpen, setNewSessionOpen] = useState(false);
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
        // The inspector belongs to the conversation; the research pages have their own.
        {...(conversation.active
          ? {
              inspector: <InspectorPane />,
              inspectorOpen: conversation.inspectorOpen,
              onInspectorOpenChange: conversation.setInspectorOpen,
            }
          : {})}
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
              // Opening a session is a mutation, so a window that may only read is not
              // offered the control; the history below it is a read and stays. The click
              // asks first: visibility is fixed at creation and decides what the session
              // may later be bound to, so it is not a choice to make on someone's behalf.
              {...(canMutate ? { onNewSession: () => setNewSessionOpen(true) } : {})}
              sessionList={<SessionListPane />}
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
      <NewSessionDialog
        open={newSessionOpen}
        onOpenChange={setNewSessionOpen}
        onCreate={(visibility) => void conversation.sessions.create(undefined, visibility)}
      />
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

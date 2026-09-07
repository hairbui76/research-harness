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
 *
 * The shell is also where the two hosts of design §11 differ, and the only place they do.
 * Under `research serve` there is one workspace and no such thing as a project, so the rail
 * shows the name `GET /overview` reported and offers nothing to do to it. Under
 * `research app` the same rail becomes the project switcher: every registered project, what
 * the host says about each one, what is still running in the ones nobody is looking at, and
 * the five lifecycle actions — which are performed by `useProjectLifecycle` and confirmed
 * by `ProjectDialogs`, never by this file.
 */
import { useCallback, useMemo, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { AppShell, ErrorNotice, ProjectRail, useToast } from "@research-harness/design";
import type {
  ProjectAction,
  ProjectModel,
  ProjectRailProps,
  ProviderStatus,
  RailItem,
} from "@research-harness/design";
import type { ProjectView } from "../api/projects";
// The shortcut layer wraps the shell so a page's commands and the rail's destinations meet
// in one palette; it renders the palette and the help sheet itself.
import { CommandsProvider } from "./commands";
import { useDaemonOutage } from "./daemonStatus";
import { useOptionalHost } from "./host";
import type { Host } from "./host";
import { projectHref, useProjectPaths } from "./projectPaths";
import { NAVIGATION, navigationForProject } from "./routes";
import type { NavigationEntry } from "./routes";
import { useSession } from "./session";
import { SettingsDialog } from "./SettingsDialog";
import { TokenBar } from "./TokenBar";
import { useProjectPolling } from "./useProjectPolling";
import { InspectorPane } from "../views/conversation/InspectorPane";
import { NewSessionDialog } from "../views/conversation/NewSessionDialog";
import { SessionListPane } from "../views/conversation/SessionListPane";
import {
  ConversationProvider,
  useConversation,
} from "../views/conversation/state";
import {
  ProjectDialogs,
  useProjectLifecycle,
} from "../views/projects/ProjectDialogs";
import type { ProjectDialog } from "../views/projects/ProjectDialogs";

/** The shell, wrapped in the conversation state its rail and inspector both read. */
export function Layout() {
  return (
    <ConversationProvider>
      <Shell />
    </ConversationProvider>
  );
}

/** Every rail prop that is the same whichever host is on the other end. */
type WorkspaceRailProps = Pick<
  ProjectRailProps,
  | "items"
  | "onNavigate"
  | "onOpenSettings"
  | "providerStatus"
  | "onNewSession"
  | "sessionList"
>;

/**
 * The daemon has stopped answering: said once, politely, without taking the cockpit away.
 *
 * `role="status"` rather than `alert`, and never a dialog: an outage is a condition to live
 * with for a moment, not an interruption to acknowledge. It states what is safe, what comes
 * back on its own, and the one thing a researcher can do about it — and it goes away by
 * itself the moment any request succeeds, because the transport that noticed the silence is
 * the same one that notices the answer.
 */
function DaemonOfflineNotice({
  outage,
  command,
  onRetry,
}: {
  outage: { path: string; reason: string };
  command: string;
  onRetry: () => void;
}) {
  return (
    <div className="rh-web-token-bar">
      <ErrorNotice
        kind="retryable"
        title="Research Harness is not answering"
        description={
          <>
            The daemon behind this window stopped responding. Every page keeps the last
            answer it was given and says so; nothing here has been thrown away. If you
            stopped it, start it again with <code>{command}</code> — this window picks the
            connection back up on its own, and the pages re-read themselves.
          </>
        }
        detail={`${outage.reason}\n${outage.path}`}
        detailLabel="Which request went unanswered"
        safety={{
          draft: "safe",
          source: "safe",
          note: "An unsent message stays in the composer, and nothing was written.",
        }}
        actions={[
          { label: "Ask the daemon again", onClick: onRetry, iconStart: "refresh-cw" },
        ]}
      />
    </div>
  );
}

function Shell() {
  const { overview, canMutate, error, loading, refresh } = useSession();
  const outage = useDaemonOutage();
  const conversation = useConversation();
  const location = useLocation();
  const host = useOptionalHost();
  const { projectId } = useProjectPaths();
  const [railOpen, setRailOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [newSessionOpen, setNewSessionOpen] = useState(false);
  const routeRailClick = useRailRouting();

  // The multi-project host, or null for `research serve` and for a shell mounted on its own.
  const registry = host?.mode === "multi" ? host : null;
  useProjectPolling(registry);

  // The registry's own row for the project this tree is mounted in. `App` validates the id
  // against the registry before it mounts the workspace, so this is null only for a legacy
  // window — or, briefly, for a project that was forgotten in another tab.
  const active =
    registry && projectId
      ? (registry.projects.find(
          (candidate) => candidate.project_id === projectId,
        ) ?? null)
      : null;

  const project: ProjectModel = {
    id: overview?.workspace ?? "unconnected",
    name: overview?.project ?? "not connected",
    ...(overview?.workspace ? { path: overview.workspace } : {}),
  };

  const items = useMemo<RailItem[]>(() => {
    // `overview.attention[].route` names the workspace-local path — `/review`, never
    // `/projects/prj_abc/review` — because a daemon behind a project prefix does not know
    // it is behind one. So an entry's `href` may be rewritten for a project while its count
    // is still looked up under the route the daemon reported. (Built here rather than at
    // module scope: `routes.tsx` imports this file, so `NAVIGATION` is not populated yet
    // while this module is being evaluated.)
    const daemonRoutes = new Map(
      NAVIGATION.map((entry) => [entry.id, entry.to]),
    );
    return navigationForProject(projectId).map((entry) => {
      // The count the daemon reported for this surface, when it reported one. The cockpit
      // never counts anything itself (PRODUCT §5 P10).
      const route = daemonRoutes.get(entry.id) ?? entry.to;
      const group = overview?.attention.find(
        (attention) => attention.route === route,
      );
      return {
        id: entry.id,
        label: entry.label,
        to: entry.to,
        icon: entry.icon,
        ...(group && group.count > 0 ? { count: group.count } : {}),
        ...(isActive(entry, location.pathname) ? { active: true } : {}),
      };
    });
  }, [location.pathname, overview, projectId]);

  const providerStatus = principalStatus({
    loading,
    error,
    canMutate,
    principal: overview?.principal,
  });

  const rail: WorkspaceRailProps = {
    items,
    onNavigate: () => setRailOpen(false),
    onOpenSettings: () => setSettingsOpen(true),
    ...(providerStatus ? { providerStatus } : {}),
    // Opening a session is a mutation, so a window that may only read is not offered the
    // control; the history below it is a read and stays. The click asks first: visibility
    // is fixed at creation and decides what the session may later be bound to, so it is
    // not a choice to make on someone's behalf.
    ...(canMutate ? { onNewSession: () => setNewSessionOpen(true) } : {}),
    sessionList: <SessionListPane />,
  };

  return (
    <CommandsProvider destinations={items}>
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
            {registry ? (
              <ProjectSwitcherRail
                host={registry}
                active={active}
                fallback={project}
                rail={rail}
              />
            ) : (
              <ProjectRail project={project} {...rail} />
            )}
          </div>
        }
        main={
          <>
            {active ? <WorkspaceHeader project={active} /> : null}
            {/*
              One notice, not two. While the daemon is silent the token bar would say the
              same thing a second time and offer a token to a process that is not there to
              take one, so the outage owns the strip until the daemon answers again — and
              then the bar comes back, because "this window may only read" is a different
              fact that survives the reconnection.
            */}
            {outage ? (
              <DaemonOfflineNotice
                outage={outage}
                command={registry ? "research app" : "research serve"}
                onRetry={refresh}
              />
            ) : (
              <TokenBar />
            )}
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
    </CommandsProvider>
  );
}

/**
 * Which project this screen belongs to, said in `main` and not only in the rail.
 *
 * Spec §4.5 asks for the active project name to stay visible in the workspace header, and
 * §11 item 6 makes it a requirement rather than a nicety: below the shell's breakpoint the
 * rail — where the name otherwise lives — is a drawer, and a researcher with two projects
 * open in two tabs must never have to open a drawer to find out which one they are about to
 * accept evidence into.
 */
function WorkspaceHeader({ project }: { project: ProjectView }) {
  return (
    <header className="rh-web-project-bar">
      <span className="rh-web-project-bar__name">{project.display_name}</span>
      <span className="rh-web-project-bar__path">{project.path}</span>
    </header>
  );
}

interface ProjectSwitcherRailProps {
  host: Host;
  /** The registry's row for the open project, when it still has one. */
  active: ProjectView | null;
  /** What the daemon itself says this workspace is; used only if the registry has lost it. */
  fallback: ProjectModel;
  rail: WorkspaceRailProps;
}

/**
 * The rail as the project switcher of design §4.5.
 *
 * It performs nothing itself. Selecting a project is a navigation — the URL owns which
 * project is open, so switching cannot silently retarget the one you were in — and every
 * lifecycle action is either a control-plane call through `useProjectLifecycle` or a dialog
 * that asks first. "Add project" opens the same Open-folder dialog Project Home offers,
 * because a folder path may only reach the host from a picker a human answered; creating a
 * new project stays on Project Home, one click away through "All projects".
 */
function ProjectSwitcherRail({
  host,
  active,
  fallback,
  rail,
}: ProjectSwitcherRailProps) {
  const navigate = useNavigate();
  const lifecycle = useProjectLifecycle();
  const { toast } = useToast();
  const [dialog, setDialog] = useState<ProjectDialog>(null);

  const projects = useMemo(
    () => host.projects.map(toProjectModel),
    [host.projects],
  );
  const project = active ? toProjectModel(active) : fallback;

  const reveal = lifecycle.reveal;
  const act = useCallback(
    (projectId: string, action: ProjectAction) => {
      const view = host.projects.find(
        (candidate) => candidate.project_id === projectId,
      );
      if (!view) return;
      if (action === "reveal") {
        // The one action with no form and nothing to confirm: it opens a file manager and
        // writes nothing. A host that could not is worth one sentence, not a dialog.
        void reveal(projectId).catch((cause: unknown) => {
          toast({
            tone: "error",
            title: "Could not open the folder",
            description: cause instanceof Error ? cause.message : String(cause),
          });
        });
        return;
      }
      setDialog({ kind: action, project: view });
    },
    [host.projects, reveal, toast],
  );

  return (
    <>
      <ProjectRail
        project={project}
        projects={projects}
        onSelectProject={(id) => navigate(projectHref(id, "/"))}
        onOpenProjectHome={() => navigate("/")}
        onAddProject={() => setDialog({ kind: "open" })}
        onProjectAction={act}
        {...rail}
      />
      <ProjectDialogs
        dialog={dialog}
        onClose={() => setDialog(null)}
        onDialog={setDialog}
      />
    </>
  );
}

/** One registry row as the rail's view model; only the field names differ. */
function toProjectModel(view: ProjectView): ProjectModel {
  return {
    id: view.project_id,
    name: view.display_name,
    path: view.path,
    availability: view.availability,
    ...(view.detail ? { detail: view.detail } : {}),
    activeRuns: view.active_runs,
  };
}

/**
 * Whether this entry is the screen currently on show.
 *
 * The conversation is `/` under the legacy host and `/projects/{id}/` under the multi-project
 * one, so the trailing slash a project prefix leaves behind is matched as well as trimmed:
 * `/projects/prj_abc` and `/projects/prj_abc/` are the same screen.
 */
function isActive(entry: NavigationEntry, pathname: string): boolean {
  const base =
    entry.to.length > 1 && entry.to.endsWith("/")
      ? entry.to.slice(0, -1)
      : entry.to;
  if (pathname === entry.to || pathname === base) return true;
  if (!entry.end && pathname.startsWith(`${base}/`)) return true;
  return entry.alsoMatches?.includes(pathname) ?? false;
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
    return { label: "Daemon", state: "offline", detail: input.error };
  }
  if (input.loading || input.principal === undefined) return undefined;
  if (input.canMutate) {
    return { label: "Daemon", state: "ok", detail: "Researcher — may accept" };
  }
  return {
    label: "Daemon",
    state: "degraded",
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
      if (
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest("a[href]");
      if (!(anchor instanceof HTMLAnchorElement)) return;
      if (anchor.target && anchor.target !== "_self") return;
      if (anchor.origin !== window.location.origin) return;
      event.preventDefault();
      navigate(`${anchor.pathname}${anchor.search}${anchor.hash}`);
    },
    [navigate],
  );
}

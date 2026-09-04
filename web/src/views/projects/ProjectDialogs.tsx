/**
 * The six things a researcher can do to the *list* of projects, and nothing else.
 *
 * Every one of them is a control-plane call (design §6): the browser never touches a
 * folder, and a path reaches the host only because a human chose it in a native dialog or
 * typed it into the fallback these dialogs offer when neither `zenity` nor `kdialog` is
 * installed. Nothing here writes research state.
 *
 * Two rules shape the whole file:
 *
 * * **Nothing happens implicitly.** `open` on a folder without `research.yaml` does not
 *   initialize it; it reports `project_needs_initialization` and this file opens the
 *   Initialize dialog so the researcher confirms, having read which files will be created
 *   (spec §4.4). Cancelling a picker mutates nothing at all.
 * * **A refusal is not a reset.** A dialog that fails keeps every value the researcher
 *   entered and shows the host's own sentence, so the fix is one edit rather than a retype.
 *
 * `useProjectLifecycle` is the same set of calls without the dialogs: the layout's project
 * rail (task 12) reveals, renames and forgets through it and reuses `ProjectDialogs` for
 * the ones that need a form.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Dialog,
  DialogBody,
  DialogFooter,
  DialogHeader,
  ErrorNotice,
  Input,
} from '@research-harness/design';
import { ControlError } from '../../api/projects';
import type { AppClient, FolderSelection, ProjectView } from '../../api/projects';
import { useHost } from '../../app/host';
import { projectHref } from '../../app/projectPaths';
import './projects.css';

/** Which lifecycle dialog is open, and what it is about. */
export type ProjectDialog =
  | { kind: 'create' }
  | { kind: 'open' }
  | { kind: 'initialize'; path: string }
  | { kind: 'locate'; project: ProjectView }
  | { kind: 'rename'; project: ProjectView }
  | { kind: 'forget'; project: ProjectView }
  | null;

/** The default workspace policy every new project is created under. */
export const DEFAULT_POLICY = 'strict';

/** What Forget promises, in the sentence the dialog and the rail both use. */
export const FORGET_EXPLANATION =
  'Research Harness removes only this entry from your project list. The files remain on ' +
  'disk exactly as they are, and you can add the folder again with Open folder.';

/** What Initialize is about to write into an ordinary folder (spec §4.4). */
export const INITIALIZED_FILES = [
  'research.yaml',
  'corpus/',
  'claims/',
  'decisions/',
  'events/',
  '.research/',
];

export interface ProjectLifecycle {
  /** False when this window holds no application token; every call below would refuse. */
  ready: boolean;
  chooseFolder: (title: string) => Promise<FolderSelection>;
  /** Creates, refreshes the list, and opens the new project. */
  create: (parent: string, name: string, policy?: string) => Promise<ProjectView>;
  open: (path: string) => Promise<ProjectView>;
  initialize: (path: string, name: string, policy?: string) => Promise<ProjectView>;
  /** Points an entry at its new folder and refreshes; it does not navigate. */
  locate: (projectId: string, path: string) => Promise<ProjectView>;
  rename: (projectId: string, displayName: string) => Promise<ProjectView>;
  /** Removes the entry, returns to Project Home, and refreshes. Deletes nothing. */
  forget: (projectId: string) => Promise<void>;
  reveal: (projectId: string) => Promise<void>;
}

/**
 * The control-plane calls, with the list refresh and the navigation that belong with them.
 *
 * The refresh always precedes the navigation: the workspace route resolves its project out
 * of `useHost().projects`, so arriving before the registry has been re-read would land on
 * "no such project" for a project that was just created.
 */
export function useProjectLifecycle(): ProjectLifecycle {
  const { appClient, refreshProjects } = useHost();
  const navigate = useNavigate();

  const client = useCallback((): AppClient => {
    if (!appClient) {
      throw new ControlError(401, 'control_permission_denied', NO_APP_CLIENT);
    }
    return appClient;
  }, [appClient]);

  const enter = useCallback(
    async (project: ProjectView): Promise<ProjectView> => {
      await refreshProjects();
      navigate(projectHref(project.project_id, '/'));
      return project;
    },
    [navigate, refreshProjects],
  );

  return {
    ready: Boolean(appClient?.authenticated),
    chooseFolder: useCallback((title: string) => client().chooseFolder(title), [client]),
    create: useCallback(
      async (parent, name, policy = DEFAULT_POLICY) =>
        enter(await client().createProject(parent, name, policy)),
      [client, enter],
    ),
    open: useCallback(async (path) => enter(await client().openProject(path)), [client, enter]),
    initialize: useCallback(
      async (path, name, policy = DEFAULT_POLICY) =>
        enter(await client().initializeProject(path, name, policy)),
      [client, enter],
    ),
    locate: useCallback(
      async (projectId, path) => {
        const project = await client().locateProject(projectId, path);
        await refreshProjects();
        return project;
      },
      [client, refreshProjects],
    ),
    rename: useCallback(
      async (projectId, displayName) => {
        const project = await client().renameProject(projectId, displayName);
        await refreshProjects();
        return project;
      },
      [client, refreshProjects],
    ),
    forget: useCallback(
      async (projectId) => {
        await client().forgetProject(projectId);
        navigate('/');
        await refreshProjects();
      },
      [client, navigate, refreshProjects],
    ),
    reveal: useCallback(
      async (projectId) => {
        await client().revealProject(projectId);
      },
      [client],
    ),
  };
}

const NO_APP_CLIENT =
  'This window is not signed in to the local application, so it cannot change the ' +
  'project list. Start Research Harness again with `research app`.';

export interface ProjectDialogsProps {
  /** Which dialog is open; null renders nothing. */
  dialog: ProjectDialog;
  /** Close the open dialog. */
  onClose: () => void;
  /** Open another in its place — Open escalates to Initialize through this. */
  onDialog: (dialog: NonNullable<ProjectDialog>) => void;
}

/** Every project lifecycle dialog, mounted from one piece of state. */
export function ProjectDialogs({ dialog, onClose, onDialog }: ProjectDialogsProps) {
  if (!dialog) return null;
  switch (dialog.kind) {
    case 'create':
      return <CreateDialog onClose={onClose} />;
    case 'open':
      return <OpenDialog onClose={onClose} onDialog={onDialog} />;
    case 'initialize':
      return <InitializeDialog path={dialog.path} onClose={onClose} />;
    case 'locate':
      return <LocateDialog project={dialog.project} onClose={onClose} />;
    case 'rename':
      return <RenameDialog project={dialog.project} onClose={onClose} />;
    case 'forget':
      return <ForgetDialog project={dialog.project} onClose={onClose} />;
  }
}

// -- new project ---------------------------------------------------------------------

function CreateDialog({ onClose }: { onClose: () => void }) {
  const lifecycle = useProjectLifecycle();
  const [name, setName] = useState('');
  const [parent, setParent] = useState('');
  const [typed, setTyped] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = async (): Promise<void> => {
    setError(null);
    try {
      const selection = await lifecycle.chooseFolder('Choose a parent folder');
      if (selection.fallback_required) {
        setTyped(true);
        return;
      }
      if (selection.cancelled || !selection.path) return;
      setParent(selection.path);
    } catch (cause) {
      setError(describeCause(cause));
    }
  };

  const submit = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await lifecycle.create(parent.trim(), name.trim(), DEFAULT_POLICY);
      onClose();
    } catch (cause) {
      setError(describeCause(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <LifecycleDialog
      title="New project"
      formId="rh-create-project"
      onClose={onClose}
      onSubmit={submit}
      submitLabel="Create project"
      submitDisabled={!name.trim() || !parent.trim()}
      busy={busy}
      error={error}
    >
      <Input
        label="Project name"
        value={name}
        autoFocus
        onChange={(event) => setName(event.target.value)}
        description="The folder is created under the parent you choose, using a safe form of this name."
      />
      <div className="rh-projects__picker">
        <Button type="button" onClick={() => void pick()}>
          Choose parent folder
        </Button>
        <p className="rh-projects__picked">
          {parent ? (
            <>
              Parent folder: <span className="rh-projects__path">{parent}</span>
            </>
          ) : (
            'No parent folder chosen yet.'
          )}
        </p>
      </div>
      {typed ? (
        <Input
          label="Parent folder path"
          value={parent}
          onChange={(event) => setParent(event.target.value)}
          description={FALLBACK_EXPLANATION}
        />
      ) : null}
    </LifecycleDialog>
  );
}

/** Why a text box appeared where a folder dialog should have been (design §7). */
export const FALLBACK_EXPLANATION =
  'This machine has no folder dialog available, so type the absolute path instead.';

// -- open folder ---------------------------------------------------------------------

function OpenDialog({
  onClose,
  onDialog,
}: {
  onClose: () => void;
  onDialog: (dialog: NonNullable<ProjectDialog>) => void;
}) {
  const lifecycle = useProjectLifecycle();
  const [path, setPath] = useState('');
  const [typed, setTyped] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const openPath = useCallback(
    async (chosen: string): Promise<void> => {
      setBusy(true);
      setError(null);
      try {
        await lifecycle.open(chosen);
        onClose();
      } catch (cause) {
        // The one refusal that is not a failure: an ordinary folder the researcher may
        // still choose to initialize, which only they can decide (spec §4.4).
        if (cause instanceof ControlError && cause.code === 'project_needs_initialization') {
          onDialog({ kind: 'initialize', path: chosen });
          return;
        }
        setTyped(true);
        setError(describeCause(cause));
      } finally {
        setBusy(false);
      }
    },
    [lifecycle, onClose, onDialog],
  );

  const pick = useCallback(async (): Promise<void> => {
    setError(null);
    try {
      const selection = await lifecycle.chooseFolder('Choose a project folder');
      if (selection.fallback_required) {
        setTyped(true);
        return;
      }
      // A cancelled picker is a normal answer and mutates nothing.
      if (selection.cancelled || !selection.path) {
        onClose();
        return;
      }
      setPath(selection.path);
      await openPath(selection.path);
    } catch (cause) {
      setTyped(true);
      setError(describeCause(cause));
    }
  }, [lifecycle, onClose, openPath]);

  useEffect(() => {
    // Once per mount, even under StrictMode's double effect: a native folder dialog must
    // not appear twice for one click.
    if (started.current) return;
    started.current = true;
    void pick();
  }, [pick]);

  return (
    <LifecycleDialog
      title="Open folder"
      formId="rh-open-project"
      onClose={onClose}
      onSubmit={() => openPath(path.trim())}
      submitLabel="Open project"
      submitDisabled={!path.trim()}
      busy={busy}
      error={error}
    >
      <p className="rh-projects__prose">
        Choose a folder that already holds a research workspace. Nothing in it is written
        until you ask for it.
      </p>
      <div className="rh-projects__picker">
        <Button type="button" onClick={() => void pick()}>
          Choose folder
        </Button>
        <p className="rh-projects__picked">
          {path ? <span className="rh-projects__path">{path}</span> : 'No folder chosen yet.'}
        </p>
      </div>
      {typed ? (
        <Input
          label="Folder path"
          value={path}
          onChange={(event) => setPath(event.target.value)}
          description={FALLBACK_EXPLANATION}
        />
      ) : null}
    </LifecycleDialog>
  );
}

// -- initialize --------------------------------------------------------------------

function InitializeDialog({ path, onClose }: { path: string; onClose: () => void }) {
  const lifecycle = useProjectLifecycle();
  const [name, setName] = useState(() => basename(path));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await lifecycle.initialize(path, name.trim(), DEFAULT_POLICY);
      onClose();
    } catch (cause) {
      setError(describeCause(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <LifecycleDialog
      title="Initialize research project"
      formId="rh-initialize-project"
      onClose={onClose}
      onSubmit={submit}
      submitLabel="Initialize project"
      submitDisabled={!name.trim()}
      busy={busy}
      error={error}
    >
      <p className="rh-projects__prose">
        <span className="rh-projects__path">{path}</span> is a folder, not a research
        workspace yet. Initializing it creates these, and changes nothing else that is
        already there:
      </p>
      <ul className="rh-projects__files">
        {INITIALIZED_FILES.map((file) => (
          <li key={file}>
            <span className="rh-projects__path">{file}</span>
          </li>
        ))}
      </ul>
      <Input
        label="Project name"
        value={name}
        autoFocus
        onChange={(event) => setName(event.target.value)}
      />
    </LifecycleDialog>
  );
}

// -- locate ---------------------------------------------------------------------------

function LocateDialog({ project, onClose }: { project: ProjectView; onClose: () => void }) {
  const lifecycle = useProjectLifecycle();
  const [path, setPath] = useState('');
  const [typed, setTyped] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const locate = useCallback(
    async (chosen: string): Promise<void> => {
      setBusy(true);
      setError(null);
      try {
        await lifecycle.locate(project.project_id, chosen);
        onClose();
      } catch (cause) {
        setTyped(true);
        setError(describeCause(cause));
      } finally {
        setBusy(false);
      }
    },
    [lifecycle, onClose, project.project_id],
  );

  const pick = useCallback(async (): Promise<void> => {
    setError(null);
    try {
      const selection = await lifecycle.chooseFolder('Locate the project folder');
      if (selection.fallback_required) {
        setTyped(true);
        return;
      }
      if (selection.cancelled || !selection.path) {
        onClose();
        return;
      }
      setPath(selection.path);
      await locate(selection.path);
    } catch (cause) {
      setTyped(true);
      setError(describeCause(cause));
    }
  }, [lifecycle, locate, onClose]);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void pick();
  }, [pick]);

  return (
    <LifecycleDialog
      title="Locate project folder"
      formId="rh-locate-project"
      onClose={onClose}
      onSubmit={() => locate(path.trim())}
      submitLabel="Locate project"
      submitDisabled={!path.trim()}
      busy={busy}
      error={error}
    >
      <p className="rh-projects__prose">
        Point <strong>{project.display_name}</strong> at the folder it moved to. Its
        remembered conversation and settings follow the project, not the path.
      </p>
      <div className="rh-projects__picker">
        <Button type="button" onClick={() => void pick()}>
          Choose folder
        </Button>
        <p className="rh-projects__picked">
          {path ? (
            <span className="rh-projects__path">{path}</span>
          ) : (
            <>
              Last known folder: <span className="rh-projects__path">{project.path}</span>
            </>
          )}
        </p>
      </div>
      {typed ? (
        <Input
          label="Folder path"
          value={path}
          onChange={(event) => setPath(event.target.value)}
          description={FALLBACK_EXPLANATION}
        />
      ) : null}
    </LifecycleDialog>
  );
}

// -- rename ---------------------------------------------------------------------------

function RenameDialog({ project, onClose }: { project: ProjectView; onClose: () => void }) {
  const lifecycle = useProjectLifecycle();
  const [name, setName] = useState(project.display_name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await lifecycle.rename(project.project_id, name.trim());
      onClose();
    } catch (cause) {
      setError(describeCause(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <LifecycleDialog
      title="Rename project"
      formId="rh-rename-project"
      onClose={onClose}
      onSubmit={submit}
      submitLabel="Rename project"
      submitDisabled={!name.trim()}
      busy={busy}
      error={error}
    >
      <Input
        label="Display name"
        value={name}
        autoFocus
        onChange={(event) => setName(event.target.value)}
        description="This is the name in this list only. It does not change research.yaml or any file in the workspace."
      />
    </LifecycleDialog>
  );
}

// -- forget ---------------------------------------------------------------------------

function ForgetDialog({ project, onClose }: { project: ProjectView; onClose: () => void }) {
  const lifecycle = useProjectLifecycle();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await lifecycle.forget(project.project_id);
      onClose();
    } catch (cause) {
      setError(describeCause(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <LifecycleDialog
      title="Forget project"
      formId="rh-forget-project"
      role="alertdialog"
      onClose={onClose}
      onSubmit={submit}
      submitLabel="Forget project"
      submitVariant="danger"
      busy={busy}
      error={error}
    >
      <p className="rh-projects__prose">
        <strong>{project.display_name}</strong> — <span className="rh-projects__path">{project.path}</span>
      </p>
      <p className="rh-projects__prose">{FORGET_EXPLANATION}</p>
    </LifecycleDialog>
  );
}

// -- the shared frame ------------------------------------------------------------------

interface LifecycleDialogProps {
  title: string;
  formId: string;
  role?: 'dialog' | 'alertdialog';
  onClose: () => void;
  onSubmit: () => Promise<void> | void;
  submitLabel: string;
  submitVariant?: 'primary' | 'danger';
  submitDisabled?: boolean;
  busy: boolean;
  error: string | null;
  children: ReactNode;
}

/**
 * One frame for all six: a titled dialog, a form, the host's refusal if there was one, and
 * a footer whose cancel half never mutates anything. The Design System's `Dialog` traps
 * focus while it is open and returns it to the control that opened it when it closes.
 */
function LifecycleDialog({
  title,
  formId,
  role = 'dialog',
  onClose,
  onSubmit,
  submitLabel,
  submitVariant = 'primary',
  submitDisabled = false,
  busy,
  error,
  children,
}: LifecycleDialogProps) {
  // The package's dialog restores focus when it is *closed*; these dialogs are unmounted
  // instead, one replacing another, so the opener is remembered here. A researcher who
  // cancels must land back on the control they pressed rather than at the top of the page.
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      const target = opener.current;
      if (target?.isConnected) target.focus({ preventScroll: true });
    };
  }, []);

  return (
    <Dialog open role={role} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogHeader>{title}</DialogHeader>
      <DialogBody>
        <form
          id={formId}
          className="rh-projects__form"
          onSubmit={(event) => {
            event.preventDefault();
            void onSubmit();
          }}
        >
          {children}
          {error ? (
            <ErrorNotice kind="retryable" title="The application refused" description={error} />
          ) : null}
        </form>
      </DialogBody>
      <DialogFooter>
        <Button type="button" onClick={onClose}>
          Cancel
        </Button>
        <Button
          type="submit"
          form={formId}
          variant={submitVariant}
          loading={busy}
          disabled={submitDisabled}
        >
          {submitLabel}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

function basename(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? '';
}

/** The host's own sentence when it sent one; otherwise whatever went wrong locally. */
export function describeCause(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

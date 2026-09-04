/**
 * Task 10.4: the lifecycle dialogs act only on what a human chose, and only when asked.
 *
 * The assertions below are the safety rules of design §6 and spec §4.4 written as
 * behaviour: a cancelled picker changes nothing; an ordinary folder is never initialized
 * because `open` happened to be clicked; Forget says in words that it deletes no files; a
 * refusal leaves the researcher's typing where it was. The Linux fallback is here too — on
 * a machine with no folder dialog the researcher must still be able to say which folder,
 * and typing it is an authenticated control-plane call like any other.
 */
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
import { AppClient, ControlError } from '../../api/projects';
import type { FolderSelection } from '../../api/projects';
import {
  expectNoAxeViolations,
  fakeAppDaemon,
  projectView,
  renderWithHost,
} from '../../test/harness';
import { ProjectDialogs } from './ProjectDialogs';
import type { ProjectDialog } from './ProjectDialogs';

const PROJECT = projectView();

const NATIVE: FolderSelection = {
  path: '/research/plain-folder',
  method: 'zenity',
  cancelled: false,
  fallback_required: false,
};
const CANCELLED: FolderSelection = {
  path: null,
  method: null,
  cancelled: true,
  fallback_required: false,
};
const NO_PICKER: FolderSelection = {
  path: null,
  method: null,
  cancelled: false,
  fallback_required: true,
};

function LocationProbe() {
  const location = useLocation();
  return <p data-testid="path">{location.pathname}</p>;
}

function DialogHarness({ initial }: { initial: NonNullable<ProjectDialog> }) {
  const [dialog, setDialog] = useState<ProjectDialog>(initial);
  return (
    <>
      <ProjectDialogs dialog={dialog} onClose={() => setDialog(null)} onDialog={setDialog} />
      <LocationProbe />
    </>
  );
}

function setup(initial: NonNullable<ProjectDialog>, options: { folder?: FolderSelection } = {}) {
  const daemon = fakeAppDaemon({ projects: [PROJECT], folder: options.folder ?? CANCELLED });
  const appClient = new AppClient({
    baseUrl: 'http://app.test',
    token: 'app-token',
    fetchImpl: daemon.fetch,
  });
  const spies = {
    chooseFolder: vi.spyOn(appClient, 'chooseFolder'),
    createProject: vi.spyOn(appClient, 'createProject'),
    openProject: vi.spyOn(appClient, 'openProject'),
    initializeProject: vi.spyOn(appClient, 'initializeProject'),
    locateProject: vi.spyOn(appClient, 'locateProject'),
    renameProject: vi.spyOn(appClient, 'renameProject'),
    forgetProject: vi.spyOn(appClient, 'forgetProject'),
  };
  const refreshProjects = vi.fn(async () => {});
  const view = renderWithHost(<DialogHarness initial={initial} />, {
    route: '/projects/prj_abc/',
    path: '*',
    host: { projects: [PROJECT], appClient, refreshProjects },
  });
  return { ...view, appClient, spies, refreshProjects, user: userEvent.setup() };
}

describe('the new-project dialog', () => {
  it('creates under the parent the native picker returned', async () => {
    const { user, spies } = setup(
      { kind: 'create' },
      { folder: { ...NATIVE, path: 'D:\\research', method: 'native' } },
    );

    await user.type(screen.getByLabelText('Project name'), 'Latency study');
    await user.click(screen.getByRole('button', { name: 'Choose parent folder' }));
    await screen.findByText(/D:\\research/);
    await user.click(screen.getByRole('button', { name: 'Create project' }));

    expect(spies.chooseFolder).toHaveBeenCalledWith('Choose a parent folder');
    await waitFor(() =>
      expect(spies.createProject).toHaveBeenCalledWith('D:\\research', 'Latency study', 'strict'),
    );
  });

  it('offers a typed path when the machine has no folder dialog', async () => {
    const { user, spies } = setup({ kind: 'create' }, { folder: NO_PICKER });

    await user.type(screen.getByLabelText('Project name'), 'Latency study');
    await user.click(screen.getByRole('button', { name: 'Choose parent folder' }));

    const typed = await screen.findByLabelText('Parent folder path');
    await user.type(typed, '/home/lee/research');
    await user.click(screen.getByRole('button', { name: 'Create project' }));

    await waitFor(() =>
      expect(spies.createProject).toHaveBeenCalledWith(
        '/home/lee/research',
        'Latency study',
        'strict',
      ),
    );
  });

  it('keeps what was typed after a refusal, and shows the host’s own sentence', async () => {
    const { user, spies } = setup(
      { kind: 'create' },
      { folder: { ...NATIVE, path: '/research', method: 'native' } },
    );
    spies.createProject.mockRejectedValue(
      new ControlError(409, 'project_exists', 'A folder named latency-study already exists.'),
    );

    await user.type(screen.getByLabelText('Project name'), 'Latency study');
    await user.click(screen.getByRole('button', { name: 'Choose parent folder' }));
    await screen.findByText(/\/research/);
    await user.click(screen.getByRole('button', { name: 'Create project' }));

    expect(
      await screen.findByText('A folder named latency-study already exists.'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Project name')).toHaveValue('Latency study');
    expect(screen.getByRole('dialog', { name: 'New project' })).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    setup({ kind: 'create' });
    await expectNoAxeViolations(document.body);
  });
});

describe('the open-folder dialog', () => {
  it('requires explicit initialization after open reports project_needs_initialization', async () => {
    const { spies } = setup({ kind: 'open' }, { folder: NATIVE });
    spies.openProject.mockRejectedValue(
      new ControlError(409, 'project_needs_initialization', 'This folder has no research.yaml.'),
    );

    expect(
      await screen.findByRole('dialog', { name: 'Initialize research project' }),
    ).toBeInTheDocument();
    expect(spies.initializeProject).not.toHaveBeenCalled();
    expect(screen.getByText('/research/plain-folder')).toBeInTheDocument();
  });

  it('mutates nothing when the researcher cancels the picker', async () => {
    const { spies } = setup({ kind: 'open' }, { folder: CANCELLED });

    await waitFor(() => expect(spies.chooseFolder).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(spies.openProject).not.toHaveBeenCalled();
    expect(spies.initializeProject).not.toHaveBeenCalled();
    expect(spies.createProject).not.toHaveBeenCalled();
  });

  it('opens a workspace the host accepted, and lands in it', async () => {
    const { spies } = setup({ kind: 'open' }, { folder: NATIVE });

    await waitFor(() => expect(spies.openProject).toHaveBeenCalledWith('/research/plain-folder'));
    await waitFor(() => expect(screen.getByTestId('path')).toHaveTextContent('/projects/prj_abc/'));
  });

  it('asks for the folder in writing when there is no picker', async () => {
    const { user, spies } = setup({ kind: 'open' }, { folder: NO_PICKER });

    const typed = await screen.findByLabelText('Folder path');
    await user.type(typed, '/research/latency-study');
    await user.click(screen.getByRole('button', { name: 'Open project' }));

    await waitFor(() =>
      expect(spies.openProject).toHaveBeenCalledWith('/research/latency-study'),
    );
  });
});

describe('the initialize dialog', () => {
  it('names every file it is about to create, and creates none until confirmed', async () => {
    const { user, spies } = setup({ kind: 'initialize', path: '/research/plain-folder' });

    for (const file of ['research.yaml', 'corpus/', 'claims/', 'decisions/', 'events/', '.research/']) {
      expect(screen.getByText(file)).toBeInTheDocument();
    }
    expect(spies.initializeProject).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Initialize project' }));

    await waitFor(() =>
      expect(spies.initializeProject).toHaveBeenCalledWith(
        '/research/plain-folder',
        'plain-folder',
        'strict',
      ),
    );
  });

  it('cancels without writing anything', async () => {
    const { user, spies } = setup({ kind: 'initialize', path: '/research/plain-folder' });

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(spies.initializeProject).not.toHaveBeenCalled();
  });
});

describe('the locate dialog', () => {
  it('points the registry entry at the folder the researcher chose', async () => {
    const { spies, refreshProjects } = setup(
      { kind: 'locate', project: PROJECT },
      { folder: { ...NATIVE, path: '/mnt/backup/latency-study' } },
    );

    await waitFor(() =>
      expect(spies.locateProject).toHaveBeenCalledWith('prj_abc', '/mnt/backup/latency-study'),
    );
    await waitFor(() => expect(refreshProjects).toHaveBeenCalled());
    // Locating is not opening: the researcher stays where they were.
    expect(screen.getByTestId('path')).toHaveTextContent('/projects/prj_abc/');
  });
});

describe('the rename dialog', () => {
  it('renames the entry and says that research.yaml is untouched', async () => {
    const { user, spies, refreshProjects } = setup({ kind: 'rename', project: PROJECT });

    const field = screen.getByLabelText('Display name');
    expect(field).toHaveValue('Latency study');
    expect(screen.getByText(/does not change research\.yaml/)).toBeInTheDocument();

    await user.clear(field);
    await user.type(field, 'Latency study 2026');
    await user.click(screen.getByRole('button', { name: 'Rename project' }));

    await waitFor(() =>
      expect(spies.renameProject).toHaveBeenCalledWith('prj_abc', 'Latency study 2026'),
    );
    await waitFor(() => expect(refreshProjects).toHaveBeenCalled());
  });
});

describe('the forget dialog', () => {
  it('states that Forget does not delete local files', () => {
    setup({ kind: 'forget', project: PROJECT });

    expect(screen.getByText(/files remain on disk/i)).toBeInTheDocument();
    expect(screen.getByText(/removes only this entry from your project list/i)).toBeInTheDocument();
  });

  it('forgets the entry and returns to Project Home', async () => {
    const { user, spies, refreshProjects } = setup({ kind: 'forget', project: PROJECT });

    await user.click(screen.getByRole('button', { name: 'Forget project' }));

    await waitFor(() => expect(spies.forgetProject).toHaveBeenCalledWith('prj_abc'));
    await waitFor(() => expect(screen.getByTestId('path')).toHaveTextContent('/'));
    expect(refreshProjects).toHaveBeenCalled();
  });

  it('asks before it does anything, and does nothing when cancelled', async () => {
    const { user, spies } = setup({ kind: 'forget', project: PROJECT });

    expect(screen.getByRole('alertdialog', { name: 'Forget project' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(spies.forgetProject).not.toHaveBeenCalled();
  });
});

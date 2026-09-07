import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { ProjectRail } from './ProjectRail';
import type { ProjectModel, RailItem } from '../models';

const project: ProjectModel = { id: 'P1', name: 'Thermal tolerance', path: '/home/r/thermal' };
const projects: ProjectModel[] = [project, { id: 'P2', name: 'Reef survey' }];

/** The registry as the application sees it on a bad day: one open, one gone, one locked. */
const mixedProjects: ProjectModel[] = [
  { ...project, activeRuns: 2 },
  {
    id: 'P2',
    name: 'Reef survey',
    availability: 'unavailable',
    detail: 'Folder not found',
  },
  {
    id: 'P3',
    name: 'Kelp forest',
    path: '/home/r/kelp',
    availability: 'busy',
    detail: 'Another window holds the lock',
  },
];

const items: RailItem[] = [
  { id: 'corpus', label: 'Corpus', to: '/corpus', icon: 'library' },
  { id: 'claims', label: 'Claims', to: '/claims', icon: 'bookmark', active: true },
  { id: 'review', label: 'Review inbox', icon: 'inbox', count: 4 },
];

/**
 * The rail the cockpit builds: two ways in, then three named runs of destinations.
 *
 * The names are the proposal's own (`docs/plans/2026-09-07-rail-grouping-proposal.md`,
 * option A), and the shape is the one property the component has to hold — a group is a run
 * of consecutive items sharing a word, not a field the caller nests by hand.
 */
const groupedItems: RailItem[] = [
  { id: 'conversation', label: 'Conversation', to: '/', icon: 'messages-square' },
  { id: 'overview', label: 'Overview', to: '/overview', icon: 'microscope' },
  { id: 'review', label: 'Review inbox', to: '/review', icon: 'inbox', count: 12, group: 'Waiting' },
  {
    id: 'conflicts',
    label: 'Conflicts',
    to: '/conflicts',
    icon: 'alert-triangle',
    count: 3,
    group: 'Waiting',
  },
  { id: 'stale', label: 'Stale', to: '/stale', icon: 'clock', count: 5, group: 'Waiting' },
  { id: 'corpus', label: 'Corpus', to: '/corpus', icon: 'library', group: 'The record' },
  { id: 'claims', label: 'Claims', to: '/claims', icon: 'scale', group: 'The record' },
  { id: 'questions', label: 'Questions', to: '/questions', icon: 'circle-help', group: 'The record' },
  { id: 'taxonomy', label: 'Taxonomy', to: '/taxonomy', icon: 'git-branch', group: 'The record' },
  { id: 'synthesis', label: 'Synthesis', to: '/synthesis', icon: 'layers', group: 'Outputs' },
  {
    id: 'manuscript',
    label: 'Manuscript',
    to: '/manuscript',
    icon: 'file-code',
    count: 2,
    group: 'Outputs',
  },
];

describe('ProjectRail', () => {
  it('names the project, its navigation and the current page', () => {
    render(<ProjectRail project={project} items={items} onNavigate={vi.fn()} />);
    expect(screen.getByRole('navigation', { name: 'Project navigation' })).toBeInTheDocument();
    expect(screen.getByText('Thermal tolerance')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Claims/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: /Corpus/ })).not.toHaveAttribute('aria-current');
  });

  it('renders a count as text beside the label', () => {
    render(<ProjectRail project={project} items={items} onNavigate={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Review inbox 4 Review inbox items' })).toBeInTheDocument();
  });

  it('switches project through a menu', async () => {
    const user = userEvent.setup();
    const onSelectProject = vi.fn();
    render(
      <ProjectRail project={project} projects={projects} onSelectProject={onSelectProject} />,
    );
    await user.click(
      screen.getByRole('button', { name: 'Project: Thermal tolerance. Switch project' }),
    );
    await user.click(screen.getByRole('menuitem', { name: 'Reef survey' }));
    expect(onSelectProject).toHaveBeenCalledWith('P2');
  });

  it('starts a new session and opens settings', async () => {
    const user = userEvent.setup();
    const onNewSession = vi.fn();
    const onOpenSettings = vi.fn();
    render(
      <ProjectRail project={project} onNewSession={onNewSession} onOpenSettings={onOpenSettings} />,
    );
    await user.click(screen.getByRole('button', { name: 'New session' }));
    await user.click(screen.getByRole('button', { name: 'Settings' }));
    expect(onNewSession).toHaveBeenCalledTimes(1);
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
  });

  it('states provider trouble in words as well as tone', () => {
    render(
      <ProjectRail
        project={project}
        providerStatus={{
          label: 'Local Ollama',
          state: 'offline',
          detail: 'No response on 127.0.0.1:11434',
        }}
      />,
    );
    expect(screen.getByText('Offline')).toBeInTheDocument();
    expect(screen.getByText('No response on 127.0.0.1:11434')).toBeInTheDocument();
  });

  it('collapses to icons and keeps every accessible name', async () => {
    const user = userEvent.setup();
    const onCollapsedChange = vi.fn();
    render(
      <ProjectRail
        project={project}
        items={items}
        onNavigate={vi.fn()}
        onNewSession={vi.fn()}
        onCollapsedChange={onCollapsedChange}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Collapse the rail' }));
    expect(onCollapsedChange).toHaveBeenCalledWith(true);

    expect(screen.getByRole('button', { name: 'Expand the rail' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    // Labels survive the collapse; nothing is available on hover alone.
    expect(screen.getByRole('link', { name: /Corpus/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New session' })).toBeInTheDocument();
  });

  it('is reachable and operable from the keyboard', async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    render(<ProjectRail project={project} items={items} onNavigate={onNavigate} />);
    const review = screen.getByRole('button', { name: /Review inbox/ });
    review.focus();
    await user.keyboard('{Enter}');
    expect(onNavigate).toHaveBeenCalledWith(items[2]);
  });

  it('shows project availability and background work in the switcher', async () => {
    const user = userEvent.setup();
    const onSelectProject = vi.fn();
    render(
      <ProjectRail
        project={mixedProjects[0] as ProjectModel}
        projects={mixedProjects}
        onSelectProject={onSelectProject}
      />,
    );
    await user.click(screen.getByRole('button', { name: /Switch project/ }));

    // `toBeDisabled` only reads the `disabled` attribute, and an ARIA menu item is not a
    // form control: the menu pattern's disabled state is `aria-disabled`.
    const unavailable = screen.getByRole('menuitem', { name: /Reef survey.*Unavailable/ });
    expect(unavailable).toHaveAttribute('aria-disabled', 'true');
    await user.click(unavailable);
    expect(onSelectProject).not.toHaveBeenCalled();

    expect(
      screen.getByRole('menuitem', { name: /Thermal tolerance.*2 active/ }),
    ).toHaveAttribute('aria-current', 'true');

    // Busy is stated in words too, and stays selectable — the work is somebody else's.
    const busy = screen.getByRole('menuitem', { name: /Kelp forest.*Busy/ });
    expect(busy).not.toHaveAttribute('aria-disabled');
    await user.click(busy);
    expect(onSelectProject).toHaveBeenCalledWith('P3');
  });

  it('states the open project availability and running work beside its name', () => {
    render(
      <ProjectRail project={mixedProjects[1] as ProjectModel} projects={mixedProjects} />,
    );
    expect(screen.getByText('Unavailable')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Project: Reef survey. Unavailable. Switch project' }),
    ).toBeInTheDocument();
  });

  it('keeps the status in the tooltip and the name when collapsed', () => {
    render(
      <ProjectRail
        project={mixedProjects[0] as ProjectModel}
        projects={mixedProjects}
        defaultCollapsed
      />,
    );
    const trigger = screen.getByRole('button', {
      name: 'Project: Thermal tolerance. 2 active. Switch project',
    });
    expect(trigger).toBeInTheDocument();
    expect(screen.queryByText('2 active')).not.toBeInTheDocument();
  });

  it('emits presentation-only project actions', async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<ProjectRail project={project} projects={[project]} onProjectAction={onAction} />);
    await user.click(screen.getByRole('button', { name: 'Project actions' }));
    expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual([
      'Show in file manager',
      'Locate folder',
      'Rename',
      'Forget project',
    ]);
    await user.click(screen.getByRole('menuitem', { name: 'Show in file manager' }));
    expect(onAction).toHaveBeenCalledWith('P1', 'reveal');
  });

  it.each([
    ['Locate folder', 'locate'],
    ['Rename', 'rename'],
    ['Forget project', 'forget'],
  ] as const)('emits %s as the %s action', async (itemLabel, action) => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<ProjectRail project={project} projects={projects} onProjectAction={onAction} />);
    await user.click(screen.getByRole('button', { name: 'Project actions' }));
    await user.click(screen.getByRole('menuitem', { name: itemLabel }));
    expect(onAction).toHaveBeenCalledWith('P1', action);
  });

  it('offers no actions menu when the host cannot act on the project', () => {
    render(<ProjectRail project={project} projects={projects} />);
    expect(screen.queryByRole('button', { name: 'Project actions' })).not.toBeInTheDocument();
  });

  it('adds a project from the switcher', async () => {
    const user = userEvent.setup();
    const onAddProject = vi.fn();
    render(<ProjectRail project={project} projects={projects} onAddProject={onAddProject} />);
    await user.click(screen.getByRole('button', { name: /Switch project/ }));
    await user.click(screen.getByRole('menuitem', { name: 'Add project' }));
    expect(onAddProject).toHaveBeenCalledTimes(1);
  });

  it('adds a project from the rail when there is no switcher', async () => {
    const user = userEvent.setup();
    const onAddProject = vi.fn();
    render(<ProjectRail project={project} onAddProject={onAddProject} />);
    await user.click(screen.getByRole('button', { name: 'Add project' }));
    expect(onAddProject).toHaveBeenCalledTimes(1);
  });

  it('opens project home from the top of the switcher', async () => {
    const user = userEvent.setup();
    const onOpenProjectHome = vi.fn();
    render(
      <ProjectRail
        project={project}
        projects={mixedProjects}
        onOpenProjectHome={onOpenProjectHome}
      />,
    );
    await user.click(screen.getByRole('button', { name: /Switch project/ }));
    const items = screen.getAllByRole('menuitem');
    expect(items[0]).toHaveTextContent('All projects');
    await user.click(screen.getByRole('menuitem', { name: 'All projects' }));
    expect(onOpenProjectHome).toHaveBeenCalledTimes(1);
  });

  it('keeps the single-project rail free of switcher markup', () => {
    const { container } = render(<ProjectRail project={project} />);
    expect(screen.queryByRole('button', { name: /Switch project/ })).not.toBeInTheDocument();
    expect(container.querySelector('button.rh-project-rail__project')).toBeNull();
  });

  it('names each run of grouped destinations and leaves the ungrouped ones flat', () => {
    render(<ProjectRail project={project} items={groupedItems} onNavigate={vi.fn()} />);

    // Each group is a list of its own, named by the heading a researcher can read.
    for (const [name, labels] of [
      ['Waiting', ['Review inbox', 'Conflicts', 'Stale']],
      ['The record', ['Corpus', 'Claims', 'Questions', 'Taxonomy']],
      ['Outputs', ['Synthesis', 'Manuscript']],
    ] as const) {
      const group = screen.getByRole('list', { name });
      expect(screen.getByText(name)).toBeInTheDocument();
      expect(
        within(group)
          .getAllByRole('link')
          .map((link) => link.textContent?.replace(/\d+ \w[\w ]*items/, '').trim()),
      ).toEqual([...labels]);
    }

    // Conversation and Overview keep no heading: they are the ways in, not a category.
    const nav = screen.getByRole('list', { name: 'Research' });
    expect(
      Array.from(nav.children)
        .filter((child) => child.querySelector(':scope > .rh-project-rail__nav-item') !== null)
        .map((child) => child.textContent),
    ).toEqual(['Conversation', 'Overview']);
  });

  it('keeps every destination’s name and count under a group', () => {
    render(<ProjectRail project={project} items={groupedItems} onNavigate={vi.fn()} />);

    expect(screen.getAllByRole('link')).toHaveLength(groupedItems.length);
    expect(
      screen.getByRole('link', { name: 'Review inbox 12 Review inbox items' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Manuscript 2 Manuscript items' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Taxonomy' })).toHaveAttribute('href', '/taxonomy');
  });

  it('adds no tab stop for a heading', () => {
    const { container } = render(
      <ProjectRail project={project} items={groupedItems} onNavigate={vi.fn()} />,
    );

    // A heading is text. The only things Tab reaches in this rail are the eleven links and
    // the collapse control — the drawer path of `browser-tests/app.spec.ts` counts on it.
    expect(container.querySelectorAll('a, button, [tabindex]')).toHaveLength(
      groupedItems.length + 1,
    );
    expect(screen.queryByRole('button', { name: 'Waiting' })).not.toBeInTheDocument();
    expect(screen.getByText('Waiting').tagName).toBe('P');
  });

  it('keeps a group’s name when the rail collapses, without printing the heading', () => {
    render(
      <ProjectRail
        project={project}
        items={groupedItems}
        onNavigate={vi.fn()}
        defaultCollapsed
      />,
    );

    // The strip is icons wide; the word survives as the list’s accessible name.
    expect(screen.getByRole('list', { name: 'Waiting' })).toBeInTheDocument();
    expect(screen.getByText('Waiting')).toHaveClass('rh-visually-hidden');
  });

  it('has no axe violations with grouped destinations', async () => {
    const { container } = render(
      <ProjectRail
        project={project}
        projects={projects}
        items={groupedItems}
        onNavigate={vi.fn()}
        onNewSession={vi.fn()}
        onOpenSettings={vi.fn()}
        providerStatus={{ label: 'Local Ollama', state: 'ok' }}
      />,
    );
    await expectNoAxeViolations(container);
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <ProjectRail
        project={project}
        projects={projects}
        items={items}
        onNavigate={vi.fn()}
        onNewSession={vi.fn()}
        onOpenSettings={vi.fn()}
        sessionList={<ul><li>Session one</li></ul>}
        providerStatus={{ label: 'Local Ollama', state: 'ok' }}
      />,
    );
    await expectNoAxeViolations(container);
  });

  it('has no axe violations with the switcher and the actions menu open', async () => {
    const user = userEvent.setup();
    render(
      <ProjectRail
        project={mixedProjects[0] as ProjectModel}
        projects={mixedProjects}
        onSelectProject={vi.fn()}
        onAddProject={vi.fn()}
        onOpenProjectHome={vi.fn()}
        onProjectAction={vi.fn()}
      />,
    );
    await user.click(screen.getByRole('button', { name: /Switch project/ }));
    await expectNoAxeViolations(document.body);
    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('button', { name: 'Project actions' }));
    await expectNoAxeViolations(document.body);
  });
});

describeThemeDensitySnapshots('ProjectRail', () => (
  <ProjectRail
    project={project}
    items={items}
    onNavigate={() => undefined}
    onNewSession={() => undefined}
    onOpenSettings={() => undefined}
    providerStatus={{ label: 'Local Ollama', state: 'ok' }}
  />
));


describeThemeDensitySnapshots('ProjectRail multi-project', () => (
  <ProjectRail
    project={mixedProjects[0] as ProjectModel}
    projects={mixedProjects}
    onSelectProject={() => undefined}
    onAddProject={() => undefined}
    onOpenProjectHome={() => undefined}
    onProjectAction={() => undefined}
    items={items}
    onNavigate={() => undefined}
    onNewSession={() => undefined}
    onOpenSettings={() => undefined}
    providerStatus={{ label: 'Local Ollama', state: 'ok' }}
  />
));


describeThemeDensitySnapshots('ProjectRail grouped', () => (
  <ProjectRail
    project={project}
    items={groupedItems}
    onNavigate={() => undefined}
    onNewSession={() => undefined}
    onOpenSettings={() => undefined}
    providerStatus={{ label: 'Local Ollama', state: 'ok' }}
  />
));

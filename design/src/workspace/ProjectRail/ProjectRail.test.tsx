import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { ProjectRail } from './ProjectRail';
import type { ProjectModel, RailItem } from '../models';

const project: ProjectModel = { id: 'P1', name: 'Thermal tolerance', path: '/home/r/thermal' };
const projects: ProjectModel[] = [project, { id: 'P2', name: 'Reef survey' }];

const items: RailItem[] = [
  { id: 'corpus', label: 'Corpus', to: '/corpus', icon: 'library' },
  { id: 'claims', label: 'Claims', to: '/claims', icon: 'bookmark', active: true },
  { id: 'review', label: 'Review inbox', icon: 'inbox', count: 4 },
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

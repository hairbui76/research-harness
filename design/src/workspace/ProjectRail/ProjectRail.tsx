import { forwardRef } from 'react';
import type { HTMLAttributes, ReactElement, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { useControllable } from '../../utils/useControllable';
import { useId } from '../../hooks/useId';
import { Button } from '../../primitives/Button';
import { Icon } from '../../primitives/Icon';
import type { IconName } from '../../primitives/Icon';
import { IconButton } from '../../primitives/IconButton';
import { Menu } from '../../primitives/Menu';
import { ScrollArea } from '../../primitives/ScrollArea';
import { Tooltip } from '../../primitives/Tooltip';
import { PROJECT_AVAILABILITY_META, PROVIDER_STATE_META } from '../models';
import type {
  ProjectAction,
  ProjectAvailability,
  ProjectModel,
  ProviderStatus,
  RailItem,
} from '../models';

/** The actions menu, in the order it is read out. Labels are the accessible names. */
const PROJECT_ACTIONS: readonly { action: ProjectAction; label: string; icon: IconName }[] = [
  { action: 'reveal', label: 'Show in file manager', icon: 'folder-open' },
  { action: 'locate', label: 'Locate folder', icon: 'search' },
  { action: 'rename', label: 'Rename', icon: 'pen-line' },
  { action: 'forget', label: 'Forget project', icon: 'trash-2' },
];

/** States in which selecting the project cannot succeed, so the switcher refuses it. */
const BLOCKED: readonly ProjectAvailability[] = ['unavailable', 'invalid', 'incompatible'];

/**
 * The destinations, cut into the runs the rail draws.
 *
 * A group is a run of *consecutive* items naming it, so the caller hands over one flat list
 * in the order it wants read and never nests anything. The same rule the command palette
 * groups by, for the same reason: the order is the caller's and is never rearranged, so a
 * name used twice in two places stays two runs rather than silently teleporting an item.
 */
function railRuns(items: readonly RailItem[]): { group?: string; items: RailItem[] }[] {
  const runs: { group?: string; items: RailItem[] }[] = [];
  for (const item of items) {
    const last = runs.at(-1);
    if (last && last.group === item.group) last.items.push(item);
    else runs.push({ ...(item.group === undefined ? {} : { group: item.group }), items: [item] });
  }
  return runs;
}

/**
 * What the rail says about a project besides its name: why it cannot be opened, and how
 * much of the researcher's work is still running in it.
 */
function statusParts(project: ProjectModel): string[] {
  const parts: string[] = [];
  const label = PROJECT_AVAILABILITY_META[project.availability ?? 'available'].label;
  if (label !== null) parts.push(label);
  if (project.activeRuns !== undefined && project.activeRuns > 0) {
    parts.push(`${project.activeRuns} active`);
  }
  return parts;
}

export interface ProjectRailProps extends HTMLAttributes<HTMLElement> {
  project: ProjectModel;
  /** Every project the switcher offers. Omit for a single-project host. */
  projects?: readonly ProjectModel[];
  onSelectProject?: (projectId: string) => void;
  /** Adds "Add project" to the switcher, or a rail control when there is no switcher. */
  onAddProject?: () => void;
  /** Adds "All projects" at the top of the switcher. */
  onOpenProjectHome?: () => void;
  /** Adds a "Project actions" menu for the open project. The host performs the action. */
  onProjectAction?: (projectId: string, action: ProjectAction) => void;
  onNewSession?: () => void;
  newSessionLabel?: string;
  /** The session history — `SessionList` in the Web client. */
  sessionList?: ReactNode;
  /**
   * The research destinations, in the order they are read. Consecutive items naming the
   * same `group` are drawn as one run under that heading; the rest stand on their own.
   */
  items?: readonly RailItem[];
  onNavigate?: (item: RailItem) => void;
  onOpenSettings?: () => void;
  providerStatus?: ProviderStatus;
  /** Collapse to icons. Controlled when provided. */
  collapsed?: boolean;
  defaultCollapsed?: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
  label?: string;
  navLabel?: string;
}

/** Wraps a control in a tooltip only while the rail is collapsed and the label is hidden. */
function MaybeTooltip({
  collapsed,
  content,
  children,
}: {
  collapsed: boolean;
  content: string;
  children: ReactElement;
}): ReactElement {
  if (!collapsed) return children;
  return <Tooltip content={content}>{children}</Tooltip>;
}

/**
 * The left pane of every research surface: which project is open, a new session, the
 * session history, the research pages, settings, and whether the model provider can be
 * reached.
 *
 * Collapsed it becomes a strip of icons — each one keeps its accessible name and gains a
 * tooltip, so nothing is available on hover alone. Every control is a real button or link,
 * so the rail is operable with Tab and Enter without a keyboard model of its own.
 */
export const ProjectRail = forwardRef<HTMLElement, ProjectRailProps>(function ProjectRail(
  {
    project,
    projects,
    onSelectProject,
    onAddProject,
    onOpenProjectHome,
    onProjectAction,
    onNewSession,
    newSessionLabel = 'New session',
    sessionList,
    items,
    onNavigate,
    onOpenSettings,
    providerStatus,
    collapsed,
    defaultCollapsed = false,
    onCollapsedChange,
    label = 'Project navigation',
    navLabel = 'Research',
    className,
    id,
    ...rest
  },
  ref,
) {
  const baseId = useId(id, 'rh-projectrail');
  const [isCollapsed, setCollapsed] = useControllable<boolean>({
    value: collapsed,
    defaultValue: defaultCollapsed,
    onChange: onCollapsedChange,
  });
  const switchable = projects !== undefined && projects.length > 0;
  const provider = providerStatus ? PROVIDER_STATE_META[providerStatus.state] : undefined;
  const openStatus = statusParts(project);
  const openTone = PROJECT_AVAILABILITY_META[project.availability ?? 'available'].tone;
  const openStatusText = openStatus.join(' · ');
  // Collapsed, the name and its status live in the tooltip and the accessible name.
  const projectTooltip =
    openStatus.length > 0 ? `${project.name} — ${openStatusText}` : project.name;
  const switchLabel =
    openStatus.length > 0
      ? `Project: ${project.name}. ${openStatus.join('. ')}. Switch project`
      : `Project: ${project.name}. Switch project`;

  /** One destination, identical whether or not a heading stands over it. */
  function renderNavItem(item: RailItem): ReactElement {
    const content = (
      <>
        <Icon name={item.icon} size={16} />
        {isCollapsed ? (
          <span className="rh-visually-hidden">{item.label}</span>
        ) : (
          <span className="rh-project-rail__nav-label">{item.label}</span>
        )}
        {item.count === undefined ? null : (
          <span className="rh-project-rail__nav-count">
            {item.count}
            <span className="rh-visually-hidden">{` ${item.label} items`}</span>
          </span>
        )}
      </>
    );
    const shared = {
      className: 'rh-project-rail__nav-item',
      'aria-current': item.active ? ('page' as const) : undefined,
      'data-active': item.active ? '' : undefined,
      onClick: () => onNavigate?.(item),
    };
    return (
      <li key={item.id}>
        <MaybeTooltip collapsed={isCollapsed} content={item.label}>
          {item.to === undefined ? (
            <button type="button" {...shared}>
              {content}
            </button>
          ) : (
            <a href={item.to} {...shared}>
              {content}
            </a>
          )}
        </MaybeTooltip>
      </li>
    );
  }

  const openStatusNode =
    openStatus.length > 0 ? (
      <span className="rh-project-rail__project-state" data-tone={openTone}>
        {openStatusText}
      </span>
    ) : null;

  return (
    <nav
      ref={ref}
      id={baseId}
      aria-label={label}
      className={cx('rh-project-rail', className)}
      data-collapsed={isCollapsed ? '' : undefined}
      {...rest}
    >
      <div className="rh-project-rail__head">
        {switchable ? (
          <Menu placement="bottom" align="start">
            <MaybeTooltip collapsed={isCollapsed} content={projectTooltip}>
              <Menu.Trigger className="rh-project-rail__project" aria-label={switchLabel}>
                <Icon name="folder" size={16} />
                {isCollapsed ? null : (
                  <>
                    <span className="rh-project-rail__project-name">{project.name}</span>
                    {openStatusNode}
                    <Icon name="chevron-down" size={14} />
                  </>
                )}
              </Menu.Trigger>
            </MaybeTooltip>
            <Menu.Content aria-label="Projects">
              {onOpenProjectHome ? (
                <>
                  <Menu.Item
                    icon={<Icon name="list" size={14} />}
                    onSelect={() => onOpenProjectHome()}
                  >
                    All projects
                  </Menu.Item>
                  <Menu.Separator />
                </>
              ) : null}
              <Menu.Group label="Projects">
                {projects.map((candidate) => {
                  const availability = candidate.availability ?? 'available';
                  const meta = PROJECT_AVAILABILITY_META[availability];
                  const isOpen = candidate.id === project.id;
                  const blocked = BLOCKED.includes(availability);
                  const runs = candidate.activeRuns ?? 0;
                  return (
                    <Menu.Item
                      key={candidate.id}
                      icon={<Icon name={isOpen ? 'check' : meta.icon} size={14} />}
                      hint={candidate.detail ?? candidate.path}
                      disabled={blocked}
                      aria-current={isOpen ? true : undefined}
                      onSelect={() => onSelectProject?.(candidate.id)}
                    >
                      <span className="rh-project-rail__option">
                        <span className="rh-project-rail__option-name">{candidate.name}</span>
                        {meta.label === null ? null : (
                          <span className="rh-project-rail__option-state" data-tone={meta.tone}>
                            {meta.label}
                          </span>
                        )}
                        {runs > 0 ? (
                          <span className="rh-project-rail__option-runs">{`${runs} active`}</span>
                        ) : null}
                      </span>
                    </Menu.Item>
                  );
                })}
              </Menu.Group>
              {onAddProject ? (
                <>
                  <Menu.Separator />
                  <Menu.Item icon={<Icon name="plus" size={14} />} onSelect={() => onAddProject()}>
                    Add project
                  </Menu.Item>
                </>
              ) : null}
            </Menu.Content>
          </Menu>
        ) : (
          <p className="rh-project-rail__project" title={project.path}>
            <Icon name="folder" size={16} />
            {isCollapsed ? (
              <span className="rh-visually-hidden">
                {openStatus.length > 0 ? `${project.name}. ${openStatus.join('. ')}` : project.name}
              </span>
            ) : (
              <>
                <span className="rh-project-rail__project-name">{project.name}</span>
                {openStatusNode}
              </>
            )}
          </p>
        )}

        {!switchable && onAddProject ? (
          <MaybeTooltip collapsed={isCollapsed} content="Add project">
            <IconButton
              className="rh-project-rail__head-control"
              icon="plus"
              label="Add project"
              size="sm"
              onClick={onAddProject}
            />
          </MaybeTooltip>
        ) : null}

        {onProjectAction ? (
          <Menu placement="bottom" align="end">
            <Menu.Trigger asChild>
              <IconButton
                className="rh-project-rail__head-control"
                icon="more-horizontal"
                label="Project actions"
                size="sm"
              />
            </Menu.Trigger>
            <Menu.Content aria-label={`Actions for ${project.name}`}>
              {PROJECT_ACTIONS.map(({ action, label: actionLabel, icon }) => (
                <Menu.Item
                  key={action}
                  icon={<Icon name={icon} size={14} />}
                  onSelect={() => onProjectAction(project.id, action)}
                >
                  {actionLabel}
                </Menu.Item>
              ))}
            </Menu.Content>
          </Menu>
        ) : null}

        <IconButton
          className="rh-project-rail__collapse"
          icon={isCollapsed ? 'panel-right' : 'panel-left'}
          label={isCollapsed ? 'Expand the rail' : 'Collapse the rail'}
          size="sm"
          aria-expanded={!isCollapsed}
          onClick={() => setCollapsed(!isCollapsed)}
        />
      </div>

      {onNewSession ? (
        <div className="rh-project-rail__new">
          <MaybeTooltip collapsed={isCollapsed} content={newSessionLabel}>
            {isCollapsed ? (
              <IconButton
                icon="plus"
                label={newSessionLabel}
                variant="primary"
                onClick={onNewSession}
              />
            ) : (
              <Button variant="primary" size="sm" iconStart="plus" fullWidth onClick={onNewSession}>
                {newSessionLabel}
              </Button>
            )}
          </MaybeTooltip>
        </div>
      ) : null}

      {sessionList !== undefined && !isCollapsed ? (
        <ScrollArea className="rh-project-rail__sessions" label="Session history">
          {sessionList}
        </ScrollArea>
      ) : null}

      {items !== undefined && items.length > 0 ? (
        <ul className="rh-project-rail__nav" aria-label={navLabel}>
          {railRuns(items).map((run, index) =>
            run.group === undefined ? (
              run.items.map(renderNavItem)
            ) : (
              <li key={`${run.group}-${index}`} className="rh-project-rail__nav-group">
                {/*
                 * The heading is text and the list's accessible name at once: a researcher
                 * reads it, a screen reader announces it on entering the run, and Tab never
                 * lands on it. Collapsed to icons there is no room to print it, so the word
                 * stays in the accessible name alone.
                 */}
                <p
                  id={`${baseId}-group-${index}`}
                  className={cx(
                    'rh-project-rail__nav-heading',
                    isCollapsed && 'rh-visually-hidden',
                  )}
                >
                  {run.group}
                </p>
                <ul
                  className="rh-project-rail__nav-items"
                  aria-labelledby={`${baseId}-group-${index}`}
                >
                  {run.items.map(renderNavItem)}
                </ul>
              </li>
            ),
          )}
        </ul>
      ) : null}

      <div className="rh-project-rail__foot">
        {providerStatus && provider ? (
          <p className="rh-project-rail__provider" data-tone={provider.tone}>
            <Icon name={provider.icon} size={14} />
            {isCollapsed ? (
              <span className="rh-visually-hidden">
                {`${providerStatus.label}: ${provider.label}`}
              </span>
            ) : (
              <span>
                <span className="rh-project-rail__provider-name">{providerStatus.label}</span>
                <span className="rh-project-rail__provider-state">{provider.label}</span>
                {providerStatus.detail ? (
                  <span className="rh-project-rail__provider-detail">{providerStatus.detail}</span>
                ) : null}
              </span>
            )}
          </p>
        ) : null}

        {onOpenSettings ? (
          <MaybeTooltip collapsed={isCollapsed} content="Settings">
            {isCollapsed ? (
              <IconButton icon="settings" label="Settings" size="sm" onClick={onOpenSettings} />
            ) : (
              <Button variant="ghost" size="sm" iconStart="settings" onClick={onOpenSettings}>
                Settings
              </Button>
            )}
          </MaybeTooltip>
        ) : null}
      </div>
    </nav>
  );
});

import { forwardRef } from 'react';
import type { HTMLAttributes, ReactElement, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { useControllable } from '../../utils/useControllable';
import { useId } from '../../hooks/useId';
import { Button } from '../../primitives/Button';
import { Icon } from '../../primitives/Icon';
import { IconButton } from '../../primitives/IconButton';
import { Menu } from '../../primitives/Menu';
import { ScrollArea } from '../../primitives/ScrollArea';
import { Tooltip } from '../../primitives/Tooltip';
import { PROVIDER_STATE_META } from '../models';
import type { ProjectModel, ProviderStatus, RailItem } from '../models';

export interface ProjectRailProps extends HTMLAttributes<HTMLElement> {
  project: ProjectModel;
  /** Every project the switcher offers. Omit for a single-project host. */
  projects?: readonly ProjectModel[];
  onSelectProject?: (projectId: string) => void;
  onNewSession?: () => void;
  newSessionLabel?: string;
  /** The session history — `SessionList` in the Web client. */
  sessionList?: ReactNode;
  /** Corpus, Claims, Questions, Synthesis, Taxonomy, Manuscript, Review, Conflicts, Stale. */
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
            <MaybeTooltip collapsed={isCollapsed} content={project.name}>
              <Menu.Trigger
                className="rh-project-rail__project"
                aria-label={`Project: ${project.name}. Switch project`}
              >
                <Icon name="folder" size={16} />
                {isCollapsed ? null : (
                  <>
                    <span className="rh-project-rail__project-name">{project.name}</span>
                    <Icon name="chevron-down" size={14} />
                  </>
                )}
              </Menu.Trigger>
            </MaybeTooltip>
            <Menu.Content aria-label="Projects">
              <Menu.Group label="Projects">
                {projects.map((candidate) => (
                  <Menu.Item
                    key={candidate.id}
                    icon={
                      <Icon name={candidate.id === project.id ? 'check' : 'folder'} size={14} />
                    }
                    hint={candidate.path}
                    onSelect={() => onSelectProject?.(candidate.id)}
                  >
                    {candidate.name}
                  </Menu.Item>
                ))}
              </Menu.Group>
            </Menu.Content>
          </Menu>
        ) : (
          <p className="rh-project-rail__project" title={project.path}>
            <Icon name="folder" size={16} />
            {isCollapsed ? (
              <span className="rh-visually-hidden">{project.name}</span>
            ) : (
              <span className="rh-project-rail__project-name">{project.name}</span>
            )}
          </p>
        )}

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
          {items.map((item) => {
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
          })}
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

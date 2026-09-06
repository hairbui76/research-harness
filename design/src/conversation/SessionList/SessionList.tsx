import { forwardRef, useRef, useState } from 'react';
import type { HTMLAttributes, KeyboardEvent as ReactKeyboardEvent, ReactElement, ReactNode } from 'react';
import { useControllableState } from '../../hooks/useControllableState';
import { Badge } from '../../primitives/Badge';
import { Button } from '../../primitives/Button';
import { IconButton } from '../../primitives/IconButton';
import { Input } from '../../primitives/Input';
import { VirtualList } from '../../primitives/VirtualList';
import { AsyncState } from '../../states/AsyncState';
import { cx } from '../../utils/cx';
import { formatMessageTime } from '../models';
import type { SessionSummary } from '../models';

export interface SessionListProps
  extends Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'onSelect'> {
  sessions: readonly SessionSummary[];
  activeId?: string | null;
  onSelect?: (sessionId: string) => void;
  /** Controlled search text. Filtering itself is the host's — this only reports typing. */
  query?: string;
  onQueryChange?: (query: string) => void;
  onNewSession?: () => void;
  /** Commit a rename. Called with the trimmed new title. */
  onRename?: (sessionId: string, title: string) => void;
  /** Controlled "which row is being renamed". */
  renamingId?: string | null;
  onRenamingChange?: (sessionId: string | null) => void;
  loading?: boolean;
  /** Windowed rendering starts at this many sessions. Default 40. */
  virtualizeFrom?: number;
  /** Height of the windowed list. Default 320. */
  height?: number;
  emptyMessage?: ReactNode;
  /** Override the timestamp formatting; the default is locale-independent. */
  formatTime?: (iso: string) => string;
  /** Accessible name for the list. Defaults to "Sessions". */
  label?: string;
}

interface SessionRowProps {
  session: SessionSummary;
  active: boolean;
  renaming: boolean;
  onSelect?: (sessionId: string) => void;
  onStartRename?: (sessionId: string) => void;
  onCommitRename: (sessionId: string, title: string) => void;
  onCancelRename: () => void;
  formatTime: (iso: string) => string;
}

function SessionRow({
  session,
  active,
  renaming,
  onSelect,
  onStartRename,
  onCommitRename,
  onCancelRename,
  formatTime,
}: SessionRowProps): ReactElement {
  const [draft, setDraft] = useState(session.title);
  const cancelled = useRef(false);

  if (renaming) {
    const commit = (): void => {
      if (cancelled.current) {
        cancelled.current = false;
        return;
      }
      const trimmed = draft.trim();
      if (trimmed.length > 0 && trimmed !== session.title) onCommitRename(session.id, trimmed);
      else onCancelRename();
    };
    const handleKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>): void => {
      if (event.key === 'Enter') {
        event.preventDefault();
        commit();
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        cancelled.current = true;
        setDraft(session.title);
        onCancelRename();
      }
    };
    return (
      <div className="rh-session-list__row" data-renaming="">
        <Input
          className="rh-session-list__rename"
          label={`Rename ${session.title}`}
          hideLabel
          size="sm"
          autoFocus
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={commit}
        />
      </div>
    );
  }

  return (
    <div className="rh-session-list__row" data-active={active || undefined}>
      <button
        type="button"
        className="rh-session-list__select"
        aria-current={active ? 'true' : undefined}
        onClick={() => onSelect?.(session.id)}
      >
        <span className="rh-session-list__title">{session.title}</span>
        {/* What this session is bound to, in the host's words — a fact about the record, so
            it sits with the title rather than in the metadata run. */}
        {session.binding !== undefined ? (
          <span className="rh-session-list__binding rh-text-secondary">{session.binding}</span>
        ) : null}
        <span className="rh-session-list__meta">
          <span className="rh-session-list__id">{session.id}</span>
          <time dateTime={session.updatedAt}>{formatTime(session.updatedAt)}</time>
          <span>
            {session.messageCount} {session.messageCount === 1 ? 'message' : 'messages'}
          </span>
          {session.visibility === 'private' ? <Badge status="private" size="sm" /> : null}
        </span>
        {session.preview !== undefined ? (
          <span className="rh-session-list__preview">{session.preview}</span>
        ) : null}
      </button>
      {onStartRename ? (
        <IconButton
          className="rh-session-list__rename-button"
          icon="pen-line"
          label={`Rename ${session.title}`}
          size="sm"
          onClick={() => onStartRename(session.id)}
        />
      ) : null}
    </div>
  );
}

/**
 * The session history: search, switch, rename, start a new one.
 *
 * Every session shows its stable `CS####` id and, where it applies, a `Private` marker —
 * a private session's transcript never leaves the machine and may not be bound to a CLI
 * runtime, and the list is the place that has to keep saying which sessions those are.
 * Long histories render through `VirtualList` so a project with a thousand sessions
 * scrolls like one with ten.
 */
export const SessionList = forwardRef<HTMLDivElement, SessionListProps>(function SessionList(
  {
    sessions,
    activeId = null,
    onSelect,
    query,
    onQueryChange,
    onNewSession,
    onRename,
    renamingId,
    onRenamingChange,
    loading = false,
    virtualizeFrom = 40,
    height = 320,
    emptyMessage = 'No sessions yet',
    formatTime = formatMessageTime,
    label = 'Sessions',
    className,
    ...rest
  },
  ref,
) {
  const [renaming, setRenaming] = useControllableState<string | null>({
    value: renamingId,
    defaultValue: null,
    onChange: onRenamingChange,
  });

  const startRename = onRename ? (sessionId: string) => setRenaming(sessionId) : undefined;
  const commitRename = (sessionId: string, title: string): void => {
    onRename?.(sessionId, title);
    setRenaming(null);
  };
  const cancelRename = (): void => setRenaming(null);

  const renderRow = (session: SessionSummary): ReactElement => (
    <SessionRow
      // Entering or leaving rename mode remounts the row, so the input starts from the
      // current title rather than from whatever was typed the last time.
      key={renaming === session.id ? 'rename' : 'view'}
      session={session}
      active={session.id === activeId}
      renaming={renaming === session.id}
      onSelect={onSelect}
      onStartRename={startRename}
      onCommitRename={commitRename}
      onCancelRename={cancelRename}
      formatTime={formatTime}
    />
  );

  const virtualise = sessions.length >= virtualizeFrom;

  return (
    <div ref={ref} className={cx('rh-session-list', className)} {...rest}>
      <div className="rh-session-list__toolbar">
        <Input
          className="rh-session-list__search"
          label="Search sessions"
          hideLabel
          size="sm"
          type="search"
          iconStart="search"
          placeholder="Search sessions"
          // Controlled only when the host actually owns the query, so an uncontrolled
          // search box still types.
          {...(query === undefined ? {} : { value: query })}
          onChange={(event) => onQueryChange?.(event.target.value)}
        />
        {onNewSession ? (
          <Button size="sm" variant="secondary" iconStart="plus" onClick={onNewSession}>
            New
          </Button>
        ) : null}
      </div>

      {loading ? (
        <AsyncState kind="loading" title="Loading sessions" compact />
      ) : sessions.length === 0 ? (
        <AsyncState
          kind="empty"
          hideKind
          title={emptyMessage}
          description={
            onNewSession
              ? 'Start a session to ask a question against this project.'
              : undefined
          }
          compact
        />
      ) : virtualise ? (
        <VirtualList<SessionSummary>
          className="rh-session-list__items"
          items={sessions}
          label={label}
          height={height}
          estimatedItemHeight={64}
          itemKey={(session) => session.id}
          renderItem={renderRow}
        />
      ) : (
        <ul className="rh-session-list__items" aria-label={label}>
          {sessions.map((session) => (
            <li key={session.id}>{renderRow(session)}</li>
          ))}
        </ul>
      )}
    </div>
  );
});

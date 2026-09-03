/**
 * The session history in the rail: search, switch, rename.
 *
 * It is in the shell rather than in the conversation route because the rail owns session
 * history on *every* screen (workspace design §2): a researcher reading a claim can still
 * see which conversation they were in and go back to it.
 *
 * Search is `session.search`, so a hit shows its snippet; with no query the list is every
 * session. Both are the daemon's answers — nothing is filtered here.
 */
import { ErrorNotice, SessionList } from '@research-harness/design';
import type { SessionSummary } from '@research-harness/design';
import { useSession } from '../../app/session';
import { toSessionSummary } from './mappers';
import { useConversation } from './state';

export function SessionListPane() {
  const { canMutate } = useSession();
  const { sessions } = useConversation();

  const shown: SessionSummary[] =
    sessions.matches === null
      ? sessions.sessions.map((session) => toSessionSummary(session))
      : sessions.matches.map((match) => {
          const record = sessions.sessions.find((session) => session.id === match.session);
          return record
            ? toSessionSummary(record, match.snippet)
            : {
                id: match.session,
                title: match.title,
                updatedAt: match.updated_at,
                messageCount: match.messages.length,
                visibility: 'private' as const,
                ...(match.snippet ? { preview: match.snippet } : {}),
              };
        });

  return (
    <>
      {sessions.refusal !== null ? (
        // The daemon's own sentence about a create or a rename it would not do.
        <ErrorNotice
          kind="blocked"
          title="That change to the session history was refused"
          description={sessions.refusal}
          safety={{ draft: 'safe', source: 'safe' }}
        />
      ) : null}
      <SessionList
        sessions={shown}
        activeId={sessions.activeId}
        onSelect={sessions.open}
        query={sessions.query}
        onQueryChange={sessions.setQuery}
        loading={sessions.loading}
        // Renaming is a mutation; a window that may only read is not offered the control.
        {...(canMutate
          ? { onRename: (id: string, title: string) => void sessions.rename(id, title) }
          : {})}
        emptyMessage={sessions.error ? 'Sessions could not be read' : 'No sessions yet'}
        height={280}
      />
    </>
  );
}

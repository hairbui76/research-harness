/**
 * The transcript: one row per turn, windowed, with the answer arriving in place.
 *
 * Everything a researcher can do to a message is in its action row rather than on hover
 * (the Design System's `Message` owns that decision): copy, retry, open the `Context used`
 * receipt, promote. Attempts are navigable inside their turn, so a retried question is one
 * row with its history rather than three rows that look like three questions.
 *
 * The Markdown renderer is the application's — `react-markdown` + KaTeX, with raw HTML off
 * and no network fetches (`src/render`) — and `rh://` links are resolved here rather than
 * navigated to, because whether a deep link may open depends on the object, not on the text.
 */
import { useCallback, useMemo } from 'react';
import type { ReactElement } from 'react';
import { useNavigate } from 'react-router-dom';
import { AsyncState, Button, ErrorNotice, Message, VirtualList } from '@research-harness/design';
import type { AttachmentModel, EntityRefModel, PromotionTarget } from '@research-harness/design';
import type { ConversationMessage } from '../../api/dto';
import { renderMarkdown } from '../../render';
import type { DeepLink } from '../../render';
import { groupAttempts, routeForDeepLink, toAttachmentModel, toMessageModel } from './mappers';
import type { MessageTurn } from './mappers';
import { useConversation } from './state';
import { useAttachmentUrls } from './useAttachmentUrls';
import { useSession } from '../../app/session';

export interface TranscriptProps {
  /** Which attempt of each turn is on screen, by turn key. */
  attemptOf: Record<string, number>;
  onAttemptChange: (turnKey: string, index: number) => void;
  onPromote: (message: ConversationMessage, target: PromotionTarget) => void;
}

export function Transcript({ attemptOf, onAttemptChange, onPromote }: TranscriptProps) {
  const {
    transcript: { transcript, loading, error, reconcile, loadMore, hasMore },
    send,
    selection,
    selectMessage,
    openRef,
    showReceipt,
    sessions,
  } = useConversation();
  const navigate = useNavigate();
  const { client } = useSession();

  // The byte routes take the token in a header, so an attachment is drawn from an object
  // URL rather than from a `src` the browser would fetch on its own.
  const records = useMemo(() => transcript?.attachments ?? [], [transcript]);
  const urls = useAttachmentUrls(client, sessions.activeId, records);

  const attachments = useMemo(() => {
    const map = new Map<string, AttachmentModel>();
    for (const record of records) map.set(record.id, toAttachmentModel(record, urls.get(record.id)));
    return map;
  }, [records, urls]);

  /**
   * The turns on disk, plus the answer that is still arriving.
   *
   * `session.send` reserves the assistant message's id before a byte of it exists, so
   * between the send and the first reconciliation there is a message id with no message
   * behind it. A placeholder turn carries the deltas until the read catches up; it is
   * keyed by that same id, so the moment `session.get` returns the real message the
   * placeholder is replaced rather than duplicated.
   */
  const turns = useMemo(() => {
    const grouped = groupAttempts(transcript?.messages ?? []);
    const streaming = send.streaming;
    if (streaming === null) return grouped;
    const known = grouped.some((turn) =>
      turn.attempts.some((message) => message.id === streaming.messageId),
    );
    if (known) return grouped;
    return [...grouped, { key: streaming.messageId, attempts: [pendingAnswer(streaming)] }];
  }, [send.streaming, transcript]);

  const unresolved = useMemo(() => new Set(send.unresolved), [send.unresolved]);

  const onDeepLink = useCallback(
    (link: DeepLink) => {
      const route = routeForDeepLink(link);
      if (route) navigate(route);
    },
    [navigate],
  );

  const render = useCallback(
    (text: string) => renderMarkdown(text, { onDeepLink }),
    [onDeepLink],
  );

  if (!sessions.activeId) {
    return (
      <AsyncState
        kind="empty"
        title="No session open"
        description="Start a session in the rail to ask a question against this project."
      />
    );
  }
  if (loading && transcript === null) return <AsyncState kind="loading" title="Reading the transcript" />;
  if (error) {
    return (
      <ErrorNotice
        kind="retryable"
        title="The transcript could not be read"
        description={error}
        safety={{ draft: 'safe', source: 'safe' }}
        actions={[{ label: 'Try again', onClick: () => void reconcile(), iconStart: 'refresh-cw' }]}
      />
    );
  }
  if (turns.length === 0) {
    return (
      <AsyncState
        kind="empty"
        title="Nothing said yet"
        description="Ask a question below. Nothing you send becomes accepted state on its own."
      />
    );
  }

  const renderTurn = (turn: MessageTurn): ReactElement => {
    const index = Math.min(attemptOf[turn.key] ?? turn.attempts.length - 1, turn.attempts.length - 1);
    const message = turn.attempts[index] as ConversationMessage;
    const streaming = send.streaming?.messageId === message.id;
    const model = toMessageModel(message, {
      attachments,
      unresolved,
      attempt: index + 1,
      attempts: turn.attempts.length,
      ...(streaming
        ? { streaming: true, streamingText: send.streaming?.text ?? '' }
        : {}),
    });
    const retryable =
      message.role === 'assistant' && !streaming
        ? () => void send.retry(message.id)
        : undefined;

    return (
      <Message
        key={message.id}
        message={model}
        renderMarkdown={render}
        selected={selection?.kind === 'message' && selection.messageId === message.id}
        onOpenRef={(entity: EntityRefModel) => openRef(entity)}
        onCopy={() => void copyMessage(message)}
        {...(retryable ? { onRetry: retryable } : {})}
        onOpenReceipt={(packId) => showReceipt({ kind: 'recorded', packId })}
        onPromote={(target: PromotionTarget) => onPromote(message, target)}
        actions={
          <>
            <Button
              size="sm"
              variant="ghost"
              iconStart="crosshair"
              onClick={() => selectMessage(message.id)}
            >
              Inspect
            </Button>
            {turn.attempts.length > 1 ? (
              <span className="rh-web-attempts">
                <Button
                  size="sm"
                  variant="ghost"
                  iconStart="chevron-left"
                  disabled={index === 0}
                  onClick={() => onAttemptChange(turn.key, index - 1)}
                >
                  Previous attempt
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  iconStart="chevron-right"
                  disabled={index === turn.attempts.length - 1}
                  onClick={() => onAttemptChange(turn.key, index + 1)}
                >
                  Next attempt
                </Button>
              </span>
            ) : null}
          </>
        }
      />
    );
  };

  return (
    <div className="rh-web-transcript">
      {hasMore ? (
        <Button size="sm" variant="secondary" iconStart="chevron-up" onClick={loadMore}>
          Load earlier messages
        </Button>
      ) : null}
      <VirtualList<MessageTurn>
        className="rh-web-transcript__list"
        items={turns}
        label="Conversation transcript"
        height="100%"
        estimatedItemHeight={220}
        itemKey={(turn) => turn.key}
        renderItem={renderTurn}
      />
    </div>
  );
}

/**
 * The message a run is writing, before `session.get` has one to return.
 *
 * It carries no content of its own: every block on screen comes from the deltas the daemon
 * has already persisted. It exists so the answer has somewhere to arrive, and it is gone as
 * soon as the transcript is re-read.
 */
function pendingAnswer(streaming: { messageId: string; attempt: number }): ConversationMessage {
  return {
    schema_version: 1,
    id: streaming.messageId,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    provenance: {},
    session: '',
    role: 'assistant',
    blocks: [],
    authority: 'private',
    visibility: 'private',
    attachments: [],
    context_pack: null,
    model: null,
    attempt: { number: streaming.attempt, status: 'complete', retry_of: null, error: null },
  };
}

/**
 * Copy one message's prose.
 *
 * The clipboard is the browser's and may refuse (no permission, no secure context); a
 * refusal is silent here because nothing was lost — the text is still on screen.
 */
async function copyMessage(message: ConversationMessage): Promise<void> {
  const text = message.blocks
    .filter((block): block is { kind: 'text'; text: string } => block.kind === 'text')
    .map((block) => block.text)
    .join('\n\n');
  try {
    await navigator.clipboard?.writeText(text);
  } catch {
    /* the researcher can still select it */
  }
}

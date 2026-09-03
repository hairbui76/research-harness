/**
 * `/` — the conversation workspace.
 *
 * The three panes of the workspace design are assembled from two places, on purpose. The
 * rail and the inspector are `AppShell`'s (`src/app/Layout.tsx`), because the shell owns
 * the narrow-screen behaviour the spec asks for: below the breakpoint both side panes
 * become drawers and `main` is never unmounted, so opening the session list cannot lose an
 * unsent draft (§9). This route owns the centre: `ConversationWorkspace` gives it a
 * toolbar, the scrolling transcript, and a composer pinned below it that never scrolls
 * away.
 *
 * The session travels in the query — `/?session=CS0001` — so a conversation is linkable
 * and survives a reload, and `rh://session/CS0001?message=M0042` resolves to
 * `/?session=CS0001&message=M0042`.
 *
 * Nothing on this screen is accepted scientific state. A message becomes reviewable only
 * through the explicit promotion dialog, and the receipt beside it says exactly what the
 * model was shown.
 */
import './conversation.css';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Badge, Button, ConversationWorkspace } from '@research-harness/design';
import type { PromotionTarget } from '@research-harness/design';
import type { ConversationMessage } from '../../api/dto';
import { ComposerPane } from './ComposerPane';
import { PromoteDialog } from './PromoteDialog';
import { Transcript } from './Transcript';
import { useConversation } from './state';

export function ConversationPage() {
  const { sessions, selectMessage, inspectorOpen, setInspectorOpen } = useConversation();
  const [params] = useSearchParams();
  const [attemptOf, setAttemptOf] = useState<Record<string, number>>({});
  const [promoting, setPromoting] = useState<{
    message: ConversationMessage;
    target: PromotionTarget;
  } | null>(null);
  const anchored = useRef<string | null>(null);

  // `?message=M0042` is a deep link into the transcript: select the turn it names, once,
  // so a later navigation inside the session is not fought over.
  const messageParam = params.get('message');
  useEffect(() => {
    if (!messageParam || anchored.current === messageParam) return;
    anchored.current = messageParam;
    selectMessage(messageParam);
  }, [messageParam, selectMessage]);

  const onAttemptChange = useCallback((turnKey: string, index: number) => {
    setAttemptOf((previous) => ({ ...previous, [turnKey]: index }));
  }, []);

  const onPromote = useCallback((message: ConversationMessage, target: PromotionTarget) => {
    setPromoting({ message, target });
  }, []);

  const session = sessions.active;

  return (
    <>
      <ConversationWorkspace
        className="rh-web-conversation"
        inspectorOpen={inspectorOpen}
        onInspectorOpenChange={setInspectorOpen}
        toolbar={
          <div className="rh-web-row">
            <h1 className="rh-text-h3">{session?.title ?? 'Conversation'}</h1>
            {session ? (
              <>
                <code>{session.id}</code>
                {session.visibility === 'private' ? <Badge status="private" size="sm" /> : null}
              </>
            ) : null}
            <Button
              size="sm"
              variant="ghost"
              iconStart="panel-right"
              aria-expanded={inspectorOpen}
              onClick={() => setInspectorOpen(!inspectorOpen)}
            >
              {inspectorOpen ? 'Hide the research inspector' : 'Show the research inspector'}
            </Button>
          </div>
        }
        transcript={
          <Transcript
            attemptOf={attemptOf}
            onAttemptChange={onAttemptChange}
            onPromote={onPromote}
          />
        }
        composer={<ComposerPane />}
      />
      <PromoteDialog
        open={promoting !== null}
        onOpenChange={(open) => !open && setPromoting(null)}
        message={promoting?.message ?? null}
        target={promoting?.target ?? 'note'}
      />
    </>
  );
}

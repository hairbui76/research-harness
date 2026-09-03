/**
 * The composer: the draft, the model, the references, and one send.
 *
 * The draft is `useDraft`'s, so it is already on disk before this component renders it;
 * nothing here clears it except a send that produced a durable message. A refusal —
 * a private session against an external provider, an agent host that may not write — is
 * rendered as the daemon's own sentence in the Design System's blocking notice, which
 * states in words that the message and its attachments are untouched.
 *
 * Two slots are deliberately empty and named for the tasks that fill them: `onAttach` and
 * `attachmentTray` (task W2, attachments), and the reference provider behind the `@`
 * picker (task W3, `graph.autocomplete`). The composer needs no change for either.
 */
import { useCallback, useMemo } from 'react';
import { Button, Composer, ErrorNotice, ModelSelector } from '@research-harness/design';
import type { ComposerBlockedReason, ComposerSendState } from '@research-harness/design';
import { useConversation } from './state';

export function ComposerPane() {
  const { sessions, draft, send, models, references, showReceipt, model, setModel } =
    useConversation();
  const session = sessions.active;

  const sendState: ComposerSendState = send.sending
    ? 'sending'
    : send.streaming !== null
      ? 'streaming'
      : 'idle';

  /**
   * A refusal blocks the send; a transport failure does not.
   *
   * Both render the daemon's own words. The difference is what to offer next: the same
   * request would be refused the same way, so a refusal disables Send until the message or
   * the model changes, while a connection that dropped is simply worth trying again.
   * Neither one touches the draft.
   */
  const blockedReasons = useMemo<ComposerBlockedReason[]>(
    () => (send.error !== null && !send.retryable ? [{ reason: send.error }] : []),
    [send.error, send.retryable],
  );

  /**
   * A refusal is about *this* message going to *that* model, so it stands until one of
   * them changes. Editing the draft or picking another model clears it and re-enables
   * Send; the words themselves are never touched by any of this.
   */
  const onChange = useCallback(
    (next: typeof draft.value) => {
      draft.setValue(next);
      if (send.error !== null) send.dismissError();
    },
    [draft, send],
  );

  const onSend = useCallback(() => {
    const references_ = draft.value.tokens.map((token) => token.id);
    void send
      .send({
        text: draft.value.text,
        references: references_,
        ...(model ? { model } : {}),
      })
      .then((ok) => {
        // Only a send that produced a durable message empties the composer (spec §8).
        if (ok) draft.clear();
      });
  }, [draft, model, send]);

  const onPreview = useCallback(() => {
    if (!session) return;
    showReceipt({
      kind: 'draft',
      text: draft.value.text,
      references: draft.value.tokens.map((token) => token.id),
      model,
    });
  }, [draft.value, model, session, showReceipt]);

  const selectedModel = model ?? models.defaultId ?? '';

  return (
    <div className="rh-web-composer">
      {models.unavailable ? (
        <p className="rh-web-composer__note rh-text-secondary">{models.unavailable}</p>
      ) : null}
      {send.error !== null && send.retryable ? (
        <ErrorNotice
          kind="retryable"
          title="The message did not get through"
          description={send.error}
          safety={{ draft: 'safe', note: 'Your message is exactly where you left it.' }}
          actions={[{ label: 'Try again', onClick: onSend, iconStart: 'refresh-cw' }]}
          onDismiss={send.dismissError}
        />
      ) : null}
      <Composer
        value={draft.value}
        onChange={onChange}
        onSend={onSend}
        onStop={() => void send.stop()}
        sendState={sendState}
        disabled={session === null}
        {...(blockedReasons.length > 0 ? { blockedReasons } : {})}
        referenceResults={references.results}
        referenceLoading={references.loading}
        onReferenceQuery={references.search}
        {...(models.options.length > 0
          ? {
              modelSelector: (
                <ModelSelector
                  options={models.options}
                  value={selectedModel}
                  onChange={(option) => {
                    setModel(option.id);
                    if (send.error !== null) send.dismissError();
                  }}
                />
              ),
            }
          : {})}
        actions={
          <Button
            size="sm"
            variant="ghost"
            iconStart="list"
            disabled={session === null}
            onClick={onPreview}
          >
            Preview context
          </Button>
        }
      />
    </div>
  );
}

/**
 * The composer: the draft, the model, the references, and one send.
 *
 * The draft is `useDraft`'s, so it is already on disk before this component renders it;
 * nothing here clears it except a send that produced a durable message. A refusal —
 * a private session against an external provider, an agent host that may not write — is
 * rendered as the daemon's own sentence in the Design System's blocking notice, which
 * states in words that the message and its attachments are untouched.
 *
 * Attachments (task W2) fill `onAttach` and `attachmentTray`: files dropped anywhere on
 * the composer, or chosen through its paperclip, go to the same intake, and the tray below
 * lists each one with its own state, its own verdict against the selected model and its
 * own `Save to corpus`. References (task W3) fill the picker behind `@` from
 * `graph.autocomplete`, and the two strips above the box are theirs: which index is
 * answering when it is not the graph, and the draft's references the resolver could not
 * confirm — marked, and still sendable.
 */
import { useCallback, useMemo } from 'react';
import { Button, Composer, ErrorNotice, ModelSelector } from '@research-harness/design';
import type { ComposerBlockedReason, ComposerSendState } from '@research-harness/design';
import { AttachmentTrayPane } from './attachments/AttachmentTrayPane';
import { GraphStatusNotice, ReferenceMarks } from './references';
import { useConversation } from './state';

export function ComposerPane() {
  const {
    sessions,
    draft,
    send,
    models,
    references,
    showReceipt,
    model,
    setModel,
    attachments,
    renderAttachmentPage,
    openRef,
    // References and the graph (task W3): which index answers `@`, and what the resolver
    // said about each token in the draft.
    graph,
    draftReferences,
  } = useConversation();
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
    () => [
      ...(send.error !== null && !send.retryable ? [{ reason: send.error }] : []),
      // Every attachment the selected model cannot take, each with its own reason and the
      // model the daemon suggests instead. All of them at once: fixing one file, being
      // refused again and fixing the next is not what "block the send" should feel like
      // (attachments design §5).
      ...attachments.blockedReasons,
    ],
    [attachments.blockedReasons, send.error, send.retryable],
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

  /**
   * Send, after one last check against the model that is selected right now.
   *
   * The check is re-run here rather than trusted from the last render because the model
   * selector and the tray are two controls the researcher can change between one and the
   * other. A verdict that comes back blocked stops the send before anything is written —
   * the reasons are already on screen, the draft is untouched, and the attachments stay
   * exactly where they are. A check that could not run at all does not stop it: the daemon
   * runs the same check inside `session.send` and refuses there in its own words.
   */
  const onSend = useCallback(() => {
    const references_ = draft.value.tokens.map((token) => token.id);
    const ids = attachments.files.sendableIds;
    void (async () => {
      if (ids.length > 0) {
        const verdict = await attachments.send.refresh();
        if (verdict !== null && !verdict.ok) return;
      }
      const ok = await send.send({
        text: draft.value.text,
        references: references_,
        ...(ids.length > 0 ? { attachments: ids } : {}),
        ...(model ? { model } : {}),
      });
      // Only a send that produced a durable message empties the composer (spec §8).
      if (ok) draft.clear();
    })();
  }, [attachments.files.sendableIds, attachments.send, draft, model, send]);

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
      {/* References and the graph (task W3). Completion falls back to the project listings
          when `graph.status` says the index is absent, rebuilding or unreadable, and this
          is the one place that says so — once, beside the composer, in the Design System's
          own wording (graph spec §8). */}
      <GraphStatusNotice
        degradation={graph.degradation}
        answering={graph.answering}
        onRecheck={graph.recheck}
      />
      {/* References and the graph (task W3). Every token in the draft is resolved against
          canonical state; the ones that did not come back clean are marked here, with the
          resolver's own sentence, before the message is sent (conversation spec §7). They
          stay sendable — nothing below removes a token or disables Send. */}
      <ReferenceMarks
        tokens={draft.value.tokens}
        flagged={draftReferences.flagged}
        onOpen={openRef}
      />
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
        {...(attachments.files.canAttach
          ? { onAttach: (files: File[]) => void attachments.files.attach(files) }
          : {})}
        attachmentTray={
          <AttachmentTrayPane
            attachments={attachments}
            renderPage={renderAttachmentPage}
            onOpenRef={openRef}
          />
        }
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

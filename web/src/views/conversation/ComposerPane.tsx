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
 *
 * The model picker binds the session (binding spec §10). Its groups are the configured
 * entries and one per CLI runtime the daemon's scan found installed, and picking one calls
 * `session.configure`, so the value on screen is read back from the record the daemon
 * stored rather than from anything held here — a second window and a reload agree about
 * it. A runtime is an external destination, so the first binding in a session shows the
 * scan's own egress notice first. A window that may not write keeps exactly today's
 * behaviour instead: the pick is this message's model, and the runtime rows are disabled
 * with the session's mutation-blocked sentence (plan ruling 5).
 */
import { useCallback, useMemo, useState } from 'react';
import {
  Button,
  Composer,
  Dialog,
  ErrorNotice,
  ModelSelector,
  Select,
} from '@research-harness/design';
import type {
  ComposerBlockedReason,
  ComposerSendState,
  ModelOption,
  ModelOptionGroup,
} from '@research-harness/design';
import { useSession } from '../../app/session';
import { AttachmentTrayPane } from './attachments/AttachmentTrayPane';
import { bindingOptionId, parseRuntimeOptionId } from './mappers';
import { GraphStatusNotice, ReferenceMarks } from './references';
import { useConversation } from './state';

/**
 * Where this browser remembers that a session's egress disclosure has been read.
 *
 * A convenience and nothing more: the daemon's receipt panel still states each message's
 * egress class, so the destination is never visible only here (binding spec §10). Storage
 * that throws — a private window, a browser with site data off — simply means the notice
 * is shown again, which is the safe way for this to fail.
 */
const DISCLOSED_PREFIX = 'rh.binding-disclosed.';

function disclosureRead(sessionId: string): boolean {
  try {
    return window.localStorage.getItem(`${DISCLOSED_PREFIX}${sessionId}`) !== null;
  } catch {
    return false;
  }
}

function rememberDisclosure(sessionId: string): void {
  try {
    window.localStorage.setItem(`${DISCLOSED_PREFIX}${sessionId}`, 'read');
  } catch {
    /* the notice is simply shown again next time */
  }
}

/** The catalogue's own heading in the picker; the runtime groups follow it (spec §10). */
const ENTRY_GROUP = 'Configured entries';

/** The reasoning option that sends nothing, so the runtime applies its own default. */
const RUNTIME_DEFAULT_REASONING = '';

export function ComposerPane() {
  const { canMutate, mutationBlockedReason } = useSession();
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
  /** The runtime pick waiting on the egress disclosure, when one is. */
  const [pending, setPending] = useState<{ runtime: string; model: string } | null>(null);

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

  /**
   * What the selector says, and where the answer comes from.
   *
   * The session record first: the binding is the daemon's, read back from what it stored,
   * so a second window and a reload agree about it (binding spec §10). `model` is the
   * per-message choice a read-only window still has (plan ruling 5) and is never set in a
   * window that binds, so the two never fight.
   */
  const bound = session ? bindingOptionId(session.defaults) : null;
  const selectedModel = model ?? bound ?? models.defaultId ?? '';

  /** The runtime binding on the record, when the record carries one. */
  const runtimeBinding = useMemo(
    () => (bound === null ? null : parseRuntimeOptionId(bound)),
    [bound],
  );

  /**
   * The picker's groups: the catalogue first, then one per installed runtime.
   *
   * A window that may not bind sees the runtime rows disabled with the session's own
   * mutation-blocked sentence rather than not at all — the researcher is told what this
   * cockpit cannot do here, not left to guess why the runtimes are missing.
   */
  const groups = useMemo<ModelOptionGroup[]>(() => {
    const runtimes = canMutate
      ? models.groups
      : models.groups.map((group) => ({
          ...group,
          options: group.options.map((option) => ({
            ...option,
            available: false,
            ...(mutationBlockedReason ? { unavailableReason: mutationBlockedReason } : {}),
          })),
        }));
    return [
      ...(models.options.length > 0
        ? [{ id: 'entries', label: ENTRY_GROUP, options: models.options }]
        : []),
      ...runtimes,
    ];
  }, [canMutate, models.groups, models.options, mutationBlockedReason]);

  /**
   * Picking a model.
   *
   * In a window that may write, a pick *binds the session*: the daemon stores it and the
   * value comes back from the record. A runtime is an external destination, so the first
   * one in a session is disclosed first, in the scan's own sentence. A read-only window
   * keeps exactly today's behaviour — the pick is this message's model and nothing
   * durable changes (plan ruling 5).
   */
  const onPickModel = useCallback(
    (option: ModelOption) => {
      if (send.error !== null) send.dismissError();
      if (!session || !canMutate) {
        setModel(option.id);
        return;
      }
      const runtime = parseRuntimeOptionId(option.id);
      if (runtime === null) {
        void sessions.configure(session.id, { entry: option.id });
        return;
      }
      if (!disclosureRead(session.id)) {
        setPending(runtime);
        return;
      }
      void sessions.configure(session.id, runtime);
    },
    [canMutate, send, session, sessions, setModel],
  );

  /** The runtime's name as the scan gave it, for the disclosure's heading. */
  const pendingRuntimeName =
    (pending && models.groups.find((group) => group.id === pending.runtime)?.label) ??
    pending?.runtime ??
    '';

  /** Confirming the disclosure: remembered for this session, then bound. */
  const onConfirmBinding = useCallback(() => {
    if (!session || pending === null) return;
    rememberDisclosure(session.id);
    setPending(null);
    void sessions.configure(session.id, pending);
  }, [pending, session, sessions]);

  /** Changing the effort level rebinds the same runtime and model with it. */
  const onPickReasoning = useCallback(
    (value: string) => {
      if (!session || runtimeBinding === null) return;
      void sessions.configure(session.id, {
        ...runtimeBinding,
        ...(value === RUNTIME_DEFAULT_REASONING ? {} : { reasoning: value }),
      });
    },
    [runtimeBinding, session, sessions],
  );

  const reasoningChoices = runtimeBinding
    ? models.reasoningChoices(runtimeBinding.runtime)
    : [];

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
                <span className="rh-web-composer__model">
                  {/* Everything is a labelled group: the catalogue has a heading of its
                      own so the runtimes below it read as the alternatives they are. */}
                  <ModelSelector
                    options={[]}
                    groups={groups}
                    value={selectedModel}
                    onChange={onPickModel}
                  />
                  {/* The effort level belongs to a runtime binding and to nothing else, so
                      it is here only while one is in force, with the runtime's own words. */}
                  {runtimeBinding !== null && reasoningChoices.length > 0 ? (
                    <Select
                      label="Reasoning"
                      hideLabel
                      size="sm"
                      value={session?.defaults.reasoning ?? RUNTIME_DEFAULT_REASONING}
                      disabled={!canMutate}
                      onChange={(event) => onPickReasoning(event.target.value)}
                    >
                      <option value={RUNTIME_DEFAULT_REASONING}>Runtime default</option>
                      {reasoningChoices.map((choice) => (
                        <option key={choice} value={choice}>
                          {choice}
                        </option>
                      ))}
                    </Select>
                  ) : null}
                </span>
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
      {/*
        The disclosure, before a session's first binding to an external destination.

        `alertdialog`, because it is a decision about where research content goes and it is
        answered before anything happens. The body is the scan's own `notice`: this cockpit
        does not write its own sentence about egress.
      */}
      <Dialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        role="alertdialog"
        size="sm"
      >
        <Dialog.Header>{`Bind this session to ${pendingRuntimeName}`}</Dialog.Header>
        <Dialog.Body>
          <p className="rh-text-secondary">{models.notice}</p>
        </Dialog.Body>
        <Dialog.Footer>
          <Button variant="ghost" onClick={() => setPending(null)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={onConfirmBinding}>
            Use this runtime
          </Button>
        </Dialog.Footer>
      </Dialog>
    </div>
  );
}

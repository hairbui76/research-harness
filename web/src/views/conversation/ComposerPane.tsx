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
 *
 * The disclosure is answered once and never seen again, so the composer also keeps a
 * standing line naming where the message in the box would go and whether it leaves the
 * machine. It is a reading of the current selection rather than a memory of that dialog,
 * and it is an addition to the surfaces that already state the destination — the rail's
 * binding words and the receipt's egress class — never a replacement for them.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { ATTACHMENT_HINT, AttachmentTrayPane } from './attachments/AttachmentTrayPane';
import {
  PROJECT_DEFAULT_OPTION,
  bindingOptionId,
  bindingWords,
  parseRuntimeOptionId,
  toProjectDefaultOption,
} from './mappers';
import { GraphStatusNote, ReferenceMarks } from './references';
import { useConversation } from './state';
import type { RuntimeDestination } from './useModels';

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

/** The row that unbinds has a heading of its own: it is about the session, not a provider. */
const SESSION_GROUP = 'Session';

/** The catalogue's own heading in the picker; the runtime groups follow it (spec §10). */
const ENTRY_GROUP = 'Configured entries';

/** The reasoning option that sends nothing, so the runtime applies its own default. */
const RUNTIME_DEFAULT_REASONING = '';

/**
 * Where this message goes, in one line, for as long as the composer is open.
 *
 * The disclosure is answered once and then never seen again, and the picker is a control:
 * it says which model is chosen, not what choosing it means. So the composer keeps a
 * standing statement of the destination, and this is the only place its wording is decided
 * (Impeccable question 4).
 *
 * Nothing here is derived from a rule of the cockpit's own. A runtime binding is read from
 * the daemon's scan — the runtime's name and the host it reaches are the same two fields
 * the CLI's `egress_sentence` uses — and every other selection is read from the catalogue
 * row the picker is showing, egress class included, so the line and the trigger can never
 * disagree about where the next message is headed. A binding whose row the picker was
 * never given is named and left at that: the same rule `ModelSelector.fallbackLabel`
 * follows, because nothing about its egress is known here.
 */
export function destinationWords(input: {
  /** The runtime the *selection* names, which is not always the record's binding. */
  runtime: { runtime: string; model: string } | null;
  /** Every scanned runtime's destination, keyed by runtime id; empty when no scan answered. */
  destinations: Record<string, RuntimeDestination>;
  /** The catalogue or session row the picker has selected, when the selection names one. */
  option: ModelOption | null;
  /** The binding words the record carries, for a binding no row was given for. */
  binding: string | null;
}): string | null {
  const { runtime, destinations, option, binding } = input;
  if (runtime !== null) {
    const scanned = destinations[runtime.runtime] ?? null;
    // Every CLI runtime is external egress with a vendor on the other end (binding spec
    // §15), so the sentence survives a scan that could not be read; only the host, which is
    // the scan's own fact, drops out of it.
    const where =
      scanned === null ? 'leaves this machine' : `leaves this machine for ${scanned.egressHost}`;
    return `Sends to ${scanned?.name ?? runtime.runtime} · ${runtime.model} — ${where}`;
  }
  if (option !== null) {
    const where =
      option.egressClass === 'local' ? 'stays on this machine' : 'leaves this machine';
    return `Sends to ${option.label} — ${where}`;
  }
  return binding === null ? null : `Sends to ${binding}`;
}

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
  /** The daemon's sentence about a binding it would not store, beside the control that asked. */
  const [refusal, setRefusal] = useState<string | null>(null);

  /**
   * Both of those are about *this* session, so neither survives a move to another one: a
   * refusal that named the session you just left, or a disclosure you never answered, would
   * be a statement about the wrong conversation.
   *
   * The ref is the same rule for an answer still in flight. `session.configure` is a round
   * trip, and the researcher can change conversation while it is out; the sentence that
   * comes back is about the session it was asked for, so it is dropped rather than planted
   * on whichever session happens to be open when it lands.
   */
  const sessionId = session?.id ?? null;
  const openSession = useRef(sessionId);
  useEffect(() => {
    openSession.current = sessionId;
    setPending(null);
    setRefusal(null);
  }, [sessionId]);

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
  const selectedModel = model ?? bound ?? PROJECT_DEFAULT_OPTION;

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
    // The row that unbinds leads, in a heading of its own: it is an answer about the
    // session, not an entry in the catalogue, and a project with no `providers:` table at
    // all still has to be able to clear a runtime binding.
    const projectDefault = toProjectDefaultOption(
      models.options.find((option) => option.id === models.defaultId) ?? null,
    );
    return [
      { id: 'session', label: SESSION_GROUP, options: [projectDefault] },
      ...(models.options.length > 0
        ? [{ id: 'entries', label: ENTRY_GROUP, options: models.options }]
        : []),
      ...runtimes,
    ];
  }, [canMutate, models.defaultId, models.groups, models.options, mutationBlockedReason]);

  /**
   * Picking a model.
   *
   * In a window that may write, a pick *binds the session*: the daemon stores it and the
   * value comes back from the record. A runtime is an external destination, so the first
   * one in a session is disclosed first, in the scan's own sentence. A read-only window
   * keeps exactly today's behaviour — the pick is this message's model and nothing
   * durable changes (plan ruling 5).
   */
  /** Bind, and keep the daemon's sentence here when it would not — for this session only. */
  const bind = useCallback(
    (target: string, input: Parameters<typeof sessions.configure>[1]) => {
      void sessions.configure(target, input).then((message) => {
        if (openSession.current !== target) return;
        setRefusal(message);
      });
    },
    [sessions],
  );

  const onPickModel = useCallback(
    (option: ModelOption) => {
      if (send.error !== null) send.dismissError();
      setRefusal(null);
      if (!session || !canMutate) {
        // The row that unbinds means "no per-message model" here: the message goes wherever
        // the session's own default sends it, which is what a read-only window may not change.
        setModel(option.id === PROJECT_DEFAULT_OPTION ? null : option.id);
        return;
      }
      if (option.id === PROJECT_DEFAULT_OPTION) {
        bind(session.id, { clear: true });
        return;
      }
      const runtime = parseRuntimeOptionId(option.id);
      if (runtime === null) {
        bind(session.id, { entry: option.id });
        return;
      }
      if (!disclosureRead(session.id)) {
        setPending(runtime);
        return;
      }
      bind(session.id, runtime);
    },
    [bind, canMutate, send, session, setModel],
  );

  /** The runtime's name as the scan gave it, for the disclosure's heading. */
  const pendingRuntimeName =
    (pending && models.groups.find((group) => group.id === pending.runtime)?.label) ??
    pending?.runtime ??
    '';

  /** Where the pending runtime sends, as the scan reports it; null when it said nothing. */
  const pendingDestination = pending ? (models.destinations[pending.runtime] ?? null) : null;

  /**
   * Confirming the disclosure: bound, and remembered only if it was stored.
   *
   * A refusal means nothing left the machine and nothing was bound, so there is nothing to
   * have disclosed — the next attempt asks again rather than skipping the notice on the
   * strength of an answer the daemon rejected.
   */
  const onConfirmBinding = useCallback(() => {
    if (!session || pending === null) return;
    const target = session.id;
    setPending(null);
    void sessions.configure(target, pending).then((message) => {
      // The answer belongs to the session it was asked for. A researcher who has moved on
      // is told nothing, and nothing is remembered on their behalf — the next visit to that
      // session asks again, which is the safe way for this to be wrong.
      if (openSession.current !== target) return;
      if (message === null) rememberDisclosure(target);
      setRefusal(message);
    });
  }, [pending, session, sessions]);

  /** Changing the effort level rebinds the same runtime and model with it. */
  const onPickReasoning = useCallback(
    (value: string) => {
      if (!session || runtimeBinding === null) return;
      setRefusal(null);
      bind(session.id, {
        ...runtimeBinding,
        ...(value === RUNTIME_DEFAULT_REASONING ? {} : { reasoning: value }),
      });
    },
    [bind, runtimeBinding, session],
  );

  const reasoningChoices = runtimeBinding
    ? models.reasoningChoices(runtimeBinding.runtime, runtimeBinding.model)
    : [];

  /**
   * What the trigger says when the binding names no row the picker was given.
   *
   * A scan that failed, a runtime that is gone, an entry removed from `research.yaml`: the
   * record is still bound, and "Select a model" would be a false statement about it. The
   * binding words go on the trigger — the same ones the rail shows — and no option is
   * synthesised to carry them, because an option is a claim that it can be chosen.
   */
  const bindingLabel = session ? (bindingWords(session.defaults) ?? '') : '';

  /**
   * Whether there is a destination to name at all.
   *
   * The same condition that decides whether the picker is offered: a catalogue, a scan, or
   * a binding. A project with none of the three has told this cockpit nothing about where
   * its messages would go, and inventing an answer there — "the project default", over a
   * `providers:` table that does not exist — would be the one claim the composer must never
   * make. The catalogue's own sentence already says what happened.
   *
   * And no session is the same case. With nothing open there is no message, so there is no
   * destination to state and nothing for a binding to bind — but the trigger was rendered
   * anyway, reading "Project default" over a composer that could not be typed in and a line
   * that had gone silent. A control that says a model and nothing about egress is precisely
   * the regression that removing the EXTERNAL/LOCAL tag must not cause, so the trigger and
   * the line stand or fall together.
   */
  const hasSelector =
    session !== null && (models.options.length > 0 || models.groups.length > 0 || bound !== null);

  /**
   * The standing line: where the message in the box would go if it were sent now.
   *
   * Read from the *selection* rather than from the record, because a read-only window still
   * has a per-message model and that is where its message would actually go. It changes
   * when the binding changes because everything it reads changes with it, and it is never
   * announced — the Design System renders it inside the composer's own frame as part of the
   * text box's description.
   */
  const selectedOption = useMemo(
    () =>
      groups.flatMap((group) => group.options).find((option) => option.id === selectedModel) ??
      null,
    [groups, selectedModel],
  );
  const destination =
    session === null || models.loading || !hasSelector
      ? null
      : destinationWords({
          runtime: parseRuntimeOptionId(selectedModel),
          destinations: models.destinations,
          option: selectedOption,
          binding: bindingLabel === '' ? null : bindingLabel,
        });

  /**
   * The one notice slot above the box, filled by whichever thing is loudest.
   *
   * Five strips used to stack here — the graph's, the draft's flagged references, the
   * catalogue's sentence, a refused binding and a failed send — with the design system's
   * own blocked notice inside the box under them. Six framed strips above an empty message
   * box is H8's named issue, and the at-rest one was the tallest. So: the `Composer`'s
   * `blockedReasons` notice wins, because it is the only one that has actually stopped the
   * send; then a refused binding, then a retryable send; then the catalogue's own sentence
   * about why it has nothing to offer. The graph state left the stack entirely — it is a
   * capability note, and it rides beside the destination line now.
   *
   * `ReferenceMarks` is not in the priority: it is not a notice about the composer but a
   * list of the draft's own tokens, and it appears only when the resolver objected to one.
   */
  const notice =
    blockedReasons.length > 0 ? null : refusal !== null ? (
      // A binding the daemon would not store, in its own words, where the pick was made.
      // Nothing durable changed, so the selector is still on the stored binding.
      <ErrorNotice
        kind="blocked"
        title="That model was not bound to this session"
        description={refusal}
        safety={{ draft: 'safe', note: 'Your message is exactly where you left it.' }}
        onDismiss={() => setRefusal(null)}
      />
    ) : send.error !== null && send.retryable ? (
      <ErrorNotice
        kind="retryable"
        title="The message did not get through"
        description={send.error}
        safety={{ draft: 'safe', note: 'Your message is exactly where you left it.' }}
        actions={[{ label: 'Try again', onClick: onSend, iconStart: 'refresh-cw' }]}
        onDismiss={send.dismissError}
      />
    ) : models.unavailable ? (
      <p className="rh-web-composer__note rh-text-secondary">{models.unavailable}</p>
    ) : null;

  return (
    <div className="rh-web-composer">
      {/* References and the graph (task W3). Every token in the draft is resolved against
          canonical state; the ones that did not come back clean are marked here, with the
          resolver's own sentence, before the message is sent (conversation spec §7). They
          stay sendable — nothing below removes a token or disables Send. */}
      <ReferenceMarks
        tokens={draft.value.tokens}
        flagged={draftReferences.flagged}
        onOpen={openRef}
      />
      {notice}
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
        {/* A project with no `providers:` table has an empty catalogue and may still have a
            CLI to bind to — which is the whole point of the feature — so the picker follows
            either source. A session that is already bound keeps it whatever the catalogue
            and the scan say: the trigger has the binding words to state, and the row that
            unbinds has to stay reachable. */
        ...(hasSelector
          ? {
              modelSelector: (
                <span className="rh-web-composer__model">
                  {/* Everything is a labelled group: the catalogue has a heading of its
                      own so the runtimes below it read as the alternatives they are. */}
                  <ModelSelector
                    options={[]}
                    groups={groups}
                    value={selectedModel}
                    {...(bindingLabel ? { fallbackLabel: bindingLabel } : {})}
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
                      {...(!canMutate && mutationBlockedReason
                        ? { description: mutationBlockedReason }
                        : {})}
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
        {/* Where an unpublished message goes, kept on screen long after the one-time
            disclosure was answered. Absent rather than vague when nothing is known. */
        ...(destination !== null ? { destination } : {})}
        {/* References and the graph (task W3). Completion falls back to the project
            listings when `graph.status` says the index is absent, rebuilding or
            unreadable, and this is the one place that says so — once, beside the line that
            says where the message goes (graph spec §8). An index that is absent or
            unreadable still carries the rebuild its own wording asks for; a window that may
            not write is offered `Check again` alone, because `state.rebuild` is admin and
            human-only. */
        ...(graph.degradation === null
          ? {}
          : {
              note: (
                <GraphStatusNote
                  degradation={graph.degradation}
                  answering={graph.answering}
                  onRecheck={graph.recheck}
                  rebuilding={graph.rebuilding}
                  rebuildError={graph.rebuildError}
                  {...(canMutate ? { onRebuild: graph.rebuild } : {})}
                />
              ),
            })}
        {/* What the paperclip accepts, on the paperclip. The strip that used to say it sat
            permanently inside the box; the host shows it now only while a file is over the
            composer. */
        ...(attachments.files.canAttach ? { attachHint: ATTACHMENT_HINT } : {})}
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
        answered before anything happens. The body names the destination and then gives the
        scan's own `notice` verbatim. Every fact in it is the daemon's — the runtime's name
        and its `egress_host` from `provider.cli.scan`, in the sentence
        `cli/commands/provider.py::egress_sentence` builds from the same two fields — so the
        cockpit decides nothing about egress and cannot drift from what the CLI discloses.
        The `notice` alone says only that content leaves the machine, never where to.
      */}
      <Dialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        role="alertdialog"
        size="sm"
      >
        <Dialog.Header>{`Bind this session to ${pendingRuntimeName}`}</Dialog.Header>
        <Dialog.Body>
          {pendingDestination !== null && (
            <p>
              {`This session sends research content to ${pendingDestination.egressHost} ` +
                `through ${pendingDestination.name}.`}
            </p>
          )}
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

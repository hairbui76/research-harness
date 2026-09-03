/**
 * `Save to corpus`: the one explicit step that gives a session file a corpus identity.
 *
 * Two capabilities, in this order and never merged: `attachment.resolve_identity` is a
 * read that answers "what would these bytes become", and `attachment.save_to_corpus` is
 * the mutation that acts on the researcher's confirmation. Nothing is saved without one —
 * an identity the resolver could not decide is offered as the two answers the capability
 * will accept, and neither of them is preselected (PRODUCT §13).
 *
 * `promoting → in_corpus | failed`, and the failed branch is the one that matters most: a
 * promotion that broke half-way leaves the session copy intact, previewable and sendable,
 * and `failed → promoting` is a legal transition on the daemon's own state machine, so the
 * retry is a retry rather than a re-attach (attachments design §6).
 *
 * Saving creates or links Work/Version/Artifact identity **and nothing else**. The result
 * says so in words rather than leaving it to be assumed: `evidence_created` is a field the
 * daemon sets, it is always false, and this is where a researcher reads it (§7).
 */
import { useCallback, useMemo, useState } from 'react';
import { SaveToCorpusAction, canSaveToCorpus } from '@research-harness/design';
import type {
  AttachmentModel,
  AttachmentSaveModel,
  EntityRefModel,
  IdentityChoice,
  SaveToCorpusState,
} from '@research-harness/design';
import type { HarnessClient } from '../../../api/client';
import type { AttachmentPromotionView, AttachmentView } from '../../../api/dto';
import { describePromotion, saveOptionsOf } from './mappers';
import type { SaveOption } from './mappers';

/** One attachment's place in the save flow, plus the answers it is waiting on. */
interface SaveSlice {
  state: SaveToCorpusState;
  options: SaveOption[];
  /** The identity the researcher confirmed, kept so a retry is the same save again. */
  confirmed?: IdentityChoice;
  error?: string;
  promotion?: AttachmentPromotionView;
}

export interface SaveToCorpusApi {
  /** The per-attachment slice the Design System's tray takes, keyed by `SA####`. */
  slices: Record<string, AttachmentSaveModel>;
  /** Begin identity resolution for one attachment. */
  start: (attachmentId: string) => void;
  /** Save under the identity the researcher confirmed. */
  confirm: (attachmentId: string, choice: IdentityChoice) => void;
  /** Try the same save again. The session copy was never touched. */
  retry: (attachmentId: string) => void;
  /** Step back out of the flow. Nothing was written. */
  cancel: (attachmentId: string) => void;
  /** What a finished promotion linked and created, keyed by `SA####`. */
  results: Record<string, AttachmentPromotionView>;
  /** False for a window the daemon will not let write; the action is not offered. */
  canSave: boolean;
  /** Why it is not offered, in the daemon's own sentence. */
  blockedReason: string | null;
}

export interface SaveToCorpusOptions {
  canMutate?: boolean;
  blockedReason?: string | null;
  /** Every updated attachment record the flow learns about, so one list stays true. */
  onRecord?: (record: AttachmentView) => void;
}

export function useSaveToCorpus(
  client: HarnessClient,
  sessionId: string | null,
  options: SaveToCorpusOptions = {},
): SaveToCorpusApi {
  const { canMutate = true, blockedReason = null, onRecord } = options;
  const [slices, setSlices] = useState<Record<string, SaveSlice>>({});

  const patch = useCallback((id: string, next: Partial<SaveSlice>) => {
    setSlices((previous) => ({
      ...previous,
      [id]: { state: 'idle', options: [], ...previous[id], ...next },
    }));
  }, []);

  const start = useCallback(
    (id: string) => {
      if (!sessionId || !canMutate) return;
      patch(id, { state: 'resolving', error: undefined });
      void client
        .resolveAttachmentIdentity(sessionId, id)
        .then((identity) => {
          patch(id, { state: 'choose_identity', options: saveOptionsOf(identity) });
        })
        .catch((cause: unknown) => {
          patch(id, { state: 'failed', error: messageOf(cause) });
        });
    },
    [canMutate, client, patch, sessionId],
  );

  /**
   * Save under one confirmed identity.
   *
   * The choice comes back as the object that was handed to the dialog, so the answer the
   * capability needs — `as_new`, or the Work to `attach_to` — is looked up by position in
   * the list this flow built rather than re-derived from what was rendered.
   */
  const confirm = useCallback(
    (id: string, choice: IdentityChoice) => {
      if (!sessionId || !canMutate) return;
      const slice = slices[id];
      const index = slice?.options.findIndex((option) => option.choice === choice) ?? -1;
      const answer = index >= 0 ? slice?.options[index]?.request ?? {} : {};
      patch(id, { state: 'promoting', confirmed: choice, error: undefined });
      void client
        .saveAttachmentToCorpus({ session: sessionId, attachment: id, ...answer })
        .then((promotion) => {
          patch(id, { state: 'in_corpus', promotion, error: undefined });
          onRecord?.(promotion.attachment);
        })
        .catch((cause: unknown) => {
          // The session copy is untouched by a failed promotion, and the daemon's own
          // record says so: it returns to `failed`, from which `promoting` is legal again.
          patch(id, { state: 'failed', error: messageOf(cause) });
        });
    },
    [canMutate, client, onRecord, patch, sessionId, slices],
  );

  const retry = useCallback(
    (id: string) => {
      // A save that had already been confirmed is retried as that same save, with the
      // identity the researcher chose; one that failed during resolution starts again from
      // the read, because there is nothing yet to repeat.
      const chosen = slices[id]?.confirmed;
      if (chosen) confirm(id, chosen);
      else start(id);
    },
    [confirm, slices, start],
  );

  const cancel = useCallback(
    (id: string) => {
      patch(id, { state: 'idle', error: undefined });
    },
    [patch],
  );

  /** The Design System's slice: state, the choices, and the failure text. */
  const trayModel = useMemo<Record<string, AttachmentSaveModel>>(() => {
    const model: Record<string, AttachmentSaveModel> = {};
    for (const [id, slice] of Object.entries(slices)) {
      model[id] = {
        state: slice.state,
        choices: slice.options.map((option) => option.choice),
        ...(slice.error ? { error: slice.error } : {}),
      };
    }
    return model;
  }, [slices]);

  const results = useMemo<Record<string, AttachmentPromotionView>>(() => {
    const found: Record<string, AttachmentPromotionView> = {};
    for (const [id, slice] of Object.entries(slices)) {
      if (slice.promotion) found[id] = slice.promotion;
    }
    return found;
  }, [slices]);

  return {
    slices: trayModel,
    start,
    confirm,
    retry,
    cancel,
    results,
    canSave: canMutate && sessionId !== null,
    blockedReason: canMutate ? null : blockedReason,
  };
}

/**
 * The tray's `save` map, with an `idle` slice for every file that could be saved.
 *
 * `AttachmentTray` offers the action only where it has a slice, so a file nobody has
 * touched yet needs one in order to be offerable at all. `canSaveToCorpus` is the Design
 * System's own answer to "is saving meaningful in this state", so a file that is still
 * validating, or one that already failed intake, is not offered a corpus action it could
 * not honour.
 */
export function saveSlicesFor(
  attachments: readonly AttachmentModel[],
  api: SaveToCorpusApi,
): Record<string, AttachmentSaveModel> {
  const slices: Record<string, AttachmentSaveModel> = {};
  for (const attachment of attachments) {
    if (!canSaveToCorpus(attachment.state)) continue;
    slices[attachment.id] = api.slices[attachment.id] ?? { state: 'idle' };
  }
  return slices;
}

export interface SaveToCorpusFlowProps {
  attachment: AttachmentModel;
  save: SaveToCorpusApi;
  onOpenRef?: (entity: EntityRefModel) => void;
  /** Button label; the transcript and the inspector name the file, the tray does not. */
  label?: string;
}

/**
 * The `Save to corpus` control for one attachment, mountable anywhere.
 *
 * The composer's tray composes the same action itself through `AttachmentTray`'s `save`
 * prop; this is the same flow for the three other places the design asks for it — the
 * transcript, the viewer, and the inspector — so a file can be promoted from wherever the
 * researcher happens to be looking at it (attachments design §4).
 */
export function SaveToCorpusFlow({ attachment, save, onOpenRef, label }: SaveToCorpusFlowProps) {
  const slice = save.slices[attachment.id];
  if (!save.canSave) {
    return save.blockedReason === null ? null : (
      <p className="rh-web-attachments__note rh-text-secondary">{save.blockedReason}</p>
    );
  }
  return (
    <div className="rh-web-attachments__save">
      <SaveToCorpusAction
        state={slice?.state ?? 'idle'}
        {...(slice?.choices ? { choices: slice.choices } : {})}
        {...(slice?.error ? { error: slice.error } : {})}
        name={attachment.name}
        {...(attachment.corpus ? { corpus: attachment.corpus } : {})}
        onStart={() => save.start(attachment.id)}
        onConfirm={(choice) => save.confirm(attachment.id, choice)}
        onRetry={() => save.retry(attachment.id)}
        onCancel={() => save.cancel(attachment.id)}
        {...(onOpenRef ? { onOpenRef } : {})}
        {...(label ? { label } : {})}
      />
      <SaveOutcome attachmentId={attachment.id} save={save} />
    </div>
  );
}

/**
 * What a finished save actually did — including what it deliberately did not do.
 *
 * The Design System's action shows the Work, Version and Artifact it linked. This adds the
 * sentence the evidence boundary needs: saving to the corpus creates identity, and
 * extraction from the saved artifact still goes through candidate, verification and review.
 * Saying it here is the difference between a researcher believing the file is now evidence
 * and knowing that it is not (attachments design §7, PRODUCT §42 N).
 */
export function SaveOutcome({
  attachmentId,
  save,
}: {
  attachmentId: string;
  save: SaveToCorpusApi;
}) {
  const promotion = save.results[attachmentId];
  if (!promotion) return null;
  return (
    <p className="rh-web-attachments__outcome rh-text-secondary" role="status">
      {describePromotion(promotion)}
    </p>
  );
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

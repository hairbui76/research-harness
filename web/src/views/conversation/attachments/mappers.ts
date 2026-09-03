/**
 * Attachment DTOs → Design System view models.
 *
 * One direction, and no rules — the same contract as `../mappers.ts`. Sendability,
 * omission reasons, suggested models, duplicate detection and Work/Version matching are
 * all decided by the daemon and carried through as text; nothing here re-derives them,
 * because a client that works out its own answer is a client that can disagree with the
 * receipt the researcher is reading (PRODUCT §5 P10).
 *
 * The one judgement this file makes is presentational and is stated where it is made: the
 * Design System's `IdentityChoice` has three kinds and the daemon's `IdentityChoice` has
 * five, so `existing_version` and `existing_work` both draw as "new version of an existing
 * work" — with the daemon's own resolution words underneath — and `undecided` becomes the
 * two answers the capability will actually accept.
 */
import type {
  AttachmentCorpusLinks,
  AttachmentModel,
  AttachmentSendability,
  ComposerBlockedReason,
  IdentityChoice,
} from '@research-harness/design';
import type {
  AttachmentIdentityView,
  AttachmentPromotionView,
  AttachmentSendCheck,
  AttachmentSendItem,
  AttachmentView,
  SessionAttachmentRecord,
} from '../../../api/dto';
import { entityRefFor, toAttachmentModel } from '../mappers';

/** The byte URLs one attachment can be drawn from, all of them object URLs for this tab. */
export interface AttachmentUrlSet {
  previewUrl?: string;
  thumbnailUrl?: string;
  downloadUrl?: string;
}

/**
 * A file the researcher chose that has no `SA####` yet.
 *
 * It is in the tray from the moment it is dropped, because the attachments design's
 * lifecycle starts at `selected` and an item the researcher believes they attached must
 * never be invisible while it is being copied. The `File` is kept so a failed upload is
 * retryable without re-picking it.
 */
export interface PendingAttachment {
  /** Local key. Not an `SA####`, and never sent anywhere. */
  key: string;
  file: File;
  filename: string;
  mediaType: string;
  size: number;
  state: 'selected' | 'validating' | 'failed';
  failureReason?: string;
}

/** One attachment's verdict, as the Design System states it beside the file. */
export function toSendability(item: AttachmentSendItem): AttachmentSendability {
  return {
    ok: item.ok,
    ...(item.reason ? { reason: item.reason } : {}),
    ...(item.suggested_model ? { suggestedModel: item.suggested_model } : {}),
  };
}

/** Where an attachment ended up in the corpus, once it was explicitly promoted. */
export function toCorpusLinks(record: AttachmentView): AttachmentCorpusLinks | null {
  if (!record.work || !record.version || !record.artifact) return null;
  return {
    work: entityRefFor(record.work, { authority: 'accepted' }),
    version: entityRefFor(record.version, { authority: 'accepted' }),
    artifact: entityRefFor(record.artifact, { authority: 'accepted' }),
  };
}

/**
 * One session attachment as the tray, the transcript and the viewer draw it.
 *
 * `toAttachmentModel` already turns the record into the view model and carries a stored
 * `failure_reason` into `sendability`. A live `attachment.check_send` verdict outranks
 * that: the daemon has just been asked about *this* model, so its answer replaces the
 * remembered one rather than being merged with it.
 */
export function attachmentModelOf(
  record: SessionAttachmentRecord | AttachmentView,
  options: { urls?: AttachmentUrlSet; send?: AttachmentSendItem } = {},
): AttachmentModel {
  const base = toAttachmentModel(record as SessionAttachmentRecord, options.urls ?? {});
  const corpus = toCorpusLinks(record);
  return {
    ...base,
    ...(options.send ? { sendability: toSendability(options.send) } : {}),
    ...(corpus ? { corpus } : {}),
  };
}

/** A file still being copied into the session, drawn with the same vocabulary. */
export function pendingModelOf(pending: PendingAttachment): AttachmentModel {
  return {
    id: pending.key,
    name: pending.filename,
    mediaType: pending.mediaType,
    size: pending.size,
    state: pending.state,
    ...(pending.failureReason
      ? { sendability: { ok: false, reason: pending.failureReason } }
      : {}),
  };
}

/**
 * Every reason the composer must not send, one line per blocked item.
 *
 * A blocked send shows all of them at once. Reporting the first and hiding the rest would
 * make the researcher fix an attachment, be refused again, and fix another — and the
 * design's promise is that nothing they reasonably believe will be considered is silently
 * dropped (attachments design §5).
 */
export function blockedReasonsOf(check: AttachmentSendCheck | null): ComposerBlockedReason[] {
  if (check === null || check.ok) return [];
  return check.items
    .filter((item) => !item.ok)
    .map((item) => ({
      attachmentId: item.attachment,
      reason: `${item.filename}: ${item.reason ?? 'this model cannot take this file.'}`,
      ...(item.suggested_model ? { suggestedModel: item.suggested_model } : {}),
    }));
}

/**
 * One identity the researcher can confirm, and the answer `attachment.save_to_corpus`
 * needs in order to act on it.
 */
export interface SaveOption {
  choice: IdentityChoice;
  /** Sent with the save. Empty when the resolver already decided and needs no answer. */
  request: { as_new?: boolean; attach_to?: string };
}

/**
 * The identities to offer for one attachment.
 *
 * A resolver that decided offers exactly one choice, and confirming it sends no answer at
 * all: `attachment.save_to_corpus` resolves the identity again inside the workspace lock,
 * so an answer invented here could only disagree with it. `undecided` is the one case that
 * needs the researcher, and it is offered as the two things the capability accepts —
 * attach to the Work it partially matched, or register a new one. Nothing is preselected.
 */
export function saveOptionsOf(identity: AttachmentIdentityView): SaveOption[] {
  const detail = identity.reasons.join(' ') || undefined;
  const refs = {
    ...(identity.work ? { work: entityRefFor(identity.work, { authority: 'accepted' }) } : {}),
    ...(identity.version
      ? { version: entityRefFor(identity.version, { authority: 'accepted' }) }
      : {}),
    ...(identity.artifact
      ? { artifact: entityRefFor(identity.artifact, { authority: 'accepted' }) }
      : {}),
  };
  switch (identity.choice) {
    case 'existing_artifact':
      return [
        {
          choice: {
            kind: 'existing_artifact',
            ...refs,
            label: `These exact bytes are already ${identity.artifact ?? 'in the corpus'}`,
            detail:
              detail ??
              'Saving links the session copy to the artifact that is already registered. ' +
                'Nothing is copied and no duplicate is created.',
          },
          request: {},
        },
      ];
    case 'existing_version':
    case 'existing_work':
      return [
        {
          choice: {
            kind: 'existing_work_new_version',
            ...refs,
            label:
              identity.title ??
              (identity.work ? `A new artifact under ${identity.work}` : 'An existing work'),
            detail:
              detail ??
              'The corpus already has this work. Saving registers the file under it and runs ' +
                'the normal parsing workflow.',
          },
          request: {},
        },
      ];
    case 'new_work':
      return [
        {
          choice: {
            kind: 'new_work',
            label: identity.title ?? 'Register this as a new work',
            detail:
              detail ?? 'Nothing in the corpus matches these bytes or this metadata.',
          },
          request: {},
        },
      ];
    case 'undecided':
      return [
        ...(identity.work
          ? [
              {
                choice: {
                  kind: 'existing_work_new_version' as const,
                  ...refs,
                  label: `Attach it to ${identity.work}`,
                  detail:
                    detail ??
                    'The metadata matches this work only partially, so the decision is yours.',
                },
                request: { attach_to: identity.work },
              },
            ]
          : []),
        {
          choice: {
            kind: 'new_work',
            label: 'Register it as a new work',
            detail:
              detail ??
              'The metadata matched more than one work, or matched one only partially. ' +
                'Nothing is guessed.',
          },
          request: { as_new: true },
        },
      ];
  }
}

/**
 * What a finished promotion did, in one sentence.
 *
 * `created` says whether anything was copied at all: saving the same bytes twice comes back
 * as `nothing`, linked to the artifact that already exists, which is the design's answer to
 * duplication (attachments design §6). The evidence half of the sentence is not a caveat
 * added here — `evidence_created` is a field the daemon sets, and it is always false.
 */
export function describePromotion(promotion: AttachmentPromotionView): string {
  const created =
    promotion.created === 'nothing'
      ? `These exact bytes were already in the corpus, so the existing artifact ${promotion.artifact} was linked and nothing was copied.`
      : promotion.created === 'artifact'
        ? `Registered as a new artifact ${promotion.artifact} of ${promotion.version}.`
        : promotion.created === 'version'
          ? `Registered as a new version ${promotion.version} of ${promotion.work}, artifact ${promotion.artifact}.`
          : `Registered as a new work ${promotion.work}, version ${promotion.version}, artifact ${promotion.artifact}.`;
  const parsed = promotion.parsed
    ? ' It was parsed into anchored blocks.'
    : ' It was not parsed.';
  const evidence = promotion.evidence_created
    ? ''
    : ' No evidence was created: extraction still goes through candidate, verification and review.';
  return `${created}${parsed}${evidence}`;
}

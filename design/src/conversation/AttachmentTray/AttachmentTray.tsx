import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { IconButton } from '../../primitives/IconButton';
import { SaveToCorpusAction } from '../../research/SaveToCorpusAction';
import type { EntityRefModel, IdentityChoice, SaveToCorpusState } from '../../research/models';
import { AsyncState } from '../../states/AsyncState';
import { cx } from '../../utils/cx';
import { AttachmentAuto } from '../attachmentAuto';
import { ATTACHMENT_STATE_META, canSaveToCorpus } from '../models';
import type { AttachmentModel } from '../models';

/** The Save-to-corpus slice for one attachment, as the host tracks it. */
export interface AttachmentSaveModel {
  state: SaveToCorpusState;
  choices?: readonly IdentityChoice[];
  error?: string;
}

export interface AttachmentTrayProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  attachments: readonly AttachmentModel[];
  /** Accessible name for the list. Defaults to "Attachments". */
  label?: string;
  onRemove?: (attachmentId: string) => void;
  /** Retry a failed validation or send for one item. */
  onRetry?: (attachmentId: string) => void;
  /** Page renderer for PDF previews, per attachment. */
  renderPage?: (attachmentId: string, pageIndex: number) => ReactNode;
  altFor?: (attachment: AttachmentModel) => string;
  /**
   * Per-attachment Save-to-corpus state, keyed by attachment id. Absent means the action
   * is not offered; the tray also hides it for states where saving makes no sense.
   */
  save?: Readonly<Record<string, AttachmentSaveModel>>;
  onSaveStart?: (attachmentId: string) => void;
  onSaveConfirm?: (attachmentId: string, choice: IdentityChoice) => void;
  onSaveRetry?: (attachmentId: string) => void;
  onSaveCancel?: (attachmentId: string) => void;
  onOpenRef?: (entity: EntityRefModel) => void;
  /** Shown when there are no attachments. Omit it to render nothing at all. */
  emptyMessage?: ReactNode;
}

/**
 * The files riding along with the current draft, or attached to a past turn.
 *
 * Each row shows its own lifecycle state, its own reason for being unsendable, and its own
 * `Save to corpus` action — because failure here is per item: one PDF that will not
 * validate must not take the draft, the other attachments or the researcher's message with
 * it. Attachments stay session-only until somebody explicitly promotes one.
 */
export const AttachmentTray = forwardRef<HTMLDivElement, AttachmentTrayProps>(
  function AttachmentTray(
    {
      attachments,
      label = 'Attachments',
      onRemove,
      onRetry,
      renderPage,
      altFor,
      save,
      onSaveStart,
      onSaveConfirm,
      onSaveRetry,
      onSaveCancel,
      onOpenRef,
      emptyMessage,
      className,
      ...rest
    },
    ref,
  ) {
    const images = attachments.filter((attachment) => attachment.mediaType.startsWith('image/'));

    if (attachments.length === 0) {
      if (emptyMessage === undefined) return null;
      return (
        <div ref={ref} className={cx('rh-attachment-tray', className)} {...rest}>
          <AsyncState kind="empty" title={emptyMessage} compact />
        </div>
      );
    }

    return (
      <div ref={ref} className={cx('rh-attachment-tray', className)} {...rest}>
        <ul className="rh-attachment-tray__list" aria-label={label}>
          {attachments.map((attachment) => {
            const meta = ATTACHMENT_STATE_META[attachment.state];
            const slice = save?.[attachment.id];
            const showSave =
              slice !== undefined && onSaveConfirm !== undefined && canSaveToCorpus(attachment.state);
            return (
              <li key={attachment.id} className="rh-attachment-tray__item">
                <AttachmentAuto
                  attachment={attachment}
                  gallery={images.length > 1 ? images : undefined}
                  renderPage={
                    renderPage ? (pageIndex) => renderPage(attachment.id, pageIndex) : undefined
                  }
                  alt={altFor?.(attachment)}
                  actions={
                    <>
                      {onRetry && attachment.state === 'failed' ? (
                        <IconButton
                          icon="rotate-ccw"
                          label={`Retry ${attachment.name}`}
                          size="sm"
                          onClick={() => onRetry(attachment.id)}
                        />
                      ) : null}
                      {onRemove ? (
                        <IconButton
                          icon="trash-2"
                          label={`Remove ${attachment.name}`}
                          size="sm"
                          disabled={meta.busy}
                          onClick={() => onRemove(attachment.id)}
                        />
                      ) : null}
                    </>
                  }
                >
                  {showSave ? (
                    <SaveToCorpusAction
                      state={slice.state}
                      choices={slice.choices}
                      error={slice.error}
                      name={attachment.name}
                      corpus={attachment.corpus}
                      onStart={onSaveStart ? () => onSaveStart(attachment.id) : undefined}
                      onConfirm={(choice) => onSaveConfirm(attachment.id, choice)}
                      onRetry={onSaveRetry ? () => onSaveRetry(attachment.id) : undefined}
                      onCancel={onSaveCancel ? () => onSaveCancel(attachment.id) : undefined}
                      onOpenRef={onOpenRef}
                    />
                  ) : null}
                </AttachmentAuto>
              </li>
            );
          })}
        </ul>
      </div>
    );
  },
);

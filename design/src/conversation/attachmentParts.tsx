import type { ReactElement, ReactNode } from 'react';
import { Badge } from '../primitives/Badge';
import { Icon } from '../primitives/Icon';
import type { IconName } from '../primitives/Icon';
import { cx } from '../utils/cx';
import { ATTACHMENT_STATE_META, formatFileSize } from './models';
import type { AttachmentModel } from './models';

/**
 * The pieces every attachment presentation shares.
 *
 * Internal to the package, like `primitives/field.tsx`: `ImageAttachment`, `PdfAttachment`
 * and the generic file card are three views of one lifecycle, and the state label, the
 * blocked-send reason and the file facts have to read identically in all three.
 */

/** The lifecycle state, as a glyph and a word. Never colour alone. */
export function AttachmentStateBadge({
  attachment,
}: {
  attachment: AttachmentModel;
}): ReactElement {
  const meta = ATTACHMENT_STATE_META[attachment.state];
  const tone =
    attachment.state === 'failed'
      ? 'error'
      : attachment.state === 'in_corpus'
        ? 'success'
        : meta.busy
          ? 'accent'
          : 'neutral';
  return (
    <Badge
      className="rh-attachment__state"
      tone={tone}
      icon={meta.icon}
      size="sm"
      data-state={attachment.state}
      title={meta.description}
    >
      {meta.label}
    </Badge>
  );
}

/** Media type, size and page count — the facts a researcher checks before sending. */
export function AttachmentFacts({ attachment }: { attachment: AttachmentModel }): ReactElement {
  return (
    <span className="rh-attachment__facts">
      <span className="rh-attachment__type">{attachment.mediaType}</span>
      <span className="rh-attachment__size">{formatFileSize(attachment.size)}</span>
      {attachment.pageCount !== undefined ? (
        <span className="rh-attachment__pages">
          {attachment.pageCount} {attachment.pageCount === 1 ? 'page' : 'pages'}
        </span>
      ) : null}
    </span>
  );
}

/**
 * Why this file cannot be sent to the selected model, in the host's words, with the model
 * it suggests instead. Rendered wherever the attachment is, so the researcher never has to
 * find the composer's notice to learn which file is the problem.
 */
export function AttachmentBlockedReason({
  attachment,
}: {
  attachment: AttachmentModel;
}): ReactElement | null {
  const sendability = attachment.sendability;
  if (sendability === undefined || sendability.ok) return null;
  return (
    <p className="rh-attachment__blocked">
      <Icon name="shield-off" size={14} />
      <span>
        {sendability.reason ?? 'The selected model cannot accept this file.'}
        {sendability.suggestedModel !== undefined ? (
          <> Try {sendability.suggestedModel}.</>
        ) : null}
      </span>
    </p>
  );
}

export interface AttachmentFileCardProps {
  attachment: AttachmentModel;
  /** Leading glyph. Defaults to a generic file. */
  icon?: IconName;
  /** Opens the preview, when this kind of file has one. */
  onOpen?: () => void;
  openLabel?: string;
  /** Buttons at the end of the row: remove, retry, download. */
  actions?: ReactNode;
  /** Extra content under the facts, e.g. a `SaveToCorpusAction`. */
  children?: ReactNode;
  className?: string;
}

/**
 * The card shape shared by PDFs and by any other file the product has no richer view for.
 * A file the workspace cannot preview is still shown, still named, and still explains what
 * would be needed to read it — it is never silently dropped.
 */
export function AttachmentFileCard({
  attachment,
  icon = 'file',
  onOpen,
  openLabel,
  actions,
  children,
  className,
}: AttachmentFileCardProps): ReactElement {
  const name = (
    <span className="rh-attachment-card__name" title={attachment.name}>
      {attachment.name}
    </span>
  );
  return (
    <div
      className={cx('rh-attachment-card', className)}
      data-state={attachment.state}
      data-sendable={attachment.sendability?.ok === false ? 'no' : undefined}
    >
      <span className="rh-attachment-card__icon">
        <Icon name={icon} size={20} />
      </span>
      <div className="rh-attachment-card__body">
        {onOpen ? (
          <button
            type="button"
            className="rh-attachment-card__open"
            aria-label={openLabel ?? `Preview ${attachment.name}`}
            onClick={onOpen}
          >
            {name}
          </button>
        ) : (
          name
        )}
        <span className="rh-attachment-card__meta">
          <AttachmentStateBadge attachment={attachment} />
          <AttachmentFacts attachment={attachment} />
        </span>
        <AttachmentBlockedReason attachment={attachment} />
        {children}
      </div>
      {actions !== undefined ? (
        <div className="rh-attachment-card__actions">{actions}</div>
      ) : null}
    </div>
  );
}

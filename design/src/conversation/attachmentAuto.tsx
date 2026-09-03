import type { ReactElement, ReactNode } from 'react';
import { AttachmentFileCard } from './attachmentParts';
import { ImageAttachment } from './ImageAttachment';
import { PdfAttachment } from './PdfAttachment';
import type { AttachmentModel } from './models';

export interface AttachmentAutoProps {
  attachment: AttachmentModel;
  /** Images this one belongs to, for the viewer's arrow keys. */
  gallery?: readonly AttachmentModel[];
  /** Page renderer handed to `PdfAttachment`. */
  renderPage?: (pageIndex: number) => ReactNode;
  /** Alt text for an image attachment. */
  alt?: string;
  /** Controls at the end of the row. */
  actions?: ReactNode;
  /** Extra content under the facts, e.g. a `SaveToCorpusAction`. */
  children?: ReactNode;
  size?: 'sm' | 'md';
}

/**
 * Picks the right presentation for one attachment.
 *
 * Internal: `AttachmentTray` and `MessageContent` both have to render a mixed list of
 * files, and they must agree on what an unrecognised type looks like. An unsupported file
 * is never dropped — it falls through to the generic card, which still names it, still
 * shows its state and still explains why it cannot be sent.
 */
export function AttachmentAuto({
  attachment,
  gallery,
  renderPage,
  alt,
  actions,
  children,
  size = 'md',
}: AttachmentAutoProps): ReactElement {
  if (attachment.mediaType.startsWith('image/')) {
    return (
      <ImageAttachment
        attachment={attachment}
        gallery={gallery}
        alt={alt}
        actions={actions}
        size={size}
      >
        {children}
      </ImageAttachment>
    );
  }
  if (attachment.mediaType === 'application/pdf') {
    return (
      <PdfAttachment attachment={attachment} renderPage={renderPage} actions={actions}>
        {children}
      </PdfAttachment>
    );
  }
  return (
    <AttachmentFileCard attachment={attachment} actions={actions}>
      {children}
    </AttachmentFileCard>
  );
}

/**
 * Getting files into the session: the drop target, and what the intake will not do.
 *
 * Two ways in, one handler. The Design System's `Composer` already drops onto its whole
 * box and already owns the paperclip that opens the file picker, so both call the same
 * `attach`; this component is the visible target inside it — the place a researcher aims
 * at, and the place the intake explains itself when it is closed.
 *
 * The drop is handled here and stops propagating so the composer's own handler does not
 * attach the same files a second time. Every path accepts several files at once, and every
 * path treats them one by one: a batch where one file is refused still leaves the others
 * attached, and neither the draft nor the ready attachments are touched by the refusal
 * (attachments design §2).
 *
 * A window the daemon resolved as an agent host may not write, so the intake is closed and
 * says why in the daemon's own sentence rather than quietly ignoring a drop (PRODUCT §29).
 */
import { useCallback, useState } from 'react';
import type { DragEvent, ReactNode } from 'react';
import { Icon } from '@research-harness/design';
import type { AttachmentsApi } from './useAttachments';

export interface AttachmentIntakeProps {
  files: AttachmentsApi;
  /** The tray, drawn inside the target so the files land where they are listed. */
  children?: ReactNode;
}

export function AttachmentIntake({ files, children }: AttachmentIntakeProps) {
  const [over, setOver] = useState(false);

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      setOver(false);
      if (!files.canAttach) return;
      event.preventDefault();
      // The composer is also a drop target; without this the same files arrive twice.
      event.stopPropagation();
      const dropped = Array.from(event.dataTransfer?.files ?? []);
      if (dropped.length > 0) void files.attach(dropped);
    },
    [files],
  );

  return (
    <div
      className="rh-web-attachments"
      data-dragging={over || undefined}
      onDragOver={(event) => {
        if (!files.canAttach) return;
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      {files.blockedReason !== null ? (
        <p className="rh-web-attachments__note rh-text-secondary">
          <Icon name="lock" size={14} />{' '}
          {`Files cannot be attached from this window. ${files.blockedReason}`}
        </p>
      ) : files.canAttach && files.models.length === 0 ? (
        <p className="rh-web-attachments__hint rh-text-secondary">
          <Icon name="paperclip" size={14} /> Drop images, PDFs and other files here, or use
          Attach files. They stay in this session until you save one to the corpus.
        </p>
      ) : null}
      {children}
    </div>
  );
}

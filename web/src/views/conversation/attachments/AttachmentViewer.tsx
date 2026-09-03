/**
 * Previewing an attachment — and the sentence that says a preview is not ingestion.
 *
 * Images get a thumbnail, a gallery with arrow keys, zoom and the original bytes to
 * download; PDFs get a file card, a page viewer and page navigation. Both come from the
 * Design System (`ImageAttachment`, `PdfAttachment`), and both draw from object URLs made
 * out of the daemon's own responses — the byte routes carry the token in a header, so
 * nothing here is a `src` the browser fetches on its own, and no attachment is ever loaded
 * from the network.
 *
 * The PDF pages are rendered by pdf.js through W0's `usePdfDocument` and `PdfPage`, over
 * the *original bytes* rather than the daemon's PNG previews: the page viewer is for
 * reading, so it should paginate and zoom like a document and not like a slideshow of
 * server-rendered images. The thumbnail on the card is still the daemon's PNG, which is
 * what makes a tray of ten PDFs cheap.
 *
 * The one thing this file insists on saying: **previewing a file, and sending it to a
 * model, adds nothing to the corpus.** The Design System's PDF dialog carries that
 * sentence itself; images get it here, because "I can see it in the app" is exactly the
 * assumption that would otherwise turn a session file into corpus state (attachments
 * design §4, §7).
 */
import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { AttachmentTray, ImageAttachment, PdfAttachment } from '@research-harness/design';
import type { AttachmentModel, EntityRefModel } from '@research-harness/design';
import { PdfPage, usePdfDocument } from '../../../pdf';
import type { HarnessClient } from '../../../api/client';
import { SaveToCorpusFlow, saveSlicesFor } from './SaveToCorpusFlow';
import type { SaveToCorpusApi } from './SaveToCorpusFlow';

/** The boundary sentence, in one place so every surface says the same thing. */
export const PREVIEW_IS_NOT_INGESTION =
  'This is a preview of the session copy. Previewing a file — or sending it to a model — ' +
  'does not add it to the corpus and does not create evidence.';

export interface AttachmentPdfPageProps {
  client: HarnessClient;
  sessionId: string;
  attachmentId: string;
  /** 0-based, as the Design System's pager counts. */
  pageIndex: number;
}

/**
 * One page of a session PDF, rendered from the attachment's original bytes.
 *
 * The bytes are read once per attachment and held for as long as this component is
 * mounted; `usePdfDocument` compares its source by identity, so the buffer is kept in state
 * rather than rebuilt on each render. A browser with no PDF engine, or a file pdf.js
 * cannot open, degrades to the words `PdfPage` prints — never to an empty frame.
 */
export function AttachmentPdfPage({
  client,
  sessionId,
  attachmentId,
  pageIndex,
}: AttachmentPdfPageProps) {
  const [bytes, setBytes] = useState<ArrayBuffer | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setBytes(null);
    setError(null);
    client
      .sessionAttachmentBytes(sessionId, attachmentId)
      .then((data) => live && setBytes(data))
      .catch((cause: unknown) => {
        if (live) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      live = false;
    };
  }, [attachmentId, client, sessionId]);

  const document = usePdfDocument(bytes);

  if (error !== null) {
    return (
      <p className="rh-web-attachments__unavailable" role="status">
        {`The daemon did not hand over ${attachmentId} (${error}). The file is unchanged in the session.`}
      </p>
    );
  }
  if (bytes === null) {
    return (
      <p className="rh-web-attachments__unavailable" role="status">
        Reading the file from this workstation…
      </p>
    );
  }
  return <PdfPage document={document} index={pageIndex + 1} label={`page ${pageIndex + 1}`} />;
}

/**
 * A page renderer for every PDF in this session, stable across renders.
 *
 * `AttachmentTray` and `MessageContent` both take a `renderPage` and both re-render often,
 * so the callback must not change identity for a reason that has nothing to do with the
 * document — the Design System hands it straight to a dialog that would otherwise remount.
 */
export function usePdfPageRenderer(
  client: HarnessClient,
  sessionId: string | null,
): (attachmentId: string, pageIndex: number) => ReactNode {
  return useMemo(
    () =>
      (attachmentId: string, pageIndex: number): ReactNode =>
        sessionId === null ? null : (
          <AttachmentPdfPage
            client={client}
            sessionId={sessionId}
            attachmentId={attachmentId}
            pageIndex={pageIndex}
          />
        ),
    [client, sessionId],
  );
}

export interface AttachmentViewerProps {
  attachment: AttachmentModel;
  /** The images this one belongs to, so the gallery's arrow keys have somewhere to go. */
  gallery?: readonly AttachmentModel[];
  renderPage?: (attachmentId: string, pageIndex: number) => ReactNode;
  /** When given, the viewer offers `Save to corpus` beside the file. */
  save?: SaveToCorpusApi;
  onOpenRef?: (entity: EntityRefModel) => void;
  size?: 'sm' | 'md';
}

/**
 * One attachment, drawn as whatever it is, with the corpus action beside it.
 *
 * An unsupported type is never dropped and never given a preview it cannot honour: it goes
 * to the Design System's own fallback through a one-item `AttachmentTray`, which names the
 * file, shows its state, and carries the daemon's reason for why it cannot be sent —
 * "which model or conversion path is required" is the daemon's sentence, printed as it came.
 */
export function AttachmentViewer({
  attachment,
  gallery,
  renderPage,
  save,
  onOpenRef,
  size = 'md',
}: AttachmentViewerProps) {
  const action = save ? (
    <SaveToCorpusFlow attachment={attachment} save={save} {...(onOpenRef ? { onOpenRef } : {})} />
  ) : null;

  if (attachment.mediaType.startsWith('image/')) {
    return (
      <ImageAttachment attachment={attachment} {...(gallery ? { gallery } : {})} size={size}>
        <p className="rh-web-attachments__boundary rh-text-secondary">
          {PREVIEW_IS_NOT_INGESTION}
        </p>
        {action}
      </ImageAttachment>
    );
  }
  if (attachment.mediaType === 'application/pdf') {
    return (
      <PdfAttachment
        attachment={attachment}
        {...(renderPage
          ? { renderPage: (pageIndex: number) => renderPage(attachment.id, pageIndex) }
          : {})}
      >
        {action}
      </PdfAttachment>
    );
  }
  return (
    <AttachmentTray
      attachments={[attachment]}
      label={attachment.name}
      {...(save
        ? {
            save: saveSlicesFor([attachment], save),
            onSaveStart: save.start,
            onSaveConfirm: save.confirm,
            onSaveRetry: save.retry,
            onSaveCancel: save.cancel,
          }
        : {})}
      {...(onOpenRef ? { onOpenRef } : {})}
    />
  );
}

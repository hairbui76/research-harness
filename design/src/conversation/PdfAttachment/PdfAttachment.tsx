import { forwardRef } from 'react';
import type { ReactNode } from 'react';
import { useControllableState } from '../../hooks/useControllableState';
import { Dialog } from '../../primitives/Dialog';
import { Icon } from '../../primitives/Icon';
import { IconButton } from '../../primitives/IconButton';
import { cx } from '../../utils/cx';
import { AttachmentFileCard } from '../attachmentParts';
import type { AttachmentModel } from '../models';

export interface PdfAttachmentProps {
  attachment: AttachmentModel;
  /**
   * Renders one page. The application supplies the renderer (pdf.js in the Web client);
   * this package never depends on a PDF engine. Without it the card still works and the
   * preview says so.
   */
  renderPage?: (pageIndex: number) => ReactNode;
  /** Controlled page, 0-based. */
  page?: number;
  defaultPage?: number;
  onPageChange?: (pageIndex: number) => void;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Controls at the end of the card row: remove, retry. */
  actions?: ReactNode;
  /** Extra content under the facts, e.g. a `SaveToCorpusAction`. */
  children?: ReactNode;
  className?: string;
}

/**
 * A PDF attachment: the file card, and a page-by-page preview.
 *
 * The preview exists so a researcher can check they attached the right paper. It is not
 * ingestion: the viewer says so in words, because "I can see it in the app" is exactly the
 * assumption that would otherwise turn a session file into corpus state. Adding it to the
 * corpus is the separate, explicit `Save to corpus` action.
 */
export const PdfAttachment = forwardRef<HTMLDivElement, PdfAttachmentProps>(function PdfAttachment(
  {
    attachment,
    renderPage,
    page,
    defaultPage = 0,
    onPageChange,
    open,
    defaultOpen = false,
    onOpenChange,
    actions,
    children,
    className,
  },
  ref,
) {
  const [isOpen, setOpen] = useControllableState<boolean>({
    value: open,
    defaultValue: defaultOpen,
    onChange: onOpenChange,
  });
  const [pageIndex, setPageIndex] = useControllableState<number>({
    value: page,
    defaultValue: defaultPage,
    onChange: onPageChange,
  });

  const pageCount = attachment.pageCount ?? 1;
  const clamp = (next: number): number => Math.min(Math.max(next, 0), Math.max(0, pageCount - 1));

  return (
    <div ref={ref} className={cx('rh-pdf-attachment', className)}>
      <AttachmentFileCard
        attachment={attachment}
        icon="file-text"
        onOpen={() => setOpen(true)}
        openLabel={`Preview ${attachment.name}`}
        actions={actions}
      >
        {children}
      </AttachmentFileCard>

      <Dialog open={isOpen} onOpenChange={setOpen} size="lg" className="rh-pdf-preview">
        <Dialog.Header>{attachment.name}</Dialog.Header>
        <Dialog.Body>
          <p className="rh-pdf-preview__boundary">
            <Icon name="info" size={14} />
            <span>
              This is a preview of the session copy. Previewing a PDF — or sending it to a
              model — does not add it to the corpus and does not create evidence.
            </span>
          </p>
          <div className="rh-pdf-preview__stage">
            {renderPage ? (
              renderPage(pageIndex)
            ) : (
              <p className="rh-pdf-preview__unavailable">
                No page renderer is available here. The file is unchanged in the session and can
                still be downloaded.
              </p>
            )}
          </div>
        </Dialog.Body>
        <Dialog.Footer>
          <div className="rh-pdf-preview__pager">
            <IconButton
              icon="chevron-left"
              label="Previous page"
              disabled={pageIndex <= 0}
              onClick={() => setPageIndex(clamp(pageIndex - 1))}
            />
            <span className="rh-pdf-preview__page" role="status">
              Page {pageIndex + 1} of {pageCount}
            </span>
            <IconButton
              icon="chevron-right"
              label="Next page"
              disabled={pageIndex >= pageCount - 1}
              onClick={() => setPageIndex(clamp(pageIndex + 1))}
            />
          </div>
          {attachment.downloadUrl !== undefined ? (
            <a
              className="rh-pdf-preview__download"
              href={attachment.downloadUrl}
              download={attachment.name}
            >
              <Icon name="download" size={16} />
              <span>Download original</span>
            </a>
          ) : null}
        </Dialog.Footer>
      </Dialog>
    </div>
  );
});

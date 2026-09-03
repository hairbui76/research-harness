import type { ReactNode } from 'react';
import { SaveToCorpusAction } from '../../research/SaveToCorpusAction';
import { SAMPLE_IDENTITY_CHOICES } from '../../research/samples';
import { SAMPLE_FAILED_ATTACHMENT, SAMPLE_PDF } from '../samples';
import { PdfAttachment } from './PdfAttachment';

export const title = 'PdfAttachment';

/** The Web client renders pages with pdf.js; the gallery draws a placeholder page. */
const renderPage = (pageIndex: number): ReactNode => (
  <div
    style={{
      inlineSize: 320,
      blockSize: 420,
      display: 'grid',
      placeItems: 'center',
      border: '1px solid currentColor',
    }}
  >
    Page {pageIndex + 1}
  </div>
);

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'File card',
    render: () => <PdfAttachment attachment={SAMPLE_PDF} renderPage={renderPage} />,
  },
  {
    name: 'Preview open — and clearly not corpus ingestion',
    render: () => <PdfAttachment attachment={SAMPLE_PDF} renderPage={renderPage} defaultOpen />,
  },
  {
    name: 'With Save to corpus',
    render: () => (
      <PdfAttachment attachment={SAMPLE_PDF} renderPage={renderPage}>
        <SaveToCorpusAction
          state="idle"
          name={SAMPLE_PDF.name}
          choices={SAMPLE_IDENTITY_CHOICES}
          onStart={() => undefined}
          onConfirm={() => undefined}
        />
      </PdfAttachment>
    ),
  },
  {
    name: 'Failed, still visible',
    render: () => <PdfAttachment attachment={SAMPLE_FAILED_ATTACHMENT} />,
  },
];

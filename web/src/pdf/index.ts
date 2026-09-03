/**
 * The pdf.js adapter: a document hook, a page component, and one place where the worker
 * is configured. Everything a caller passes or receives in PDF coordinates is in PDF user
 * space, so a SyncTeX answer needs no conversion on the way in or out.
 */
export { PdfPage } from './PdfPage';
export type { PdfHighlight, PdfPageProps, PdfRect } from './PdfPage';
export { usePdfDocument } from './usePdfDocument';
export type { PdfDocumentState, PdfSource, PdfStatus } from './usePdfDocument';
export { loadPdfjs, resetPdfjs } from './worker';
export type { Pdfjs } from './worker';

/**
 * Loading pdf.js, once, with its worker pointed at a file inside the bundle.
 *
 * Two rules live here. pdf.js is *lazy*, so a researcher who never opens a PDF never pays
 * for a PDF engine (the review screen has done this since v0.4). And the worker is
 * *local*: `new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url)` is a specifier
 * Vite resolves at build time and emits into `dist/assets`, which is what keeps the no-CDN
 * rule (plan §0.6) true at runtime rather than only in the source.
 *
 * `components/SourcePane.tsx` does the same wiring inline; the migration task points it
 * here so the worker is configured in exactly one place.
 */
import type * as PdfjsLib from 'pdfjs-dist';

export type Pdfjs = typeof PdfjsLib;

let loading: Promise<Pdfjs> | null = null;

/** The pdf.js module, with `GlobalWorkerOptions.workerSrc` already set. */
export function loadPdfjs(): Promise<Pdfjs> {
  if (!loading) {
    loading = import('pdfjs-dist')
      .then((pdfjs) => {
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          'pdfjs-dist/build/pdf.worker.min.mjs',
          import.meta.url,
        ).toString();
        return pdfjs;
      })
      .catch((cause: unknown) => {
        // One failed load must not poison every later attempt: a retry may well work.
        loading = null;
        throw cause;
      });
  }
  return loading;
}

/** Forget the cached module. Tests use it; nothing in the app should need it. */
export function resetPdfjs(): void {
  loading = null;
}

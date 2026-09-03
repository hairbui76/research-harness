/**
 * One PDF document, loaded lazily, for as long as a component wants it.
 *
 * The manuscript workspace (LaTeX spec §3) and the review screen both need the same three
 * things: a document that loads without blocking the rest of the cockpit, pages on demand,
 * and an honest state when there is no PDF to show — a build that has not run yet, a
 * compiler that failed, an engine this browser could not start. `status` carries that, and
 * `error` carries the reason as text, because the pane must degrade to words rather than
 * to an empty frame (LaTeX spec §9).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist';
import { loadPdfjs } from './worker';

/** A URL the daemon serves, or the bytes themselves when the caller already read them. */
export type PdfSource = string | ArrayBuffer | Uint8Array;

export type PdfStatus = 'idle' | 'loading' | 'ready' | 'unavailable';

export interface PdfDocumentState {
  /** `idle` with no source, `unavailable` when the document or the engine failed. */
  status: PdfStatus;
  /** 0 until the document is `ready`. */
  numPages: number;
  /** One page, numbered from 1 as PDF pages and SyncTeX both are. */
  getPage: (page: number) => Promise<PDFPageProxy>;
  /** Why there is no document, in the words the failure came with. */
  error: string | null;
  /** Load again after a failure — a daemon that has just started, a token that arrived. */
  reload: () => void;
}

/**
 * Load `source` and keep it until the source changes or the component unmounts.
 *
 * The bytes are copied before they are handed to pdf.js, which transfers (and so detaches)
 * the buffer it is given; without the copy a caller could not render the same
 * `ArrayBuffer` twice, and `reload()` would fail on the second attempt.
 *
 * `source` is compared by identity, so hold it steady: a URL string built inside the
 * render, or a fresh `ArrayBuffer` each time, reloads the document on every render.
 */
export function usePdfDocument(source: PdfSource | null | undefined): PdfDocumentState {
  const [state, setState] = useState<{ status: PdfStatus; numPages: number; error: string | null }>(
    { status: source ? 'loading' : 'idle', numPages: 0, error: null },
  );
  const [attempt, setAttempt] = useState(0);

  // The document currently being loaded, and the pages already asked for. Both live in
  // refs so that `getPage` keeps one identity for the life of the hook: a component that
  // renders a page must not re-run its effect every time the status changes.
  const documentRef = useRef<Promise<PDFDocumentProxy> | null>(null);
  const pagesRef = useRef(new Map<number, Promise<PDFPageProxy>>());

  useEffect(() => {
    pagesRef.current = new Map();
    if (!source) {
      documentRef.current = null;
      setState({ status: 'idle', numPages: 0, error: null });
      return;
    }

    let live = true;
    setState({ status: 'loading', numPages: 0, error: null });

    const task = loadPdfjs().then((pdfjs) =>
      pdfjs.getDocument({
        ...(typeof source === 'string' ? { url: source } : { data: copyOf(source) }),
        // Untrusted bytes: a PDF from a corpus is someone else's file (Product 4).
        isEvalSupported: false,
      }),
    );

    documentRef.current = task.then((loading) => loading.promise);

    documentRef.current
      .then((document) => {
        if (!live) return;
        setState({ status: 'ready', numPages: document.numPages, error: null });
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setState({ status: 'unavailable', numPages: 0, error: messageOf(cause) });
      });

    return () => {
      live = false;
      pagesRef.current = new Map();
      // Tear the load down whether or not it finished: an aborted load leaves a worker
      // and a fetch behind otherwise.
      void task.then((loading) => loading.destroy()).catch(() => undefined);
      documentRef.current = null;
    };
  }, [source, attempt]);

  const getPage = useCallback(async (page: number): Promise<PDFPageProxy> => {
    const pending = documentRef.current;
    if (!pending) throw new Error('no PDF document is loaded');
    const cached = pagesRef.current.get(page);
    if (cached) return cached;
    const request = pending.then((document) => {
      if (page < 1 || page > document.numPages) {
        throw new Error(`page ${page} is outside this document (1–${document.numPages})`);
      }
      return document.getPage(page);
    });
    pagesRef.current.set(page, request);
    request.catch(() => pagesRef.current.delete(page));
    return request;
  }, []);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);

  return { status: state.status, numPages: state.numPages, error: state.error, getPage, reload };
}

/** pdf.js detaches the buffer it is handed, so it is never handed the caller's own. */
function copyOf(source: ArrayBuffer | Uint8Array): Uint8Array {
  return source instanceof Uint8Array ? source.slice() : new Uint8Array(source.slice(0));
}

function messageOf(cause: unknown): string {
  if (cause instanceof Error) return cause.message;
  return String(cause);
}

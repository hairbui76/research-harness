/**
 * Source ⇄ PDF navigation, or the honest reason there is none.
 *
 * LaTeX spec §6: when the mapping exists the cursor jumps to the PDF and a click in the PDF
 * jumps back; when it does not, compilation and preview still work and the interface *says*
 * bidirectional navigation is unavailable rather than guessing. So both directions are
 * refused here unless `manuscript.build` reported `synctex_available`, and the reason it
 * gave is carried through untouched.
 *
 * Coordinates stay in the space the daemon speaks — PDF points from the page's top left.
 * The flip into pdf.js's user space happens in the preview, which is where the page's real
 * height is known.
 */
import { useCallback, useEffect, useState } from 'react';
import type { HarnessClient } from '../../api/client';
import type { PdfLocation, SourceLocation } from '../../api/dto';

export interface SynctexState {
  available: boolean;
  /** Why not, in the daemon's words. Undefined when navigation is available. */
  reason: string | undefined;
  /** The last forward lookup's rectangles, in PDF points from the page's top left. */
  locations: PdfLocation[];
  /** The page those rectangles are on, for the preview to turn to. */
  page: number | null;
  busy: boolean;
  /** A lookup that returned nothing, said plainly. Not an error state. */
  note: string | null;
  error: string | null;
  forward: (file: string, line: number) => Promise<void>;
  /** `x` and `y` are PDF points from the page's top left. */
  inverse: (page: number, x: number, y: number) => Promise<SourceLocation | null>;
  clear: () => void;
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export function useSynctex(
  client: HarnessClient,
  options: { buildId: string | null; available: boolean; reason: string | undefined },
): SynctexState {
  const { buildId, available, reason } = options;
  const [locations, setLocations] = useState<PdfLocation[]>([]);
  const [page, setPage] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const clear = useCallback(() => {
    setLocations([]);
    setPage(null);
    setNote(null);
    setError(null);
  }, []);

  // A new build is a new map. A rectangle from the previous one would point at a place in
  // a PDF that no longer exists, which is exactly the guess §6 forbids.
  useEffect(() => {
    clear();
  }, [buildId, clear]);

  const forward = useCallback(
    async (file: string, line: number): Promise<void> => {
      if (!available) return;
      setBusy(true);
      setError(null);
      setNote(null);
      try {
        const view = await client.manuscriptSynctexForward(file, line, buildId);
        if (!view.available) {
          setLocations([]);
          setPage(null);
          setNote(view.detail ?? 'This build has no SyncTeX map.');
          return;
        }
        setLocations(view.pdf_locations);
        setPage(view.pdf_locations[0]?.page ?? null);
        if (view.pdf_locations.length === 0) {
          setNote(`The map records no PDF box for ${file}:${line}.`);
        }
      } catch (cause) {
        setError(messageOf(cause));
      } finally {
        setBusy(false);
      }
    },
    [available, buildId, client],
  );

  const inverse = useCallback(
    async (pdfPage: number, x: number, y: number): Promise<SourceLocation | null> => {
      if (!available) return null;
      setBusy(true);
      setError(null);
      setNote(null);
      try {
        const view = await client.manuscriptSynctexInverse(pdfPage, x, y, buildId);
        if (!view.available) {
          setNote(view.detail ?? 'This build has no SyncTeX map.');
          return null;
        }
        const source = view.source_location ?? null;
        if (source === null) setNote(`Nothing on page ${pdfPage} maps back to a source line.`);
        return source;
      } catch (cause) {
        setError(messageOf(cause));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [available, buildId, client],
  );

  return {
    available,
    reason: available ? undefined : reason,
    locations,
    page,
    busy,
    note,
    error,
    forward,
    inverse,
    clear,
  };
}

/**
 * One build: what the compiler said, what the audit says, and the PDF to show.
 *
 * `manuscript.build` is a *read*, so this hook can answer for an agent host and for a
 * workspace with no LaTeX engine installed at all — which is how the workspace learns that
 * the toolchain is missing and shows the setup guidance without starting a compile it knows
 * would be refused (LaTeX spec §9). `manuscript.compile` is the mutation, and it answers
 * with the same `BuildView`, so a successful compile needs no second read.
 *
 * The PDF is fetched as bytes rather than pointed at with a `<embed src>`: the byte route
 * needs the bearer token, and `usePdfDocument` compares its source by identity, so the
 * buffer is held steady by `useAsync` exactly as the review screen holds an artifact's.
 *
 * The build id the bytes come from is always concrete, never the `latest`/`last-good`
 * alias, so that a new last-good build refetches instead of quietly serving the old one.
 */
import { useCallback, useMemo, useState } from 'react';
import type { HarnessClient } from '../../api/client';
import type { BuildView } from '../../api/dto';
import { useAsync } from '../../app/useAsync';

export interface BuildState {
  /** The latest build the daemon reported, or null before the first read finished. */
  view: BuildView | null;
  loading: boolean;
  error: string | null;
  /** Re-read the build and its audit; used after a save, which can move findings. */
  refresh: () => void;
  compiling: boolean;
  compileError: string | null;
  compile: () => Promise<void>;
  /** The bytes of the PDF a reader should be looking at, or null when there is none. */
  pdfBytes: ArrayBuffer | null;
  pdfError: string | null;
  pdfLoading: boolean;
  /** The build whose PDF is on screen — this build's, or the last one that compiled. */
  pdfBuildId: string | null;
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

/**
 * Which build's PDF a reader should be looking at.
 *
 * This build's when it produced one; otherwise the last one that did, which is what stays
 * on screen under the stale banner while the diagnostics describe the source as it is now.
 */
export function pdfBuildIdOf(view: BuildView | null): string | null {
  if (!view) return null;
  if (view.pdf && view.build_id) return view.build_id;
  return view.last_good?.build_id ?? null;
}

export function useBuild(client: HarnessClient): BuildState {
  const [tick, setTick] = useState(0);
  const [compiled, setCompiled] = useState<BuildView | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [compileError, setCompileError] = useState<string | null>(null);

  const read = useAsync(() => client.manuscriptBuild(), [client, tick]);
  // The compile's own answer wins until the next read replaces it: both are the same
  // `BuildView`, and re-reading after compiling would only ask the audit to run twice.
  const view = compiled ?? read.data;

  const refresh = useCallback(() => {
    setCompiled(null);
    setTick((value) => value + 1);
  }, []);

  const compile = useCallback(async (): Promise<void> => {
    setCompiling(true);
    setCompileError(null);
    try {
      setCompiled(await client.manuscriptCompile());
    } catch (cause) {
      setCompileError(messageOf(cause));
    } finally {
      setCompiling(false);
    }
  }, [client]);

  const pdfBuildId = useMemo(() => pdfBuildIdOf(view), [view]);
  const pdf = useAsync(
    async () => (pdfBuildId === null ? null : client.manuscriptBuildPdf(pdfBuildId)),
    [client, pdfBuildId],
  );

  return {
    view,
    loading: read.loading && compiled === null,
    error: read.error,
    refresh,
    compiling,
    compileError,
    compile,
    pdfBytes: pdf.data,
    pdfError: pdfBuildId === null ? null : pdf.error,
    pdfLoading: pdfBuildId !== null && pdf.loading,
    pdfBuildId,
  };
}

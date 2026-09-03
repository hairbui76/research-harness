/**
 * The scan, and the three researcher acts on it.
 *
 * Every answer is the daemon's; the hook only sequences calls, re-reads the scan after a
 * write so the cards show the daemon's new truth rather than an optimistic guess, and
 * remembers the last test report per entry.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { HarnessClient } from '../../api/client';
import type {
  CliProviderConfigureRequest,
  CliProviderConfigured,
  CliProviderRemoved,
  CliProviderTestReport,
  CliScanReport,
} from '../../api/dto';

export interface CliRuntimesApi {
  report: CliScanReport | null;
  loading: boolean;
  error: string | null;
  /** The entry name an action is running for, or the word `scan`; disables the controls. */
  busy: string | null;
  lastTest: Record<string, CliProviderTestReport>;
  rescan: () => Promise<void>;
  /** Resolves with the daemon's receipt, which names the file it wrote. */
  configure: (request: CliProviderConfigureRequest) => Promise<CliProviderConfigured>;
  remove: (name: string) => Promise<CliProviderRemoved>;
  test: (name: string) => Promise<void>;
}

function message(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export function useCliRuntimes(
  client: HarnessClient,
  options: { enabled?: boolean } = {},
): CliRuntimesApi {
  const enabled = options.enabled ?? true;
  const [report, setReport] = useState<CliScanReport | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [lastTest, setLastTest] = useState<Record<string, CliProviderTestReport>>({});

  // The tab unmounts when the researcher switches away; a scan that lands afterwards must
  // not write into a dead tree.
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  const load = useCallback(
    async (rescan: boolean) => {
      setLoading(true);
      try {
        const next = await client.providerCliScan(rescan);
        if (!live.current) return;
        setReport(next);
        setError(null);
      } catch (cause) {
        if (!live.current) return;
        setError(message(cause));
      } finally {
        if (live.current) setLoading(false);
      }
    },
    [client],
  );

  useEffect(() => {
    if (enabled) void load(false);
  }, [enabled, load]);

  /**
   * One write, then a fresh scan. The write's own failure is the caller's to report — the
   * card raises it as a toast — so it is re-thrown rather than swallowed into `error`,
   * which belongs to the scan.
   */
  const run = useCallback(
    async <T,>(key: string, action: () => Promise<T>): Promise<T> => {
      setBusy(key);
      try {
        const result = await action();
        await load(true);
        return result;
      } finally {
        if (live.current) setBusy(null);
      }
    },
    [load],
  );

  const rescan = useCallback(async () => {
    await run('scan', async () => undefined);
  }, [run]);

  const configure = useCallback(
    (request: CliProviderConfigureRequest) =>
      run(request.name, () => client.providerCliConfigure(request)),
    [client, run],
  );

  const remove = useCallback(
    (name: string) => run(name, () => client.providerCliRemove(name)),
    [client, run],
  );

  /**
   * A test does not change research.yaml, so it does not re-scan: it records one report
   * against the entry it was run for and leaves the cards alone.
   */
  const test = useCallback(
    async (name: string) => {
      setBusy(name);
      try {
        const result = await client.providerCliTest(name);
        if (live.current) setLastTest((current) => ({ ...current, [name]: result }));
      } finally {
        if (live.current) setBusy(null);
      }
    },
    [client],
  );

  return useMemo(
    () => ({ report, loading, error, busy, lastTest, rescan, configure, remove, test }),
    [busy, configure, error, lastTest, loading, remove, report, rescan, test],
  );
}

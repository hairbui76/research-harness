/**
 * The models this project may send to (`provider.list`), and the CLI runtimes it may bind
 * a session to (`provider.cli.scan`).
 *
 * The catalogue is derived server-side from the router configuration and the egress
 * report, so the selector shows what the daemon says exists — including the models it
 * cannot use, each with the daemon's own reason — and works out no provider rule for
 * itself (PRODUCT §5 P10, §34).
 *
 * When the capability is not there yet the hook says so and offers nothing. It does not
 * invent an option from the session defaults: an entry in a model selector is a claim
 * about where a request would go, and a client is not entitled to make that claim. The
 * composer then sends without a `model`, which is exactly what the session default means.
 *
 * The scan is read beside the catalogue rather than instead of it, and the two are kept
 * apart: a scan that fails leaves the entries exactly as they were and simply offers no
 * runtime groups, because a runtime binding is the extra the researcher can do without.
 */
import { useEffect, useMemo, useState } from 'react';
import type { ModelOption, ModelOptionGroup } from '@research-harness/design';
import type { HarnessClient } from '../../api/client';
import type { CliScanReport, ProviderModel } from '../../api/dto';
import { groupRuntimes } from '../../app/settings/mappers';
import { reasoningChoicesFor, toModelOption, toRuntimeGroup } from './mappers';

export interface ModelsApi {
  options: ModelOption[];
  /**
   * One group per installed CLI runtime, in the daemon's registry order, each listing the
   * scan's own models. Empty when the scan could not be read (binding spec §10).
   */
  groups: ModelOptionGroup[];
  /**
   * The effort names one model of a runtime offers, as the scan reports them: the model's
   * own list when it published one, the runtime's otherwise. Empty when neither offers any.
   */
  reasoningChoices: (runtime: string, model: string) => string[];
  /** The scan's egress sentence, shown before a session is first bound to a runtime. */
  notice: string | null;
  /** The daemon's default model, when it named one. */
  defaultId: string | null;
  loading: boolean;
  /** Why there is no selector, in one sentence, when there is none. */
  unavailable: string | null;
}

export function useModels(client: HarnessClient, options: { enabled?: boolean } = {}): ModelsApi {
  const enabled = options.enabled ?? true;
  const [models, setModels] = useState<ProviderModel[] | null>(null);
  const [scan, setScan] = useState<CliScanReport | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [unavailable, setUnavailable] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    setLoading(true);
    client
      .providers()
      .then((catalog) => {
        if (!live) return;
        setModels(catalog.models);
        setUnavailable(null);
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setModels(null);
        setUnavailable(
          `The model catalogue is unavailable, so this message goes to the session's ` +
            `default model: ${cause instanceof Error ? cause.message : String(cause)}`,
        );
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [client, enabled]);

  // The scan is its own read: on a daemon that has no `provider.cli.scan`, or a workstation
  // where detection failed, the entries above are still the whole selector and nothing here
  // is said about it twice.
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    client
      .providerCliScan()
      .then((report) => live && setScan(report))
      .catch(() => live && setScan(null));
    return () => {
      live = false;
    };
  }, [client, enabled]);

  return useMemo(() => {
    const runtimes = scan?.runtimes ?? [];
    return {
      options: (models ?? []).map(toModelOption),
      groups: scan ? groupRuntimes(scan).installed.map(toRuntimeGroup) : [],
      reasoningChoices: (runtime: string, model: string) => {
        const status = runtimes.find((item) => item.runtime === runtime);
        return status ? reasoningChoicesFor(status, model) : [];
      },
      notice: scan?.notice ?? null,
      defaultId: models?.find((model) => model.default)?.id ?? models?.[0]?.id ?? null,
      loading,
      unavailable,
    };
  }, [loading, models, scan, unavailable]);
}

/**
 * The models this project may send to (`provider.list`).
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
 */
import { useEffect, useMemo, useState } from 'react';
import type { ModelOption } from '@research-harness/design';
import type { HarnessClient } from '../../api/client';
import type { ProviderModel } from '../../api/dto';
import { toModelOption } from './mappers';

export interface ModelsApi {
  options: ModelOption[];
  /** The daemon's default model, when it named one. */
  defaultId: string | null;
  loading: boolean;
  /** Why there is no selector, in one sentence, when there is none. */
  unavailable: string | null;
}

export function useModels(client: HarnessClient, options: { enabled?: boolean } = {}): ModelsApi {
  const enabled = options.enabled ?? true;
  const [models, setModels] = useState<ProviderModel[] | null>(null);
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

  return useMemo(
    () => ({
      options: (models ?? []).map(toModelOption),
      defaultId: models?.find((model) => model.default)?.id ?? models?.[0]?.id ?? null,
      loading,
      unavailable,
    }),
    [loading, models, unavailable],
  );
}

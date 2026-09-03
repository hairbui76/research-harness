/**
 * The API providers tab: what `provider.list` says is configured, read-only.
 *
 * There is nothing to edit here. An API provider is a `research.yaml` entry with an
 * `api_key_env`, and the key itself is an environment variable on the workstation — a
 * browser must never be a place where one is typed, stored or shown, so this tab reports
 * the catalogue and says where the key comes from.
 *
 * The `local_cli` rows are filtered out: they are the other tab's subject, and a CLI entry
 * shown in both places would read as two providers.
 */
import { Empty, ErrorBox, Loading } from '../../components/Feedback';
import type { HarnessClient } from '../../api/client';
import { useAsync } from '../useAsync';

export function ApiProvidersTab({ client }: { client: HarnessClient }) {
  const catalog = useAsync(() => client.providers(), [client]);
  const rows = (catalog.data?.models ?? []).filter((item) => item.provider !== 'local_cli');

  return (
    <div className="rh-settings-providers">
      <p className="rh-settings-providers__notice">
        API providers are configured in <code>research.yaml</code> with <code>api_key_env</code>.
        API keys are read from environment variables on the workstation and never enter the
        browser.
      </p>

      {catalog.loading ? <Loading what="the API providers" /> : null}
      {catalog.error ? <ErrorBox error={catalog.error} retry={catalog.reload} /> : null}
      {catalog.data && rows.length === 0 ? <Empty>No API provider is configured.</Empty> : null}

      {rows.length > 0 ? (
        <ul className="rh-settings-providers__list">
          {rows.map((item) => (
            <li key={item.id}>
              <strong>{item.label}</strong>
              {` · ${item.provider} · ${item.egress_class} · ` +
                (item.available
                  ? 'available'
                  : `unavailable — ${item.unavailable_reason ?? 'no reason given'}`)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

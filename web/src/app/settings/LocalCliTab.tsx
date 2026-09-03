/**
 * The Local CLIs tab: the daemon's scan, grouped, and a rescan.
 *
 * The egress notice above the list is the daemon's own sentence — the cockpit does not
 * write its own warning about where research content goes.
 */
import { Button } from '@research-harness/design';
import { Empty, ErrorBox, Loading } from '../../components/Feedback';
import type { HarnessClient } from '../../api/client';
import { configuredFor, groupRuntimes } from './mappers';
import { RuntimeCard } from './RuntimeCard';
import { useCliRuntimes } from './useCliRuntimes';

export interface LocalCliTabProps {
  client: HarnessClient;
  canMutate: boolean;
  mutationBlockedReason: string | null;
}

export function LocalCliTab({ client, canMutate, mutationBlockedReason }: LocalCliTabProps) {
  const cli = useCliRuntimes(client);
  const report = cli.report;
  const groups = report ? groupRuntimes(report) : null;

  return (
    <div className="rh-settings-providers">
      <div className="rh-settings-providers__toolbar">
        {report ? <p className="rh-settings-providers__notice">{report.notice}</p> : null}
        <Button
          variant="secondary"
          size="sm"
          iconStart="refresh-cw"
          onClick={() => void cli.rescan()}
          disabled={cli.busy !== null}
        >
          Rescan
        </Button>
      </div>

      {cli.loading && report === null ? <Loading what="the local CLI scan" /> : null}
      {cli.error ? <ErrorBox error={cli.error} retry={() => void cli.rescan()} /> : null}

      {groups && groups.installed.length === 0 && cli.error === null ? (
        <Empty>
          No supported CLI is installed on this workstation. Install one of the runtimes below and
          rescan.
        </Empty>
      ) : null}

      {report && groups && groups.installed.length > 0 ? (
        <section aria-label="Installed" className="rh-settings-providers__group">
          <h3 className="rh-text-h4">Installed</h3>
          {groups.installed.map((status) => (
            <RuntimeCard
              key={status.runtime}
              status={status}
              report={report}
              canMutate={canMutate}
              mutationBlockedReason={mutationBlockedReason}
              busy={cli.busy}
              lastTest={cli.lastTest[configuredFor(report, status.runtime)?.name ?? '']}
              onConfigure={cli.configure}
              onRemove={cli.remove}
              onTest={cli.test}
            />
          ))}
        </section>
      ) : null}

      {report && groups && groups.unavailable.length > 0 ? (
        <section aria-label="Not installed" className="rh-settings-providers__group">
          <h3 className="rh-text-h4">Not installed</h3>
          {groups.unavailable.map((status) => (
            <RuntimeCard
              key={status.runtime}
              status={status}
              report={report}
              canMutate={canMutate}
              mutationBlockedReason={mutationBlockedReason}
              busy={cli.busy}
              lastTest={undefined}
              onConfigure={cli.configure}
              onRemove={cli.remove}
              onTest={cli.test}
            />
          ))}
        </section>
      ) : null}
    </div>
  );
}

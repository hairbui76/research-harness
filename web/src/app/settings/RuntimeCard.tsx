/**
 * One runtime: what the daemon found, and the researcher's controls over it.
 *
 * Every word of state comes from the report — the badges, the login guidance, the
 * diagnostics, the reason a runtime cannot be routed to, the report of a test. The card
 * decides nothing: the Add/Update control is disabled by the daemon's own `routable`
 * verdict and repeats the daemon's own `unavailable_reason` beside it, so a browser never
 * gets a second opinion about whether a CLI is safe to use (spec §18).
 */
import { useId, useState } from 'react';
import { Badge, Button, Input, Select, useToast } from '@research-harness/design';
import type {
  CliProviderConfigureRequest,
  CliProviderConfigured,
  CliProviderRemoved,
  CliProviderTestReport,
  CliRuntimeStatus,
  CliScanReport,
} from '../../api/dto';
import { configuredFor, defaultEntryName, runtimeBadges } from './mappers';

export interface RuntimeCardProps {
  status: CliRuntimeStatus;
  report: CliScanReport;
  canMutate: boolean;
  /** Why mutation is refused, in the session's own sentence, when it is refused. */
  mutationBlockedReason: string | null;
  busy: string | null;
  lastTest: CliProviderTestReport | undefined;
  onConfigure: (request: CliProviderConfigureRequest) => Promise<CliProviderConfigured>;
  onRemove: (name: string) => Promise<CliProviderRemoved>;
  onTest: (name: string) => Promise<void>;
}

/**
 * Where a request through this runtime ends up, from the daemon's two egress fields.
 *
 * `unknown_external` is the daemon saying it could not establish the host, which is a
 * worse answer than a named one and is written as such rather than dressed up.
 */
function egressSentence(status: CliRuntimeStatus): string {
  const destination =
    status.egress_kind === 'external'
      ? status.egress_host
      : 'a destination the CLI does not disclose';
  return `The process runs here, but research content and object IDs leave the machine for ${destination}.`;
}

export function RuntimeCard({
  status,
  report,
  canMutate,
  mutationBlockedReason,
  busy,
  lastTest,
  onConfigure,
  onRemove,
  onTest,
}: RuntimeCardProps) {
  const { toast } = useToast();
  const configured = configuredFor(report, status.runtime);
  const badges = runtimeBadges(status);
  const headingId = useId();
  const reasonId = useId();

  const [name, setName] = useState(configured?.name ?? defaultEntryName(status.runtime));
  const [model, setModel] = useState(configured?.model ?? 'default');
  const [reasoning, setReasoning] = useState<string>(configured?.reasoning ?? '');
  const [priority, setPriority] = useState(configured?.priority ?? 10);

  const modelReasoning = status.models.find((item) => item.id === model)?.reasoning ?? [];
  const reasoningChoices = modelReasoning.length > 0 ? modelReasoning : status.reasoning_choices;
  // A reasoning effort the chosen model does not offer is not sent; the runtime's own
  // default is what an empty choice means.
  const reasoningValue = reasoningChoices.includes(reasoning) ? reasoning : '';
  const working = busy !== null;

  async function submit() {
    const request: CliProviderConfigureRequest = {
      name,
      runtime: status.runtime,
      model,
      priority,
      ...(reasoningValue ? { reasoning: reasoningValue } : {}),
    };
    try {
      const receipt = await onConfigure(request);
      toast({
        tone: 'success',
        title: `${receipt.entry.name} ${receipt.created ? 'added to' : 'updated in'} ${receipt.file}`,
      });
    } catch (cause) {
      toast({ tone: 'error', title: cause instanceof Error ? cause.message : String(cause) });
    }
  }

  async function act(action: () => Promise<unknown>) {
    try {
      await action();
    } catch (cause) {
      toast({ tone: 'error', title: cause instanceof Error ? cause.message : String(cause) });
    }
  }

  return (
    <article className="rh-runtime-card" aria-labelledby={headingId}>
      <header className="rh-runtime-card__header">
        <h4 id={headingId} className="rh-text-h4">
          {status.name}
        </h4>
        <span className="rh-runtime-card__version">
          {status.version ?? (status.available ? 'version unknown' : 'not installed')}
        </span>
      </header>

      {status.available ? (
        <div className="rh-runtime-card__badges">
          <Badge tone={badges.login.tone}>{badges.login.label}</Badge>
          <Badge tone={badges.bounded.tone}>{badges.bounded.label}</Badge>
          <Badge tone={badges.compatibility.tone}>{badges.compatibility.label}</Badge>
        </div>
      ) : null}

      {status.auth_status === 'missing' && status.auth_guidance ? (
        <p className="rh-runtime-card__guidance">{status.auth_guidance}</p>
      ) : null}

      {status.diagnostics.length > 0 ? (
        <ul className="rh-runtime-card__diagnostics">
          {status.diagnostics.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}

      {status.unavailable_reason !== null ? (
        <p id={reasonId} className="rh-runtime-card__reason">
          {status.unavailable_reason}
        </p>
      ) : null}

      {status.available ? (
        <>
          <p className="rh-runtime-card__egress">{egressSentence(status)}</p>

          {configured ? (
            <p className="rh-runtime-card__configured">
              {`Configured as ${configured.name} (${configured.model}, priority ${configured.priority}) — ` +
                (configured.available
                  ? 'available'
                  : `unavailable: ${configured.unavailable_reason ?? 'no reason given'}`)}
            </p>
          ) : null}

          <div className="rh-runtime-card__form">
            <Select
              label="Model"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              disabled={!canMutate || working}
            >
              {status.models.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </Select>
            <Select
              label="Reasoning"
              value={reasoningValue}
              onChange={(event) => setReasoning(event.target.value)}
              disabled={!canMutate || working || reasoningChoices.length === 0}
            >
              <option value="">Runtime default</option>
              {reasoningChoices.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
            <Input
              label="Entry name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={!canMutate || working}
            />
            <Input
              label="Priority"
              type="number"
              value={priority}
              onChange={(event) => setPriority(Number(event.target.value))}
              disabled={!canMutate || working}
            />
          </div>

          <div className="rh-runtime-card__actions">
            <Button
              variant="primary"
              size="sm"
              disabled={!canMutate || working || !status.routable}
              {...(status.unavailable_reason !== null ? { 'aria-describedby': reasonId } : {})}
              onClick={() => void submit()}
            >
              {configured ? 'Update provider' : 'Add provider'}
            </Button>
            {configured ? (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!canMutate || working}
                  onClick={() => void act(() => onTest(configured.name))}
                >
                  Test
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={!canMutate || working}
                  onClick={() => void act(() => onRemove(configured.name))}
                >
                  Remove
                </Button>
              </>
            ) : null}
          </div>

          {!canMutate && mutationBlockedReason !== null ? (
            <p className="rh-runtime-card__blocked">{mutationBlockedReason}</p>
          ) : null}

          {lastTest ? (
            <p
              role="status"
              className={`rh-runtime-card__test rh-runtime-card__test--${lastTest.ok ? 'ok' : 'failed'}`}
            >
              {lastTest.message}
              {lastTest.diagnostic ? (
                <code className="rh-runtime-card__diagnostic">{lastTest.diagnostic}</code>
              ) : null}
            </p>
          ) : null}
        </>
      ) : null}
    </article>
  );
}

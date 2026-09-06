/**
 * One runtime: what the daemon found, and the researcher's controls over it.
 *
 * Every word of state comes from the report — the badges, the login guidance, the
 * diagnostics, the reason a runtime cannot be routed to, the report of a test. The card
 * decides nothing: the Add/Update control is disabled by the daemon's own `routable`
 * verdict and repeats the daemon's own `unavailable_reason` beside it, so a browser never
 * gets a second opinion about whether a CLI is safe to use (spec §18).
 *
 * Removing asks first. `provider.cli.remove` drops one `local_cli` entry from
 * `research.yaml` and does nothing else — the CLI stays installed, the subscription login
 * is untouched, and no session, transcript or accepted object moves — but a researcher
 * cannot know that from a button that acts on one press, and forgetting a project already
 * asks. The confirmation states that consequence rather than asking "Are you sure?".
 */
import { useEffect, useId, useRef, useState } from 'react';
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
  // Held as the field's own text, so that a half-typed or cleared value stays on screen
  // exactly as the researcher left it instead of being coerced to a number behind them.
  const [priority, setPriority] = useState(String(configured?.priority ?? 10));
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);
  const confirmRemoval = useRef<HTMLButtonElement | null>(null);

  // The confirmation is a question, so it takes the caret: Enter answers it and Escape
  // abandons it without hunting for either control.
  useEffect(() => {
    if (confirmingRemoval) confirmRemoval.current?.focus();
  }, [confirmingRemoval]);

  const modelReasoning = status.models.find((item) => item.id === model)?.reasoning ?? [];
  const reasoningChoices = modelReasoning.length > 0 ? modelReasoning : status.reasoning_choices;
  // A reasoning effort the chosen model does not offer is not sent; the runtime's own
  // default is what an empty choice means.
  const reasoningValue = reasoningChoices.includes(reasoning) ? reasoning : '';
  // An empty or unparseable priority is not a priority of zero: the field is simply not
  // sent, and the daemon applies its own default.
  const priorityNumber = Number(priority);
  const hasPriority = priority.trim() !== '' && Number.isFinite(priorityNumber);
  const working = busy !== null;

  // Why the *entry* is unusable, when that is not already on screen as why the *runtime*
  // is. The daemon stamps an entry with the runtime's own reason when the runtime is the
  // problem, and with a different sentence (a policy refusal) when it is not; printing the
  // same sentence twice would only bury the case where the two differ.
  const entryReason =
    configured && !configured.available && configured.unavailable_reason
      ? configured.unavailable_reason === status.unavailable_reason
        ? null
        : configured.unavailable_reason
      : null;

  async function submit() {
    const request: CliProviderConfigureRequest = {
      name,
      runtime: status.runtime,
      model,
      ...(hasPriority ? { priority: priorityNumber } : {}),
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
        <p className="rh-runtime-card__egress">{egressSentence(status)}</p>
      ) : null}

      {/*
        Outside the installed guard on purpose. `report.configured` is read from
        research.yaml independently of what detection found, so an entry whose CLI has been
        uninstalled still routes — and a settings screen that hid it would leave the
        researcher with a provider they cannot see and cannot remove.
      */}
      {configured ? (
        <p className="rh-runtime-card__configured">
          {`Configured as ${configured.name} (${configured.model}, priority ${configured.priority}) — ` +
            (configured.available ? 'available' : 'unavailable')}
        </p>
      ) : null}

      {entryReason !== null ? (
        <p className="rh-runtime-card__reason">{entryReason}</p>
      ) : null}

      {status.available ? (
        <>
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
              onChange={(event) => setPriority(event.target.value)}
              disabled={!canMutate || working}
            />
          </div>

        </>
      ) : null}

      {status.available || configured ? (
        <div className="rh-runtime-card__actions">
          {status.available ? (
            <Button
              variant="primary"
              size="sm"
              disabled={!canMutate || working || !status.routable}
              {...(status.unavailable_reason !== null ? { 'aria-describedby': reasonId } : {})}
              onClick={() => void submit()}
            >
              {configured ? 'Update provider' : 'Add provider'}
            </Button>
          ) : null}
          {configured ? (
            <>
              {/* A test spends a real request through the CLI, so it needs the same green
                  gates the daemon requires before it would route to it. */}
              <Button
                variant="secondary"
                size="sm"
                disabled={!canMutate || working || !status.routable}
                {...(status.unavailable_reason !== null ? { 'aria-describedby': reasonId } : {})}
                onClick={() => void act(() => onTest(configured.name))}
              >
                Test
              </Button>
              {/* Removing an entry only edits research.yaml, so it is always offered: a
                  researcher must be able to take out a provider that stopped working. The
                  press opens the question; the answer below it does the writing. */}
              <Button
                variant="secondary"
                size="sm"
                disabled={!canMutate || working || confirmingRemoval}
                onClick={() => setConfirmingRemoval(true)}
              >
                Remove
              </Button>
            </>
          ) : null}
        </div>
      ) : null}

      {configured && confirmingRemoval ? (
        <div
          role="group"
          aria-label={`Confirm removing ${configured.name}`}
          className="rh-runtime-card__confirm"
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return;
            event.stopPropagation();
            setConfirmingRemoval(false);
          }}
        >
          <p className="rh-runtime-card__confirm-text">
            {`Remove ${configured.name} from research.yaml. Requests stop routing through it and ` +
              'it leaves the model picker. ' +
              (status.available
                ? `${status.name} stays installed and logged in on this workstation. `
                : `${status.name} is not installed here in any case. `) +
              'No session, transcript or accepted object changes, and adding it again ' +
              'restores the entry.'}
          </p>
          <div className="rh-runtime-card__actions">
            <Button
              ref={confirmRemoval}
              variant="danger"
              size="sm"
              disabled={!canMutate || working}
              onClick={() =>
                void act(async () => {
                  const receipt = await onRemove(configured.name);
                  setConfirmingRemoval(false);
                  return receipt;
                })
              }
            >
              {`Remove ${configured.name}`}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirmingRemoval(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      {!canMutate && mutationBlockedReason !== null && (status.available || configured) ? (
        <p className="rh-runtime-card__blocked">{mutationBlockedReason}</p>
      ) : null}

      {/*
        Mounted before there is anything to say, so a verdict is an update to a live region
        assistive technology already watches rather than a region that appears with its text
        already in place, which is not reliably announced.
      */}
      {configured ? (
        <p
          role="status"
          className={
            lastTest
              ? `rh-runtime-card__test rh-runtime-card__test--${lastTest.ok ? 'ok' : 'failed'}`
              : 'rh-runtime-card__test'
          }
        >
          {lastTest ? lastTest.message : null}
          {lastTest?.diagnostic ? (
            <code className="rh-runtime-card__diagnostic">{lastTest.diagnostic}</code>
          ) : null}
        </p>
      ) : null}
    </article>
  );
}

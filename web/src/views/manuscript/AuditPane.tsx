/**
 * The collapsible inspector: what the compiler said, what the science says, and the anchors
 * behind both.
 *
 * The two lists live in `DiagnosticsPanel`, which keeps them under separate headings with
 * separate words and separate counts, because a document may compile while failing its
 * audit and pass its audit while failing to compile (LaTeX spec §7). Nothing on this pane
 * sums them, and the tab label carries both counts side by side rather than a total.
 *
 * The second tab is the v1.0 Manuscript screen, folded in: every stored anchor with the
 * verdict `manuscript.anchors` currently gives it, `manuscript.trace` down to the Claim and
 * source spans behind one sentence, and `manuscript.revalidate` — the one mutation here,
 * human-only, because a reworded sentence going stale is a change to accepted state
 * (ADR-008).
 */
import { useState } from 'react';
import {
  Button,
  CompilerStatus,
  DiagnosticsPanel,
  Tabs,
  useToast,
} from '@research-harness/design';
import type { AuditFindingModel, BuildModel, DiagnosticModel } from '@research-harness/design';
import type { AnchorVerdict, JsonObject, ManuscriptAnchors } from '../../api/dto';
import {
  Empty,
  ErrorBox,
  Field,
  Fields,
  Loading,
  Panel,
  StatusBadge,
} from '../../components/Feedback';
import { ObjectRef } from '../../components/ObjectRef';
import { useProjectPaths } from '../../app/projectPaths';
import { useSession } from '../../app/session';
import { useAsync } from '../../app/useAsync';
import type { Async } from '../../app/useAsync';

export interface AuditPaneProps {
  build: BuildModel;
  diagnostics: readonly DiagnosticModel[];
  findings: readonly AuditFindingModel[];
  /** The entry file the anchors and trace reads are scoped to. */
  entryFile: string;
  /** Set when the audit could not run at all; an empty list would otherwise read as clean. */
  auditUnavailableReason?: string | null;
  /** A compile the daemon refused — no engine, or no authority to start one. */
  compileError?: string | null;
  onOpenSource: (file: string, line: number) => void;
  onNavigate: (target: { kind: 'claim' | 'anchor'; id: string }) => void;
}

const BUILD_TAB = 'build';
const ANCHORS_TAB = 'anchors';

export function AuditPane({
  build,
  diagnostics,
  findings,
  entryFile,
  auditUnavailableReason,
  compileError,
  onOpenSource,
  onNavigate,
}: AuditPaneProps) {
  const { client } = useSession();
  const [notice, setNotice] = useState<string | null>(null);
  const anchors = useAsync(() => client.manuscriptAnchors(null, entryFile), [client, entryFile, notice]);

  return (
    <Tabs defaultValue={BUILD_TAB} keepMounted>
      <Tabs.List aria-label="Manuscript inspector">
        <Tabs.Tab value={BUILD_TAB}>
          Build and audit{' '}
          <span className="rh-text-secondary">
            {`${diagnostics.length} compiler · ${findings.length} audit`}
          </span>
        </Tabs.Tab>
        <Tabs.Tab value={ANCHORS_TAB}>
          Anchors <span className="rh-text-secondary">{anchors.data?.count ?? 0}</span>
        </Tabs.Tab>
      </Tabs.List>

      <Tabs.Panel value={BUILD_TAB}>
        {/* The panel's own heading. `DiagnosticsPanel` opens at h3, so without this the
            document would jump from the workspace's h1 straight past h2. */}
        <h2 className="rh-visually-hidden">Build and audit</h2>
        {compileError ? <ErrorBox error={compileError} /> : null}
        {auditUnavailableReason ? (
          <p className="rh-text-secondary" role="status">
            {`The scientific audit did not run for this build (${auditUnavailableReason}), so the list below is empty because nothing was checked — not because nothing was found.`}
          </p>
        ) : null}
        {/* `CompilerStatus` reports; it is not given `onCompile`, because Compile is one
            action with one button, and that button lives in the source frame's toolbar. */}
        <DiagnosticsPanel
          diagnostics={diagnostics}
          findings={findings}
          status={<CompilerStatus build={build} />}
          onOpenSource={onOpenSource}
          onNavigate={onNavigate}
        />
      </Tabs.Panel>

      <Tabs.Panel value={ANCHORS_TAB}>
        <AnchorsTab
          anchors={anchors}
          entryFile={entryFile}
          notice={notice}
          onNotice={setNotice}
          onOpenSource={onOpenSource}
        />
      </Tabs.Panel>
    </Tabs>
  );
}

function AnchorsTab({
  anchors,
  entryFile,
  notice,
  onNotice,
  onOpenSource,
}: {
  anchors: Async<ManuscriptAnchors>;
  entryFile: string;
  notice: string | null;
  onNotice: (notice: string) => void;
  onOpenSource: (file: string, line: number) => void;
}) {
  const { client, canMutate, mutationBlockedReason, refresh } = useSession();
  const { href } = useProjectPaths();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [traced, setTraced] = useState<{ file: string; line: number } | null>(null);

  async function revalidate(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const result = await client.revalidateManuscript(null, entryFile);
      onNotice(
        `${result.checked} anchors re-found: ${result.valid} valid, ${result.relocated} ` +
          `relocated, ${result.stale} stale, ${result.missing} missing. ` +
          `${result.applied.length} recorded.`,
      );
      toast({ tone: 'success', title: 'Anchors revalidated' });
      refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  if (anchors.loading) return <Loading what="the manuscript anchors" />;
  if (anchors.error) return <ErrorBox error={anchors.error} retry={anchors.reload} />;

  const stored = anchors.data?.anchors ?? [];
  const verdicts = anchors.data?.verdicts ?? [];

  return (
    <div className="rh-web-stack">
      <Panel
        title={`Anchors (${anchors.data?.count ?? 0})`}
        action={
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={!canMutate || busy}
            loading={busy}
            title={mutationBlockedReason ?? undefined}
            onClick={() => void revalidate()}
          >
            Revalidate anchors
          </Button>
        }
      >
        <p className="rh-text-secondary">
          Revalidating records what the manuscript now says: a sentence that moved keeps its
          anchor, and one that was reworded goes stale for review rather than being silently
          reattached (ADR-008). That is a researcher’s decision, so it needs the local token.
        </p>
        {!canMutate ? (
          <p className="rh-text-secondary" data-testid="revalidate-blocked">
            {mutationBlockedReason}
          </p>
        ) : null}
        {notice ? <p className="rh-text-secondary">{notice}</p> : null}
        {error ? <ErrorBox error={error} /> : null}

        {stored.length === 0 ? (
          <Empty>No manuscript sentence is bound to a Claim yet.</Empty>
        ) : (
          <ul className="rh-web-list rh-web-list--rules">
            {stored.map((anchor) => {
              const verdict = verdictFor(verdicts, anchor.file, anchor.line_start);
              return (
                <li
                  key={`${anchor.file}:${anchor.line_start}`}
                  className="rh-web-stack rh-web-stack--tight"
                >
                  <p className="rh-web-row">
                    <code>
                      {anchor.file}:{anchor.line_start}
                    </code>
                    <StatusBadge status={anchor.status} />
                    {anchor.stale === 'stale' ? <StatusBadge status="stale" /> : null}
                    {verdict && verdict.status !== anchor.status ? (
                      <StatusBadge status={verdict.status}>now {verdict.status}</StatusBadge>
                    ) : null}
                  </p>
                  <p>{anchor.sentence}</p>
                  <p className="rh-web-row rh-text-secondary">
                    asserts
                    <ObjectRef id={anchor.claim} kind="claim" to={href(`/claims/${anchor.claim}`)} />
                    {anchor.citation_keys.length ? (
                      <span>cites {anchor.citation_keys.join(', ')}</span>
                    ) : null}
                    {verdict?.reason ? <span>{verdict.reason}</span> : null}
                    {verdict?.relocated_to ? (
                      <span>{`found at ${verdict.relocated_to[0]}-${verdict.relocated_to[1]}`}</span>
                    ) : null}
                  </p>
                  <div className="rh-web-row">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      iconStart="file-code"
                      onClick={() => onOpenSource(anchor.file, anchor.line_start)}
                    >
                      Open in the editor
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      iconStart="crosshair"
                      onClick={() => setTraced({ file: anchor.file, line: anchor.line_start })}
                    >
                      Trace this sentence
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>

      {traced ? (
        <TracePanel where={traced} entryFile={entryFile} onClose={() => setTraced(null)} />
      ) : null}
    </div>
  );
}

/** The verdict `manuscript.anchors` computed for one stored anchor, when it produced one. */
function verdictFor(
  verdicts: AnchorVerdict[],
  file: string,
  lineStart: number,
): AnchorVerdict | undefined {
  return verdicts.find((verdict) => verdict.file === file && verdict.line_start === lineStart);
}

/** One sentence down to its Claim and the exact spans behind it (`manuscript.trace`). */
function TracePanel({
  where,
  entryFile,
  onClose,
}: {
  where: { file: string; line: number };
  entryFile: string;
  onClose: () => void;
}) {
  const { client } = useSession();
  const { href } = useProjectPaths();
  const state = useAsync(
    () => client.traceManuscript(where.file, where.line, null, entryFile),
    [client, entryFile, where.file, where.line],
  );
  const label = `${where.file}:${where.line}`;

  return (
    <Panel
      title={`Trace — ${label}`}
      action={
        <Button type="button" variant="ghost" size="sm" iconStart="x" onClick={onClose}>
          Close
        </Button>
      }
    >
      {state.loading ? <Loading what={`the trace for ${label}`} /> : null}
      {state.error ? <ErrorBox error={state.error} retry={state.reload} /> : null}
      {state.data ? (
        <>
          <blockquote className="rh-web-quote">{state.data.sentence}</blockquote>
          <Fields>
            <Field label="Anchor">{state.data.anchor ?? '— this sentence carries none'}</Field>
            <Field label="Claim">
              {state.data.claim ? (
                <ObjectRef
                  id={state.data.claim}
                  kind="claim"
                  to={href(`/claims/${state.data.claim}`)}
                />
              ) : (
                '— none'
              )}
            </Field>
            <Field label="Evidence">{evidenceOf(state.data.link).join(', ') || '—'}</Field>
            <Field label="Source spans">{spansOf(state.data.link)}</Field>
          </Fields>
        </>
      ) : null}
    </Panel>
  );
}

function evidenceOf(link: JsonObject | null | undefined): string[] {
  return ((link?.evidence as string[] | undefined) ?? []).map(String);
}

function spansOf(link: JsonObject | null | undefined): string {
  const spans = (link?.spans as JsonObject[] | undefined) ?? [];
  if (spans.length === 0) return '— no parse was available for the artifacts behind it';
  return spans
    .map((span) => `${String(span.block)} · page ${String(span.page ?? '?')}`)
    .join(' · ');
}

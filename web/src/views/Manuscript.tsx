/**
 * Manuscript (PRODUCT §30): every anchored sentence, its Claim, and what the audit found.
 *
 * Three capabilities answer this screen and none of them is recomputed here.
 * `manuscript.anchors` reads every stored anchor with the verdict it currently earns;
 * `manuscript.audit` reports findings, each carrying the structured `location` it was
 * raised at; `manuscript.trace` walks one sentence down to the Claim and source spans
 * behind it. All three are reads: they report, they never repair.
 *
 * `manuscript.revalidate` is the one mutation, and it is human-only for the reason ADR-008
 * gives — a moved sentence adopts its new lines, a reworded one goes stale, and deciding
 * that a sentence still says what its anchor claims is a researcher's act, not a refresh.
 *
 * All four need a LaTeX project on disk, so the page asks for one and says plainly when
 * there is none, rather than showing an empty report that could be mistaken for a clean one.
 *
 * W4 replaces this page with the manuscript workspace (`ManuscriptWorkspace`, the
 * CodeMirror editor and the pdf.js preview). Until then it stays the anchor-and-audit
 * report it has always been, composed from the package.
 */
import { useState } from 'react';
import { Button, FullPageWorkspace, Input, useToast } from '@research-harness/design';
import type {
  AnchorVerdict,
  JsonObject,
  ManuscriptAnchors,
  ManuscriptAuditFinding,
} from '../api/dto';
import {
  DataTable,
  Empty,
  ErrorBox,
  Field,
  Fields,
  Loading,
  Panel,
  StatusBadge,
} from '../components/Feedback';
import { ObjectRef } from '../components/ObjectRef';
import { useSession } from '../app/session';
import { useAsync } from '../app/useAsync';
import type { Async } from '../app/useAsync';

export function ManuscriptPage() {
  const { client, canMutate, mutationBlockedReason, refresh } = useSession();
  const { toast } = useToast();
  const [projectRoot, setProjectRoot] = useState('');
  const [requested, setRequested] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [traced, setTraced] = useState<string | null>(null);

  const root = requested === null ? null : requested || null;
  const anchors = useAsync(() => client.manuscriptAnchors(root), [client, root, notice]);
  const audit = useAsync(
    async () => (requested === null ? null : client.auditManuscript(root)),
    [client, requested, root, notice],
  );

  async function revalidate() {
    setBusy(true);
    setError(null);
    try {
      const result = await client.revalidateManuscript(root);
      const summary =
        `${result.checked} anchors re-found: ${result.valid} valid, ${result.relocated} ` +
        `relocated, ${result.stale} stale, ${result.missing} missing. ` +
        `${result.applied.length} recorded.`;
      setNotice(summary);
      // The summary stays on the page; the toast only says the write landed.
      toast({ tone: 'success', title: 'Anchors revalidated' });
      refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <FullPageWorkspace
      title="Manuscript"
      description="Every anchored sentence, the Claim it asserts, and what the audit found."
    >
      <div className="rh-web-stack">
        <Panel title="Project">
          <form
            className="rh-web-stack rh-web-stack--tight"
            onSubmit={(event) => {
              event.preventDefault();
              setRequested(projectRoot.trim());
            }}
          >
            <Input
              id="project-root"
              label="LaTeX project root (blank uses the workspace default)"
              placeholder="/path/to/paper"
              value={projectRoot}
              onChange={(event) => setProjectRoot(event.target.value)}
            />
            <div className="rh-web-row">
              <Button type="submit" variant="primary" size="sm">
                Audit the manuscript
              </Button>
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
            </div>
          </form>
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
        </Panel>

        <AnchorsPanel anchors={anchors} onTrace={(file, line) => setTraced(`${file}:${line}`)} />

        {traced ? <TracePanel where={traced} root={root} onClose={() => setTraced(null)} /> : null}

        <Panel title="Audit">
          {requested === null ? <Empty>Name a project above to audit it.</Empty> : null}
          {requested !== null && audit.loading ? <Loading what="the manuscript audit" /> : null}
          {audit.error ? <ErrorBox error={audit.error} /> : null}
          {audit.data ? (
            <>
              <Fields>
                <Field label="Sentences checked">{audit.data.sentences_checked}</Field>
                <Field label="Anchored">{audit.data.anchored_sentences}</Field>
                <Field label="Substantive but unanchored">
                  {audit.data.unanchored_substantive}
                </Field>
              </Fields>
              {audit.data.findings.length === 0 ? (
                <Empty>The audit raised nothing.</Empty>
              ) : (
                <DataTable
                  label="Audit findings"
                  head={
                    <tr>
                      <th scope="col">Severity</th>
                      <th scope="col">Finding</th>
                      <th scope="col">Where</th>
                      <th scope="col">Message</th>
                    </tr>
                  }
                >
                  {audit.data.findings.map((finding, position) => (
                    <tr key={position}>
                      <td>
                        <StatusBadge status={finding.severity} />
                      </td>
                      <th scope="row">{finding.kind}</th>
                      <td className="rh-text-secondary">
                        <code>{whereOf(finding)}</code>
                      </td>
                      <td>{finding.message}</td>
                    </tr>
                  ))}
                </DataTable>
              )}
            </>
          ) : null}
        </Panel>
      </div>
    </FullPageWorkspace>
  );
}

/**
 * Where a finding was raised, from the finding's own `location`.
 *
 * The auditor also writes the location into the message, but parsing prose to place a
 * finding would be a second implementation of something the daemon already answers — and it
 * cannot answer for a finding no sentence produced, which is exactly when `location` is
 * absent and this says so.
 */
export function whereOf(finding: ManuscriptAuditFinding): string {
  const location = finding.location;
  if (!location) return 'whole project';
  const lines =
    location.line_end > location.line_start
      ? `${location.line_start}-${location.line_end}`
      : `${location.line_start}`;
  return `${location.file}:${lines}`;
}

function AnchorsPanel({
  anchors,
  onTrace,
}: {
  anchors: Async<ManuscriptAnchors>;
  onTrace: (file: string, line: number) => void;
}) {
  if (anchors.loading) return <Loading what="the manuscript anchors" />;
  if (anchors.error) return <ErrorBox error={anchors.error} retry={anchors.reload} />;

  const stored = anchors.data?.anchors ?? [];
  const verdicts = anchors.data?.verdicts ?? [];
  return (
    <Panel title={`Anchors (${anchors.data?.count ?? 0})`}>
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
                  <ObjectRef id={anchor.claim} kind="claim" to={`/claims/${anchor.claim}`} />
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
                    iconStart="crosshair"
                    onClick={() => onTrace(anchor.file, anchor.line_start)}
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
  root,
  onClose,
}: {
  where: string;
  root: string | null;
  onClose: () => void;
}) {
  const { client } = useSession();
  const [file, line] = splitWhere(where);
  const state = useAsync(() => client.traceManuscript(file, line), [client, file, line, root]);

  return (
    <Panel
      title={`Trace — ${where}`}
      action={
        <Button type="button" variant="ghost" size="sm" iconStart="x" onClick={onClose}>
          Close
        </Button>
      }
    >
      {state.loading ? <Loading what={`the trace for ${where}`} /> : null}
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
                  to={`/claims/${state.data.claim}`}
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

function splitWhere(where: string): [string, number] {
  const at = where.lastIndexOf(':');
  return [where.slice(0, at), Number(where.slice(at + 1))];
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

/**
 * Manuscript (Product 30): every anchored sentence, its Claim, and what the audit found.
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
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import type {
  AnchorVerdict,
  JsonObject,
  ManuscriptAnchors,
  ManuscriptAuditFinding,
} from '../api/dto';
import { Empty, ErrorBox, Field, Loading, Panel, Tag } from '../components/Feedback';
import { useSession } from '../app/session';
import { useAsync } from '../app/useAsync';
import type { Async } from '../app/useAsync';

export function ManuscriptPage() {
  const { client, canMutate, mutationBlockedReason, refresh } = useSession();
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
      setNotice(
        `${result.checked} anchors re-found: ${result.valid} valid, ${result.relocated} ` +
          `relocated, ${result.stale} stale, ${result.missing} missing. ` +
          `${result.applied.length} recorded.`,
      );
      refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="manuscript">
      <h1>Manuscript</h1>

      <Panel title="Project">
        <form
          className="prompt"
          onSubmit={(event) => {
            event.preventDefault();
            setRequested(projectRoot.trim());
          }}
        >
          <label htmlFor="project-root">LaTeX project root (blank uses the workspace default)</label>
          <input
            id="project-root"
            value={projectRoot}
            onChange={(event) => setProjectRoot(event.target.value)}
            placeholder="/path/to/paper"
          />
          <div className="actions">
            <button type="submit">Audit the manuscript</button>
            <button
              type="button"
              className="secondary"
              disabled={!canMutate || busy}
              title={mutationBlockedReason ?? undefined}
              onClick={() => void revalidate()}
            >
              Revalidate anchors
            </button>
          </div>
        </form>
        <p className="muted">
          Revalidating records what the manuscript now says: a sentence that moved keeps its
          anchor, and one that was reworded goes stale for review rather than being silently
          reattached (ADR-008). That is a researcher’s decision, so it needs the local token.
        </p>
        {!canMutate ? (
          <p className="muted" data-testid="revalidate-blocked">
            {mutationBlockedReason}
          </p>
        ) : null}
        {notice ? <p className="notice">{notice}</p> : null}
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}
      </Panel>

      <AnchorsPanel
        anchors={anchors}
        onTrace={(file, line) => setTraced(`${file}:${line}`)}
      />

      {traced ? <TracePanel where={traced} root={root} onClose={() => setTraced(null)} /> : null}

      <Panel title="Audit">
        {requested === null ? (
          <Empty>Name a project above to audit it.</Empty>
        ) : null}
        {requested !== null && audit.loading ? <Loading what="the manuscript audit" /> : null}
        {audit.error ? <ErrorBox error={audit.error} /> : null}
        {audit.data ? (
          <>
            <Field label="Sentences checked">{audit.data.sentences_checked}</Field>
            <Field label="Anchored">{audit.data.anchored_sentences}</Field>
            <Field label="Substantive but unanchored">{audit.data.unanchored_substantive}</Field>
            {audit.data.findings.length === 0 ? (
              <Empty>The audit raised nothing.</Empty>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Finding</th>
                    <th>Where</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.data.findings.map((finding, position) => (
                    <tr key={position}>
                      <td>
                        <Tag kind={finding.severity}>{finding.severity}</Tag>
                      </td>
                      <td>{finding.kind}</td>
                      <td className="muted">{whereOf(finding)}</td>
                      <td>{finding.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        ) : null}
      </Panel>
    </div>
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
        <ul>
          {stored.map((anchor) => {
            const verdict = verdictFor(verdicts, anchor.file, anchor.line_start);
            return (
              <li key={`${anchor.file}:${anchor.line_start}`}>
                <code>
                  {anchor.file}:{anchor.line_start}
                </code>{' '}
                <Tag kind={anchor.status}>{anchor.status}</Tag>
                {anchor.stale === 'stale' ? <Tag kind="stale">stale</Tag> : null}
                {verdict && verdict.status !== anchor.status ? (
                  <Tag kind={verdict.status}>now {verdict.status}</Tag>
                ) : null}
                <div>{anchor.sentence}</div>
                <div className="muted">
                  asserts <Link to={`/claims/${anchor.claim}`}>{anchor.claim}</Link>
                  {anchor.citation_keys.length ? ` · cites ${anchor.citation_keys.join(', ')}` : ''}
                  {verdict?.reason ? ` · ${verdict.reason}` : ''}
                  {verdict?.relocated_to
                    ? ` · found at ${verdict.relocated_to[0]}-${verdict.relocated_to[1]}`
                    : ''}
                </div>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onTrace(anchor.file, anchor.line_start)}
                >
                  Trace this sentence
                </button>
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
        <button type="button" className="secondary" onClick={onClose}>
          Close
        </button>
      }
    >
      {state.loading ? <Loading what={`the trace for ${where}`} /> : null}
      {state.error ? <ErrorBox error={state.error} retry={state.reload} /> : null}
      {state.data ? (
        <>
          <blockquote>{state.data.sentence}</blockquote>
          <Field label="Anchor">{state.data.anchor ?? '— this sentence carries none'}</Field>
          <Field label="Claim">
            {state.data.claim ? (
              <Link to={`/claims/${state.data.claim}`}>{state.data.claim}</Link>
            ) : (
              '— none'
            )}
          </Field>
          <Field label="Evidence">{evidenceOf(state.data.link).join(', ') || '—'}</Field>
          <Field label="Source spans">{spansOf(state.data.link)}</Field>
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

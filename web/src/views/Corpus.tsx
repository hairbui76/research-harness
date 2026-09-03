/**
 * Corpus: works, their revisions, their immutable files, and whether each file is parsed.
 *
 * A file with no stored parse cannot have an anchor replayed against it, which is why
 * "parsed" is on the list rather than buried: it is the difference between a source you can
 * open at a span and one you cannot (Product 16, 42 D).
 *
 * Not here, and deliberately: the `work.update_metadata` proposals a discovery run turns up
 * (`discovery/search_runs.py::MetadataEnrichment`). Nothing in the capability surface reads
 * a recorded `SearchRun` back — `state.index` does not list runs and there is no
 * `search_run.list` — so the cockpit cannot show a proposal it has no way to fetch. Showing
 * one would mean recomputing the funnel client-side, which is exactly what P10 forbids.
 * A read capability over recorded runs and their enrichments would close it.
 */
import { Link, useParams } from 'react-router-dom';
import { Empty, ErrorBox, Field, Loading, Panel, Tag } from '../components/Feedback';
import { useSession } from '../app/session';
import { useAsync } from '../app/useAsync';

export function CorpusPage() {
  const { client } = useSession();
  // `work.list`: this view needs the corpus and nothing else on the navigation.
  const state = useAsync(() => client.works(), [client]);

  if (state.loading) return <Loading what="the corpus" />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data || state.data.length === 0) return <Empty>The corpus is empty.</Empty>;

  return (
    <div className="corpus">
      <h1>Corpus</h1>
      {state.data.map((work) => (
        <Panel
          key={work.id}
          title={work.title}
          action={<Tag kind={work.screening}>{work.screening}</Tag>}
        >
          <Field label="Id">
            <Link to={`/corpus/${work.id}`}>{work.id}</Link>
          </Field>
          <Field label="Authors">{work.authors.join(', ') || '—'}</Field>
          <Field label="Year">{work.year ?? '—'}</Field>
          <Field label="Venue">{work.venue ?? '—'}</Field>
          <Field label="Accepted evidence">{work.evidence}</Field>
          <table>
            <thead>
              <tr>
                <th>Artifact</th>
                <th>Version</th>
                <th>Type</th>
                <th>Size</th>
                <th>Parsed</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {work.artifacts.map((artifact) => (
                <tr key={artifact.id}>
                  <td>{artifact.id}</td>
                  <td>{artifact.version}</td>
                  <td>{artifact.mime_type}</td>
                  <td>{artifact.size_bytes} bytes</td>
                  <td>{artifact.parsed ? 'yes' : 'no parse stored'}</td>
                  <td>
                    <a href={client.artifactBytesUrl(artifact.id)} target="_blank" rel="noreferrer">
                      open the file
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      ))}
    </div>
  );
}

export function WorkPage() {
  const { workId = '' } = useParams();
  const { client } = useSession();
  const state = useAsync(
    async () => {
      const [work, evidence] = await Promise.all([
        client.work(workId),
        // `evidence.list` names what was accepted from this Work; the count alone cannot
        // be opened, and staged proposals are deliberately not in it (ADR-003).
        client.evidence(workId),
      ]);
      return { work, evidence };
    },
    [client, workId],
  );

  if (state.loading) return <Loading what={`work ${workId}`} />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data) return <Empty>No work {workId}.</Empty>;

  const { work, evidence } = state.data;
  return (
    <div className="work">
      <h1>{work.title}</h1>
      <Panel title="Identity">
        <Field label="Id">{work.id}</Field>
        <Field label="Authors">{work.authors.join(', ') || '—'}</Field>
        <Field label="Year">{work.year ?? '—'}</Field>
        <Field label="Venue">{work.venue ?? '—'}</Field>
        <Field label="Screening">{work.screening}</Field>
        <Field label="Identifiers">
          <code>{JSON.stringify(work.identifiers)}</code>
        </Field>
      </Panel>
      <Panel title="Derived">
        <Field label="Blocks">{work.blocks}</Field>
        <Field label="Accepted evidence">{work.evidence}</Field>
      </Panel>
      <Panel title="Files">
        <ul>
          {work.artifacts.map((artifact) => (
            <li key={artifact.id}>
              {artifact.id} · {artifact.kind} · {artifact.original_filename ?? 'unnamed'} ·{' '}
              <code>{artifact.file_hash}</code>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title={`Accepted evidence (${evidence.length})`}>
        {evidence.length === 0 ? (
          <Empty>Nothing has been accepted from this work yet.</Empty>
        ) : (
          <ul>
            {evidence.map((item) => (
              <li key={item.id}>
                <Link to={`/evidence/${item.id}`}>{item.id}</Link>{' '}
                <Tag kind={item.status}>{item.status}</Tag>
                {item.stale === 'stale' ? <Tag kind="stale">stale</Tag> : null}
                <span className="muted">
                  {' '}
                  {item.field ?? 'no field'} · {item.evidence_type} · {item.strength}
                  {item.verdict ? ` · ${item.verdict}` : ''}
                </span>
                <blockquote>{item.exact_text}</blockquote>
                {item.qualification ? <p className="muted">{item.qualification}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

/** One accepted Evidence object, opened at the exact span it was accepted from. */
export function EvidencePage() {
  const { evidenceId = '' } = useParams();
  const { client } = useSession();
  const state = useAsync(() => client.object(evidenceId), [client, evidenceId]);

  if (state.loading) return <Loading what={`evidence ${evidenceId}`} />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data) return <Empty>No evidence {evidenceId}.</Empty>;

  const evidence = state.data.object as Record<string, any>;
  const source = evidence.source ?? {};
  const content = evidence.content ?? {};
  return (
    <div className="evidence">
      <h1>{evidenceId}</h1>
      <blockquote className="exact-text">{String(content.exact_text ?? '')}</blockquote>
      <Panel title="Epistemics">
        <Field label="Origin">{String(evidence.origin ?? '')}</Field>
        <Field label="Type">{String(evidence.evidence_type ?? '')}</Field>
        <Field label="Strength">{String(evidence.strength ?? '')}</Field>
        <Field label="Status">{String(evidence.verification?.status ?? '')}</Field>
        <Field label="Accepted by">{String(evidence.verification?.accepted_by ?? '—')}</Field>
        <Field label="Review action">{String(evidence.verification?.review_action ?? '—')}</Field>
        <Field label="Rationale">{String(evidence.verification?.rationale ?? '—')}</Field>
      </Panel>
      <Panel title="Source">
        <Field label="Work">{String(source.work ?? '')}</Field>
        <Field label="Artifact">
          <a href={client.artifactBytesUrl(String(source.artifact ?? ''))} target="_blank" rel="noreferrer">
            {String(source.artifact ?? '')}
          </a>
        </Field>
        <Field label="Page">{String(source.page ?? '—')}</Field>
        <Field label="Block">{String(source.block ?? '')}</Field>
        <Field label="File hash">
          <code>{String(source.file_hash ?? '')}</code>
        </Field>
      </Panel>
    </div>
  );
}

/**
 * Corpus: works, their revisions, their immutable files, and whether each file is parsed.
 *
 * A file with no stored parse cannot have an anchor replayed against it, which is why
 * "parsed" is on the list rather than buried: it is the difference between a source you can
 * open at a span and one you cannot (PRODUCT §16, §42 D).
 *
 * Not here, and deliberately: the `work.update_metadata` proposals a discovery run turns up
 * (`discovery/search_runs.py::MetadataEnrichment`). Nothing in the capability surface reads
 * a recorded `SearchRun` back — `state.index` does not list runs and there is no
 * `search_run.list` — so the cockpit cannot show a proposal it has no way to fetch. Showing
 * one would mean recomputing the funnel client-side, which is exactly what P10 forbids.
 * A read capability over recorded runs and their enrichments would close it.
 */
import { useParams } from 'react-router-dom';
import { EvidenceCard, FullPageWorkspace, Icon } from '@research-harness/design';
import type { EvidenceModel } from '@research-harness/design';
import type { EvidenceSummary } from '../api/dto';
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

export function CorpusPage() {
  const { client } = useSession();
  // `work.list`: this view needs the corpus and nothing else on the navigation.
  const state = useAsync(() => client.works(), [client]);

  if (state.loading) return <Loading what="the corpus" />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data || state.data.length === 0) return <Empty>The corpus is empty.</Empty>;

  return (
    <FullPageWorkspace
      title="Corpus"
      description={`${state.data.length} works. A file with no stored parse cannot have an anchor replayed against it.`}
    >
      <div className="rh-web-stack">
        {state.data.map((work) => (
          <Panel
            key={work.id}
            title={work.title}
            action={<StatusBadge status={work.screening} />}
          >
            <Fields>
              <Field label="Id">
                <ObjectRef id={work.id} kind="work" to={`/corpus/${work.id}`} />
              </Field>
              <Field label="Authors">{work.authors.join(', ') || '—'}</Field>
              <Field label="Year">{work.year ?? '—'}</Field>
              <Field label="Venue">{work.venue ?? '—'}</Field>
              <Field label="Accepted evidence">{work.evidence}</Field>
            </Fields>
            <DataTable
              label={`Files of ${work.id}`}
              head={
                <tr>
                  <th scope="col">Artifact</th>
                  <th scope="col">Version</th>
                  <th scope="col">Type</th>
                  <th scope="col">Size</th>
                  <th scope="col">Parsed</th>
                  <th scope="col">Source</th>
                </tr>
              }
            >
              {work.artifacts.map((artifact) => (
                <tr key={artifact.id}>
                  <th scope="row">
                    <code>{artifact.id}</code>
                  </th>
                  <td>{artifact.version}</td>
                  <td>{artifact.mime_type}</td>
                  <td>{artifact.size_bytes} bytes</td>
                  <td>
                    <StatusBadge status={artifact.parsed ? 'valid' : 'unverified'}>
                      {artifact.parsed ? 'yes' : 'no parse stored'}
                    </StatusBadge>
                  </td>
                  <td>
                    <a href={client.artifactBytesUrl(artifact.id)} target="_blank" rel="noreferrer">
                      open the file
                    </a>
                  </td>
                </tr>
              ))}
            </DataTable>
          </Panel>
        ))}
      </div>
    </FullPageWorkspace>
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
    <FullPageWorkspace
      title={work.title}
      description={`${work.id} · ${work.authors.join(', ') || 'no authors recorded'}`}
      toolbar={<StatusBadge status={work.screening} size="md" />}
    >
      <div className="rh-web-stack">
        <Panel title="Identity">
          <Fields>
            <Field label="Id">
              <code>{work.id}</code>
            </Field>
            <Field label="Authors">{work.authors.join(', ') || '—'}</Field>
            <Field label="Year">{work.year ?? '—'}</Field>
            <Field label="Venue">{work.venue ?? '—'}</Field>
            <Field label="Screening">{work.screening}</Field>
            <Field label="Identifiers">
              <code>{JSON.stringify(work.identifiers)}</code>
            </Field>
          </Fields>
        </Panel>

        <Panel title="Derived">
          <Fields>
            <Field label="Blocks">{work.blocks}</Field>
            <Field label="Accepted evidence">{work.evidence}</Field>
          </Fields>
        </Panel>

        <Panel title="Files">
          <DataTable
            label={`Files of ${work.id}`}
            head={
              <tr>
                <th scope="col">Artifact</th>
                <th scope="col">Kind</th>
                <th scope="col">Filename</th>
                <th scope="col">File hash</th>
              </tr>
            }
          >
            {work.artifacts.map((artifact) => (
              <tr key={artifact.id}>
                <th scope="row">
                  <code>{artifact.id}</code>
                </th>
                <td>{artifact.kind}</td>
                <td>{artifact.original_filename ?? 'unnamed'}</td>
                <td>
                  <code>{artifact.file_hash}</code>
                </td>
              </tr>
            ))}
          </DataTable>
        </Panel>

        <Panel title={`Accepted evidence (${evidence.length})`}>
          {evidence.length === 0 ? (
            <Empty>Nothing has been accepted from this work yet.</Empty>
          ) : (
            <ul className="rh-web-list">
              {evidence.map((item) => (
                <li key={item.id}>
                  <EvidenceCard evidence={acceptedEvidenceModel(item)} />
                  {item.qualification ? (
                    <p className="rh-text-secondary">{item.qualification}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </FullPageWorkspace>
  );
}

/**
 * One accepted `EvidenceSummary` as the Design System's evidence view model.
 *
 * Everything mapped here was decided by the daemon: `accepted` is what `evidence.list`
 * returns (staged proposals are not in it, ADR-003) and `stale` is the mark the staleness
 * pass recorded. Nothing is inferred.
 */
function acceptedEvidenceModel(item: EvidenceSummary): EvidenceModel {
  return {
    id: item.id,
    workId: item.work,
    workLabel: item.work,
    quote: item.exact_text,
    evidenceType: item.evidence_type,
    strength: item.strength,
    origin: item.origin,
    authority: 'accepted',
    stale: item.stale === 'stale',
    anchor: { artifactId: item.artifact, stale: item.stale === 'stale' },
    ...(item.field ? { field: item.field } : {}),
  };
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
  const artifact = String(source.artifact ?? '');
  return (
    <FullPageWorkspace
      title={evidenceId}
      description="One accepted Evidence object, with the exact span it was accepted from."
      toolbar={
        <a
          className="rh-web-row"
          href={client.artifactBytesUrl(artifact)}
          target="_blank"
          rel="noreferrer"
        >
          <Icon name="external-link" size={14} />
          Open the source file
        </a>
      }
    >
      <div className="rh-web-stack">
        <blockquote className="rh-web-quote">{String(content.exact_text ?? '')}</blockquote>

        <Panel title="Epistemics">
          <Fields>
            <Field label="Origin">{String(evidence.origin ?? '')}</Field>
            <Field label="Type">{String(evidence.evidence_type ?? '')}</Field>
            <Field label="Strength">{String(evidence.strength ?? '')}</Field>
            <Field label="Status">{String(evidence.verification?.status ?? '')}</Field>
            <Field label="Accepted by">{String(evidence.verification?.accepted_by ?? '—')}</Field>
            <Field label="Review action">
              {String(evidence.verification?.review_action ?? '—')}
            </Field>
            <Field label="Rationale">{String(evidence.verification?.rationale ?? '—')}</Field>
          </Fields>
        </Panel>

        <Panel title="Source">
          <Fields>
            <Field label="Work">
              <ObjectRef
                id={String(source.work ?? '')}
                kind="work"
                to={`/corpus/${String(source.work ?? '')}`}
              />
            </Field>
            <Field label="Artifact">
              <a href={client.artifactBytesUrl(artifact)} target="_blank" rel="noreferrer">
                {artifact}
              </a>
            </Field>
            <Field label="Page">{String(source.page ?? '—')}</Field>
            <Field label="Block">{String(source.block ?? '')}</Field>
            <Field label="File hash">
              <code>{String(source.file_hash ?? '')}</code>
            </Field>
          </Fields>
        </Panel>
      </div>
    </FullPageWorkspace>
  );
}

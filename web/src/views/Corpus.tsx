/**
 * Corpus: works, their revisions, their immutable files, and whether each file is parsed.
 *
 * The corpus list is windowed. `work.list` answers the whole corpus in one read — the
 * daemon imposes no page size, and PRODUCT §5 P10 forbids the cockpit inventing one — so a
 * project of a thousand works used to mount a thousand cards, each with its own nested file
 * table, before the first one could be read. `VirtualList` keeps only what is near the
 * viewport in the DOM; each card renders exactly as it always did once it is mounted.
 *
 * Windowing costs the browser's own find-in-page, and pretending otherwise would be the
 * dishonest part: Ctrl/Cmd+F can only search the works the DOM currently holds. So the page
 * carries a find of its own, over the whole list rather than over the window, and says how
 * many of the corpus it is showing. The browser's shortcut is deliberately not intercepted
 * — taking a key away from the researcher to hide a trade-off is worse than the trade-off.
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
 *
 * All three screens mount their frame before the read resolves: the heading, the toolbar
 * and the page's shape survive loading, a refusal, and an object that is not there.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Button,
  EvidenceCard,
  FullPageWorkspace,
  Icon,
  Input,
  VirtualList,
  formatFileSize,
} from '@research-harness/design';
import type { EvidenceModel } from '@research-harness/design';
import type { EvidenceSummary, WorkSummary } from '../api/dto';
import type { HarnessClient } from '../api/client';
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
import { useDaemonOutage } from '../app/daemonStatus';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';
import './corpus.css';

/** About how tall one work's card is before it has been measured, in CSS pixels. */
const WORK_CARD_HEIGHT = 320;

/**
 * Whether one work answers what was typed into the page's find field.
 *
 * Every term has to match somewhere, and a term may match anywhere: an id, the title, an
 * author, the venue or the year. It only ever *hides* — the corpus is the daemon's list in
 * the daemon's order, and a find that reordered it would be the cockpit deciding what a
 * researcher should read first (PRODUCT §5 P10).
 */
export function matchesWork(work: WorkSummary, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = [work.id, work.title, work.venue ?? '', String(work.year ?? ''), ...work.authors]
    .join(' ')
    .toLowerCase();
  return terms.every((term) => haystack.includes(term));
}

export function CorpusPage() {
  const { client } = useSession();
  const { href } = useProjectPaths();
  // `work.list`: this view needs the corpus and nothing else on the navigation.
  const state = useAsync(() => client.works(), [client]);
  const [query, setQuery] = useState('');
  const outage = useDaemonOutage();

  // The last corpus the daemon actually sent.
  //
  // Silence is not an answer. A refusal is the daemon speaking and its answer replaces what
  // came before, but a daemon that has gone quiet has said nothing about the corpus — the
  // list on screen is still true of the last moment it spoke. So the list is kept and
  // labelled for what it is, rather than thrown away to show an empty page; `state.data`
  // going null on a failed re-read does not take it with it.
  const kept = useRef<WorkSummary[] | null>(null);
  if (state.data !== null) kept.current = state.data;
  const works = state.data ?? kept.current ?? [];
  const stale = outage !== null && works.length > 0;

  // The daemon came back: ask again, so the page catches up without a reload.
  const wasOffline = useRef(false);
  useEffect(() => {
    if (outage !== null) {
      wasOffline.current = true;
      return;
    }
    if (!wasOffline.current) return;
    wasOffline.current = false;
    state.reload();
  }, [outage, state]);

  const shown = useMemo(
    () => works.filter((work) => matchesWork(work, query)),
    [query, works],
  );
  const failed = state.error !== null && !stale;
  return (
    <FullPageWorkspace
      busy={state.loading}
      title="Corpus"
      description="The sources this project reads from, and the files kept for each."
      toolbar={
        works.length > 0 ? (
          <Input
            label="Find a work by title, author, venue, year or id"
            hideLabel
            size="sm"
            type="search"
            iconStart="search"
            placeholder="Title, author, venue, year or id"
            fieldClassName="rh-web-corpus__find"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        ) : (
          <></>
        )
      }
    >
      {state.loading ? (
        <Loading what="the corpus" shape="cards" />
      ) : failed ? (
        <ErrorBox error={state.error as string} retry={state.reload} />
      ) : works.length === 0 ? (
        <Empty
          description="The corpus is the set of sources this project reads from: each work, the files kept for it, and whether a file has a stored parse. A file enters it by being attached to a conversation and saved to the corpus."
          action={<Link to={href('/')}>Open the conversation to attach a source</Link>}
        >
          No works in the corpus yet
        </Empty>
      ) : (
        <div className="rh-web-corpus">
          <p className="rh-text-secondary" role="status">
            {stale
              ? `The last corpus the daemon sent: ${works.length} works. It has not answered since.`
              : query
                ? `Showing ${shown.length} of ${works.length} works.`
                : `${works.length} works.`}
          </p>
          {shown.length === 0 ? (
            <Empty
              description="The find only hides. Every work the daemon listed is still in the corpus underneath it."
              action={
                <Button size="sm" variant="secondary" onClick={() => setQuery('')}>
                  Clear the find
                </Button>
              }
            >
              No work matches this find
            </Empty>
          ) : (
            <VirtualList
              className="rh-web-corpus__list"
              label="Works in the corpus"
              items={shown}
              itemKey={(work) => work.id}
              estimatedItemHeight={WORK_CARD_HEIGHT}
              renderItem={(work) => <WorkCard work={work} client={client} href={href} />}
            />
          )}
        </div>
      )}
    </FullPageWorkspace>
  );
}

/**
 * One work in the corpus list: identity, then the files kept for it.
 *
 * Lifted out of the list body unchanged, because the list now mounts it rather than the
 * page: what a researcher sees when a card is on screen is exactly what they saw before,
 * down to the compact density the file table sits in.
 */
function WorkCard({
  work,
  client,
  href,
}: {
  work: WorkSummary;
  client: HarnessClient;
  href: (path: string) => string;
}) {
  return (
    <Panel title={work.title} action={<StatusBadge status={work.screening} />}>
      <Fields>
        <Field label="Id">
          <ObjectRef id={work.id} kind="work" to={href(`/corpus/${work.id}`)} />
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
            {/* The package's own file-size wording, so a file reads the same here
                as it does in the composer's attachment tray. */}
            <td>{formatFileSize(artifact.size_bytes)}</td>
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
  );
}

export function WorkPage() {
  const { workId = '' } = useParams();
  const { client } = useSession();
  const { href } = useProjectPaths();
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

  const work = state.data?.work ?? null;
  const evidence = state.data?.evidence ?? [];
  return (
    <FullPageWorkspace
      busy={state.loading}
      title={work ? work.title : workId}
      description={
        work
          ? `${work.id} · ${work.authors.join(', ') || 'no authors recorded'}`
          : 'One work in the corpus, with its files and what has been accepted from it.'
      }
      {...(work ? { toolbar: <StatusBadge status={work.screening} size="md" /> } : {})}
    >
      {state.loading ? (
        <Loading what={`work ${workId}`} shape="cards" />
      ) : state.error ? (
        <ErrorBox error={state.error} retry={state.reload} />
      ) : !work ? (
        <Empty
          description="No work is stored under that id in this project. It may belong to another project, or the link may have outlived it."
          action={<Link to={href('/corpus')}>Back to the corpus</Link>}
        >
          {`No work ${workId} in this corpus`}
        </Empty>
      ) : (
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
              <Empty
                flat
                description="Evidence is accepted one candidate at a time, beside the page it was read off. Nothing from this work has been through that yet."
                action={<Link to={href('/review')}>Open the review inbox</Link>}
              >
                Nothing has been accepted from this work
              </Empty>
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
      )}
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
  const { href } = useProjectPaths();
  const state = useAsync(() => client.object(evidenceId), [client, evidenceId]);

  const evidence = (state.data?.object ?? null) as Record<string, any> | null;
  const source = evidence?.source ?? {};
  const content = evidence?.content ?? {};
  const artifact = String(source.artifact ?? '');
  return (
    <FullPageWorkspace
      busy={state.loading}
      title={evidenceId}
      description="One accepted Evidence object, with the exact span it was accepted from."
      {...(evidence
        ? {
            toolbar: (
              <a
                className="rh-web-row"
                href={client.artifactBytesUrl(artifact)}
                target="_blank"
                rel="noreferrer"
              >
                <Icon name="external-link" size={14} />
                Open the source file
              </a>
            ),
          }
        : {})}
    >
      {state.loading ? (
        <Loading what={`evidence ${evidenceId}`} shape="cards" />
      ) : state.error ? (
        <ErrorBox error={state.error} retry={state.reload} />
      ) : !evidence ? (
        <Empty
          description="No accepted Evidence is stored under that id in this project. A proposal that is still in review has no Evidence id yet."
          action={<Link to={href('/review')}>Open the review inbox</Link>}
        >
          {`No evidence ${evidenceId} in this project`}
        </Empty>
      ) : (
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
                  to={href(`/corpus/${String(source.work ?? '')}`)}
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
      )}
    </FullPageWorkspace>
  );
}

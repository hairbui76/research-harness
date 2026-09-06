/**
 * The research inspector: what the conversation is currently about, beside the conversation.
 *
 * Six tabs, and none of them holds an opinion. Context is the `Context used` receipt;
 * Evidence, Claims, Review inbox, Conflicts and Stale are the same reads the full research
 * pages make (`evidence.list`, `claim.list`, `review.inbox`, `GET /overview`,
 * `state.stale`), rendered small. The counts on the tabs are the daemon's own, from
 * `overview.attention[].route` and `overview.counts`; nothing is counted here. Only the
 * open tab is mounted, so opening the inspector costs one read rather than five.
 *
 * Two-way navigation (conversation spec §2) is the point of the pane:
 *
 * - a reference in the transcript selects it here, and the header's Open button leaves for
 *   the object's full page;
 * - the object lists **every message that referenced it**, and each one selects that
 *   message back in the transcript.
 *
 * That second direction reads the loaded transcript rather than the graph, so it keeps
 * working while the projection is being rebuilt (spec §8).
 */
import { useMemo } from 'react';
import type { ReactNode } from 'react';
import {
  AsyncState,
  Badge,
  Button,
  EntityRef,
  ErrorNotice,
  ResearchInspector,
} from '@research-harness/design';
import type { EntityRefModel, InspectorSelection, InspectorTab } from '@research-harness/design';
import type { HarnessClient } from '../../api/client';
import type { ConversationMessage, OverviewReport } from '../../api/dto';
import { useSession } from '../../app/session';
import { useAsync } from '../../app/useAsync';
import { authorityOf } from '../../components/Feedback';
import { AttachmentViewer } from './attachments/AttachmentViewer';
import { useProjectPaths } from '../../app/projectPaths';
import { entityRefFor, messagesReferencing } from './mappers';
import { GraphContextPanel } from './references';
import { ReceiptPanel } from './ReceiptPanel';
import { useConversation } from './state';

export function InspectorPane() {
  const { client, overview, error: overviewError, refresh } = useSession();
  const {
    selection,
    following,
    setFollowing,
    tab,
    setTab,
    transcript,
    selectMessage,
    navigateTo,
    openRef,
  } = useConversation();

  const messages = transcript.transcript?.messages ?? [];

  const counts = useMemo<Partial<Record<InspectorTab, number>>>(
    () => tabCounts(overview),
    [overview],
  );

  const dsSelection = useMemo<InspectorSelection | undefined>(() => {
    if (!selection) return undefined;
    if (selection.kind === 'message') {
      return {
        kind: 'message',
        label: selection.messageId,
        detail: 'The turn this pane is following.',
        ref: { kind: 'message', id: selection.messageId },
      };
    }
    const ref = selection.ref;
    return {
      kind: 'reference',
      label: ref.label ? `${ref.id} — ${ref.label}` : ref.id,
      detail: `A ${ref.kind.replace(/_/g, ' ')} referenced in this conversation.`,
      ref: { kind: ref.kind, id: ref.id, ...(ref.href ? { href: ref.href } : {}) },
    };
  }, [selection]);

  const back =
    selection?.kind === 'reference' ? (
      <UsedIn
        target={selection.ref.id}
        messages={messages}
        onSelectMessage={selectMessage}
      />
    ) : null;

  return (
    <ResearchInspector
      tab={tab}
      onTabChange={setTab}
      counts={counts}
      following={following}
      onFollow={setFollowing}
      onNavigate={navigateTo}
      {...(dsSelection ? { selection: dsSelection } : {})}
      panels={{
        context: (
          <Stack>
            {back}
            {/* References and the graph (task W3). `back` is the transcript's own answer to
                "where was this used?" and keeps working while the projection rebuilds; this
                is the graph's — the provenance path to the exact artifact anchor, and the
                one-hop neighbourhood, which is where cross-session `mentioned_in` messages
                appear, exactly as the graph returns them under this session's egress class
                (graph spec §8; nothing is filtered on this side). */}
            <GraphContextPanel enabled={tab === 'context'} />
            {/* Attachments (task W2): the fourth place `Save to corpus` is offered. */}
            <SelectedAttachment />
            <ReceiptPanel />
          </Stack>
        ),
        evidence: (
          <Stack>
            {back}
            <EvidenceTab client={client} onOpen={openRef} />
          </Stack>
        ),
        claims: (
          <Stack>
            {back}
            <ClaimsTab client={client} onOpen={openRef} />
          </Stack>
        ),
        review: <ReviewTab client={client} onOpen={navigateTo} />,
        conflicts: (
          <ConflictsTab overview={overview} error={overviewError} retry={refresh} />
        ),
        stale: <StaleTab client={client} onOpen={openRef} />,
      }}
    />
  );
}

function Stack({ children }: { children: ReactNode }) {
  return <div className="rh-web-stack rh-web-stack--tight">{children}</div>;
}

/* -- attachments (task W2) ------------------------------------------------ */

/**
 * The session attachment the inspector is following, with its corpus action.
 *
 * `Save to corpus` is offered from the composer's tray, the transcript, the viewer and
 * here, because a file the researcher has just opened in the inspector is exactly where
 * they decide it belongs in the corpus (attachments design §4). The flow is the workspace's
 * own, so a save started in one place is finished and reported in all four.
 */
function SelectedAttachment() {
  const { selection, attachments, renderAttachmentPage, openRef } = useConversation();
  if (selection?.kind !== 'reference' || selection.ref.kind !== 'attachment') return null;
  const attachment = attachments.modelOf(selection.ref.id);
  if (attachment === null) {
    return (
      <AsyncState
        kind="empty"
        compact
        title={`${selection.ref.id} is not in the open session`}
        description="Open the session it belongs to to preview or save it."
      />
    );
  }
  return (
    <section className="rh-web-stack rh-web-stack--tight">
      <h3 className="rh-text-h4">{attachment.name}</h3>
      <AttachmentViewer
        attachment={attachment}
        renderPage={renderAttachmentPage}
        save={attachments.save}
        onOpenRef={openRef}
        size="sm"
      />
    </section>
  );
}

/** The daemon's counts, keyed by tab. Nothing here counts anything (PRODUCT §5 P10). */
function tabCounts(overview: OverviewReport | null): Partial<Record<InspectorTab, number>> {
  if (!overview) return {};
  const routeCount = (route: string): number | undefined =>
    overview.attention.find((group) => group.route === route)?.count;
  const review = routeCount('/review');
  const stale = routeCount('/stale');
  const counts = overview.counts;
  return {
    ...(counts ? { evidence: counts.accepted_evidence, claims: counts.claims } : {}),
    conflicts: overview.conflicts.length,
    ...(review === undefined ? {} : { review }),
    ...(stale === undefined ? {} : { stale }),
  };
}

/** The other half of the two-way link: the messages a reference was used in. */
function UsedIn({
  target,
  messages,
  onSelectMessage,
}: {
  target: string;
  messages: readonly ConversationMessage[];
  onSelectMessage: (messageId: string) => void;
}) {
  const used = useMemo(() => messagesReferencing(messages, target), [messages, target]);
  return (
    <section className="rh-web-stack rh-web-stack--tight">
      <h3 className="rh-text-h4">{`Where ${target} was used`}</h3>
      {used.length === 0 ? (
        <AsyncState
          kind="empty"
          compact
          title="Not referenced in the loaded transcript"
          description="Earlier pages of a long session may still reference it."
        />
      ) : (
        <ul className="rh-web-list rh-web-list--tight">
          {used.map((message) => (
            <li key={message.id}>
              <Button
                size="sm"
                variant="ghost"
                iconStart="message-square"
                onClick={() => onSelectMessage(message.id)}
              >
                {`${message.id} · ${message.role}`}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

interface TabProps {
  client: HarnessClient;
  onOpen: (entity: EntityRefModel) => void;
}

function EvidenceTab({ client, onOpen }: TabProps) {
  const { href } = useProjectPaths();
  const state = useAsync(() => client.evidence(), [client]);
  if (state.loading) return <AsyncState kind="loading" compact title="Reading accepted evidence" />;
  if (state.error) return <Failed error={state.error} retry={state.reload} />;
  const evidence = state.data ?? [];
  if (evidence.length === 0) {
    return <AsyncState kind="empty" compact title="No accepted evidence yet" />;
  }
  return (
    <ul className="rh-web-list rh-web-list--tight">
      {evidence.slice(0, 40).map((item) => (
        <li key={item.id}>
          <EntityRef
            size="sm"
            entity={entityRefFor(item.id, {
              label: item.exact_text,
              authority: authorityOf(item.status, item.stale === 'stale'),
              href,
            })}
            onOpen={onOpen}
          />
        </li>
      ))}
    </ul>
  );
}

function ClaimsTab({ client, onOpen }: TabProps) {
  const { href } = useProjectPaths();
  const state = useAsync(() => client.claims(), [client]);
  if (state.loading) return <AsyncState kind="loading" compact title="Reading claims" />;
  if (state.error) return <Failed error={state.error} retry={state.reload} />;
  const claims = state.data ?? [];
  if (claims.length === 0) return <AsyncState kind="empty" compact title="No claims yet" />;
  return (
    <ul className="rh-web-list rh-web-list--tight">
      {claims.slice(0, 40).map((claim) => (
        <li key={claim.id}>
          <EntityRef
            size="sm"
            entity={entityRefFor(claim.id, {
              label: claim.statement,
              authority: authorityOf(claim.status, claim.stale === 'stale'),
              href,
            })}
            onOpen={onOpen}
          />
        </li>
      ))}
    </ul>
  );
}

function ReviewTab({
  client,
  onOpen,
}: {
  client: HarnessClient;
  onOpen: (ref: { kind: string; id: string; href?: string }) => void;
}) {
  const { href } = useProjectPaths();
  const state = useAsync(() => client.reviewInbox(), [client]);
  if (state.loading) return <AsyncState kind="loading" compact title="Reading the review queue" />;
  if (state.error) return <Failed error={state.error} retry={state.reload} />;
  const items = state.data?.items ?? [];
  if (items.length === 0) return <AsyncState kind="empty" compact title="The queue is empty" />;
  return (
    <ul className="rh-web-list rh-web-list--tight">
      {items.slice(0, 40).map((item) => (
        <li key={item.candidate_id}>
          <Button
            size="sm"
            variant="ghost"
            iconStart="inbox"
            onClick={() =>
              onOpen({
                kind: 'candidate',
                id: item.candidate_id,
                href: href(`/review/${item.candidate_id}`),
              })
            }
          >
            {`${item.field} · ${item.work}`}
          </Button>{' '}
          <Badge tone="neutral" size="sm">
            {item.category.replace(/_/g, ' ')}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

/**
 * The open conflicts, and — unlike the other five tabs — the failure of the read behind
 * them.
 *
 * This tab does not fetch: it renders what `GET /overview` already returned. When that
 * read failed there are no conflicts to show, and saying "No open conflicts" would report
 * agreement the daemon never claimed. So the refusal is shown instead, with the same retry
 * the rest of the cockpit offers.
 */
function ConflictsTab({
  overview,
  error,
  retry,
}: {
  overview: OverviewReport | null;
  error: string | null;
  retry: () => void;
}) {
  if (error) return <Failed error={error} retry={retry} />;
  const conflicts = overview?.conflicts ?? [];
  if (conflicts.length === 0) return <AsyncState kind="empty" compact title="No open conflicts" />;
  return (
    <ul className="rh-web-list rh-web-list--tight">
      {conflicts.map((conflict) => (
        <li key={conflict.conflict_id}>
          <Badge status="contested" size="sm" /> {conflict.subject}
          <p className="rh-text-secondary">{conflict.summary}</p>
        </li>
      ))}
    </ul>
  );
}

function StaleTab({ client, onOpen }: TabProps) {
  const { href } = useProjectPaths();
  const state = useAsync(() => client.stale(50), [client]);
  if (state.loading) return <AsyncState kind="loading" compact title="Reading the stale set" />;
  if (state.error) return <Failed error={state.error} retry={state.reload} />;
  const marks = state.data?.marks ?? [];
  if (marks.length === 0) return <AsyncState kind="empty" compact title="Nothing is stale" />;
  return (
    <ul className="rh-web-list rh-web-list--tight">
      {marks.map((mark) => (
        <li key={`${mark.object_id}:${mark.source_change}`}>
          <EntityRef
            size="sm"
            entity={entityRefFor(mark.object_id, { authority: 'stale', href })}
            onOpen={onOpen}
          />{' '}
          <span className="rh-text-secondary">{mark.reason}</span>
        </li>
      ))}
    </ul>
  );
}

function Failed({ error, retry }: { error: string; retry: () => void }) {
  return (
    <ErrorNotice
      kind="retryable"
      title="The daemon could not answer"
      description={error}
      safety={{ draft: 'safe', source: 'safe' }}
      actions={[{ label: 'Try again', onClick: retry, iconStart: 'refresh-cw' }]}
    />
  );
}

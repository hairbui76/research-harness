/**
 * `Context used`: what the model was shown, what it was not, and why.
 *
 * The panel serves both halves of conversation spec §5. A *recorded* receipt is read with
 * `context.get` from the `CP####` the message carries — the receipt has to be inspectable
 * after the answer, or a researcher cannot explain what the model saw. A *draft* receipt is
 * `context.preview` with `persist: false`: the same view, assembled and deliberately not
 * written, so previewing a draft leaves nothing behind.
 *
 * Discrepancies get their own component. When remembered conversation contradicts an
 * accepted Claim or Decision, the assembler has already resolved it — accepted state was
 * sent — and `ConflictNotice` exists so the researcher can see the disagreement rather than
 * only its outcome (spec §4).
 */
import { useEffect, useState } from 'react';
import { AsyncState, Badge, ConflictNotice, ContextReceipt, ErrorNotice } from '@research-harness/design';
import type { EntityRefModel } from '@research-harness/design';
import { useProjectPaths } from '../../app/projectPaths';
import { useSession } from '../../app/session';
import type { ContextPackView } from '../../api/dto';
import { entityRefFor, toContextReceiptModel } from './mappers';
import { useConversation } from './state';
import type { ReceiptSource } from './state';

export function ReceiptPanel() {
  const { client } = useSession();
  const { href } = useProjectPaths();
  const { receipt, sessions, openRef } = useConversation();
  const sessionId = sessions.activeId;
  const [view, setView] = useState<ContextPackView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!receipt || !sessionId) {
      setView(null);
      setError(null);
      return;
    }
    let live = true;
    setLoading(true);
    read(client, sessionId, receipt)
      .then((answer) => {
        if (!live) return;
        setView(answer);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setView(null);
        setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [client, receipt, sessionId]);

  if (!receipt) {
    return (
      <AsyncState
        kind="empty"
        compact
        hideKind
        title="No receipt open"
        description="Open Context used on an answer, or preview the context this draft would send."
      />
    );
  }
  if (loading && view === null) {
    return <AsyncState kind="loading" compact title="Reading the context receipt" />;
  }
  if (error !== null) {
    // `context.get` arrives with the P18 backend; until then this is the honest state.
    return (
      <ErrorNotice
        kind="retryable"
        title="Receipt unavailable"
        description={error}
        safety={{ draft: 'safe', source: 'safe' }}
        detail={receipt.kind === 'recorded' ? receipt.packId : 'context.preview'}
      />
    );
  }
  if (view === null) return <AsyncState kind="empty" compact hideKind title="No receipt open" />;

  const onOpen = (entity: EntityRefModel): void => openRef(entity);

  return (
    <div className="rh-web-stack rh-web-stack--tight">
      {view.pack.egress === 'none' ? (
        <p className="rh-text-secondary">
          <Badge tone="neutral" icon="hard-drive" size="sm">
            Not sent
          </Badge>{' '}
          Assembled for this draft and not sent to any model.
        </p>
      ) : null}

      <ContextReceipt receipt={toContextReceiptModel(view, href)} onOpenRef={onOpen} />

      {view.unresolved.length > 0 ? (
        <ErrorNotice
          kind="partial"
          title={`${view.unresolved.length} reference${
            view.unresolved.length === 1 ? '' : 's'
          } did not resolve`}
          description={view.unresolved.join(', ')}
          safety={{ draft: 'safe' }}
        />
      ) : null}

      {view.discrepancies.map((discrepancy, index) => (
        <ConflictNotice
          key={`${discrepancy.accepted}-${index}`}
          conflict={{
            accepted: {
              ref: entityRefFor(discrepancy.accepted, { authority: 'accepted', href }),
              excerpt: discrepancy.detail,
            },
            chat: {
              ref: entityRefFor(discrepancy.message, {
                authority: 'private',
                session: sessionId,
                href,
              }),
              excerpt: discrepancy.message,
            },
            explanation:
              'Accepted scientific state outranks remembered conversation, so the accepted ' +
              'object was sent and this message was not.',
          }}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}

function read(
  client: ReturnType<typeof useSession>['client'],
  session: string,
  source: ReceiptSource,
): Promise<ContextPackView> {
  if (source.kind === 'recorded') return client.getContext(session, source.packId);
  return client.previewContext({
    session,
    text: source.text,
    ...(source.references.length > 0 ? { references: source.references } : {}),
    ...(source.model ? { model: source.model } : {}),
    // A preview writes no pack: inspecting a draft must not leave a receipt behind.
    persist: false,
  });
}

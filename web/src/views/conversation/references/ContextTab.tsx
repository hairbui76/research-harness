/**
 * The graph half of the inspector's Context tab.
 *
 * W1's Context tab answers "what was this answer shown?" — the `Context used` receipt — and
 * "which messages used this object?", both read off the loaded transcript so they keep
 * working while the projection is rebuilding. This adds the third question, which only the
 * graph can answer: **what is this object, and what is it joined to across the whole
 * project?**
 *
 * The two directions of conversation spec §2 meet here:
 *
 * - a reference selected in a message shows its provenance and its neighbourhood, and the
 *   `Mentioned in messages` group lists the messages that referenced it — *including
 *   messages in other sessions*, which the transcript-only view cannot see, and only ever
 *   the ones the graph returns under this session's egress class;
 * - a message selected in the transcript shows what that message mentions, so the same
 *   pane walks from the turn to the objects and back.
 *
 * Everything is a read. Nothing on this tab writes, promotes or accepts anything.
 */
import { useCallback } from 'react';
import { AsyncState } from '@research-harness/design';
import type { EntityRefModel } from '@research-harness/design';
import { useSession } from '../../../app/session';
import { entityRefFor } from '../mappers';
import { useConversation } from '../state';
import { ReferenceDetails } from './ReferenceDetails';

export interface GraphContextPanelProps {
  /** False while the Context tab is not the one on screen; nothing is read. */
  enabled?: boolean;
}

/**
 * What the graph says about the current selection.
 *
 * Mounted inside the Context tab beside the receipt. With nothing selected it renders a
 * single empty row rather than a heading with nothing under it.
 */
export function GraphContextPanel({ enabled = true }: GraphContextPanelProps) {
  const { client } = useSession();
  const { selection, sessions, selectMessage, selectReference, openAnchor } = useConversation();
  const session = sessions.activeId;
  const visibility = sessions.active?.visibility ?? null;

  /**
   * Following a neighbour keeps the researcher in this pane.
   *
   * `openRef` is the transcript's door into the inspector and takes a Claim to the Claims
   * tab, which is the right answer for a chip in a message and the wrong one here: walking
   * Claim → Evidence → anchor and back is one continuous movement, and being thrown to a
   * list of every claim in the project halfway through it is not a walk. So a step inside
   * the graph pane only changes what is followed, never which tab is open.
   */
  const follow = useCallback(
    (entity: EntityRefModel) => {
      if (entity.kind === 'message') selectMessage(entity.id);
      else selectReference(entity);
    },
    [selectMessage, selectReference],
  );

  if (!selection) {
    return (
      <AsyncState
        kind="empty"
        compact
        title="Nothing selected"
        description="Open a reference or inspect a message to see what the graph joins it to."
      />
    );
  }

  // A message is an object in the graph like any other: its `mentioned_in` edges are what
  // it referenced, so selecting a turn shows the turn's own research neighbourhood.
  const entity =
    selection.kind === 'message'
      ? entityRefFor(selection.messageId, { session })
      : selection.ref;

  return (
    <ReferenceDetails
      client={client}
      entity={entity}
      session={session}
      visibility={visibility}
      onOpen={follow}
      onOpenAnchor={openAnchor}
      enabled={enabled}
    />
  );
}

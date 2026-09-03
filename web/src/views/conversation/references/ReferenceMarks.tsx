/**
 * The references in this draft that are not plainly usable, marked before it is sent.
 *
 * Conversation spec §7: *broken, stale, private, or unresolved references are visibly
 * marked before sending*. The Design System's `Composer` draws each token as a `Tag` — an
 * id and a title, removable — which is right for the ninety-nine per cent case and cannot
 * carry a resolution state; `EntityRef` can, and renders it as an icon **and** a word, so
 * nothing here depends on noticing a colour.
 *
 * So this is a strip above the composer listing only the tokens the resolver objected to,
 * each with the daemon's own sentence for why. Three deliberate properties:
 *
 * - **It never blocks the send.** No control here removes a token or disables anything.
 *   A researcher may want to write about a reference precisely *because* it is stale.
 * - **It says nothing when there is nothing to say.** A draft whose references all resolve
 *   renders no strip at all.
 * - **The words are the daemon's.** "E0500 anchor text_hash no longer matches A0017-1" is
 *   the resolver's sentence, printed as it came.
 */
import { EntityRef } from '@research-harness/design';
import type { EntityRefModel } from '@research-harness/design';
import type { ResolvedReference } from './useResolveReferences';

export interface ReferenceMarksProps {
  /** Every token, marked. Only the ones that are not `resolved` are listed. */
  tokens: readonly EntityRefModel[];
  /** What the resolver said about each of them. */
  flagged: readonly ResolvedReference[];
  /** Open one in the inspector. */
  onOpen?: (entity: EntityRefModel) => void;
}

export function ReferenceMarks({ tokens, flagged, onOpen }: ReferenceMarksProps) {
  if (flagged.length === 0) return null;
  const byId = new Map(tokens.map((token) => [token.id, token]));
  return (
    <section
      className="rh-web-stack rh-web-stack--tight rh-web-graph__marks"
      aria-label="References to check before sending"
    >
      <p className="rh-web-composer__note rh-text-secondary">
        These references are still sendable. They are marked because the resolver could not
        confirm them against the project files:
      </p>
      <ul className="rh-web-list rh-web-list--tight">
        {flagged.map((answer) => {
          const token = byId.get(answer.id);
          return (
            <li key={answer.id} className="rh-web-stack rh-web-stack--tight">
              <EntityRef
                size="sm"
                describe={false}
                entity={token ?? { id: answer.id, kind: 'block', resolution: answer.resolution }}
                {...(onOpen ? { onOpen } : {})}
              />
              {answer.problems.map((problem) => (
                <p key={problem} className="rh-web-composer__note rh-text-secondary">
                  {problem}
                </p>
              ))}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

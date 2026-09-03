/**
 * A deep link that was not followed, explaining itself.
 *
 * `rh://` links in a message are resolved rather than navigated (`deepLinks.ts`), and the
 * interesting case is the one where the answer is no. Plan §0.1 requires the resolver to
 * check the project, the object's existence, authority, privacy and anchor freshness before
 * anything opens; this is what the researcher sees when one of those says no.
 *
 * Two rules for the wording. The sentences are the **daemon's**, printed verbatim — a
 * client paraphrase of "why not" is a client opinion about scientific state. And the notice
 * says what is safe: nothing was opened, nothing was sent, and the draft is untouched.
 *
 * "Open anyway" appears only when the object exists and this cockpit has a screen for it.
 * A stale anchor or a private target is still something a researcher may look at, once they
 * have read why it was flagged; a link into a project this is not has nowhere to go at all.
 */
import { ErrorNotice } from '@research-harness/design';
import type { DeepLinkProblem } from './deepLinks';

export interface DeepLinkNoticeProps {
  problem: DeepLinkProblem | null;
  onDismiss: () => void;
  onOpenAnyway: () => void;
}

export function DeepLinkNotice({ problem, onDismiss, onOpenAnyway }: DeepLinkNoticeProps) {
  if (problem === null) return null;
  const exists = problem.view?.exists ?? false;
  return (
    <ErrorNotice
      className="rh-web-graph__deep-link"
      kind={exists ? 'stale' : 'blocked'}
      title={`${problem.link.href} was not opened`}
      description={problem.problems.join(' ')}
      safety={{
        draft: 'safe',
        source: 'safe',
        note: 'Nothing was opened and nothing was sent.',
      }}
      actions={
        problem.href === null
          ? []
          : [
              {
                label: 'Open anyway',
                onClick: onOpenAnyway,
                iconStart: 'external-link',
                variant: 'secondary',
              },
            ]
      }
      onDismiss={onDismiss}
    />
  );
}

/**
 * A model rewrite of one span, staged as a candidate and applied only on purpose.
 *
 * LaTeX spec §4 and §10.5: model output is always a candidate diff, never a silent source
 * rewrite. `manuscript.suggest` stages one under `.research/staging` and leaves the file
 * byte-identical; `manuscript.apply_suggestion` is the only path from that candidate into
 * the manuscript, it is human-only, and it takes the hash of the snapshot the reviewer has
 * open so a candidate reviewed against text somebody has since changed is refused rather
 * than merged.
 *
 * Nothing here decides whether a candidate may be applied. `audit_status`,
 * `blocked_reason` and `protected_violations` are the daemon's verdict; this hook carries
 * them to the diff, and the diff disables Apply and prints the reason.
 */
import { useCallback, useState } from 'react';
import type { HarnessClient } from '../../api/client';
import type { AppliedSuggestion, SuggestionCandidate, SuggestionRequest } from '../../api/dto';

export interface SuggestionState {
  candidate: SuggestionCandidate | null;
  suggesting: boolean;
  applying: boolean;
  error: string | null;
  suggest: (request: SuggestionRequest) => Promise<SuggestionCandidate | null>;
  /** Applies the open candidate against `expectedHash`. Null when the daemon refused. */
  apply: (expectedHash?: string | null) => Promise<AppliedSuggestion | null>;
  /** Dismiss the candidate. It stays staged on disk; nothing is written to the source. */
  reject: () => void;
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export function useSuggestion(client: HarnessClient): SuggestionState {
  const [candidate, setCandidate] = useState<SuggestionCandidate | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const suggest = useCallback(
    async (request: SuggestionRequest): Promise<SuggestionCandidate | null> => {
      setSuggesting(true);
      setError(null);
      try {
        const staged = await client.manuscriptSuggest(request);
        setCandidate(staged);
        return staged;
      } catch (cause) {
        setError(messageOf(cause));
        return null;
      } finally {
        setSuggesting(false);
      }
    },
    [client],
  );

  const apply = useCallback(
    async (expectedHash?: string | null): Promise<AppliedSuggestion | null> => {
      if (!candidate) return null;
      setApplying(true);
      setError(null);
      try {
        const applied = await client.manuscriptApplySuggestion(candidate.candidate_id, expectedHash);
        setCandidate(null);
        return applied;
      } catch (cause) {
        setError(messageOf(cause));
        return null;
      } finally {
        setApplying(false);
      }
    },
    [candidate, client],
  );

  const reject = useCallback(() => {
    setCandidate(null);
    setError(null);
  }, []);

  return { candidate, suggesting, applying, error, suggest, apply, reject };
}

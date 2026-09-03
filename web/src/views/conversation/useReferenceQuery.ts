/**
 * `@` completion, behind one seam.
 *
 * Conversation spec §7 says typing `@` searches *stable research references* and that the
 * selected reference becomes a structured token rather than text that looks like an id.
 * Which index answers the search is not part of that promise, so it is a parameter:
 * `ReferenceProvider` is the whole contract, and `useReferenceQuery` knows nothing else.
 *
 * Two providers exist by design.
 *
 * - `indexReferenceProvider` (here) completes over `state.index` and `evidence.list` — the
 *   same listings the research pages read. It is prefix-and-substring matching over ids
 *   and titles, cached for the life of the client, and it works with no projection at all.
 * - `graph.autocomplete` (task W3) replaces it with the ResearchGraph's own completion:
 *   fuzzy titles, neighbours, privacy filtering, and a real `resolution` per hit.
 *
 * The swap is `<ConversationRoute referenceProvider={graphReferenceProvider(client)} />`
 * and nothing else: the picker, the composer and the token round-trip are unchanged,
 * because they already only ever see `EntityRefModel`s.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { EntityRefModel } from '@research-harness/design';
import type { HarnessClient } from '../../api/client';
import { authorityOf } from '../../components/Feedback';
import { entityRefFor } from './mappers';

/** How many rows the picker is offered. Beyond this, typing more is the better answer. */
const LIMIT = 12;

export interface ReferenceProvider {
  /** A stable name, so a test and a report can say which index answered. */
  readonly id: string;
  /**
   * Matches for one query. `query` is what follows the `@`, and may be empty — an empty
   * query offers the most likely references rather than nothing.
   */
  search(query: string): Promise<EntityRefModel[]>;
}

interface Candidate {
  ref: EntityRefModel;
  /** The lower-cased text the query is matched against: the id and the title. */
  haystack: string;
}

/**
 * Completion over the listings the cockpit already reads.
 *
 * Everything here came out of the daemon's own index, so each hit is `resolved`: the
 * object exists and this window may read it. A reference whose *authority* matters —
 * stale, private, contested — carries the label the listing reported, never one derived
 * here.
 */
export function indexReferenceProvider(client: HarnessClient): ReferenceProvider {
  let loaded: Promise<Candidate[]> | null = null;

  const load = async (): Promise<Candidate[]> => {
    const [index, evidence] = await Promise.all([
      client.index(),
      // Accepted evidence is not in `state.index`; it is a list of its own, and it is the
      // reference a researcher reaches for most often.
      client.evidence().catch(() => []),
    ]);
    const candidates: Candidate[] = [];
    const add = (id: string, label: string, authority?: EntityRefModel['authority']): void => {
      candidates.push({
        ref: entityRefFor(id, { label, ...(authority ? { authority } : {}) }),
        haystack: `${id} ${label}`.toLowerCase(),
      });
    };
    for (const work of index.works) add(work.id, work.title);
    for (const claim of index.claims) {
      add(claim.id, claim.statement, authorityOf(claim.status, claim.stale === 'stale'));
    }
    for (const question of index.questions) add(question.id, question.question);
    for (const decision of index.decisions) add(decision.id, decision.title ?? decision.id);
    for (const item of evidence) {
      add(item.id, item.exact_text, authorityOf(item.status, item.stale === 'stale'));
    }
    return candidates;
  };

  return {
    id: 'state.index',
    async search(query: string): Promise<EntityRefModel[]> {
      loaded ??= load();
      const candidates = await loaded;
      const needle = query.trim().toLowerCase();
      if (needle.length === 0) return candidates.slice(0, LIMIT).map((entry) => entry.ref);
      // An id typed in full should be the first row, so a prefix beats a substring.
      const prefix: EntityRefModel[] = [];
      const contains: EntityRefModel[] = [];
      for (const entry of candidates) {
        if (entry.ref.id.toLowerCase().startsWith(needle)) prefix.push(entry.ref);
        else if (entry.haystack.includes(needle)) contains.push(entry.ref);
      }
      return [...prefix, ...contains].slice(0, LIMIT);
    },
  };
}

export interface ReferenceQueryApi {
  results: EntityRefModel[];
  loading: boolean;
  /** Report what has been typed after the `@`. The composer calls this. */
  search: (query: string) => void;
}

/** Runs `provider.search` for whatever the composer reports, newest query wins. */
export function useReferenceQuery(provider: ReferenceProvider): ReferenceQueryApi {
  const [results, setResults] = useState<EntityRefModel[]>([]);
  const [loading, setLoading] = useState(false);
  const latest = useRef(0);
  const live = useRef(true);

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  const search = useCallback(
    (query: string) => {
      const ticket = ++latest.current;
      setLoading(true);
      provider
        .search(query)
        .then((found) => {
          // A slower earlier query must not overwrite a faster later one.
          if (!live.current || ticket !== latest.current) return;
          setResults(found);
        })
        .catch(() => {
          if (live.current && ticket === latest.current) setResults([]);
        })
        .finally(() => {
          if (live.current && ticket === latest.current) setLoading(false);
        });
    },
    [provider],
  );

  return { results, loading, search };
}

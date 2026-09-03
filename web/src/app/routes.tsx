/**
 * One route table, and the research navigation derived from it.
 *
 * The rail and the router read the same list, so a screen cannot appear in one and not
 * the other. `NAVIGATION` carries the `RailItem` shape the Design System's `ProjectRail`
 * takes (plan §0.6): a stable id, the icon, and the route the daemon reports counts
 * against in `overview.attention[].route`.
 *
 * ── For W1 ────────────────────────────────────────────────────────────────────────────
 * Today `/` renders the Overview, and `/overview` renders it too, so the conversation
 * route can take the root without moving anything. Mounting the conversation workspace is
 * two one-line edits and nothing else:
 *
 *   1. `const HOME = <ConversationPage />;` below;
 *   2. `export const OVERVIEW_PATH = '/overview';` below.
 *
 * The rail entry for Overview already points at `OVERVIEW_PATH`, `/overview` is already
 * mounted, and every other route keeps its path. Add the conversation's own rail entry to
 * `NAVIGATION` (icon `messages-square`) and the session list to `ProjectRail`'s
 * `sessionList` slot in `Layout.tsx`.
 */
import type { ReactElement } from 'react';
import { Route, Routes } from 'react-router-dom';
import type { IconName } from '@research-harness/design';
import { Layout } from './Layout';
import { ClaimDetailPage, ClaimsPage } from '../views/Claims';
import { ConflictsPage } from '../views/Conflicts';
import { CorpusPage, EvidencePage, WorkPage } from '../views/Corpus';
import { EvidenceReviewPage } from '../views/EvidenceReview';
import { ManuscriptPage } from '../views/Manuscript';
import { OverviewPage } from '../views/Overview';
import { QuestionsPage } from '../views/Questions';
import { ReviewInboxPage } from '../views/ReviewInbox';
import { StalePage } from '../views/Stale';
import { SynthesisPage } from '../views/Synthesis';
import { TaxonomyPage } from '../views/Taxonomy';

/** Where the Overview lives. `'/'` today; `'/overview'` once W1 takes the root. */
export const OVERVIEW_PATH = '/';

/** What `/` renders. `<ConversationPage />` once W1 takes the root. */
const HOME: ReactElement = <OverviewPage />;

export interface NavigationEntry {
  /** Stable id; also the `RailItem` id. */
  id: string;
  label: string;
  to: string;
  icon: IconName;
  /** `NavLink`-style exact matching, for the route that is a prefix of every other. */
  end?: boolean;
  /**
   * Extra paths this entry is the active one for. Only the Overview has one, because `/`
   * and `/overview` both render it today; W1 deletes it when `OVERVIEW_PATH` moves.
   */
  alsoMatches?: readonly string[];
}

/** The research navigation of PRODUCT §26, in the order the rail lists it. */
export const NAVIGATION: NavigationEntry[] = [
  {
    id: 'overview',
    label: 'Overview',
    to: OVERVIEW_PATH,
    icon: 'microscope',
    end: true,
    alsoMatches: ['/overview'],
  },
  { id: 'review', label: 'Review inbox', to: '/review', icon: 'inbox' },
  { id: 'conflicts', label: 'Conflicts', to: '/conflicts', icon: 'alert-triangle' },
  { id: 'stale', label: 'Stale', to: '/stale', icon: 'clock' },
  { id: 'corpus', label: 'Corpus', to: '/corpus', icon: 'library' },
  { id: 'claims', label: 'Claims', to: '/claims', icon: 'scale' },
  { id: 'questions', label: 'Questions', to: '/questions', icon: 'circle-help' },
  { id: 'synthesis', label: 'Synthesis', to: '/synthesis', icon: 'layers' },
  { id: 'taxonomy', label: 'Taxonomy', to: '/taxonomy', icon: 'git-branch' },
  { id: 'manuscript', label: 'Manuscript', to: '/manuscript', icon: 'file-code' },
];

/** The cockpit's routes: one per navigation entry, plus the detail screens. */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={HOME} />
        <Route path="overview" element={<OverviewPage />} />
        <Route path="review" element={<ReviewInboxPage />} />
        <Route path="review/:candidateId" element={<EvidenceReviewPage />} />
        <Route path="conflicts" element={<ConflictsPage />} />
        <Route path="stale" element={<StalePage />} />
        <Route path="corpus" element={<CorpusPage />} />
        <Route path="corpus/:workId" element={<WorkPage />} />
        <Route path="evidence/:evidenceId" element={<EvidencePage />} />
        <Route path="claims" element={<ClaimsPage />} />
        <Route path="claims/:claimId" element={<ClaimDetailPage />} />
        <Route path="questions" element={<QuestionsPage />} />
        <Route path="synthesis" element={<SynthesisPage />} />
        <Route path="taxonomy" element={<TaxonomyPage />} />
        <Route path="manuscript" element={<ManuscriptPage />} />
        <Route path="*" element={HOME} />
      </Route>
    </Routes>
  );
}

/**
 * One route table, and the research navigation derived from it.
 *
 * The rail and the router read the same list, so a screen cannot appear in one and not
 * the other. `NAVIGATION` carries the `RailItem` shape the Design System's `ProjectRail`
 * takes (plan §0.6): a stable id, the icon, and the route the daemon reports counts
 * against in `overview.attention[].route`.
 *
 * `/` is the conversation workspace and `/overview` is the Overview. The conversation
 * carries its session in the query — `/?session=CS0001`, optionally `&message=M0042` — so
 * the root stays one route, a conversation is linkable and bookmarkable, and the deep link
 * `rh://session/CS0001?message=M0042` of plan §0.1 has somewhere to land. Every other
 * route kept the path it had.
 */
import type { ReactElement } from 'react';
import { Route, Routes } from 'react-router-dom';
import type { IconName } from '@research-harness/design';
import { Layout } from './Layout';
import { ClaimDetailPage, ClaimsPage } from '../views/Claims';
import { ConversationPage } from '../views/conversation/ConversationRoute';
import { ConflictsPage } from '../views/Conflicts';
import { CorpusPage, EvidencePage, WorkPage } from '../views/Corpus';
import { EvidenceReviewPage } from '../views/EvidenceReview';
import { ManuscriptPage } from '../views/manuscript/ManuscriptWorkspace';
import { OverviewPage } from '../views/Overview';
import { QuestionsPage } from '../views/Questions';
import { ReviewInboxPage } from '../views/ReviewInbox';
import { StalePage } from '../views/Stale';
import { SynthesisPage } from '../views/Synthesis';
import { TaxonomyPage } from '../views/Taxonomy';

/** Where the Overview lives, now that the conversation workspace has the root. */
export const OVERVIEW_PATH = '/overview';

/** What `/` renders: the conversation workspace (`?session=CS0001`). */
const HOME: ReactElement = <ConversationPage />;

export interface NavigationEntry {
  /** Stable id; also the `RailItem` id. */
  id: string;
  label: string;
  to: string;
  icon: IconName;
  /** `NavLink`-style exact matching, for the route that is a prefix of every other. */
  end?: boolean;
  /** Extra paths this entry is the active one for. */
  alsoMatches?: readonly string[];
}

/** The research navigation of PRODUCT §26, in the order the rail lists it. */
export const NAVIGATION: NavigationEntry[] = [
  // The conversation is `/` and matches only `/`: the session travels in the query, so
  // `/?session=CS0001` is the same screen and `location.pathname` is still exactly `/`.
  { id: 'conversation', label: 'Conversation', to: '/', icon: 'messages-square', end: true },
  { id: 'overview', label: 'Overview', to: OVERVIEW_PATH, icon: 'microscope', end: true },
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
        {/* An unknown path lands on "what needs attention" rather than on an inert
            conversation: the root is a session, and a mistyped URL names none. */}
        <Route path="*" element={<OverviewPage />} />
      </Route>
    </Routes>
  );
}

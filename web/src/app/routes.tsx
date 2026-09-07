/**
 * One route table, and the research navigation derived from it.
 *
 * The rail and the router read the same list, so a screen cannot appear in one and not
 * the other. `NAVIGATION` carries the `RailItem` shape the Design System's `ProjectRail`
 * takes (plan §0.6): a stable id, the icon, and the route the daemon reports counts
 * against in `overview.attention[].route`.
 *
 * `/source/:artifactId` is not on the navigation: it is where `rh://artifact/…?page=&block=`
 * deep links land, and it is reached from a reference rather than from the rail.
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
import { projectHref } from './projectPaths';
import { ClaimDetailPage, ClaimsPage } from '../views/Claims';
import { ConversationPage } from '../views/conversation/ConversationRoute';
import { ArtifactSourcePage } from '../views/conversation/references';
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
  /**
   * The rail heading this entry is listed under (roadmap 3L, option A).
   *
   * The rail and the palette both draw a group as a run of consecutive entries naming it,
   * so this table's order *is* the grouping; an entry without one stands on its own.
   */
  group?: string;
  /** `NavLink`-style exact matching, for the route that is a prefix of every other. */
  end?: boolean;
  /** Extra paths this entry is the active one for. */
  alsoMatches?: readonly string[];
}

/**
 * The research navigation of PRODUCT §26, in the order the rail lists it.
 *
 * Eleven destinations under three headings — the flow of a session, from what is waiting
 * through what the project holds to what it produces (roadmap 3L, option A of
 * `docs/plans/2026-09-07-rail-grouping-proposal.md`). Conversation and Overview carry no
 * group: they are the ways in, not a category. Every label, route, icon, count and `end`
 * flag is the one that shipped; only Taxonomy and Synthesis changed places, because a group
 * is a run of consecutive entries and Taxonomy is part of the record while Synthesis is an
 * output.
 */
export const NAVIGATION: NavigationEntry[] = [
  // The conversation is `/` and matches only `/`: the session travels in the query, so
  // `/?session=CS0001` is the same screen and `location.pathname` is still exactly `/`.
  { id: 'conversation', label: 'Conversation', to: '/', icon: 'messages-square', end: true },
  { id: 'overview', label: 'Overview', to: OVERVIEW_PATH, icon: 'microscope', end: true },
  { id: 'review', label: 'Review inbox', to: '/review', icon: 'inbox', group: 'Waiting' },
  {
    id: 'conflicts',
    label: 'Conflicts',
    to: '/conflicts',
    icon: 'alert-triangle',
    group: 'Waiting',
  },
  { id: 'stale', label: 'Stale', to: '/stale', icon: 'clock', group: 'Waiting' },
  { id: 'corpus', label: 'Corpus', to: '/corpus', icon: 'library', group: 'The record' },
  { id: 'claims', label: 'Claims', to: '/claims', icon: 'scale', group: 'The record' },
  {
    id: 'questions',
    label: 'Questions',
    to: '/questions',
    icon: 'circle-help',
    group: 'The record',
  },
  { id: 'taxonomy', label: 'Taxonomy', to: '/taxonomy', icon: 'git-branch', group: 'The record' },
  { id: 'synthesis', label: 'Synthesis', to: '/synthesis', icon: 'layers', group: 'Outputs' },
  { id: 'manuscript', label: 'Manuscript', to: '/manuscript', icon: 'file-code', group: 'Outputs' },
];

/**
 * The same navigation, pointed at one project.
 *
 * The rail is rendered by the shell, which is mounted inside whichever of the two route
 * trees the host selected (`App.tsx`). Under the multi-project host every workspace screen
 * lives below `/projects/{project_id}`, so the rail's `to` — and the extra paths an entry
 * counts as active for — are the local paths of `NAVIGATION` run through `projectHref`
 * exactly once. A null id is the legacy host and returns `NAVIGATION` itself, unchanged and
 * with a stable identity, so nothing downstream re-renders for a prefix that is not there.
 */
export function navigationForProject(projectId: string | null): NavigationEntry[] {
  if (!projectId) return NAVIGATION;
  return NAVIGATION.map((entry) => ({
    ...entry,
    to: projectHref(projectId, entry.to),
    ...(entry.alsoMatches
      ? { alsoMatches: entry.alsoMatches.map((path) => projectHref(projectId, path)) }
      : {}),
  }));
}

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
        {/* Where an artifact deep link lands (task W3): `rh://artifact/A0017-3?page=6&
            block=B0081` resolves to `/source/A0017-3?page=6&block=B0081`, which opens the
            artifact's own bytes at that page with that block highlighted. It is not in
            `NAVIGATION` on purpose — an artifact is reached through a reference, a piece of
            evidence or a link, never by browsing to "source". */}
        <Route path="source/:artifactId" element={<ArtifactSourcePage />} />
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

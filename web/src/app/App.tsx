/** The cockpit's routes: one per navigation entry of Product 26, plus the detail screens. */
import { Route, Routes } from 'react-router-dom';
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

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
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
        <Route path="*" element={<OverviewPage />} />
      </Route>
    </Routes>
  );
}

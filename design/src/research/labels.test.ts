/**
 * The vocabulary a person reads.
 *
 * Two things are asserted here. First, that every value the daemon can send has a word of
 * its own — a rename on the daemon's side shows up as a failing list rather than as a
 * `snake_case` token on a research page. Second, that nothing this module hands to a
 * surface is an identifier: no label carries an underscore, and the fallback for a value
 * no vocabulary documents is a readable phrase rather than the raw token.
 */
import { describe, expect, it } from 'vitest';
import {
  CANDIDATE_FIELD_META,
  CLAIM_RELATION_META,
  CLAIM_SCOPE_META,
  CLAIM_STATUS_META,
  CLAIM_TYPE_META,
  CONFLICT_KIND_META,
  EVIDENCE_ORIGIN_META,
  EVIDENCE_STRENGTH_META,
  EVIDENCE_TYPE_META,
  NEGATIVE_STATE_META,
  RESEARCH_VOCABULARIES,
  REVIEW_CATEGORY_META,
  REVIEW_TIER_META,
  SCREENING_STATE_META,
  VERIFICATION_VERDICT_META,
  humaniseResearchTokens,
  humaniseTerm,
  researchDescription,
  researchLabel,
  termDescription,
  termLabel,
} from './labels';

/** The values the daemon's own enumerations declare, in their declaration order. */
const DAEMON_VALUES: Record<string, readonly string[]> = {
  evidenceOrigin: [
    'source_observed',
    'author_claimed',
    'author_interpreted',
    'researcher_inferred',
    'model_proposed',
    'external_metadata',
  ],
  evidenceType: [
    'method_description',
    'representation_description',
    'experimental_setup',
    'experimental_result',
    'ablation_result',
    'dataset_description',
    'baseline_description',
    'limitation',
    'author_conclusion',
    'definition',
    'theoretical_result',
    'implementation_detail',
    'deployment_assumption',
    'bibliographic_metadata',
  ],
  evidenceStrength: ['direct', 'indirect', 'derived'],
  evidenceStatus: [
    'proposed',
    'verified',
    'accepted',
    'rejected',
    'deferred',
    'stale',
    'superseded',
  ],
  verdict: ['supported', 'partially_supported', 'contradicted', 'insufficient_evidence'],
  claimType: [
    'descriptive',
    'comparative',
    'prevalence',
    'absence',
    'causal',
    'taxonomic',
    'methodological',
    'synthesis',
    'recommendation',
  ],
  claimScope: [
    'individual',
    'observed_subset',
    'corpus_pattern',
    'field_generalization',
    'universal_or_absence',
  ],
  claimStatus: [
    'unverified',
    'supported',
    'qualified',
    'contested',
    'unsupported',
    'superseded',
  ],
  claimRelation: [
    'supports',
    'contradicts',
    'qualifies',
    'contextualizes',
    'exemplifies',
    'incomparable_under_current_evidence',
  ],
  negativeState: ['absent', 'not_found', 'not_reported', 'not_applicable', 'unclear'],
  reviewCategory: ['conflict', 'high_risk', 'stale', 'ambiguous', 'routine'],
  reviewTier: ['0', '1', '2'],
  anchorStatus: ['valid', 'stale', 'missing'],
  questionStatus: ['open', 'partially_answered', 'answered', 'blocked'],
  decisionType: [
    'taxonomy_revision',
    'epistemic_override',
    'inclusion',
    'exclusion',
    'methodology',
    'other',
  ],
  decisionStatus: ['proposed', 'accepted', 'superseded'],
  screeningState: ['discovered', 'screened', 'included', 'excluded'],
  overturnRisk: ['low', 'low_moderate', 'moderate', 'high', 'unknown'],
  staleState: ['fresh', 'stale'],
  conflictKind: [
    'provider_disagreement',
    'extractor_verifier',
    'candidate_vs_accepted',
    'new_evidence_vs_claim',
    'version_vs_anchor',
    'taxonomy_vs_classification',
  ],
  candidateField: ['dataset', 'metric_result', 'method_summary', 'author_limitation', 'baseline'],
};

describe('every vocabulary the daemon exposes', () => {
  it.each(Object.keys(DAEMON_VALUES))('covers every %s the daemon can send', (name) => {
    const vocabulary = RESEARCH_VOCABULARIES[name as keyof typeof RESEARCH_VOCABULARIES];
    expect(Object.keys(vocabulary).sort()).toEqual([...DAEMON_VALUES[name]!].sort());
  });

  it('never hands a surface an identifier', () => {
    for (const vocabulary of Object.values(RESEARCH_VOCABULARIES)) {
      for (const meta of Object.values(vocabulary)) {
        expect(meta.label).not.toMatch(/_/);
        expect(meta.label[0]).toBe(meta.label[0]?.toUpperCase());
      }
    }
  });

  it('ends every description it states as a sentence', () => {
    for (const vocabulary of Object.values(RESEARCH_VOCABULARIES)) {
      for (const meta of Object.values(vocabulary)) {
        if (meta.description === undefined) continue;
        expect(meta.description).toMatch(/[.!?]$/);
        expect(meta.description).not.toMatch(/_/);
      }
    }
  });
});

describe('the words themselves', () => {
  it('spells the review queue in the order and the words the product uses', () => {
    expect(termLabel(REVIEW_CATEGORY_META, 'conflict')).toBe('Conflicts');
    expect(termLabel(REVIEW_CATEGORY_META, 'high_risk')).toBe('High-risk scientific claims');
    expect(termLabel(REVIEW_CATEGORY_META, 'stale')).toBe('Stale high-impact objects');
    expect(termLabel(REVIEW_CATEGORY_META, 'ambiguous')).toBe('Ambiguous extractions');
    expect(termLabel(REVIEW_CATEGORY_META, 'routine')).toBe('Routine verified candidates');
  });

  it('keeps the claim scope ladder’s level in front of its name', () => {
    expect(termLabel(CLAIM_SCOPE_META, 'individual')).toBe('L0 Individual');
    expect(termLabel(CLAIM_SCOPE_META, 'observed_subset')).toBe('L1 Observed subset');
    expect(termLabel(CLAIM_SCOPE_META, 'corpus_pattern')).toBe('L2 Corpus pattern');
    expect(termLabel(CLAIM_SCOPE_META, 'field_generalization')).toBe('L3 Field generalization');
    expect(termLabel(CLAIM_SCOPE_META, 'universal_or_absence')).toBe('L4 Universal or absence');
  });

  it('names the tier and what the tier means', () => {
    expect(termLabel(REVIEW_TIER_META, '2')).toBe('Tier 2 — deep review');
    expect(termDescription(REVIEW_TIER_META, '0')).toMatch(/hashes/);
  });

  it('says what a verdict of insufficient evidence means', () => {
    expect(termLabel(VERIFICATION_VERDICT_META, 'partially_supported')).toBe('Partially supported');
    expect(termDescription(VERIFICATION_VERDICT_META, 'insufficient_evidence')).toMatch(
      /could not find its quoted support/,
    );
  });

  it('warns that derived evidence is not direct evidence', () => {
    expect(termDescription(EVIDENCE_STRENGTH_META, 'derived')).toMatch(/never shown as direct/);
  });

  it('says which origins only a researcher may accept', () => {
    for (const origin of ['author_interpreted', 'researcher_inferred', 'model_proposed']) {
      expect(termDescription(EVIDENCE_ORIGIN_META, origin)).toMatch(/only a researcher/);
    }
    expect(termDescription(EVIDENCE_ORIGIN_META, 'source_observed')).toBeUndefined();
  });

  it('keeps absence and a missing keyword apart', () => {
    expect(termDescription(NEGATIVE_STATE_META, 'absent')).toMatch(/audited/);
    expect(termDescription(NEGATIVE_STATE_META, 'not_found')).toMatch(/not evidence of absence/);
  });

  it('names each conflict as the two sides that disagree', () => {
    expect(termLabel(CONFLICT_KIND_META, 'extractor_verifier')).toBe('Extractor against verifier');
    expect(termLabel(CONFLICT_KIND_META, 'candidate_vs_accepted')).toBe(
      'Candidate against accepted state',
    );
  });

  it('says what each question of the baseline schema asks', () => {
    expect(termLabel(CANDIDATE_FIELD_META, 'metric_result')).toBe('Metric result');
    expect(termDescription(CANDIDATE_FIELD_META, 'metric_result')).toMatch(/measured result/);
  });

  it('reads an evidence type as the statement it carries', () => {
    expect(termLabel(EVIDENCE_TYPE_META, 'experimental_result')).toBe('Experimental result');
    expect(termLabel(EVIDENCE_TYPE_META, 'bibliographic_metadata')).toBe('Bibliographic metadata');
  });

  it('says where a screening state sits between a discovery result and the corpus', () => {
    // The one vocabulary that stated no meanings, so a thousand-row corpus separated its
    // four values by tint alone. Each sentence restates Product 14's own pipeline.
    expect(termDescription(SCREENING_STATE_META, 'discovered')).toMatch(/not a corpus member/);
    expect(termDescription(SCREENING_STATE_META, 'screened')).toMatch(/screening/);
    expect(termDescription(SCREENING_STATE_META, 'included')).toMatch(/research corpus/);
    expect(termDescription(SCREENING_STATE_META, 'excluded')).toMatch(/reason is recorded/);
  });

  it('reads a claim relation as the edge it is', () => {
    expect(termLabel(CLAIM_RELATION_META, 'incomparable_under_current_evidence')).toBe(
      'Incomparable under current evidence',
    );
    expect(termLabel(CLAIM_TYPE_META, 'methodological')).toBe('Methodological');
    expect(termLabel(CLAIM_STATUS_META, 'unsupported')).toBe('Unsupported');
  });
});

describe('a value no vocabulary documents', () => {
  it('is humanised rather than printed as an identifier', () => {
    expect(humaniseTerm('traffic_representation_family')).toBe('Traffic representation family');
    expect(humaniseTerm('metric_result:interpretation')).toBe('Metric result: interpretation');
    expect(humaniseTerm('traffic.dataset')).toBe('Traffic dataset');
    expect(humaniseTerm('baseline')).toBe('Baseline');
  });

  it('is what a vocabulary falls back to for a field a plugin declared', () => {
    expect(termLabel(CANDIDATE_FIELD_META, 'traffic_unit')).toBe('Traffic unit');
    expect(termDescription(CANDIDATE_FIELD_META, 'traffic_unit')).toBeUndefined();
  });

  it('never turns an id into a phrase', () => {
    expect(humaniseResearchTokens('cand_44c1f007fc0db0b2 is waiting')).toBe(
      'cand_44c1f007fc0db0b2 is waiting',
    );
  });
});

describe('the daemon’s own sentences', () => {
  it('reads its vocabulary out in words, and leaves the rest of the sentence alone', () => {
    expect(humaniseResearchTokens('the verifier reported partially_supported')).toBe(
      'the verifier reported partially supported',
    );
    expect(humaniseResearchTokens("records absence as 'not_reported'")).toBe(
      "records absence as 'not reported'",
    );
    expect(humaniseResearchTokens("origin 'author_interpreted' is interpretive")).toBe(
      "origin 'author interpreted' is interpretive",
    );
    expect(humaniseResearchTokens('verified supported, tier 1, anchor valid')).toBe(
      'verified supported, tier 1, anchor valid',
    );
    expect(
      humaniseResearchTokens("2 candidate(s) answer field 'metric_result' without competing"),
    ).toBe("2 candidate(s) answer field 'metric result' without competing");
  });
});

describe('the vocabulary reached by name', () => {
  it('answers with the label and the description of the named vocabulary', () => {
    expect(researchLabel('reviewCategory', 'high_risk')).toBe('High-risk scientific claims');
    expect(researchDescription('reviewCategory', 'stale')).toMatch(/anchor/);
    expect(researchLabel('candidateField', 'metric_result')).toBe('Metric result');
  });

  it('humanises a value the named vocabulary does not know', () => {
    expect(researchLabel('reviewCategory', 'needs_a_second_reader')).toBe(
      'Needs a second reader',
    );
    expect(researchDescription('reviewCategory', 'needs_a_second_reader')).toBeUndefined();
  });
});

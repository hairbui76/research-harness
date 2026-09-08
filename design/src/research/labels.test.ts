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
  ANCHOR_STATUS_META,
  CONFLICT_KIND_META,
  EVIDENCE_ORIGIN_META,
  EVIDENCE_STRENGTH_META,
  EVIDENCE_TYPE_META,
  MANUSCRIPT_FINDING_META,
  NEGATIVE_STATE_META,
  RESEARCH_VOCABULARIES,
  RESEARCH_VOCABULARY_DESCRIPTIONS,
  REVIEW_CATEGORY_META,
  REVIEW_TIER_META,
  SCREENING_STATE_META,
  VERIFICATION_VERDICT_META,
  humaniseResearchTokens,
  humaniseTerm,
  researchDescription,
  researchLabel,
  researchMeaning,
  researchVocabularyDescription,
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
  // `ManuscriptFindingKind`, which the audit inspector reads out on every finding card.
  manuscriptFinding: [
    'unregistered_claim',
    'over_strong_wording',
    'citation_mismatch',
    'unsupported_numeric',
    'stale_claim',
    'invalid_evidence_anchor',
  ],
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

  it('writes what it states about a whole vocabulary the same way', () => {
    for (const [name, description] of Object.entries(RESEARCH_VOCABULARY_DESCRIPTIONS)) {
      expect(RESEARCH_VOCABULARIES).toHaveProperty(name);
      expect(description).toMatch(/[.!?]$/);
      expect(description).not.toMatch(/_/);
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
  });

  /**
   * `source_observed` used to be asserted as having no meaning at all, which was true of
   * PRODUCT §9.1 — it lists the six values and defines none. It was not true of the
   * product: the extractor's role contract tells a model to separate exactly these three
   * ("`source_observed` for something measured or reported, `author_claimed` for what the
   * authors assert"), and `roles/schemas.py` says why `external_metadata` is not one of
   * them. A first-timer reading ORIGIN: Source observed had none of that on screen, so the
   * sentences the product already writes are now here.
   */
  it('separates the three origins the extractor is told to tell apart', () => {
    expect(termDescription(EVIDENCE_ORIGIN_META, 'source_observed')).toMatch(
      /measured or reported/,
    );
    expect(termDescription(EVIDENCE_ORIGIN_META, 'author_claimed')).toMatch(/authors assert/);
    expect(termDescription(EVIDENCE_ORIGIN_META, 'external_metadata')).toMatch(/provenance/);
  });

  /**
   * The audit inspector used to spell its own six kinds, and four of the six words it had
   * were for identifiers the daemon does not send (`unsupported_statement`,
   * `wording_stronger_than_claim`, `invalid_anchor`, `protected_span_changed`). A real
   * finding therefore arrived as a humanised token. The words are the auditor's own now,
   * keyed on the kinds it actually raises.
   */
  it('names every manuscript audit kind the auditor raises, and says what it detects', () => {
    expect(termLabel(MANUSCRIPT_FINDING_META, 'unregistered_claim')).toBe('Unregistered claim');
    expect(termLabel(MANUSCRIPT_FINDING_META, 'over_strong_wording')).toBe(
      'Wording stronger than the Claim',
    );
    expect(termLabel(MANUSCRIPT_FINDING_META, 'unsupported_numeric')).toBe('Unsupported number');
    expect(termDescription(MANUSCRIPT_FINDING_META, 'unregistered_claim')).toMatch(
      /attached to no Claim/,
    );
    expect(termDescription(MANUSCRIPT_FINDING_META, 'invalid_evidence_anchor')).toMatch(
      /no longer opens at its source/,
    );
  });

  it('still teaches something about a manuscript finding kind it has never met', () => {
    expect(researchLabel('manuscriptFinding', 'future_rule')).toBe('Future rule');
    expect(researchMeaning('manuscriptFinding', 'future_rule')).toMatch(
      /checked against the project’s accepted scientific state/,
    );
  });

  it('says what a valid anchor is, beside what a stale one is', () => {
    expect(termDescription(ANCHOR_STATUS_META, 'valid')).toMatch(/still replays/);
    expect(termDescription(ANCHOR_STATUS_META, 'stale')).toMatch(/source moved/);
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

/**
 * The vocabularies PRODUCT enumerates without defining a single member.
 *
 * Evidence type and evidence strength are bare lists in §9.2 and §9.3, so no member of
 * either carries a sentence and none is invented for it. What the product does state is
 * what the axis is for, and that is what a page falls back to, so STRENGTH over "Direct"
 * is no longer a word with nothing behind it.
 */
describe('what the product states about a vocabulary rather than a value', () => {
  it('states the axis for the vocabularies whose members it never defines', () => {
    expect(researchVocabularyDescription('evidenceStrength')).toBe(
      'How directly the source supports the evidence.',
    );
    expect(researchVocabularyDescription('evidenceType')).toBe(
      'What kind of statement the evidence carries.',
    );
    expect(researchVocabularyDescription('evidenceOrigin')).toMatch(/what the source does/);
    expect(researchVocabularyDescription('reviewTier')).toMatch(/property of the question/);
    expect(researchVocabularyDescription('anchorStatus')).toMatch(/stored parse/);
    expect(researchVocabularyDescription('negativeState')).toMatch(/missing keyword/);
  });

  it('states nothing about a vocabulary the product does not describe as a whole', () => {
    expect(researchVocabularyDescription('claimType')).toBeUndefined();
    expect(researchVocabularyDescription('decisionType')).toBeUndefined();
  });

  it('prefers the value’s own meaning and falls back to the vocabulary’s', () => {
    // `derived` is the one strength PRODUCT §9.3 says something about, so it keeps its own
    // sentence; its two neighbours borrow the axis.
    expect(researchMeaning('evidenceStrength', 'derived')).toMatch(/never shown as direct/);
    expect(researchMeaning('evidenceStrength', 'direct')).toBe(
      'How directly the source supports the evidence.',
    );
    expect(researchMeaning('evidenceType', 'experimental_result')).toBe(
      'What kind of statement the evidence carries.',
    );
    expect(researchMeaning('reviewTier', '2')).toMatch(/Interpretation/);
  });

  it('leaves a word the product says nothing about anywhere undescribed', () => {
    expect(researchMeaning('claimType', 'descriptive')).toBeUndefined();
    expect(researchMeaning('candidateField', 'traffic_unit')).toBeUndefined();
  });
});

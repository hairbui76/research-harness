/**
 * The words a person reads for the daemon's controlled vocabularies.
 *
 * The daemon speaks in identifiers — `observed_subset`, `partially_supported`, `high_risk`
 * — because canonical YAML has to stay schema-validated and diffable. A researcher does
 * not, so this module is the single place where each of those values gets its word and,
 * where the product states one, its one-line meaning.
 *
 * Three rules hold everything here together:
 *
 * - **The words are the product's.** A label is lifted from PRODUCT or from a guide
 *   wherever either names the value; only where neither does is the identifier humanised
 *   (Title case, spaces), and then it says nothing the identifier did not already say.
 * - **One term per concept.** A value has exactly one label, used in a table cell, a badge,
 *   a select option and a heading alike. Where a sentence needs the lower-case form,
 *   the caller lower-cases the label rather than keeping a second word for the same thing.
 * - **A description is a meaning, never a claim.** Descriptions restate what the product
 *   already says about a value. Nothing here decides anything about an object.
 *
 * A value no vocabulary knows still renders as a phrase: domain plugins extend these
 * vocabularies and a project's interrogation schema names its own fields, so the fallback
 * has to be readable rather than absent.
 */
import { STATUS_META } from '../primitives/Badge';

export interface TermMeta {
  /** What a person reads. Never an identifier. */
  label: string;
  /** One line the product states about this value. Absent where it states none. */
  description?: string;
}

/** One controlled vocabulary: the daemon's value, and the word for it. */
export type Vocabulary = Readonly<Record<string, TermMeta>>;

/* Evidence (Product 9) ------------------------------------------------------------------ */

/**
 * Accepting an interpretive origin is a judgement, so the domain reserves it for a person
 * (`INTERPRETIVE_ORIGINS`).
 *
 * The other three are the ones the extractor's own role contract tells a model to
 * separate — "`source_observed` for something measured or reported, `author_claimed` for
 * what the authors assert" (`roles/extractor.py`) — and `external_metadata`, which
 * `roles/schemas.py` excludes from that list because it "describe[s] how a record was
 * produced, which is provenance, not what the source says". PRODUCT §9.1 lists the six
 * values; those two files are where the product says what they are, so the sentences
 * below restate them and add nothing.
 */
const INTERPRETIVE =
  'Interpretive: accepting it is a judgement only a researcher may make.';

export const EVIDENCE_ORIGIN_META: Vocabulary = {
  source_observed: {
    label: 'Source observed',
    description: 'Something the source measured or reported, visible in the artifact itself.',
  },
  author_claimed: {
    label: 'Author claimed',
    description: 'What the authors assert, rather than something the source measured.',
  },
  author_interpreted: { label: 'Author interpreted', description: INTERPRETIVE },
  researcher_inferred: { label: 'Researcher inferred', description: INTERPRETIVE },
  model_proposed: { label: 'Model proposed', description: INTERPRETIVE },
  external_metadata: {
    label: 'External metadata',
    description: 'How the record was produced, which is provenance rather than what the source says.',
  },
};

export const EVIDENCE_TYPE_META: Vocabulary = {
  method_description: { label: 'Method description' },
  representation_description: { label: 'Representation description' },
  experimental_setup: { label: 'Experimental setup' },
  experimental_result: { label: 'Experimental result' },
  ablation_result: { label: 'Ablation result' },
  dataset_description: { label: 'Dataset description' },
  baseline_description: { label: 'Baseline description' },
  limitation: { label: 'Limitation' },
  author_conclusion: { label: 'Author conclusion' },
  definition: { label: 'Definition' },
  theoretical_result: { label: 'Theoretical result' },
  implementation_detail: { label: 'Implementation detail' },
  deployment_assumption: { label: 'Deployment assumption' },
  bibliographic_metadata: { label: 'Bibliographic metadata' },
};

/**
 * PRODUCT §9.3 lists the three strengths and states one thing about one of them, so
 * `direct` and `indirect` have no sentence here and are not given one. What the axis
 * means is stated (`domain/enums.py`: "How directly the source supports the evidence"),
 * and that sentence lives in `RESEARCH_VOCABULARY_DESCRIPTIONS` below, where a value with
 * no meaning of its own falls back to it.
 */
export const EVIDENCE_STRENGTH_META: Vocabulary = {
  direct: { label: 'Direct' },
  indirect: { label: 'Indirect' },
  derived: {
    label: 'Derived',
    description: 'Permitted, but never shown as direct evidence.',
  },
};

export const EVIDENCE_STATUS_META: Vocabulary = {
  proposed: { label: 'Proposed', description: 'Staged by a run and carrying no authority.' },
  verified: { label: 'Verified' },
  accepted: { label: 'Accepted', description: STATUS_META.accepted.description },
  rejected: {
    label: 'Rejected',
    description: 'Considered and not accepted; the refusal is on record.',
  },
  deferred: { label: 'Deferred', description: 'Left in the queue for later.' },
  stale: { label: 'Stale', description: STATUS_META.stale.description },
  superseded: { label: 'Superseded' },
};

export const VERIFICATION_VERDICT_META: Vocabulary = {
  supported: {
    label: 'Supported',
    description: 'An independent reader confirmed the assertion in the span it was given.',
  },
  partially_supported: {
    label: 'Partially supported',
    description: 'The independent reader confirmed part of it, so the queue calls this ambiguous.',
  },
  contradicted: {
    label: 'Contradicted',
    description: 'The independent reader contradicted the candidate, so the queue calls this a conflict.',
  },
  insufficient_evidence: {
    label: 'Insufficient evidence',
    description:
      'The verifier could not find its quoted support inside the span, so the verdict was downgraded.',
  },
};

/** Absence states, deliberately distinct (Product 11): a missing keyword is not absence. */
export const NEGATIVE_STATE_META: Vocabulary = {
  absent: { label: 'Absent', description: 'An audited conclusion, not a missing keyword.' },
  not_found: {
    label: 'Not found',
    description: 'The search did not find it, which is not evidence of absence.',
  },
  not_reported: { label: 'Not reported' },
  not_applicable: { label: 'Not applicable' },
  unclear: { label: 'Unclear' },
};

/* Claims (Product 10) ------------------------------------------------------------------- */

export const CLAIM_TYPE_META: Vocabulary = {
  descriptive: { label: 'Descriptive' },
  comparative: { label: 'Comparative' },
  prevalence: { label: 'Prevalence' },
  absence: { label: 'Absence' },
  causal: { label: 'Causal' },
  taxonomic: { label: 'Taxonomic' },
  methodological: { label: 'Methodological' },
  synthesis: { label: 'Synthesis' },
  recommendation: { label: 'Recommendation' },
};

/**
 * The scope ladder, with the level in front of the name exactly as the product writes it
 * (`L0 individual` … `L4 universal_or_absence`). The level is what a reader compares, so
 * dropping it would make two neighbouring rungs look like unrelated words.
 */
export const CLAIM_SCOPE_META: Vocabulary = {
  individual: { label: 'L0 Individual' },
  observed_subset: {
    label: 'L1 Observed subset',
    description: 'A strong result in a few papers is still an observed subset: confidence is not scope.',
  },
  corpus_pattern: { label: 'L2 Corpus pattern' },
  field_generalization: { label: 'L3 Field generalization' },
  universal_or_absence: {
    label: 'L4 Universal or absence',
    description:
      'Needs an audited search with stated coverage, never the mere absence of hits.',
  },
};

export const CLAIM_STATUS_META: Vocabulary = {
  unverified: { label: 'Unverified' },
  supported: { label: 'Supported' },
  qualified: { label: 'Qualified', description: STATUS_META.qualified.description },
  contested: { label: 'Contested', description: STATUS_META.contested.description },
  unsupported: { label: 'Unsupported' },
  superseded: { label: 'Superseded' },
};

export const CLAIM_RELATION_META: Vocabulary = {
  supports: { label: 'Supports' },
  contradicts: { label: 'Contradicts' },
  qualifies: { label: 'Qualifies' },
  contextualizes: { label: 'Contextualizes' },
  exemplifies: { label: 'Exemplifies' },
  incomparable_under_current_evidence: {
    label: 'Incomparable under current evidence',
    description:
      'Results that differ under different metrics, datasets, or conditions are incomparable, not contradictory.',
  },
};

/** Estimated risk that new evidence overturns a claim (Product 18). */
export const OVERTURN_RISK_META: Vocabulary = {
  low: { label: 'Low' },
  low_moderate: { label: 'Low to moderate' },
  moderate: { label: 'Moderate' },
  high: { label: 'High' },
  unknown: { label: 'Unknown' },
};

/* Review (Product 24) ------------------------------------------------------------------- */

/**
 * Why an item is waiting, in the priority order of Product 24.2. The descriptions are the
 * review guide's own table of what puts an item in each category.
 */
export const REVIEW_CATEGORY_META: Vocabulary = {
  conflict: {
    label: 'Conflicts',
    description:
      'The verifier contradicted it, accepted evidence reads the same span differently, two providers disagree, or a competing answer is on record.',
  },
  high_risk: {
    label: 'High-risk scientific claims',
    description:
      'Tier 2, or the candidate carries a number, records an absence, or has an interpretive origin.',
  },
  stale: {
    label: 'Stale high-impact objects',
    description: 'The anchor no longer replays against the stored parse.',
  },
  ambiguous: {
    label: 'Ambiguous extractions',
    description: 'Nothing has verified it yet, or the verdict was partial or insufficient.',
  },
  routine: {
    label: 'Routine verified candidates',
    description: 'Verified supported, Tier 0 or 1, and the anchor is valid.',
  },
};

/**
 * The tier is a property of the *question*, not of the answer or of any model's confidence
 * (Product 24.1). Keyed by the number the daemon sends, as a string.
 */
export const REVIEW_TIER_META: Vocabulary = {
  '0': {
    label: 'Tier 0 — automatic',
    description: 'Deterministic, mechanical facts: hashes, page counts, resolved DOIs.',
  },
  '1': {
    label: 'Tier 1 — quick triage',
    description: 'Directly evidenced extraction: a dataset name, a reported metric, a traffic unit.',
  },
  '2': {
    label: 'Tier 2 — deep review',
    description:
      'Interpretation: taxonomy placement, methodological limitations, gap and absence claims, claim strength, counter-evidence.',
  },
};

/** What replaying an anchor against the stored parse said. */
export const ANCHOR_STATUS_META: Vocabulary = {
  valid: {
    label: 'Valid',
    // The review guide's own wording for the condition a routine candidate has to meet:
    // "the anchor still replays as valid" (docs/guide/review.md).
    description: 'The anchor still replays against the stored parse.',
  },
  stale: {
    label: 'Stale',
    description: 'The source moved after the anchor was recorded; nothing is silently re-anchored.',
  },
  missing: { label: 'Missing', description: 'The span the anchor names is no longer in the parse.' },
};

/** The two sides of a disagreement, named as Product 25 names them. */
export const CONFLICT_KIND_META: Vocabulary = {
  provider_disagreement: { label: 'Provider against provider' },
  extractor_verifier: { label: 'Extractor against verifier' },
  candidate_vs_accepted: { label: 'Candidate against accepted state' },
  new_evidence_vs_claim: { label: 'New evidence against an existing claim' },
  version_vs_anchor: { label: 'Revised version against an existing anchor' },
  taxonomy_vs_classification: { label: 'Taxonomy revision against dependent classifications' },
};

/* The rest of the workspace ------------------------------------------------------------- */

export const QUESTION_STATUS_META: Vocabulary = {
  open: { label: 'Open' },
  partially_answered: { label: 'Partially answered' },
  answered: { label: 'Answered' },
  blocked: { label: 'Blocked' },
};

export const DECISION_TYPE_META: Vocabulary = {
  taxonomy_revision: { label: 'Taxonomy revision' },
  epistemic_override: { label: 'Epistemic override' },
  inclusion: { label: 'Inclusion' },
  exclusion: { label: 'Exclusion' },
  methodology: { label: 'Methodology' },
  other: { label: 'Other' },
};

export const DECISION_STATUS_META: Vocabulary = {
  proposed: { label: 'Proposed' },
  accepted: { label: 'Accepted' },
  superseded: { label: 'Superseded' },
};

/**
 * Where a work stands on the way from a discovery result to a corpus member (Product 14).
 *
 * It was the one vocabulary in the product with no meanings written down, so a thousand-row
 * corpus separated these four by tint alone. Each sentence restates the pipeline Product 14
 * draws — discovery result, candidate work, screening, source acquisition, included corpus —
 * and decides nothing about any work.
 */
export const SCREENING_STATE_META: Vocabulary = {
  discovered: {
    label: 'Discovered',
    description: 'A discovery run returned it. A discovery result is not a corpus member.',
  },
  screened: {
    label: 'Screened',
    description: 'It has been through screening, the step between a candidate work and acquiring its source.',
  },
  included: { label: 'Included', description: 'It is a member of this project’s research corpus.' },
  excluded: {
    label: 'Excluded',
    description: 'Screening ruled it out, and the reason is recorded with it.',
  },
};

export const STALE_STATE_META: Vocabulary = {
  fresh: { label: 'Fresh' },
  stale: { label: 'Stale', description: STATUS_META.stale.description },
};

/**
 * The questions the plugin-neutral baseline interrogation schema asks, which is where the
 * candidate `field` of a review item comes from. A domain plugin contributes its own
 * schema, so a field this does not know falls back to the humanised identifier.
 */
export const CANDIDATE_FIELD_META: Vocabulary = {
  dataset: {
    label: 'Dataset',
    description: 'Which dataset or corpus the reported experiments use.',
  },
  metric_result: {
    label: 'Metric result',
    description:
      'The measured result the paper reports for its own system, with the metric, dataset and table it comes from.',
  },
  method_summary: {
    label: 'Method summary',
    description: 'How the paper describes its own method or representation.',
  },
  author_limitation: {
    label: 'Author limitation',
    description: 'A limitation, threat to validity, or scope restriction the authors state themselves.',
  },
  baseline: {
    label: 'Baseline',
    description: 'The baselines or comparison systems the paper evaluates against.',
  },
};

/* Reaching a vocabulary ----------------------------------------------------------------- */

/** Every vocabulary, by the name a surface asks for it under. */
export const RESEARCH_VOCABULARIES = {
  anchorStatus: ANCHOR_STATUS_META,
  candidateField: CANDIDATE_FIELD_META,
  claimRelation: CLAIM_RELATION_META,
  claimScope: CLAIM_SCOPE_META,
  claimStatus: CLAIM_STATUS_META,
  claimType: CLAIM_TYPE_META,
  conflictKind: CONFLICT_KIND_META,
  decisionStatus: DECISION_STATUS_META,
  decisionType: DECISION_TYPE_META,
  evidenceOrigin: EVIDENCE_ORIGIN_META,
  evidenceStatus: EVIDENCE_STATUS_META,
  evidenceStrength: EVIDENCE_STRENGTH_META,
  evidenceType: EVIDENCE_TYPE_META,
  negativeState: NEGATIVE_STATE_META,
  overturnRisk: OVERTURN_RISK_META,
  questionStatus: QUESTION_STATUS_META,
  reviewCategory: REVIEW_CATEGORY_META,
  reviewTier: REVIEW_TIER_META,
  screeningState: SCREENING_STATE_META,
  staleState: STALE_STATE_META,
  verdict: VERIFICATION_VERDICT_META,
} as const;

export type VocabularyName = keyof typeof RESEARCH_VOCABULARIES;

/**
 * What the product states about a whole vocabulary, for values it never defines one by one.
 *
 * PRODUCT §9.2 and §9.3 list the fourteen evidence types and the three strengths as bare
 * enumerations: nothing in the product says what `experimental_result` or `direct` means,
 * so a page reading TYPE over "Experimental result" or STRENGTH over "Direct" had nothing
 * to explain it, which is what a first-timer met on the review screen. What the product
 * *does* state is what each axis is for, in the daemon's own enumerations
 * (`domain/enums.py`), the extractor's role contract, and PRODUCT §11 and §24.1. Those
 * sentences are these, restated and nothing more.
 *
 * A value with a meaning of its own keeps it; this is the fallback under it, never a
 * replacement for it, and a vocabulary whose axis the product does not state is absent
 * here rather than given a sentence someone made up.
 */
export const RESEARCH_VOCABULARY_DESCRIPTIONS: Partial<Record<VocabularyName, string>> = {
  // "Epistemic origin of an evidence object" (Product 9.1), classified "by what the source
  // does, not by what you believe" (`roles/extractor.py`).
  evidenceOrigin:
    'Where a statement comes from, classified by what the source does rather than by what a reader believes.',
  // "What kind of statement the evidence carries" (Product 9.2, `domain/enums.py`).
  evidenceType: 'What kind of statement the evidence carries.',
  // "How directly the source supports the evidence" (Product 9.3, `domain/enums.py`).
  evidenceStrength: 'How directly the source supports the evidence.',
  // "The following states must be different… A missing keyword is not sufficient evidence
  // of absence" (Product 11).
  negativeState:
    'Absence states the product keeps apart, because a missing keyword is not sufficient evidence of absence.',
  // The tier is a property of the question (Product 24.1).
  reviewTier:
    'How much reading the question needs — a property of the question, not of the answer or of any model’s confidence.',
  // What `review.stale` reports and refuses to repair (docs/guide/review.md, ADR-008).
  anchorStatus: 'What replaying the anchor against the stored parse said.',
};

/**
 * A readable phrase for an identifier no vocabulary documents: `_`, `-` and `.` become
 * spaces, `:` keeps its place because a split candidate is staged as
 * `<field>:interpretation`, and the first letter is capitalised. It adds no meaning — it
 * only stops a page printing a token a person has to decode.
 */
export function humaniseTerm(value: string): string {
  const spaced = value.replace(/[_\-.]+/g, ' ').replace(/\s*:\s*/g, ': ').trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** The word for a value, or the humanised identifier when the vocabulary has none. */
export function termLabel(vocabulary: Vocabulary, value: string): string {
  return vocabulary[value]?.label ?? humaniseTerm(value);
}

/** The one line the product states about a value, when it states one. */
export function termDescription(vocabulary: Vocabulary, value: string): string | undefined {
  return vocabulary[value]?.description;
}

/** The word for a value of the named vocabulary. */
export function researchLabel(name: VocabularyName, value: string): string {
  return termLabel(RESEARCH_VOCABULARIES[name], value);
}

/** The one line the named vocabulary states about a value. */
export function researchDescription(name: VocabularyName, value: string): string | undefined {
  return termDescription(RESEARCH_VOCABULARIES[name], value);
}

/** The one line the product states about a whole vocabulary, when it states one. */
export function researchVocabularyDescription(name: VocabularyName): string | undefined {
  return RESEARCH_VOCABULARY_DESCRIPTIONS[name];
}

/**
 * The meaning to put on the page beside one value: the value's own sentence when the
 * product states one, and otherwise what it states about the vocabulary the value belongs
 * to.
 *
 * This is what a surface asks for when it makes a word reachable, so that a vocabulary
 * that defines its axis but not its members still teaches something, and a word the
 * product says nothing about anywhere stays undescribed rather than taking a tab stop that
 * leads to nothing.
 */
export function researchMeaning(name: VocabularyName, value: string): string | undefined {
  return researchDescription(name, value) ?? researchVocabularyDescription(name);
}

/**
 * Every identifier any vocabulary knows that a sentence could carry, so the rewrite below
 * can be whitelist-only. A candidate id is `cand_<16 hex>` and looks exactly like a
 * vocabulary value to a regular expression; only a value some vocabulary declares is ever
 * touched.
 */
const SENTENCE_TERMS: ReadonlySet<string> = new Set(
  Object.values(RESEARCH_VOCABULARIES)
    .flatMap((vocabulary) => Object.keys(vocabulary))
    .filter((value) => value.includes('_')),
);

/**
 * The daemon's own sentence, with its vocabulary read out in words.
 *
 * The queue explains itself in sentences it builds around its own enumerations — "the
 * verifier reported partially_supported", "records absence as 'not_reported'". The sentence
 * is the daemon's and stays the daemon's; only the identifiers inside it are spelled the
 * way the rest of the screen spells them. Anything that is not a value of a vocabulary —
 * an id, a metric name, a file name — is left exactly as it came.
 */
export function humaniseResearchTokens(text: string): string {
  return text.replace(/[a-z][a-z0-9]*(?:_[a-z0-9]+)+/g, (token) =>
    SENTENCE_TERMS.has(token) ? token.replace(/_/g, ' ') : token,
  );
}

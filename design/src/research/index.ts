/**
 * Research semantics: the components that present authority, provenance, sources and the
 * receipt for a model call. They render what the host tells them and decide nothing.
 */

export * from './models';
export * from './labels';

export { AuthorityBadge } from './AuthorityBadge';
export type { AuthorityBadgeProps } from './AuthorityBadge';
export {
  DESCRIBED_TERM_HOVER_MS,
  DESCRIBED_TERM_PRESS_MS,
  DescribedTerm,
  useDescribedTerm,
} from './DescribedTerm';
export type { DescribedTermParts, DescribedTermProps } from './DescribedTerm';
export { EntityRef } from './EntityRef';
export type { EntityRefElement, EntityRefProps, EntityRefSize } from './EntityRef';
export { SourceAnchor } from './SourceAnchor';
export type { SourceAnchorProps, SourceAnchorVariant } from './SourceAnchor';
export { EvidenceCard } from './EvidenceCard';
export type { EvidenceCardProps, EvidenceFactMeanings } from './EvidenceCard';
export { ClaimCard } from './ClaimCard';
export type { ClaimCardProps } from './ClaimCard';
export { ChangeList, CHANGE_BY_META, CHANGE_KINDS, CHANGE_KIND_META } from './ChangeList';
export type {
  ChangeBy,
  ChangeKind,
  ChangeKindMeta,
  ChangeListEntry,
  ChangeListProps,
} from './ChangeList';
export { ProvenancePath } from './ProvenancePath';
export type { ProvenancePathOrientation, ProvenancePathProps } from './ProvenancePath';
export { ContextReceipt } from './ContextReceipt';
export type { ContextReceiptProps } from './ContextReceipt';
export { ReviewDecisionBar } from './ReviewDecisionBar';
export type { ReviewDecisionBarProps } from './ReviewDecisionBar';
export { ConflictNotice } from './ConflictNotice';
export type { ConflictNoticeProps } from './ConflictNotice';
export { SaveToCorpusAction } from './SaveToCorpusAction';
export type { SaveToCorpusActionProps, SaveToCorpusCorpusLinks } from './SaveToCorpusAction';

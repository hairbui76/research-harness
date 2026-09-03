/**
 * Research semantics: the components that present authority, provenance, sources and the
 * receipt for a model call. They render what the host tells them and decide nothing.
 */

export * from './models';

export { AuthorityBadge } from './AuthorityBadge';
export type { AuthorityBadgeProps } from './AuthorityBadge';
export { EntityRef } from './EntityRef';
export type { EntityRefElement, EntityRefProps, EntityRefSize } from './EntityRef';
export { SourceAnchor } from './SourceAnchor';
export type { SourceAnchorProps, SourceAnchorVariant } from './SourceAnchor';
export { EvidenceCard } from './EvidenceCard';
export type { EvidenceCardProps } from './EvidenceCard';
export { ClaimCard } from './ClaimCard';
export type { ClaimCardProps } from './ClaimCard';
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

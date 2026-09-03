import { forwardRef } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { Card } from '../../primitives/Card';
import type { CardProps } from '../../primitives/Card';
import { Icon } from '../../primitives/Icon';
import { cx } from '../../utils/cx';
import { AuthorityBadge } from '../AuthorityBadge';
import { SourceAnchor } from '../SourceAnchor';
import type { EvidenceModel, SourceAnchorModel } from '../models';

export interface EvidenceCardProps
  extends Omit<CardProps, 'header' | 'footer' | 'children' | 'onSelect'> {
  evidence: EvidenceModel;
  /** Open the evidence object itself. */
  onOpen?: (evidence: EvidenceModel) => void;
  /** Open the source at the exact anchor. */
  onOpenAnchor?: (anchor: SourceAnchorModel) => void;
  /** Actions belonging to this card — usually a `ReviewDecisionBar`. */
  actions?: ReactNode;
  /** Drop the quote and the metadata grid, for a dense list. */
  compact?: boolean;
  /** Marks the card as the inspector's current selection. */
  selected?: boolean;
}

interface FactProps {
  label: string;
  value: ReactNode;
}

function Fact({ label, value }: FactProps): ReactElement | null {
  if (value === undefined || value === null || value === '') return null;
  return (
    <div className="rh-evidence-card__fact">
      <dt className="rh-text-label">{label}</dt>
      <dd className="rh-evidence-card__fact-value">{value}</dd>
    </div>
  );
}

/**
 * One piece of evidence: the quoted words, where they came from, and what the project has
 * decided about them.
 *
 * The quote is the point of the card, so it is set in serif at reading size and never
 * truncated to a single line. Everything else — type, strength, origin, the extracted
 * number — is metadata around it. The card renders the authority it is given and offers no
 * way to change it: acceptance happens in a review flow, through `ReviewDecisionBar`.
 */
export const EvidenceCard = forwardRef<HTMLElement, EvidenceCardProps>(function EvidenceCard(
  { evidence, onOpen, onOpenAnchor, actions, compact = false, selected = false, className, ...rest },
  ref,
) {
  const stale = evidence.stale === true || evidence.anchor.stale === true;
  const title = (
    <span className="rh-evidence-card__title">
      <Icon name="quote" size={16} />
      {onOpen ? (
        <button type="button" className="rh-evidence-card__id" onClick={() => onOpen(evidence)}>
          {evidence.id}
        </button>
      ) : (
        <span className="rh-evidence-card__id">{evidence.id}</span>
      )}
      <span className="rh-evidence-card__work">{evidence.workLabel}</span>
    </span>
  );

  return (
    <Card
      ref={ref}
      as="article"
      className={cx('rh-evidence-card', selected && 'is-selected', className)}
      data-authority={evidence.authority}
      data-stale={stale ? '' : undefined}
      data-selected={selected || undefined}
      header={
        <>
          {title}
          <span className="rh-evidence-card__badges">
            <AuthorityBadge authority={evidence.authority} size="sm" />
            {stale ? <AuthorityBadge authority="stale" size="sm" /> : null}
          </span>
        </>
      }
      footer={
        <div className="rh-evidence-card__footer">
          <SourceAnchor anchor={evidence.anchor} onOpen={onOpenAnchor} />
          {actions !== undefined ? (
            <div className="rh-evidence-card__actions">{actions}</div>
          ) : null}
        </div>
      }
      {...rest}
    >
      <blockquote className="rh-evidence-card__quote">{evidence.quote}</blockquote>
      {evidence.numeric !== undefined ? (
        <p className="rh-evidence-card__numeric">
          <span className="rh-evidence-card__numeric-value">
            {evidence.numeric.value}
            {evidence.numeric.unit !== undefined ? ` ${evidence.numeric.unit}` : ''}
          </span>
          {evidence.numeric.metric !== undefined ? (
            <span className="rh-evidence-card__numeric-meta">{evidence.numeric.metric}</span>
          ) : null}
          {evidence.numeric.dataset !== undefined ? (
            <span className="rh-evidence-card__numeric-meta">{evidence.numeric.dataset}</span>
          ) : null}
        </p>
      ) : null}
      {compact ? null : (
        <dl className="rh-evidence-card__facts">
          <Fact label="Work" value={evidence.workId} />
          <Fact label="Type" value={evidence.evidenceType} />
          <Fact label="Strength" value={evidence.strength} />
          <Fact label="Origin" value={evidence.origin} />
          <Fact label="Field" value={evidence.field} />
        </dl>
      )}
    </Card>
  );
});

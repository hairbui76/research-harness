import { forwardRef } from 'react';
import type { ReactNode } from 'react';
import { Card } from '../../primitives/Card';
import type { CardProps } from '../../primitives/Card';
import { Icon } from '../../primitives/Icon';
import { cx } from '../../utils/cx';
import { AuthorityBadge } from '../AuthorityBadge';
import { useDescribedTerm } from '../DescribedTerm';
import type { DescribedTermParts } from '../DescribedTerm';
import { SourceAnchor } from '../SourceAnchor';
import type { EvidenceModel, SourceAnchorModel } from '../models';

/**
 * The one line the product states about each metadata fact, keyed by the fact.
 *
 * The card is handed words, not identifiers — the host has already spelled `direct` as
 * `Direct` — so it cannot look a meaning up, and it is given one per fact instead. A fact
 * with no sentence here stays plain text: `Work` is an identifier and means nothing beyond
 * itself, and a vocabulary the product never defines gets no invented definition.
 */
export interface EvidenceFactMeanings {
  work?: string;
  type?: string;
  strength?: string;
  origin?: string;
  field?: string;
}

export interface EvidenceCardProps
  extends Omit<CardProps, 'header' | 'footer' | 'children' | 'onSelect' | 'title'> {
  evidence: EvidenceModel;
  /**
   * What this evidence is called on the page that is showing it.
   *
   * Given, it is the card's heading and the object's identifier is not printed at all —
   * it stays on the element as `data-evidence-id` for anything that has to address it.
   * Omitted, the heading is the identifier and the work label beside it, which is right
   * where the identifier is the researcher's own handle for the object (an accepted
   * `EV0012`) and wrong where it is the daemon's (`cand_<hex>`).
   */
  title?: ReactNode;
  /** Open the evidence object itself. */
  onOpen?: (evidence: EvidenceModel) => void;
  /** Open the source at the exact anchor. */
  onOpenAnchor?: (anchor: SourceAnchorModel) => void;
  /**
   * Put the meaning of the metadata facts on the page.
   *
   * Each sentence given makes its fact reachable — the value takes a tab stop, is
   * `aria-describedby` the sentence and prints it underneath on focus, exactly as the
   * authority badge in the header does. Pass it where a reader has to know what `Direct`
   * or `Source observed` is in order to judge the evidence; leave it off and the facts
   * render as before.
   */
  meanings?: EvidenceFactMeanings;
  /** Actions belonging to this card — usually a `ReviewDecisionBar`. */
  actions?: ReactNode;
  /** Drop the quote and the metadata grid, for a dense list. */
  compact?: boolean;
  /** Marks the card as the inspector's current selection. */
  selected?: boolean;
}

interface FactSpec {
  key: string;
  label: string;
  value: ReactNode;
  /** The tab stop and the sentence, when the host stated one for this fact. */
  term: DescribedTermParts;
}

/**
 * One piece of evidence: the quoted words, where they came from, and what the project has
 * decided about them.
 *
 * The quote is the point of the card, so it is set in serif at reading size and never
 * truncated to a single line. Everything else — type, strength, origin, the extracted
 * number — is metadata around it. The card renders the authority it is given and offers no
 * way to change it: acceptance happens in a review flow, through `ReviewDecisionBar`.
 *
 * The heading is `title` when the host has a name for this evidence, and the object's own
 * identifier only when it has not.
 */
export const EvidenceCard = forwardRef<HTMLElement, EvidenceCardProps>(function EvidenceCard(
  {
    evidence,
    title,
    onOpen,
    onOpenAnchor,
    meanings,
    actions,
    compact = false,
    selected = false,
    className,
    ...rest
  },
  ref,
) {
  const stale = evidence.stale === true || evidence.anchor.stale === true;

  /*
   * The five metadata facts, and the sentence each one offers.
   *
   * The hooks are called for all five whether or not the host stated a meaning, because a
   * hook cannot be called conditionally; one given nothing hands back nothing — no tab
   * stop, no sentence — and the fact renders as plain text. `Work` is the usual such fact:
   * an identifier means nothing beyond itself.
   */
  const facts: FactSpec[] = (
    [
      { key: 'work', label: 'Work', value: evidence.workId, term: useDescribedTerm(meanings?.work) },
      {
        key: 'type',
        label: 'Type',
        value: evidence.evidenceType,
        term: useDescribedTerm(meanings?.type),
      },
      {
        key: 'strength',
        label: 'Strength',
        value: evidence.strength,
        term: useDescribedTerm(meanings?.strength),
      },
      {
        key: 'origin',
        label: 'Origin',
        value: evidence.origin,
        term: useDescribedTerm(meanings?.origin),
      },
      {
        key: 'field',
        label: 'Field',
        value: evidence.field,
        term: useDescribedTerm(meanings?.field),
      },
    ] satisfies FactSpec[]
  ).filter((fact) => fact.value !== undefined && fact.value !== null && fact.value !== '');

  const heading = (
    <span className="rh-evidence-card__title">
      <Icon name="quote" size={16} />
      {title !== undefined ? (
        onOpen ? (
          <button type="button" className="rh-evidence-card__name" onClick={() => onOpen(evidence)}>
            {title}
          </button>
        ) : (
          <span className="rh-evidence-card__name">{title}</span>
        )
      ) : (
        <>
          {onOpen ? (
            <button type="button" className="rh-evidence-card__id" onClick={() => onOpen(evidence)}>
              {evidence.id}
            </button>
          ) : (
            <span className="rh-evidence-card__id">{evidence.id}</span>
          )}
          <span className="rh-evidence-card__work">{evidence.workLabel}</span>
        </>
      )}
    </span>
  );

  return (
    <Card
      ref={ref}
      as="article"
      className={cx('rh-evidence-card', selected && 'is-selected', className)}
      data-authority={evidence.authority}
      data-evidence-id={evidence.id}
      data-stale={stale ? '' : undefined}
      data-selected={selected || undefined}
      header={
        <>
          {heading}
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
          {facts.map(({ key, label, value, term }) => (
            <div key={key} className="rh-evidence-card__fact">
              <dt className="rh-text-label">{label}</dt>
              <dd className="rh-evidence-card__fact-value">
                {term.named === null ? (
                  value
                ) : (
                  <>
                    <span className="rh-described-term__word" {...term.word}>
                      {value}
                    </span>
                    {term.named}
                  </>
                )}
              </dd>
            </div>
          ))}
          {/*
            Every sentence after every term, and never inside the one it belongs to.
            The grid gives it a row of its own spanning the whole width, so opening one
            leaves the terms — which are the next tab stops — exactly where they were.
          */}
          {facts.map(({ key, term }) =>
            term.hint === null ? null : (
              <div key={`${key}-hint`} className="rh-evidence-card__fact-hint">
                {term.hint}
              </div>
            ),
          )}
        </dl>
      )}
    </Card>
  );
});



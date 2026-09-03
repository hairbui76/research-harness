import { forwardRef } from 'react';
import type { ReactNode } from 'react';
import { Card } from '../../primitives/Card';
import type { CardProps } from '../../primitives/Card';
import { Icon } from '../../primitives/Icon';
import type { IconName } from '../../primitives/Icon';
import { cx } from '../../utils/cx';
import { AuthorityBadge } from '../AuthorityBadge';
import type { ClaimModel } from '../models';

export interface ClaimCardProps
  extends Omit<CardProps, 'header' | 'footer' | 'children' | 'onSelect'> {
  claim: ClaimModel;
  /** Open the claim object. */
  onOpen?: (claim: ClaimModel) => void;
  /** Open the evidence behind one relation — `supports`, `contradicts` or `qualifies`. */
  onOpenSupport?: (relation: keyof ClaimModel['support'], claim: ClaimModel) => void;
  /** Actions belonging to this card — usually a `ReviewDecisionBar`. */
  actions?: ReactNode;
  selected?: boolean;
}

const SUPPORT_META: Array<{
  key: keyof ClaimModel['support'];
  label: string;
  icon: IconName;
}> = [
  { key: 'supports', label: 'support', icon: 'circle-check' },
  { key: 'contradicts', label: 'contradict', icon: 'alert-triangle' },
  { key: 'qualifies', label: 'qualify', icon: 'info' },
];

/**
 * One claim: the sentence the project would defend, and the evidence standing behind and
 * against it.
 *
 * The support counts are the honest part — a claim with contradicting evidence shows that
 * count in the same row as its support, at the same size, so the reader cannot see one
 * without the other. A wording ceiling, where the reviewer set one, is printed in full:
 * it is the sentence the evidence actually licenses.
 */
export const ClaimCard = forwardRef<HTMLElement, ClaimCardProps>(function ClaimCard(
  { claim, onOpen, onOpenSupport, actions, selected = false, className, ...rest },
  ref,
) {
  return (
    <Card
      ref={ref}
      as="article"
      className={cx('rh-claim-card', selected && 'is-selected', className)}
      data-authority={claim.authority}
      data-stale={claim.stale === true ? '' : undefined}
      data-selected={selected || undefined}
      header={
        <>
          <span className="rh-claim-card__title">
            <Icon name="scale" size={16} />
            {onOpen ? (
              <button type="button" className="rh-claim-card__id" onClick={() => onOpen(claim)}>
                {claim.id}
              </button>
            ) : (
              <span className="rh-claim-card__id">{claim.id}</span>
            )}
            <span className="rh-claim-card__status">{claim.status}</span>
          </span>
          <span className="rh-claim-card__badges">
            <AuthorityBadge authority={claim.authority} size="sm" />
            {claim.stale === true ? <AuthorityBadge authority="stale" size="sm" /> : null}
          </span>
        </>
      }
      footer={
        <div className="rh-claim-card__footer">
          <ul className="rh-claim-card__support">
            {SUPPORT_META.map(({ key, label, icon }) => {
              const count = claim.support[key];
              const body = (
                <>
                  <Icon name={icon} size={14} />
                  <span className="rh-claim-card__support-count">{count}</span>
                  <span>{label}</span>
                </>
              );
              return (
                <li key={key} className="rh-claim-card__support-item" data-relation={key}>
                  {onOpenSupport ? (
                    <button
                      type="button"
                      className="rh-claim-card__support-button"
                      onClick={() => onOpenSupport(key, claim)}
                    >
                      {body}
                    </button>
                  ) : (
                    <span className="rh-claim-card__support-button">{body}</span>
                  )}
                </li>
              );
            })}
          </ul>
          {actions !== undefined ? <div className="rh-claim-card__actions">{actions}</div> : null}
        </div>
      }
      {...rest}
    >
      <p className="rh-claim-card__text">{claim.text}</p>
      <dl className="rh-claim-card__facts">
        <div className="rh-claim-card__fact">
          <dt className="rh-text-label">Type</dt>
          <dd className="rh-claim-card__fact-value">{claim.claimType}</dd>
        </div>
        <div className="rh-claim-card__fact">
          <dt className="rh-text-label">Scope</dt>
          <dd className="rh-claim-card__fact-value">{claim.scope}</dd>
        </div>
      </dl>
      {claim.wordingCeiling !== undefined ? (
        <p className="rh-claim-card__ceiling">
          <Icon name="info" size={14} />
          <span>
            <span className="rh-text-label">Wording ceiling</span> {claim.wordingCeiling}
          </span>
        </p>
      ) : null}
    </Card>
  );
});

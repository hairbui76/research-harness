import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { Badge } from '../../primitives/Badge';
import { Card } from '../../primitives/Card';
import { Icon } from '../../primitives/Icon';
import { cx } from '../../utils/cx';
import { EntityRef } from '../EntityRef';
import type { ConflictNoticeModel, EntityRefModel } from '../models';

export interface ConflictNoticeProps extends Omit<HTMLAttributes<HTMLElement>, 'children' | 'title'> {
  conflict: ConflictNoticeModel;
  /** Open either side of the disagreement. */
  onOpen?: (entity: EntityRefModel) => void;
  /** Heading text. Defaults to "Accepted state was used". */
  title?: ReactNode;
  /** Extra controls, e.g. "Promote the chat answer for review". */
  actions?: ReactNode;
}

/**
 * Remembered conversation disagreeing with accepted scientific state.
 *
 * The resolution is never in doubt — accepted state wins, and the assembler already sent
 * it. What the researcher needs is to *see* the disagreement: what the chat said, what the
 * project accepted, and why the accepted object outranked it. Both sides open, so a chat
 * turn that turns out to be right can be taken through review rather than argued with.
 */
export const ConflictNotice = forwardRef<HTMLElement, ConflictNoticeProps>(function ConflictNotice(
  { conflict, onOpen, title = 'Accepted state was used', actions, className, ...rest },
  ref,
) {
  return (
    <Card
      ref={ref}
      as="section"
      padding="sm"
      className={cx('rh-conflict-notice', className)}
      header={
        <>
          <span className="rh-conflict-notice__title">
            <Icon name="alert-triangle" size={16} />
            <span>{title}</span>
          </span>
          <Badge status="contested" size="sm" />
        </>
      }
      footer={actions === undefined ? undefined : actions}
      {...rest}
    >
      <p className="rh-conflict-notice__explanation">{conflict.explanation}</p>
      <div className="rh-conflict-notice__sides">
        <div className="rh-conflict-notice__side" data-side="accepted">
          <p className="rh-conflict-notice__side-label">
            <Icon name="circle-check" size={14} />
            <span>Accepted — sent to the model</span>
          </p>
          <EntityRef entity={conflict.accepted.ref} onOpen={onOpen} size="sm" />
          <blockquote className="rh-conflict-notice__excerpt">
            {conflict.accepted.excerpt}
          </blockquote>
        </div>
        <div className="rh-conflict-notice__side" data-side="chat">
          <p className="rh-conflict-notice__side-label">
            <Icon name="message-square" size={14} />
            <span>From this conversation — not used</span>
          </p>
          <EntityRef entity={conflict.chat.ref} onOpen={onOpen} size="sm" />
          <blockquote className="rh-conflict-notice__excerpt">{conflict.chat.excerpt}</blockquote>
        </div>
      </div>
    </Card>
  );
});

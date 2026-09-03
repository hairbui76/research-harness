import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode, Ref } from 'react';
import { Badge } from '../../primitives/Badge';
import { Icon } from '../../primitives/Icon';
import { IconButton } from '../../primitives/IconButton';
import { Menu } from '../../primitives/Menu';
import type { EntityRefModel } from '../../research/models';
import { cx } from '../../utils/cx';
import { MessageContent } from '../MessageContent';
import {
  MESSAGE_ROLE_META,
  PROMOTION_TARGETS,
  PROMOTION_TARGET_META,
  formatMessageTime,
} from '../models';
import type { AttachmentModel, MessageModel, PromotionTarget } from '../models';

export type MessageElement = 'article' | 'li' | 'div';

export interface MessageProps
  extends Omit<HTMLAttributes<HTMLElement>, 'children' | 'onCopy' | 'title'> {
  message: MessageModel;
  /** The application's Markdown/KaTeX renderer, handed straight to `MessageContent`. */
  renderMarkdown: (text: string) => ReactNode;
  onOpenRef?: (entity: EntityRefModel) => void;
  /** Start a new attempt. The failed attempt's metadata stays on the transcript. */
  onRetry?: () => void;
  /** Copy the message. This component never touches the clipboard itself. */
  onCopy?: () => void;
  /** Open the `Context used` receipt for the call that produced this message. */
  onOpenReceipt?: (contextPackId: string) => void;
  /** Promote the message into the host's review flow. Never mutates anything here. */
  onPromote?: (target: PromotionTarget) => void;
  /** Which promotions this host offers. Defaults to all four. */
  promotionTargets?: readonly PromotionTarget[];
  /** Extra controls in the action row, before the standard ones. */
  actions?: ReactNode;
  /** Page renderer for PDF attachments in this message. */
  renderPage?: (pageIndex: number) => ReactNode;
  altFor?: (attachment: AttachmentModel) => string;
  /** Override the timestamp formatting; the default is locale-independent. */
  formatTime?: (iso: string) => string;
  selected?: boolean;
  as?: MessageElement;
}

/**
 * One turn of a conversation.
 *
 * Everything that says where the turn came from — role, author, time, provider, model,
 * which attempt this is — sits in the header as text, so a transcript can be read and
 * explained months later. The action row is always visible rather than revealed on hover:
 * promotion and the context receipt are how a researcher gets from a chat answer to
 * reviewable state, and they must be reachable by keyboard without hunting.
 *
 * Promotion opens the host's review form. Nothing here accepts anything.
 */
export const Message = forwardRef<HTMLElement, MessageProps>(function Message(
  {
    message,
    renderMarkdown,
    onOpenRef,
    onRetry,
    onCopy,
    onOpenReceipt,
    onPromote,
    promotionTargets = PROMOTION_TARGETS,
    actions,
    renderPage,
    altFor,
    formatTime = formatMessageTime,
    selected = false,
    as = 'article',
    className,
    ...rest
  },
  ref,
) {
  const role = MESSAGE_ROLE_META[message.role];
  const Root = as as 'article';
  const retryable = message.status === 'failed' || message.status === 'incomplete';

  return (
    <Root
      ref={ref as Ref<HTMLElement>}
      className={cx('rh-message', selected && 'is-selected', className)}
      data-role={message.role}
      data-status={message.status}
      data-message-id={message.id}
      {...rest}
    >
      <header className="rh-message__header">
        <span className="rh-message__role">
          <Icon name={role.icon} size={16} />
          <span className="rh-message__role-label">{message.author ?? role.label}</span>
        </span>
        <span className="rh-message__meta">
          <span className="rh-message__id">{message.id}</span>
          <time className="rh-message__time" dateTime={message.createdAt}>
            {formatTime(message.createdAt)}
          </time>
          {message.provider !== undefined ? (
            <span className="rh-message__provider">{message.provider}</span>
          ) : null}
          {message.model !== undefined ? (
            <span className="rh-message__model">{message.model}</span>
          ) : null}
          {message.attempt !== undefined ? (
            <span className="rh-message__attempt">
              attempt {message.attempt}
              {message.attempts !== undefined ? ` of ${message.attempts}` : ''}
            </span>
          ) : null}
          {message.status === 'streaming' ? (
            <Badge tone="accent" icon="loader" size="sm">
              Streaming
            </Badge>
          ) : null}
          {message.status === 'incomplete' ? (
            <Badge tone="warning" icon="circle-dashed" size="sm">
              Incomplete
            </Badge>
          ) : null}
          {message.status === 'failed' ? (
            <Badge tone="error" icon="alert-circle" size="sm">
              Failed
            </Badge>
          ) : null}
        </span>
      </header>

      <MessageContent
        blocks={message.blocks}
        renderMarkdown={renderMarkdown}
        status={message.status}
        onOpenRef={onOpenRef}
        onRetry={onRetry}
        renderPage={renderPage}
        altFor={altFor}
      />

      <div className="rh-message__actions">
        {actions}
        {onCopy ? <IconButton icon="copy" label="Copy message" size="sm" onClick={onCopy} /> : null}
        {onRetry ? (
          <IconButton
            icon="rotate-ccw"
            label={retryable ? 'Retry this turn' : 'Ask again'}
            size="sm"
            onClick={onRetry}
          />
        ) : null}
        {onOpenReceipt && message.contextPackId !== undefined ? (
          <IconButton
            icon="list"
            label={`Context used (${message.contextPackId})`}
            size="sm"
            onClick={() => onOpenReceipt(message.contextPackId as string)}
          />
        ) : null}
        {onPromote && promotionTargets.length > 0 ? (
          <Menu>
            <Menu.Trigger asChild>
              <IconButton icon="arrow-up-right" label="Promote this message" size="sm" />
            </Menu.Trigger>
            <Menu.Content aria-label="Promote this message">
              {promotionTargets.map((target) => {
                const meta = PROMOTION_TARGET_META[target];
                return (
                  <Menu.Item
                    key={target}
                    icon={<Icon name={meta.icon} size={16} />}
                    onSelect={() => onPromote(target)}
                  >
                    {meta.label}
                  </Menu.Item>
                );
              })}
            </Menu.Content>
          </Menu>
        ) : null}
      </div>
    </Root>
  );
});

import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode, Ref } from 'react';
import { Badge } from '../../primitives/Badge';
import { Button } from '../../primitives/Button';
import { Icon } from '../../primitives/Icon';
import { IconButton } from '../../primitives/IconButton';
import { Menu } from '../../primitives/Menu';
import type { IconName } from '../../primitives/Icon';
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

/** Where copy, retry and the context receipt live in the action row. */
export type MessageSecondaryActions = 'inline' | 'menu';

/**
 * A control the host adds to the same place the message's own secondary acts go.
 *
 * A host that folds the row (`secondaryActions="menu"`) has one overflow, and a control it
 * contributes belongs *in* it rather than beside it: a transcript that adds Inspect, a
 * corpus save per attachment and attempt navigation to the row is exactly how eight
 * controls end up beside one paragraph. The shape is the same as the built-in acts, so
 * neither arrangement can offer a different set.
 */
export interface MessageMenuAction {
  key: string;
  icon: IconName;
  label: string;
  run: () => void;
}

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
  /**
   * Host controls that belong beside copy, retry and the receipt: in the overflow when the
   * row is folded, and on the row when it is not.
   */
  menuActions?: readonly MessageMenuAction[];
  /**
   * `inline` (the default) puts copy, retry and the context receipt on the row beside
   * promotion. `menu` folds them into one overflow, leaving promotion as the row's visible
   * action — for a host, like a transcript, that adds controls of its own to the row.
   */
  secondaryActions?: MessageSecondaryActions;
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
 * Always visible is not the same as all at once. The row is one named group, and
 * `secondaryActions="menu"` keeps promotion — the act that leads somewhere — on the page
 * while copy, retry and the receipt fold into a single overflow, which is how a host that
 * adds controls of its own keeps a turn from carrying eight of them.
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
    menuActions,
    secondaryActions = 'inline',
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

  const retry = onRetry ? (
    <IconButton
      icon="rotate-ccw"
      label={retryable ? 'Retry this turn' : 'Ask again'}
      size="sm"
      onClick={onRetry}
    />
  ) : null;

  /* Copy, the receipt, and asking again: the same acts whether they sit on the row or in
     the overflow, so neither arrangement can quietly offer a different set. Retry is the
     exception — a turn that failed or was cut short keeps it on the row, because recovery
     from an error is never something a researcher should have to open a menu to find. */
  const secondary: MessageMenuAction[] = [...(menuActions ?? [])];
  if (onCopy) secondary.push({ key: 'copy', icon: 'copy', label: 'Copy message', run: onCopy });
  if (onRetry && !retryable) {
    secondary.push({ key: 'retry', icon: 'rotate-ccw', label: 'Ask again', run: onRetry });
  }
  if (onOpenReceipt && message.contextPackId !== undefined) {
    const packId = message.contextPackId;
    secondary.push({
      key: 'receipt',
      icon: 'list',
      label: `Context used (${packId})`,
      run: () => onOpenReceipt(packId),
    });
  }
  // One control is not a crowd: an overflow holding a single item hides it for nothing.
  const folded = secondaryActions === 'menu' && secondary.length > 1;

  /*
   * The act that turns a conversation into scientific state, with its name on it.
   *
   * It was a 16px arrow between a labelled control and an overflow — the least legible thing
   * in the transcript, and the one thing on the row that leads somewhere. A label is what a
   * researcher recognises rather than recalls; the ellipsis says the same thing the arrow
   * was trying to, that a choice of destination follows.
   */
  const promotion =
    onPromote && promotionTargets.length > 0 ? (
      <Menu>
        <Menu.Trigger asChild>
          <Button size="sm" variant="secondary" iconStart="arrow-up-right">
            Promote…
          </Button>
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
    ) : null;

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

      <div
        className="rh-message__actions"
        role="group"
        aria-label={`Actions for ${message.id}`}
      >
        {actions}
        {folded && retryable ? retry : null}
        {folded ? promotion : null}
        {folded ? (
          <Menu>
            <Menu.Trigger asChild>
              <IconButton icon="more-horizontal" label="More actions" size="sm" />
            </Menu.Trigger>
            <Menu.Content aria-label={`More actions for ${message.id}`}>
              {secondary.map((item) => (
                <Menu.Item
                  key={item.key}
                  icon={<Icon name={item.icon} size={16} />}
                  onSelect={item.run}
                >
                  {item.label}
                </Menu.Item>
              ))}
            </Menu.Content>
          </Menu>
        ) : (
          <>
            {onCopy ? (
              <IconButton icon="copy" label="Copy message" size="sm" onClick={onCopy} />
            ) : null}
            {retry}
            {onOpenReceipt && message.contextPackId !== undefined ? (
              <IconButton
                icon="list"
                label={`Context used (${message.contextPackId})`}
                size="sm"
                onClick={() => onOpenReceipt(message.contextPackId as string)}
              />
            ) : null}
            {promotion}
          </>
        )}
      </div>
    </Root>
  );
});

import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { Icon } from '../../primitives/Icon';
import { ErrorNotice } from '../../states/ErrorNotice';
import { EntityRef } from '../../research/EntityRef';
import type { EntityRefModel } from '../../research/models';
import { cx } from '../../utils/cx';
import { AttachmentAuto } from '../attachmentAuto';
import type { AttachmentModel, MessageBlock, MessageStatus } from '../models';

export interface MessageContentProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  blocks: readonly MessageBlock[];
  /**
   * Renders one text block. Required, and deliberately not optional: Markdown and KaTeX are
   * the application's business — this package must not depend on `react-markdown` or
   * `katex` — so a surface that wants prose has to say how prose is drawn. Pass
   * `(text) => text` for a plain-text surface.
   */
  renderMarkdown: (text: string) => ReactNode;
  /** Drives the streaming live region and the interrupted marker. */
  status?: MessageStatus;
  onOpenRef?: (entity: EntityRefModel) => void;
  /** Retry the turn. Shown on the interrupted marker and on retryable error blocks. */
  onRetry?: () => void;
  /** Page renderer handed to any PDF attachment in the message. */
  renderPage?: (pageIndex: number) => ReactNode;
  /** Alt text for an image attachment, when the researcher recorded one. */
  altFor?: (attachment: AttachmentModel) => string;
}

/**
 * The body of one message: prose, references, attachments and failures, in order.
 *
 * A streaming message is a polite live region, so a screen reader hears the reply arrive
 * without being interrupted mid-sentence. An interrupted one keeps everything that did
 * arrive and says, in words, that it stopped early — partial content is never silently
 * presented as a finished answer, and it is never quietly thrown away either.
 */
export const MessageContent = forwardRef<HTMLDivElement, MessageContentProps>(
  function MessageContent(
    { blocks, renderMarkdown, status = 'complete', onOpenRef, onRetry, renderPage, altFor, className, ...rest },
    ref,
  ) {
    const gallery = blocks
      .filter(
        (block): block is Extract<MessageBlock, { kind: 'attachment' }> =>
          block.kind === 'attachment' && block.attachment.mediaType.startsWith('image/'),
      )
      .map((block) => block.attachment);

    const retryAction = onRetry
      ? [{ label: 'Retry', onClick: onRetry, iconStart: 'rotate-ccw' as const }]
      : undefined;

    return (
      <div
        ref={ref}
        className={cx('rh-message-content', className)}
        data-status={status}
        aria-live={status === 'streaming' ? 'polite' : undefined}
        aria-busy={status === 'streaming' ? true : undefined}
        {...rest}
      >
        {blocks.map((block, index) => {
          switch (block.kind) {
            case 'text':
              return (
                <div key={index} className="rh-message-content__text">
                  {renderMarkdown(block.text)}
                </div>
              );
            case 'reference':
              return (
                <div key={index} className="rh-message-content__reference">
                  <EntityRef entity={block.ref} onOpen={onOpenRef} />
                </div>
              );
            case 'attachment':
              return (
                <div key={index} className="rh-message-content__attachment">
                  <AttachmentAuto
                    attachment={block.attachment}
                    gallery={gallery.length > 1 ? gallery : undefined}
                    renderPage={renderPage}
                    alt={altFor?.(block.attachment)}
                  />
                </div>
              );
            case 'error':
              return (
                <ErrorNotice
                  key={index}
                  className="rh-message-content__error"
                  kind={block.retryable ? 'retryable' : 'fatal'}
                  title={block.message}
                  safety={{ draft: 'safe', source: 'safe' }}
                  actions={block.retryable ? retryAction : undefined}
                />
              );
          }
        })}

        {status === 'streaming' ? (
          <p className="rh-message-content__streaming">
            <Icon name="loader" size={14} />
            <span>Streaming…</span>
          </p>
        ) : null}

        {status === 'incomplete' ? (
          <ErrorNotice
            className="rh-message-content__interrupted"
            kind="partial"
            title="Incomplete — response was interrupted"
            description="Everything that arrived before the connection dropped is kept above and marked partial."
            safety={{
              draft: 'safe',
              source: 'safe',
              note: 'Nothing was accepted into the corpus from a partial reply.',
            }}
            actions={retryAction}
          />
        ) : null}
      </div>
    );
  },
);

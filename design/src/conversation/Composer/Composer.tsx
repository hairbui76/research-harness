import { forwardRef, useCallback, useLayoutEffect, useRef, useState } from 'react';
import type {
  ChangeEvent,
  DragEvent as ReactDragEvent,
  HTMLAttributes,
  KeyboardEvent as ReactKeyboardEvent,
  ReactNode,
} from 'react';
import { useId } from '../../hooks/useId';
import { Button } from '../../primitives/Button';
import { Icon } from '../../primitives/Icon';
import { IconButton } from '../../primitives/IconButton';
import { Tag } from '../../primitives/Tag';
import { Textarea } from '../../primitives/Textarea';
import type { EntityRefModel } from '../../research/models';
import { ErrorNotice } from '../../states/ErrorNotice';
import { cx } from '../../utils/cx';
import { ReferencePicker } from '../ReferencePicker';
import type { ComposerBlockedReason, ComposerSendState, ComposerValue } from '../models';

/** `@` only opens the picker at a word boundary, so an e-mail address is left alone. */
const AT_TRIGGER = /(?:^|\s)@([^\s@]*)$/;

/**
 * The horizontal offset of the caret inside a textarea, for anchoring the picker.
 *
 * A textarea exposes no caret geometry, so the text before the caret is measured in a
 * mirror element that copies the box's typography. Where there is no layout engine — jsdom,
 * SSR — every measurement is 0 and the panel simply anchors at the start of the box.
 */
function caretOffsetLeft(textarea: HTMLTextAreaElement, caret: number): number {
  const doc = textarea.ownerDocument;
  const view = doc.defaultView;
  if (view === null) return 0;
  const source = view.getComputedStyle(textarea);
  const mirror = doc.createElement('div');
  for (const property of [
    'fontFamily',
    'fontSize',
    'fontWeight',
    'lineHeight',
    'letterSpacing',
    'paddingLeft',
    'paddingRight',
    'borderLeftWidth',
    'borderRightWidth',
    'width',
  ] as const) {
    mirror.style[property] = source[property];
  }
  mirror.style.position = 'absolute';
  mirror.style.top = '0';
  mirror.style.left = '-9999px';
  mirror.style.visibility = 'hidden';
  mirror.style.whiteSpace = 'pre-wrap';
  mirror.style.overflowWrap = 'break-word';
  mirror.textContent = textarea.value.slice(0, caret);
  const marker = doc.createElement('span');
  marker.textContent = '\u200b';
  mirror.appendChild(marker);
  doc.body.appendChild(mirror);
  const left = marker.offsetLeft;
  doc.body.removeChild(mirror);
  return left;
}

export interface ComposerProps
  extends Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'onChange'> {
  /**
   * The draft. Drafts survive navigation, refresh and a failed send because the
   * application owns them — this component keeps no copy of the researcher's words.
   */
  value: ComposerValue;
  onChange: (value: ComposerValue) => void;
  onSend: () => void;
  /** Stop a streaming response. Whatever arrived is kept by the host. */
  onStop?: () => void;
  /** Retry the last attempt. */
  onRetry?: () => void;
  sendState?: ComposerSendState;
  /** Accessible name for the text box. Defaults to "Message". */
  label?: string;
  placeholder?: string;
  /** Rows the box grows to before it scrolls. Default 12. */
  maxRows?: number;
  disabled?: boolean;
  /**
   * Why the host will not send. Rendered as a blocking notice with the send disabled; the
   * draft and its attachments are left exactly as they are.
   */
  blockedReasons?: readonly ComposerBlockedReason[];
  /** Matches for the `@` picker, found by the host. */
  referenceResults?: readonly EntityRefModel[];
  onReferenceQuery?: (query: string) => void;
  referenceLoading?: boolean;
  /** The `AttachmentTray` for this draft. */
  attachmentTray?: ReactNode;
  /** The `ModelSelector` for this session. */
  modelSelector?: ReactNode;
  /** Extra controls in the toolbar, before the send button. */
  actions?: ReactNode;
  /** Receives dropped or chosen files. Validation is the host's. */
  onAttach?: (files: File[]) => void;
  /** `accept` for the file picker. */
  attachAccept?: string;
  /** Overrides the keyboard hint under the box. */
  hint?: ReactNode;
  /**
   * Where an unpublished message would go, stated for as long as the composer is open.
   *
   * A standing fact, not an announcement: it keeps its own line beside the keyboard hint,
   * it is part of the text box's own description, and it is never a live region — a
   * researcher forty messages into a session should be able to look, not be told again on
   * every render. Every word is the host's; nothing here derives or decorates a
   * destination, because where research content goes is not a presentation decision.
   */
  destination?: ReactNode;
  /**
   * A capability note that belongs beside the destination, not above the box.
   *
   * Which index is answering reference completion, and what to do about it, is a standing
   * fact about what the composer can do — not a failure of anything the researcher just
   * did. It shares the destination's row, so the one notice slot above the box stays for
   * the thing that actually stopped a send.
   */
  note?: ReactNode;
  /**
   * What the paperclip accepts, given to the paperclip.
   *
   * A permanent strip inside the box explaining the drop target was the loudest thing on
   * an empty conversation, so this is the button's own description instead; the host shows
   * the visible version while a file is actually over the box.
   */
  attachHint?: ReactNode;
  sendLabel?: string;
}

/**
 * The message composer: prose, structured references, attachments, and one send.
 *
 * References typed with `@` become tokens beside the text rather than characters inside it,
 * so what gets resolved at send time is an object and not a string that looks like an id.
 * A blocked send says which attachment is the problem and what would accept it, and it
 * never edits, clears or silently drops any part of the draft — the whole point of the
 * blocking notice is that the researcher's words and files survive it.
 *
 * Focus returns to the text box after send and stop, so a keyboard user can keep typing.
 */
export const Composer = forwardRef<HTMLDivElement, ComposerProps>(function Composer(
  {
    value,
    onChange,
    onSend,
    onStop,
    onRetry,
    sendState = 'idle',
    label = 'Message',
    placeholder = 'Ask about this project. Type @ to reference a work, evidence or claim.',
    maxRows = 12,
    disabled = false,
    blockedReasons,
    referenceResults = [],
    onReferenceQuery,
    referenceLoading = false,
    attachmentTray,
    modelSelector,
    actions,
    onAttach,
    attachAccept,
    hint,
    destination,
    note,
    attachHint,
    sendLabel = 'Send',
    className,
    ...rest
  },
  ref,
) {
  const baseId = useId(undefined, 'rh-composer');
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState('');
  const [pickerLeft, setPickerLeft] = useState(0);
  const triggerStart = useRef<number | null>(null);
  const [dragging, setDragging] = useState(false);

  const blocked = blockedReasons !== undefined && blockedReasons.length > 0;
  const empty = value.text.trim().length === 0 && value.tokens.length === 0;
  const busy = sendState !== 'idle';
  const canSend = !disabled && !blocked && !busy && !empty;

  // Grow with the text up to `maxRows`, then scroll. Without layout (jsdom, SSR)
  // scrollHeight is 0 and the box keeps its rows attribute.
  useLayoutEffect(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.style.height = 'auto';
    const scrollHeight = node.scrollHeight;
    if (scrollHeight <= 0) return;
    const view = node.ownerDocument.defaultView;
    const lineHeight = view ? Number.parseFloat(view.getComputedStyle(node).lineHeight) : Number.NaN;
    const max = Number.isFinite(lineHeight) ? lineHeight * maxRows : Number.POSITIVE_INFINITY;
    node.style.height = `${Math.min(scrollHeight, max)}px`;
  }, [maxRows, value.text]);

  const focusTextarea = useCallback((caret?: number): void => {
    const node = textareaRef.current;
    if (!node) return;
    node.focus();
    if (caret !== undefined) node.setSelectionRange(caret, caret);
  }, []);

  const closePicker = useCallback(
    (restoreFocus: boolean): void => {
      setPickerOpen(false);
      setPickerQuery('');
      const caret = triggerStart.current;
      triggerStart.current = null;
      if (restoreFocus) focusTextarea(caret === null ? undefined : caret + 1);
    },
    [focusTextarea],
  );

  const handleTextChange = (event: ChangeEvent<HTMLTextAreaElement>): void => {
    const next = event.target.value;
    onChange({ ...value, text: next });
    if (pickerOpen) return;
    const caret = event.target.selectionStart ?? next.length;
    const match = AT_TRIGGER.exec(next.slice(0, caret));
    if (match === null) return;
    const query = match[1] ?? '';
    triggerStart.current = caret - query.length - 1;
    setPickerLeft(caretOffsetLeft(event.target, caret));
    setPickerQuery(query);
    setPickerOpen(true);
    onReferenceQuery?.(query);
  };

  const handleTextKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.key === 'Enter' && !event.shiftKey) {
      // IME composition also fires Enter; sending mid-composition eats the candidate.
      if (event.nativeEvent.isComposing) return;
      event.preventDefault();
      if (canSend) {
        onSend();
        focusTextarea();
      }
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      if (pickerOpen) closePicker(true);
      else textareaRef.current?.blur();
    }
  };

  const insertReference = (entity: EntityRefModel): void => {
    const start = triggerStart.current;
    const text =
      start === null
        ? value.text
        : `${value.text.slice(0, start)}${value.text.slice(start + 1 + pickerQuery.length)}`;
    const tokens = value.tokens.some((token) => token.id === entity.id)
      ? value.tokens
      : [...value.tokens, entity];
    onChange({ text, tokens });
    setPickerOpen(false);
    setPickerQuery('');
    triggerStart.current = null;
    focusTextarea(start ?? text.length);
  };

  const removeToken = (id: string): void => {
    onChange({ ...value, tokens: value.tokens.filter((token) => token.id !== id) });
  };

  const handleDrop = (event: ReactDragEvent<HTMLDivElement>): void => {
    setDragging(false);
    if (onAttach === undefined) return;
    event.preventDefault();
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length > 0) onAttach(files);
  };

  return (
    <div
      ref={ref}
      className={cx('rh-composer', dragging && 'is-dragging', className)}
      data-send-state={sendState}
      data-blocked={blocked || undefined}
      onDragOver={
        onAttach === undefined
          ? undefined
          : (event) => {
              event.preventDefault();
              setDragging(true);
            }
      }
      onDragLeave={onAttach === undefined ? undefined : () => setDragging(false)}
      onDrop={onAttach === undefined ? undefined : handleDrop}
      {...rest}
    >
      {attachmentTray}

      {blocked ? (
        <ErrorNotice
          className="rh-composer__blocked"
          kind="blocked"
          title="This message cannot be sent yet"
          safety={{
            draft: 'safe',
            note: 'Your message and its attachments are untouched.',
          }}
        >
          <ul className="rh-composer__blocked-list">
            {blockedReasons?.map((reason, index) => (
              <li key={`${reason.attachmentId ?? 'message'}-${index}`}>
                {reason.reason}
                {reason.suggestedModel !== undefined ? <> Try {reason.suggestedModel}.</> : null}
              </li>
            ))}
          </ul>
        </ErrorNotice>
      ) : null}

      {value.tokens.length > 0 ? (
        <ul className="rh-composer__tokens" aria-label="References in this message">
          {value.tokens.map((token) => (
            <li key={token.id}>
              <Tag
                icon="at-sign"
                size="sm"
                onRemove={() => removeToken(token.id)}
                removeLabel={`Remove reference ${token.id}`}
              >
                {token.id}
                {token.label !== undefined ? ` ${token.label}` : ''}
              </Tag>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="rh-composer__field">
        <Textarea
          ref={textareaRef}
          className="rh-composer__textarea"
          label={label}
          hideLabel
          rows={3}
          resize="none"
          placeholder={placeholder}
          disabled={disabled}
          value={value.text}
          aria-describedby={
            destination === undefined
              ? `${baseId}-hint`
              : `${baseId}-hint ${baseId}-destination`
          }
          onChange={handleTextChange}
          onKeyDown={handleTextKeyDown}
        />
        {pickerOpen ? (
          <div
            className="rh-composer__picker"
            style={{ insetInlineStart: `${pickerLeft}px` }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') closePicker(true);
            }}
          >
            <ReferencePicker
              results={referenceResults}
              query={pickerQuery}
              loading={referenceLoading}
              autoFocus
              defaultOpen
              onQueryChange={(next) => {
                setPickerQuery(next);
                onReferenceQuery?.(next);
              }}
              onSelect={insertReference}
            />
          </div>
        ) : null}
      </div>

      <div className="rh-composer__toolbar">
        {onAttach ? (
          <>
            {/* `hidden` rather than visually hidden: the button beside it is the control,
                and a second file input in the tab order would be a duplicate of it. */}
            <input
              ref={fileInputRef}
              hidden
              type="file"
              multiple
              accept={attachAccept}
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                if (files.length > 0) onAttach(files);
                event.target.value = '';
              }}
            />
            <IconButton
              icon="paperclip"
              label="Attach files"
              size="sm"
              disabled={disabled}
              {...(attachHint === undefined
                ? {}
                : { 'aria-describedby': `${baseId}-attach-hint` })}
              onClick={() => fileInputRef.current?.click()}
            />
            {attachHint === undefined ? null : (
              <span className="rh-visually-hidden" id={`${baseId}-attach-hint`}>
                {attachHint}
              </span>
            )}
          </>
        ) : null}
        {modelSelector}
        <span className="rh-composer__spacer" />
        {actions}
        {onRetry ? (
          <Button size="sm" variant="secondary" iconStart="rotate-ccw" onClick={onRetry}>
            Retry
          </Button>
        ) : null}
        {busy && onStop ? (
          <Button
            size="sm"
            variant="secondary"
            iconStart="square"
            onClick={() => {
              onStop();
              focusTextarea();
            }}
          >
            Stop
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="accent"
          iconStart="send"
          loading={sendState === 'sending'}
          loadingLabel="Sending"
          disabled={!canSend}
          onClick={() => {
            onSend();
            focusTextarea();
          }}
        >
          {sendLabel}
        </Button>
      </div>

      <p className="rh-composer__hint" id={`${baseId}-hint`}>
        {hint ?? (
          <>
            <Icon name="corner-down-left" size={14} />
            <span>
              Enter sends · Shift+Enter starts a new line · @ inserts a research reference
            </span>
          </>
        )}
      </p>

      {destination === undefined && note === undefined ? null : (
        <div className="rh-composer__footer">
          {destination === undefined ? null : (
            <p className="rh-composer__destination" id={`${baseId}-destination`}>
              {destination}
            </p>
          )}
          {note === undefined ? null : <div className="rh-composer__note">{note}</div>}
        </div>
      )}
    </div>
  );
});

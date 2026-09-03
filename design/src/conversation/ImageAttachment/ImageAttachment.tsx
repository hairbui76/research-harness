import { forwardRef, useEffect, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react';
import { useControllableState } from '../../hooks/useControllableState';
import { Dialog } from '../../primitives/Dialog';
import { Icon } from '../../primitives/Icon';
import { IconButton } from '../../primitives/IconButton';
import { cx } from '../../utils/cx';
import {
  AttachmentBlockedReason,
  AttachmentFacts,
  AttachmentStateBadge,
} from '../attachmentParts';
import type { AttachmentModel } from '../models';

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;
const ZOOM_STEP = 0.25;

function clampZoom(zoom: number): number {
  return Math.min(Math.max(Number(zoom.toFixed(2)), MIN_ZOOM), MAX_ZOOM);
}

export interface ImageAttachmentProps {
  attachment: AttachmentModel;
  /**
   * The images this one belongs to. The viewer's arrow keys move between them, so a
   * researcher who attached six figures reads them as a set rather than six dialogs.
   * Defaults to the single attachment.
   */
  gallery?: readonly AttachmentModel[];
  /**
   * Alt text. Defaults to the file name, which is honest but rarely useful: pass the
   * researcher's description when there is one. It is deliberately separate from any
   * scientific interpretation of the image.
   */
  alt?: string;
  /** Alt text for other images in the gallery. */
  altFor?: (attachment: AttachmentModel) => string;
  /** Controls at the end of the thumbnail row: remove, retry. */
  actions?: ReactNode;
  /** Extra content under the facts, e.g. a `SaveToCorpusAction`. */
  children?: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  size?: 'sm' | 'md';
  className?: string;
}

/**
 * An image attachment: a thumbnail in the composer or the transcript, and a viewer.
 *
 * The viewer zooms with `+`, `-` and `0`, and moves through the gallery with the arrow
 * keys, so nothing in it needs a pointer. Zoom is a CSS transform on the original bytes —
 * the image is never resampled, downloaded again or sent anywhere by opening it.
 */
export const ImageAttachment = forwardRef<HTMLDivElement, ImageAttachmentProps>(
  function ImageAttachment(
    {
      attachment,
      gallery,
      alt,
      altFor,
      actions,
      children,
      open,
      defaultOpen = false,
      onOpenChange,
      size = 'md',
      className,
    },
    ref,
  ) {
    const images = gallery ?? [attachment];
    const startIndex = Math.max(
      0,
      images.findIndex((item) => item.id === attachment.id),
    );
    const [isOpen, setOpen] = useControllableState<boolean>({
      value: open,
      defaultValue: defaultOpen,
      onChange: onOpenChange,
    });
    const [index, setIndex] = useState(startIndex);
    const [zoom, setZoom] = useState(1);

    // Reopening starts on the image that was clicked, at its natural size.
    useEffect(() => {
      if (isOpen) {
        setIndex(startIndex);
        setZoom(1);
      }
    }, [isOpen, startIndex]);

    const current = images[index] ?? attachment;
    const altText = (index === startIndex ? alt : undefined) ?? altFor?.(current) ?? current.name;

    const move = (delta: number): void => {
      if (images.length < 2) return;
      setIndex((previous) => (previous + delta + images.length) % images.length);
      setZoom(1);
    };

    const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>): void => {
      switch (event.key) {
        case 'ArrowRight':
          event.preventDefault();
          move(1);
          return;
        case 'ArrowLeft':
          event.preventDefault();
          move(-1);
          return;
        case '+':
        case '=':
          event.preventDefault();
          setZoom((value) => clampZoom(value + ZOOM_STEP));
          return;
        case '-':
        case '_':
          event.preventDefault();
          setZoom((value) => clampZoom(value - ZOOM_STEP));
          return;
        case '0':
          event.preventDefault();
          setZoom(1);
          return;
        default:
      }
    };

    return (
      <div
        ref={ref}
        className={cx('rh-image-attachment', `rh-image-attachment--${size}`, className)}
        data-state={attachment.state}
      >
        <button
          type="button"
          className="rh-image-attachment__thumb"
          aria-label={`Open ${attachment.name}`}
          onClick={() => setOpen(true)}
        >
          {attachment.thumbnailUrl !== undefined ? (
            <img
              className="rh-image-attachment__image"
              src={attachment.thumbnailUrl}
              alt={alt ?? attachment.name}
            />
          ) : (
            <span className="rh-image-attachment__placeholder">
              <Icon name="image" size={20} />
              <span>{attachment.name}</span>
            </span>
          )}
        </button>
        <div className="rh-image-attachment__body">
          <span className="rh-image-attachment__name" title={attachment.name}>
            {attachment.name}
          </span>
          <span className="rh-image-attachment__meta">
            <AttachmentStateBadge attachment={attachment} />
            <AttachmentFacts attachment={attachment} />
          </span>
          <AttachmentBlockedReason attachment={attachment} />
          {children}
        </div>
        {actions !== undefined ? (
          <div className="rh-image-attachment__actions">{actions}</div>
        ) : null}

        <Dialog
          open={isOpen}
          onOpenChange={setOpen}
          size="lg"
          className="rh-image-gallery"
          onKeyDown={handleKeyDown}
        >
          <Dialog.Header>{current.name}</Dialog.Header>
          <Dialog.Body>
            <p className="rh-image-gallery__position" role="status">
              {images.length > 1 ? `${index + 1} of ${images.length} · ` : ''}
              {current.name} · {Math.round(zoom * 100)}%
            </p>
            <div className="rh-image-gallery__stage">
              {current.previewUrl ?? current.thumbnailUrl ? (
                <img
                  className="rh-image-gallery__image"
                  src={current.previewUrl ?? current.thumbnailUrl}
                  alt={altText}
                  style={{ transform: `scale(${zoom})` }}
                />
              ) : (
                <p className="rh-image-gallery__unavailable">
                  No preview is available for this file. The original bytes are unchanged in the
                  session and can still be downloaded.
                </p>
              )}
            </div>
            <p className="rh-image-gallery__hint">
              Arrow keys move between images. <kbd>+</kbd> and <kbd>-</kbd> zoom, <kbd>0</kbd>{' '}
              resets.
            </p>
          </Dialog.Body>
          <Dialog.Footer>
            <div className="rh-image-gallery__controls">
              <IconButton
                icon="chevron-left"
                label="Previous image"
                disabled={images.length < 2}
                onClick={() => move(-1)}
              />
              <IconButton
                icon="chevron-right"
                label="Next image"
                disabled={images.length < 2}
                onClick={() => move(1)}
              />
              <IconButton
                icon="zoom-out"
                label="Zoom out"
                disabled={zoom <= MIN_ZOOM}
                onClick={() => setZoom((value) => clampZoom(value - ZOOM_STEP))}
              />
              <IconButton
                icon="zoom-in"
                label="Zoom in"
                disabled={zoom >= MAX_ZOOM}
                onClick={() => setZoom((value) => clampZoom(value + ZOOM_STEP))}
              />
              <IconButton icon="maximize" label="Reset zoom" onClick={() => setZoom(1)} />
            </div>
            {current.downloadUrl !== undefined ? (
              <a
                className="rh-image-gallery__download"
                href={current.downloadUrl}
                download={current.name}
              >
                <Icon name="download" size={16} />
                <span>Download original</span>
              </a>
            ) : null}
          </Dialog.Footer>
        </Dialog>
      </div>
    );
  },
);

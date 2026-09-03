/**
 * The composer's attachment tray: the files riding along with this draft.
 *
 * Every row is its own story. Its own lifecycle state, spelled as a word and not as a
 * colour; its own reason for being unsendable, with the model the daemon suggests instead;
 * its own remove, its own retry, and its own `Save to corpus`. That is the whole point of
 * per-item failure: one PDF that will not validate must not take the draft, the other
 * attachments, or the researcher's message with it.
 *
 * The tray renders the *daemon's* answers. `attachment.check_send` decided what can be
 * sent, `attachment.resolve_identity` decided what a save would mean, and this component
 * chooses none of it.
 */
import type { ReactNode } from 'react';
import { AttachmentTray, ErrorNotice } from '@research-harness/design';
import type { EntityRefModel } from '@research-harness/design';
import { AttachmentIntake } from './AttachmentIntake';
import { SaveOutcome, saveSlicesFor } from './SaveToCorpusFlow';
import type { AttachmentWorkspace } from './useAttachments';

export interface AttachmentTrayPaneProps {
  attachments: AttachmentWorkspace;
  renderPage?: (attachmentId: string, pageIndex: number) => ReactNode;
  onOpenRef?: (entity: EntityRefModel) => void;
}

export function AttachmentTrayPane({
  attachments,
  renderPage,
  onOpenRef,
}: AttachmentTrayPaneProps) {
  const { files, save, send } = attachments;

  return (
    <AttachmentIntake files={files}>
      {send.error !== null ? (
        <ErrorNotice
          kind="partial"
          title="These attachments could not be checked against the selected model"
          description={send.error}
          safety={{
            draft: 'safe',
            note:
              'Nothing was dropped. The daemon runs the same check when the message is sent ' +
              'and will refuse there, with your words and your files untouched.',
          }}
        />
      ) : null}

      <AttachmentTray
        attachments={files.models}
        label="Attachments on this message"
        {...(files.canAttach ? { onRemove: (id: string) => void files.remove(id) } : {})}
        {...(files.canAttach ? { onRetry: (id: string) => void files.retry(id) } : {})}
        {...(renderPage ? { renderPage } : {})}
        {...(save.canSave
          ? {
              save: saveSlicesFor(files.models, save),
              onSaveStart: save.start,
              onSaveConfirm: save.confirm,
              onSaveRetry: save.retry,
              onSaveCancel: save.cancel,
            }
          : {})}
        {...(onOpenRef ? { onOpenRef } : {})}
      />

      {/* What a finished save linked, and what it deliberately did not create. The Design
          System's action shows the ids; the boundary sentence belongs to the product. */}
      {files.models.map((attachment) => (
        <SaveOutcome key={attachment.id} attachmentId={attachment.id} save={save} />
      ))}
    </AttachmentIntake>
  );
}

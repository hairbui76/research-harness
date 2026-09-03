/**
 * Bytes for the attachments already in a transcript.
 *
 * The two session byte routes carry the daemon's token in an `Authorization` header, the
 * way `HarnessClient.artifactBytes` does, so they cannot be dropped into an `<img src>`.
 * The bytes are therefore fetched and turned into object URLs, which is also what keeps
 * the no-network rule true: an attachment is drawn from the local daemon's response and
 * from nothing else. Every URL is revoked when it stops being used.
 *
 * This hook *renders* what a session already holds. Choosing files, validating them and
 * uploading them is task W2 (`attachment.add` and the multipart route); the composer's
 * `onAttach` and `attachmentTray` slots are where that lands, and nothing here changes
 * when it does.
 */
import { useEffect, useState } from 'react';
import type { HarnessClient } from '../../api/client';
import type { SessionAttachmentRecord } from '../../api/dto';

/** The URLs one attachment can be drawn from, all of them object URLs for this tab. */
export interface AttachmentUrls {
  downloadUrl?: string;
  previewUrl?: string;
  thumbnailUrl?: string;
}

/** States in which the bytes are durably in the session and worth asking for. */
const STORED = new Set(['ready', 'sending', 'session_only', 'promoting', 'in_corpus']);

function objectUrl(bytes: ArrayBuffer, mediaType: string): string | null {
  try {
    return URL.createObjectURL(new Blob([bytes], { type: mediaType }));
  } catch {
    // jsdom and any browser without object URLs: the attachment still renders its name,
    // size and state, which is the part that must never be missing.
    return null;
  }
}

export function useAttachmentUrls(
  client: HarnessClient,
  sessionId: string | null,
  records: readonly SessionAttachmentRecord[],
): Map<string, AttachmentUrls> {
  const [urls, setUrls] = useState<Map<string, AttachmentUrls>>(new Map());
  // The ids, so a re-rendered but unchanged list does not re-fetch every file.
  const key = records.map((record) => `${record.id}:${record.state}`).join(',');

  useEffect(() => {
    if (!sessionId) return;
    const wanted = records.filter((record) => STORED.has(record.state));
    if (wanted.length === 0) {
      setUrls(new Map());
      return;
    }
    let live = true;
    const created: string[] = [];

    void (async () => {
      const found = new Map<string, AttachmentUrls>();
      for (const record of wanted) {
        try {
          const bytes = await client.sessionAttachmentBytes(sessionId, record.id);
          const url = objectUrl(bytes, record.media_type);
          if (url === null) continue;
          created.push(url);
          const entry: AttachmentUrls = { downloadUrl: url };
          if (record.media_type.startsWith('image/')) {
            entry.previewUrl = url;
            entry.thumbnailUrl = url;
          } else if (record.media_type === 'application/pdf') {
            // A PDF's first page is a rendered preview, not the file itself.
            const preview = await client
              .sessionAttachmentPreview(sessionId, record.id, 1)
              .catch(() => null);
            const previewUrl = preview === null ? null : objectUrl(preview, 'image/png');
            if (previewUrl !== null) {
              created.push(previewUrl);
              entry.thumbnailUrl = previewUrl;
            }
          }
          found.set(record.id, entry);
        } catch {
          // A file the daemon will not hand over is still listed by name and state.
        }
      }
      if (live) setUrls(found);
      else for (const url of created) URL.revokeObjectURL(url);
    })();

    return () => {
      live = false;
      for (const url of created) {
        try {
          URL.revokeObjectURL(url);
        } catch {
          /* nothing to revoke */
        }
      }
    };
    // Keyed on the ids and their states rather than on the array itself: a transcript
    // re-render hands over a new array with the same files in it.
  }, [client, key, records, sessionId]);

  return urls;
}

# Research Attachments — Design Specification

**Status:** Design approved in conversation; awaiting review of this written specification.

**Scope:** Design only; no implementation is authorised by this document.

## 1. Purpose

Let a researcher add images, PDFs, and other supported files to a conversation without silently changing the scientific corpus. Attachments are session working material until the researcher explicitly chooses `Save to corpus`.

## 2. Lifecycle

```text
selected → validating → ready → sending → session-only
                  │          │             │
                  └→ failed  └→ failed     └→ Save to corpus
                                               │
                                     promoting → in corpus
                                               └→ failed
```

An attachment gets a stable session attachment ID (`SA####`) as soon as it is durably copied into the session. Failure of one attachment does not remove other ready attachments or the composer draft.

## 3. Session-only by default

All attachments, including PDFs, initially live under:

```text
conversations/<session-id>/attachments/
```

They may be sent to a model only when the selected model supports the media and the project/provider egress policy permits it. They are not searchable as accepted corpus works and do not receive Work/Version/Artifact identity merely because they were attached.

## 4. Presentation

### Images

- thumbnail in the composer and transcript;
- gallery navigation when multiple images are attached;
- zoom/pan and original-file download;
- clear processing, unsupported, omitted, and failed states;
- optional alt text or description captured separately from scientific interpretation.

### PDFs

- file card with name, size, page count when known, and status;
- page preview/viewer;
- page navigation and download;
- `Save to corpus` action available from the composer, transcript, viewer, and inspector;
- no implication that preview or model reading equals corpus ingestion or evidence acceptance.

### Other files

Supported files receive an appropriate preview or metadata card. Unsupported formats remain visible and explain which model or conversion path is required.

## 5. Model compatibility and send behaviour

Before sending, the workspace validates every attachment against:

- selected model input capabilities;
- size/page/count constraints;
- provider egress rules;
- local conversion availability;
- project privacy classification.

If an item cannot be sent, the send action is blocked with a per-item reason and, where possible, a compatible model suggestion. The product never silently drops an attachment the researcher reasonably believes will be considered.

The response's `Context used` receipt identifies each attachment sent, converted, or omitted.

## 6. `Save to corpus`

Promotion is explicit and uses existing corpus identity rules:

1. compute content hash and inspect available metadata;
2. detect exact Artifact duplication and possible Work/Version matches;
3. let the researcher confirm an existing Work/Version or create the missing identity;
4. copy the immutable artifact into canonical corpus storage;
5. run the normal parsing/indexing workflow;
6. retain a link from the session attachment to the resulting Work, Version, and Artifact.

Saving never overwrites a different artifact. Ambiguous identity is presented for resolution. A failed promotion leaves the original session attachment intact and retryable.

## 7. Evidence boundary

`Save to corpus` creates or links corpus identity; it does not accept Evidence, Claims, or scientific interpretations. Evidence extraction from the saved artifact still follows candidate, verification, and review gates with exact anchors.

## 8. Privacy, safety, and retention

- Original attachment bytes remain local unless an authorised model request or explicit export sends them elsewhere.
- The interface names the destination provider before external egress.
- Temporary conversions and thumbnails are projections and can be rebuilt.
- Session deletion and attachment deletion are separate, explicit retention operations and are outside this design's automatic behaviours.
- File names are display metadata, not trusted paths; previews must not execute embedded content.

## 9. Acceptance scenarios

1. Drag an image and a PDF into a draft; preview both without creating corpus objects.
2. Send them with a compatible model and inspect both in `Context used`.
3. Choose an incompatible model; block send and retain the complete draft and attachments.
4. Save the PDF to an existing Work as a new Version/Artifact after identity confirmation.
5. Save the same bytes again and resolve to the existing Artifact without duplication.
6. Fail during corpus promotion and confirm the session copy remains usable and retryable.
7. Verify that saving to corpus does not create accepted Evidence automatically.

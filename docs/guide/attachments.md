# Attachments

A file you attach to a session is **working material**, not corpus state. It gets an
`SA####` identity as soon as its bytes are copied into `conversations/<session>/attachments/`,
and that is all attaching creates: no Work, no Version, no Artifact, no Evidence, no Claim.
Turning it into corpus identity is one explicit command, `research attachment save`
(ADR-026, PRODUCT §42 N).

## Attaching

```console
$ research attachment add CS0001 ~/papers/netgpt.pdf
SA0001  netgpt.pdf  application/pdf  1841203 bytes  [ready]
  pages              10
  content hash       sha256:8f2c…
  visibility         private
session-only: no Work, Version, Artifact, or Evidence was created

$ research attachment list CS0001
$ research attachment remove CS0001 SA0001      # deletes the bytes and the previews
```

The media type is sniffed from the bytes (`--media-type` overrides it); the filename is
kept for you to read and is never used as a path. `--description` records alt text or a
description, deliberately kept apart from any scientific reading of the file.
`--visibility` defaults to the session's.

One bad file never costs a good one. Attaching five files where one is corrupt leaves four
`ready` attachments and one `failed` one carrying its reason, and a `failed` attachment can
be retried rather than having to be re-added.

Previews (an image thumbnail, a rendered PDF page) are projections under
`.research/cache/attachments/`. Deleting the cache costs a re-render.

## What blocks a send

Before anything leaves the machine, every attachment in the composer is checked against the
selected model and the project's policy. The check is a *total* function: each attachment
comes back `sent`, `converted`, or `omitted` with a reason, and any **ready** attachment
that cannot go blocks the whole send.

```console
$ research attachment check CS0001 --provider local
model  local/qwen2.5-7b-instruct
BLOCKED SA0002  omitted   synthetic_two_column_paper.pdf
          the selected model does not accept application/pdf input
BLOCKED SA0003  omitted   tiny.png
          the selected model does not accept image/png input
          try vision/gpt-4o-mini

2 attachment(s) cannot be sent to local/qwen2.5-7b-instruct: …
```

What is checked, and what each answer means:

| check | outcome |
|---|---|
| the model's declared input media | a text-only model gets `unsupported_media`; text attachments are `converted` (inlined) rather than refused |
| size, page count, and how many items one request may carry | `unsupported_media`, or `token_budget` for the count ceiling |
| the egress policy and the endpoint | `egress_blocked` — see [Providers](providers.md) |
| the attachment's visibility | a `private` attachment is not offered to an external endpoint |
| whether another configured entry could take it | the refusal names it: `try vision/gpt-4o-mini` |

Two things worth knowing:

* `attachment.check_send` needs a `providers:` list in `research.yaml` to have something to
  check against. A workspace with no providers configured answers "no model providers
  configured" rather than guessing.
* A **private** attachment gets no external-model suggestion, because suggesting one would
  be suggesting an egress the policy forbids. The refusal is still per-item; only the
  "try …" line is absent.

Whatever the check decided is what the response's `Context used` receipt reports as sent,
converted, or omitted ([the conversation workspace](conversation.md#context-used)).

## `Save to corpus`

Promotion is two steps, and the first one writes nothing.

```console
$ research attachment resolve CS0001 SA0001
SA0001  existing_artifact
  content hash       sha256:2fe74d…
  resolver outcome   same_artifact
  work               W0001
  version            V0001-1
  artifact           A0001-1
  reason             file hash matches artifact A0001-1
these exact bytes are already registered; saving links to them
```

`resolve` hashes the session copy, reads what bibliographic metadata the file offers, and
asks the same identity resolver `research ingest` uses what it matches — an exact Artifact,
a possible Version, a possible Work, or nothing yet. Then:

```console
$ research attachment save CS0001 SA0001
SA0001  ->  W0001 / V0001-1 / A0001-1
  outcome            same_artifact (linked the existing Artifact; nothing was copied)
  parsed             no
  attachment state   in_corpus
no Evidence and no Claim were created: extraction still goes through review
```

| flag | when |
|---|---|
| `--attach-to W0017` | save this file under an existing Work as a new Version/Artifact |
| `--as-new` | register a new Work even though the identity looks familiar |
| `--no-parse` | register the bytes without parsing them now (`research parse` later) |

Saving stages the immutable bytes and hands them to the same ingest path
`research ingest` uses, so the same bytes twice resolve to the existing Artifact and copy
nothing. The attachment moves to `in_corpus` only after the corpus write succeeded; a
failure records `failed` with the reason, **leaves the session bytes intact**, and leaves
the operation retryable.

**Saving creates identity, never evidence.** Extraction from the saved artifact still goes
through `research interrogate` / `research verify` / review with exact anchors
([Review](review.md)).

## The lifecycle, in full

```text
selected → validating → ready → sending → session_only
                  │        │                   │
                  └ failed └ failed            └ promoting → in_corpus
                                                          └ failed (retryable)
```

`failed` is reachable from every working state and leads back into `validating`, `sending`,
or `promoting`, which is what makes "a failure never loses your file" a property of the
state machine rather than a promise. `in_corpus` is terminal: the corpus copy is immutable
and identity-resolved.

## From the Web cockpit

The browser uploads bytes to `POST /sessions/{id}/attachments` — the one route that writes
without being a capability call. It is deliberately narrow: it writes only session-only
state, through the same service `attachment.add` uses, authorised exactly as
`attachment.add` is (researcher only). Reading is
`GET /sessions/{id}/attachments/{sa}/bytes` and `…/preview`, both served inert: the media
type is narrowed to the attachment allowlist, `nosniff` and `default-src 'none'` are set,
and a preview is a PNG the harness rendered itself. See [the daemon](http.md).

## See also

* [The conversation workspace](conversation.md) — sessions, sends, and the receipt.
* [The workspace](workspace.md) — where attachment bytes and previews live.
* [Providers](providers.md) — what each configured model accepts, and the egress policy.

# ADR-026: Attachments are session-only until an explicit Save to corpus

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §13, §39, §42 (N); ROADMAP.md Phase 19, Gate P19; `docs/superpowers/specs/2026-09-03-research-attachments-design.md` §2–§9; implemented in `domain/conversation.py` (`SessionAttachment`, `ATTACHMENT_TRANSITIONS`), `conversation/attachments.py`, `conversation/promotion_corpus.py`, `capabilities/attachments.py`, `server/routes_attachments.py`, `providers/models/media.py`

## Context

Dropping a PDF into a chat is the most natural gesture in the product and the most
dangerous one. The corpus is an identity system — Work, Version, Artifact, immutable bytes,
an anchor that must still resolve in two years (ADR-002) — and a drag-and-drop that
registered an Artifact would let identity be created by an accident of the composer. The
mirror-image failure is a send that silently drops the figure the researcher believes the
model is looking at, and then answers as if it had seen it.

## Decision

An attached file is **session working material**. It gets an `SA####` identity as soon as
its bytes are durably copied into `conversations/<session>/attachments/`, and that identity
is the whole of what attaching creates: no Work, no Version, no Artifact, no Evidence, no
Claim. Its life is the state machine of `ATTACHMENT_TRANSITIONS`
(`selected → validating → ready → sending → session_only`, with `failed` reachable from
each and retryable out of), so a failure is a visible state rather than a disappearance,
and one bad file in a batch of five costs the other four nothing — `add` returns a `failed`
attachment instead of raising.

**Nothing is silently omitted from a send.** `sendability` is a *total* function over the
composer's attachments: each one comes back `sent`, `converted`, or `omitted` with a reason,
checked against the selected model's declared input media, the size and page and count
limits, the egress policy, and the attachment's own visibility. Any *ready* attachment that
cannot go blocks the whole send, and where another configured entry could take it, the
refusal names it (`suggested_model`). The same helper writes the receipt lines, so what the
`Context used` receipt says was sent is what the check decided. Providers gained typed media
inputs for this (`providers/models/media.py`): OpenAI and Anthropic encode images and PDFs,
text is always inlined, and a model that declares no vision cannot be handed an image.

**Byte intake is the one documented non-capability write.** `POST /sessions/{id}/attachments`
takes the raw body because base64-ing a 30 MB PDF through a JSON capability request buys
nothing. It is narrow on purpose: it writes only session-only state, it goes through
`AttachmentService.add` — the same service `attachment.add` calls — and it is authorised
exactly as `attachment.add` is (`mutate`, researcher only), so it is not a way around a
permission. Reads are inert: original bytes are served with the media type narrowed to the
attachment allowlist under `nosniff` and `default-src 'none'`, and a preview is a PNG the
harness rendered itself into `.research/cache/attachments/`.

**`Save to corpus` is the one crossing, and it is a two-step.** `attachment.resolve_identity`
is a pure read: it hashes the session copy, reads what metadata the file offers, and asks
the existing identity resolver what it matches — an exact Artifact, a Version, a Work, or
nothing yet — so the researcher can look before choosing. `attachment.save_to_corpus` then
stages the immutable bytes and hands them to `IngestService`, which registers them through
the same `work.register` / `work.add_artifact` capabilities `corpus.ingest` uses and parses
them the same way; saving the same bytes twice therefore links the existing Artifact and
copies nothing. The attachment moves `promoting → in_corpus` only after the corpus write
succeeded; any failure records `promoting → failed`, leaves the session bytes intact, and
leaves the operation retryable. **No Evidence and no Claim is created by any of this.**

## Consequences

### Positive

- The corpus keeps one entrance. Everything in it was registered by an explicit human act
  under resolved identity, whatever surface asked for it.
- A blocked send is actionable rather than mysterious: per-item reason, and the name of a
  configured model that would take the item.
- A failed promotion is not a lost file. The bytes are still in the session, in a state
  whose only outgoing transitions are "try again".

### Negative / costs

- Bytes exist twice after a save — the session copy and the immutable corpus artifact —
  and the session copy is not reclaimed automatically. Deletion is a separate, explicit
  retention action, which is the right default and a real disk cost.
- A private attachment gets no external-model suggestion, because suggesting one would be
  suggesting an egress the policy forbids. The CLI prints the refusal without saying that
  privacy is why no alternative was named.
- `attachment.check_send` needs a configured `providers:` entry to have anything to check
  against, so a scripted, provider-less workspace cannot exercise it.

## Invariants this ADR protects

- Attaching a file creates no corpus object and no accepted state (§42 N); only
  `attachment.save_to_corpus` creates identity, and even then it creates no Evidence.
- Work/Version/Artifact identity is resolved through the existing resolver and never
  invented at the composer (ADR-002); saving never overwrites a different artifact.
- An unsupported item is never silently dropped from a model request; the send refuses and
  says why, per item (attachments spec §5).
- A partial failure preserves every other attachment, the composer draft, and the failed
  item itself in a retryable state.
- The capability layer remains the only surface that mutates accepted state: the one byte
  route writes session-only material and is authorised as `attachment.add` (ADR-004).
- A filename is display metadata, never a path; a preview never executes what a file
  contains (attachments spec §8).

## Rejected alternatives

- **Ingest attachments automatically, and let review sort it out.** Puts unreviewed
  identity into the corpus at the speed of drag-and-drop, and makes "what is in my corpus"
  a question about chat history.
- **Base64 uploads through `POST /capabilities/attachment.add`.** Same bytes, same service,
  three times the memory, and a JSON body no one can debug — with no boundary bought.
- **Drop unsupported attachments and answer anyway.** The failure mode the spec names
  first: the researcher believes the figure was considered.
- **Let `save_to_corpus` extract Evidence while it has the parse open.** It is exactly the
  moment where an automatic reading looks harmless; extraction stays behind candidate,
  verification, and review with exact anchors (§42 N, ADR-003).
- **Delete the session copy once the artifact is registered.** Makes a promotion
  irreversible and destroys the working material a researcher may still be reading.

## Where it is enforced

- `src/research_harness/domain/conversation.py`: `SessionAttachment`,
  `ATTACHMENT_TRANSITIONS`, `STORED_ATTACHMENT_STATES`.
- `conversation/attachments.py`: `add` (per-item validation, media sniffing, durable copy),
  `sendability` / `_check_one` / `_suggest`, `receipt_items`, `preview`.
- `conversation/promotion_corpus.py`: `resolve` (a read) and `save` (stage → `IngestService`
  → link back), with the `promoting → failed` retry path.
- `capabilities/attachments.py` and `server/routes_attachments.py` (the intake route's
  `_authorize`, the inert read headers).
- `providers/models/media.py` and the OpenAI/Anthropic/local/scripted adapters' typed media
  inputs.
- Tests: `tests/e2e/test_attachments_gate.py`, `tests/contract/capabilities/test_attachments.py`,
  `tests/contract/providers/test_media_inputs.py`,
  `tests/integration/conversation/test_attachments_intake.py` and `test_save_to_corpus.py`,
  `tests/unit/conversation/test_attachments_sendability.py`, `tests/unit/providers/test_media.py`.

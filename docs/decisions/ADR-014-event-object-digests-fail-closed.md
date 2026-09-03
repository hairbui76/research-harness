# ADR-014: Events carry object digests, and the workspace fails closed on disagreement

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §8.2, §19.3, §34, §42 K, §44.21; ROADMAP.md Task 1.5, Task 17.2, Task 17.4; `docs/architecture/domain-changelog.md` entries 6 and 8; implemented in `workspace/events.py`, `domain/research.py`, `workspace/repository.py`, `privacy/policy.py`

## Context

ADR-001 makes `events/research.jsonl` an audit companion rather than a second authority,
and §8.2 requires that an event disagreeing with its mutation make the workspace fail
closed. That only works if an event says enough to be checked. An event naming subject ids
cannot detect an edited value, and one carrying the objects themselves would duplicate
canonical state in the log — the second authority §8.2 rules out. What is needed is a
witness: small, checkable, and not a copy.

## Decision

`ResearchEvent.objects` maps an object key to the digest of that object's canonical YAML
after the mutation. It is a field of its own rather than payload entries, so recording a
large mutation never competes with the payload budget the audit narrative needs: 10,000
object keys against the payload's 32. Keys are the object's own id where it has one and a
prefixed form where it has none — `taxonomy/`, `blocks/`, `anchor/<file>#<fp>`,
`rejection/<work>#<candidate id>`; the legacy `object:` payload form is still read.

The digest is taken over canonical YAML, not the stored file bytes: reformatting a file by
hand is not a scientific change and must not fail the workspace closed, while editing a
value must. `verify_consistency` compares the latest event per object — the log is an audit
companion, not a state machine to replay — and `open` raises `WorkspaceInconsistentError`
unless given `repair=True`, which reports and rewrites nothing. `assert_semantic_event`
refuses a payload carrying prompts, reasoning, raw responses, or traces; those belong in
disposable `.research/traces/`. Configuration is not scientific state, so the
privacy-policy write goes through the same journal and lock but appends **no** event.

## Consequences

### Positive

- A hand-edited canonical value is caught the next time the workspace opens, with the key,
  the expected digest, and the event that recorded it.
- The check costs one digest per named object rather than a log replay, so §19.3 holds and
  reformatting a canonical file is not an incident.

### Negative / costs

- Verification dominates the cost of opening a project, and digesting the YAML form makes
  every write serialize an object twice (ADR-023).
- Changing the digest basis would invalidate every recorded digest, so it is an event-log
  version decision, not a local optimization.

## Invariants this ADR protects

- An event whose digest disagrees with its canonical file makes `open` fail closed, and
  `repair=True` rewrites nothing — §42 K; an event without its mutation is never valid.
- Prompts, reasoning, and tool output never enter the Git-visible log (§19.3, §34).
- Object digests cannot crowd out the audit payload; a mutation too large to record is
  split rather than truncated, and canonical files are never rewritten to satisfy the log.

## Rejected alternatives

- **Name subject ids only.** Blind to the failure that matters: an edited value in a file
  the event already names.
- **Embed the objects in the event.** Makes the log a second copy of canonical state, which
  §8.2 and ADR-001 reject.
- **Digest the stored file bytes.** A reformat would fail the workspace closed, teaching
  researchers to run `repair`.
- **Auto-repair by rewriting canonical files from the log.** Promotes the audit companion
  to the authority; replaying the whole log to verify is forbidden by §19.3.

## Where it is enforced

- `src/research_harness/workspace/events.py`: `object_digest`, `digest_key`,
  `with_object_digests`, `MAX_EVENT_OBJECTS`, `assert_semantic_event`,
  `verify_consistency`.
- `domain/research.py`: `ResearchEvent.objects` and its validators,
  `MAX_EVENT_OBJECT_KEYS`, `MAX_EVENT_PAYLOAD_KEYS`, `EVENT_PAYLOAD_FORBIDDEN_KEYS`.
- `workspace/repository.py`: `open` (fail closed), `WorkspaceInconsistentError`, and
  `update_config` (journalled, not evented); `privacy/policy.py` holds the policy.
- Tests: `tests/unit/workspace/test_events.py`, `tests/integration/privacy/`,
  `tests/integration/workspace/test_repository.py`, `tests/e2e/crash/`,
  `tests/e2e/invariants/test_k_atomic_mutation.py`.

# ADR-012: Candidates are regenerable staging; acceptances and refusals are canonical

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §8.2, §8.3, §9, §24.3, §42 (C, E, H); ROADMAP.md Phase 6 Tasks 6.1–6.3, Task 3.5; `docs/architecture/domain-changelog.md` entry 8; implemented in `evidence/staging.py`, `evidence/review.py`, `workspace/rejections.py`, `capabilities/handlers.py`

## Context

ADR-003 puts every model judgment through staging before acceptance, and ADR-001 makes
`.research/` regenerable. That decides where a proposal lives but not what happens to the
two things a review produces. An acceptance is obviously canonical. A *refusal* is the
awkward one: it is a scientific act, and if it lives only in disposable staging, deleting
`.research/` re-proposes the rejected reading with nothing to say it was already answered.

## Decision

Candidates live under `.research/staging/evidence/<work>/<candidate_id>.json`: deleting the
tree loses proposals, never conclusions. A staged `EvidenceCandidate` carries the
provisional id `E0000` and cannot hold evidence in an accepted state. Candidate ids are
content-addressed — `cand_` plus 16 hex of a SHA-256 over what the candidate says and where
it came from, deliberately not over which model proposed it — so two providers reading one
span produce one candidate and a re-run adds no second copy.

A refusal is canonical. `RejectionRecord` is appended to
`corpus/works/W####/rejections.jsonl`; it is deliberately not an `Evidence` object, never
receives an `EvidenceId`, and is not projected into SQLite. A re-proposal is recognized
after a wiped staging tree by candidate id, anchor fingerprint, or text hash plus field.
The guard against accepting one span twice likewise reads **canonical** `evidence.jsonl`,
not staging: an identical repeat returns the existing id with a warning and journals
nothing, while a repeat carrying a different qualification is refused as a new judgment.

## Consequences

### Positive

- `rm -rf .research/` costs proposals and nothing else; the acceptance, the refusal, and
  the reason survive in Git-visible files, and the reviewer is not asked twice.
- Content addressing makes resume cheap, and committing canonical-first leaves the only
  crash window with regenerable state behind canonical state — the harmless direction.

### Negative / costs

- Staged candidates are lost to a rebuild, so an unreviewed backlog is fragile in a way
  accepted state is not (ADR-003 accepts this).
- `rejections.jsonl` grows without bound and has no projection, so questions about refusals
  are file scans; the duplicate guard is O(accepted evidence in the work).

## Invariants this ADR protects

- Deleting `.research/` and rebuilding reproduces the same accepted Evidence and the same
  refusals — §42 C.
- Staging never holds accepted evidence, and a rejected candidate never gets an `EvidenceId`.
- Accepting the same anchor and content twice does not mint a second `EvidenceId`; the
  guard is on canonical evidence, because staging is regenerable.
- Two providers reading one span produce one candidate id, so agreement is visible rather
  than duplicated (ADR-017).
- Canonical state commits before the staging mark, never after.

## Rejected alternatives

- **Keep rejections in staging.** A rebuild would re-propose refused readings; the
  researcher's "no" would be the only decision the system forgets.
- **Record a rejection as an `Evidence` object with a rejected status.** Gives a refusal an
  `EvidenceId` and a place in `evidence.jsonl`, which says the opposite of what happened.
- **Delete a candidate once reviewed.** The inbox could not show what was answered, and a
  crash before the delete would look like a fresh item.
- **Guard duplicates on the staging record.** Staging is regenerable, so a crash before the
  mark mints a second `EvidenceId` for one span — consistent, and wrong.

## Where it is enforced

- `src/research_harness/evidence/staging.py` (`StagingStore`, `EvidenceCandidate`,
  `candidate_id_for`, `PROVISIONAL_EVIDENCE_ID`), `evidence/review.py` (`_previous_rejection`).
- `workspace/rejections.py` (`RejectionRecord`), `workspace/layout.py` (`rejections_path`,
  `staging_dir`, `is_regenerable`), `workspace/repository.py` (`append_rejection`,
  `iter_rejections`).
- `capabilities/handlers.py`: `accept_evidence`, `_accepted_duplicate`, `reject_evidence`.
- Tests: `tests/unit/evidence/test_staging.py`,
  `tests/integration/evidence/test_review_gate.py`,
  `tests/e2e/crash/test_review_acceptance.py`, `tests/e2e/invariants/test_h_human_review.py`.

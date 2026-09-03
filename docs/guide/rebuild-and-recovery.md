# Rebuild and recovery

Canonical files carry the science; `.research/` carries nothing that cannot be recomputed
(ADR-001). This page is what to do when the two disagree, or when something was
interrupted.

## `research rebuild`

Rebuilds `.research/research.db` — every table, the dependency edges, the FTS5 index, and
the stale marks — from canonical files. It never writes canonical state.

```console
$ research rebuild
rebuilt 46 objects, 34 indexed rows, 0 stale marks in 117 ms
  Work               1
  Version            1
  Artifact           1
  DocumentBlock      30
  Evidence           2
  Claim              1
  ManuscriptAnchor   1
  ResearchEvent      9
  canonical digest   sha256:127ca1900af90cf8ba330b2ca175fa460718a9c0f500602bde20ece9e30f82e9
```

Three properties make it safe to run at any time:

* **Read-only.** It opens no canonical file for writing and takes no workspace
  transaction.
* **Fail closed.** Every canonical file is read and validated before the database is
  touched. One unparseable file and the rebuild reports it, exits 1, and leaves the
  existing projection exactly as it was — a projection that silently omits a corrupted
  Claim is worse than no projection.
* **Atomic.** The new database is built beside the target and moved over it, so a crash
  mid-rebuild leaves the previous projection intact.

It is also deterministic. Delete the whole tree and rebuild, and the canonical digest is
identical:

```console
$ rm -rf .research && research rebuild
rebuilt 46 objects, 34 indexed rows, 0 stale marks in 111 ms
  ...
  canonical digest   sha256:127ca1900af90cf8ba330b2ca175fa460718a9c0f500602bde20ece9e30f82e9
```

You lose the daemon token (regenerated on next `research serve`), any staged proposals
that had not been reviewed (re-run `research interrogate`), the retrieval indexes
(`research index build`), and the run history. You lose no accepted conclusion. The
end-to-end assertion is in `tests/e2e/test_evidence_cli_loop.py`.

Run it after: pulling someone's canonical files, restoring from backup, changing the
projection schema, or any time search results look stale.

## `research doctor`

Run from inside a workspace, `doctor` adds the workspace checks to the environment ones:

```console
$ research doctor
[ok  ] research-harness  0.1.0
[ok  ] python            3.12.13 (requires >= 3.12)
[ok  ] pydantic          2.13.5
[ok  ] typer             0.27.2
[ok  ] sqlite-fts5       available
[ok  ] node              /home/you/.nvm/versions/node/v24.14.1/bin/node
[ok  ] pnpm              /home/you/.nvm/versions/node/v24.14.1/bin/pnpm
[ok  ] workspace         /home/you/projects/traffic-survey (schema 1, policy strict)
[ok  ] consistency       13 objects consistent with the event log
[ok  ] projection        research.db agrees with canonical state
[ok  ] providers         2 configured in research.yaml
[ok  ]   fast            openai/gpt-4o-mini, OPENAI_API_KEY set
[note]   local           local_openai_compatible/qwen2.5:14b, LOCAL_MODEL_API_KEY unset
[note] egress policy     external models allowed, search allowed, hosts any declared host, traces verbatim
[note] daemon token      /home/you/projects/traffic-survey/.research/daemon-token
[note] plugins           academic-writing, structured-traffic (in /home/you/research-harness/plugins)
```

| marker | meaning |
|---|---|
| `[ok  ]` | checked and fine |
| `[note]` | information; never a reason to exit non-zero |
| `[FAIL]` | a real problem; `doctor` exits 1 |

Only four things fail: an unusable interpreter or missing package, no FTS5, a workspace
that will not open or is inconsistent with its event log, and a projection that disagrees
with canonical state. A missing `node`, an unset API key, an unbuilt projection, and a
missing daemon token are all notes.

`doctor` opens the workspace with `repair=True`, so an inconsistent workspace is
*reported* rather than raising — telling you what disagrees is the whole job. It writes
nothing except journal recovery, which the workspace performs on any open. Provider lines
name the credential *variable* and whether it is set, never a value, so the output is safe
to paste into an issue.

`doctor` takes `-w` and `RESEARCH_WORKSPACE` like every other command, and outside a
workspace it runs the environment checks alone.

## Journal recovery

A canonical mutation touches several files at once — the object, the Work's
`evidence.jsonl`, `events/research.jsonl`, dependency invalidation — and lands as one unit
through a durable transaction journal under `.research/journal/`. Interrupting one leaves
a prepared record there.

Recovery is automatic and runs under the workspace lock every time a workspace is opened,
before the config is read, so nothing ever sees a half-applied mutation. Each leftover
transaction is either rolled forward to completion or rolled back to its pre-image.
Recovery is idempotent, so it is safe if it is itself interrupted. There is no command to
run: opening the workspace is the command. When recovery had to touch something, `doctor`
reports it:

```text
[note] journal           1 completed, 0 rolled back, 0 cleaned
```

A half-written object, or an event without its matching mutation, is never a valid
workspace state.

## A hand-edited canonical file

The event log records the digest of every object it changed. Editing a canonical file
behind the harness's back makes the two disagree, and the workspace then fails closed:

```console
$ research inbox
error: workspace /home/you/projects/traffic-survey is inconsistent: 1 of 9 objects disagree with
the event log: C0001: canonical content does not match the digest recorded with the event (event
claim.audited recorded sha256:3c1cfa31..., found sha256:87740e4a...). Canonical files are
authoritative and are never rewritten automatically; open with repair=True to inspect the report,
then reconcile the difference.
```

Nothing is repaired for you, and that is deliberate: canonical files are authoritative, so
the harness will not overwrite your edit to satisfy its log, and it will not rewrite the
log to bless an edit it did not make.

To sort it out:

1. `research doctor` — it opens with `repair=True` and prints the full report, naming
   every object that disagrees.
2. `research rebuild` — also opens with `repair=True`, so an inconsistent workspace still
   gets an index to diagnose with.
3. Decide which side is right.
   * **The edit was a mistake** — `git checkout -- claims/C0001.yaml` (or restore from
     backup). The digests match again and the workspace opens.
   * **The edit was intentional** — redo it through the harness so the change gets its own
     event: `research claim create`, `research claim audit`, `research review`,
     `research taxonomy set`, and so on. Revert the file first, then make the change the
     supported way.
4. `research doctor` again to confirm `[ok  ] consistency`.

This is why the recommended path for changing accepted state is always a command, even
though the files are readable by design.

## Projection out of date

`doctor` compares the id set of every canonical collection with the projection's primary
keys, in both directions:

```text
[FAIL] projection        5 discrepancy(ies), run `research rebuild`: decisions: 1 canonical
object(s) not projected: D0001; questions: 1 canonical object(s) not projected: RQ0001; ...
```

A canonical object missing from the projection means the index is behind. A projected id
with no canonical object is worse — it would make the projection an authority, the one
thing it may never be. `research rebuild` fixes both. A projection built by an older
schema version reports `the projection must be rebuilt`.

## Schema versions

`research.yaml` declares `schema_version`. The current version is **1**, and there are no
migrations registered yet because nothing has needed one.

* **Older workspace** — registered migrations run in order on open. With no migration for
  a step the harness refuses rather than guessing.
* **Newer workspace** — refused before anything is touched:

  ```text
  workspace schema version 2 was written by a newer Research Harness; this build supports up to
  version 1. Upgrade the harness rather than editing research.yaml: opening it here could drop
  fields this version does not know about.
  ```

  Upgrade the harness. Do not hand-edit the version.

The projection has its own version, stored in `research.db`; a mismatch is a rebuild, not
a migration, because the projection holds nothing that is not in a canonical file.

## When `.research/` is corrupt

Delete it.

```bash
rm -rf .research
research rebuild
research doctor
```

There is no state in there worth recovering — that is the design. If `rebuild` then
reports invalid canonical files, the problem is in the canonical tree and the fix is Git:
`git status`, `git diff`, and restore the file that will not parse.

If the workspace lock is held by a process that no longer exists, delete `.research/lock`
and try again.

## Staleness is not corruption

`research stale` lists anchors that no longer replay against the stored parse, and
accepted objects an upstream change has marked stale — a revised taxonomy, a re-audited
claim, a reworded manuscript sentence.

```console
$ research stale
nothing stale
```

None of it is repaired automatically. Silently re-anchoring would move the source an
accepted conclusion rests on, and silently rewriting a downstream object would change a
conclusion nobody reviewed (ADR-008). Stale means *look at this*: re-run the audit,
re-attach the sentence, or accept that the classification changed — as a researcher
action, with its own event.

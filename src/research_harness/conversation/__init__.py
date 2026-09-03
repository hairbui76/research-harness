"""Sessions, messages, attachments, context packs, promotion, and save-to-corpus.

Everything in this package is *durable working context*: a transcript and its attachments
survive deleting `.research/`, and none of it is accepted scientific state (workspace
design SS3). Promotion out of a session -- into a Note, a Question, a Claim candidate, a
Decision candidate, or a corpus Artifact -- goes through `capabilities/` like every other
mutation, so the review gate cannot be routed around from here.
"""

from __future__ import annotations

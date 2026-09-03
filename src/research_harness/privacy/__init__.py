"""Privacy and egress controls for a local-first workstation (Product SS34, Task 17.4).

Three modules, deliberately not re-exported as one:

* `privacy.policy` — `EgressPolicy` and `check_egress`. Provider- and workspace-free, so
  both `workspace/` (which stores the policy in `research.yaml`) and `providers/` (which
  enforces it) can import it without breaking the layering of
  `docs/architecture/conventions.md`. That surface is re-exported here.
* `privacy.traces` — `TraceWriter` for the disposable, optionally redacted traces under
  `.research/traces/`.
* `privacy.egress` — the enforcement helpers and the `research egress` report. It imports
  `providers/`, so it is imported directly rather than from here: importing this package
  must never pull an adapter into `workspace/`.
"""

from __future__ import annotations

from research_harness.privacy.policy import (
    LOOPBACK_HOSTS,
    SECRET_CONFIG_KEYS,
    EgressCheck,
    EgressDeniedError,
    EgressKind,
    EgressPolicy,
    check_egress,
    denial,
    enforce_egress,
    is_local_endpoint,
    load_policy,
    refuse_inline_secrets,
    secret_keys_in,
)

__all__ = [
    "LOOPBACK_HOSTS",
    "SECRET_CONFIG_KEYS",
    "EgressCheck",
    "EgressDeniedError",
    "EgressKind",
    "EgressPolicy",
    "check_egress",
    "denial",
    "enforce_egress",
    "is_local_endpoint",
    "load_policy",
    "refuse_inline_secrets",
    "secret_keys_in",
]

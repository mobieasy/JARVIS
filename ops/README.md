# Release controller scaffold — not installed

Uses Linux flock, atomic records and fixed host-owned hooks instead of an agent-session restart script. No external dependency or service is introduced. See [the release plan](../docs/RELIABLE-JARVIS-PLAN.md) for mandatory host inventory and restore gates.

## Contract

An administrator must provision a root-owned, non-group/world-writable tree and policy, outside agent write access. The controller itself and its Python import environment must also be host-owned. Never grant an agent unrestricted sudo for this script, policy selection, or hook editing.

Policy keys: absolute `root`, `hook_timeout_seconds` (1–120, default 30), and `hooks`: fixed argv lists for `preflight`, `drain`, `stop`, `backup`, `start`, `ready`, `resume`. Executable paths must be absolute and trusted. Hooks must not delegate to agent-writable scripts/configuration. Run via a dedicated host systemd service with a bounded overall timeout and control-group cleanup; subprocess timeout alone does not kill all hook descendants.

Layout beneath root:

- `releases/<40-character-commit>/payload/`: immutable regular files, no links or special files.
- `releases/<commit>/manifest.json`: `revision`, `rollback_safe: true`, `payload_sha256` from `tree_digest(payload)` after final file modes are set.
- `current`: relative symlink to the existing release.
- `deploy.lock`, `deployment.json`: host-private controller state, not application state.

Only an explicitly selected, pushed and verified commit may be packaged. The manifest digest detects corruption; it is not a signature or proof of Git provenance. Administrator-side artifact admission must establish that provenance before installation. Do not execute an untrusted build as root.

## Hook responsibilities

Preflight checks capacity, rollback artifact and compatible configuration, backup readiness and isolated staging evidence. Drain fences dispatch and scheduled effects. Stop must verify every production writer stopped. Backup must produce a consistent recoverable checkpoint and fail if that cannot be proven. Start targets only this service. Ready performs bounded authenticated session/tool/persistence checks. Resume is idempotent and establishes single scheduler ownership.

Hooks must be idempotent, bounded and produce private host audit evidence without secrets. Application configuration must remain compatible with both releases. No state/config migrations are implemented; `rollback_safe` is an admission assertion requiring review, not an automatic compatibility test. Rollback selects the old code but does not restore a database. Do not admit candidates that need state restoration or whose effects cannot be reconciled.

## Interrupted execution

Unfinished `preparing`, `draining`, `drain_failed`, `activating`, `rolling_back`, or `rollback_failed` records require host-admin reconciliation. Do not delete a transaction record merely to retry: inspect the current symlink, actual processes, queue fencing, checkpoints and external effects first. A partial drain can leave dispatch paused. A crash after switching the symlink is not automatically recovered by this scaffold. Automated boot-time reconciliation remains future work.

## Verification

`python3 -m unittest discover -s ops -p 'test_*.py' -v`

These tests use synthetic temporary releases and mocked hooks. They prove transaction ordering and fail-closed checks, not real systemd behavior, real backups or VPS recovery. Before installation: inventory the live host; restore a backup in isolation; implement/review fixed hooks and resource limits; rehearse a failing release in isolated staging; prove independent operator recovery. No production service is changed by these files.

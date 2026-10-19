# Reliable Jarvis: implementation and same-VPS release plan

Status: proposed implementation plan, not an implemented production deployment.

## Goal and constraints

Deliver a persistent developer/operator assistant that checkpoints work, resumes safely, verifies outcomes, and exposes blockers. Preserve the working assistant throughout development on its own VPS. No claim of parity with proprietary products. No new paid service or recurring model jobs by default.

Repository inspection confirms an OpenClaw integration, Workboard configuration, Docker sandbox template, optional SMS auth proxy, invoice tool, and roadmap. The template is not evidence of live host configuration. Remote host inspection was unavailable in the planning environment (SSH client absent); capacity, live service names, ports, backups and installed runtime must be inventoried before implementation or activation.

## Architecture: reuse before building

Use OpenClaw sessions, Workboard, automations and progress surfaces first. Assess upstream recovery, task dispatch, approvals and audit capabilities against the acceptance criteria below. Only implement narrowly missing pieces. Reuse systemd for supervision/resource control, Docker for execution isolation, Git for source, and the existing reverse proxy for routing. Do not introduce a second scheduler, vector database or dashboard without demonstrating a gap. A same-host staging environment tests software isolation, not host-failure resilience.

Separate these planes:

- Production: immutable release, production identity/configuration, private writable state, existing public route.
- Development: topic-branch worktrees, test fixtures, constrained build workers; no production state mounts or automatic deploy on push.
- Staging: separate runtime identity, configuration, port, state, sandbox prefix and credentials; loopback-only, synthetic data, no real outbound messages or duplicate scheduled jobs.
- Release controller: host-owned bounded service independent of the assistant session/container; accepts a validated immutable revision, serializes releases, records results and can restore the old release if Jarvis goes offline.

Example future layout (confirm existing paths first): `/opt/jarvis/releases/<commit>`, `/opt/jarvis/current`, `/opt/jarvis/previous`, `/var/lib/jarvis`, `/etc/jarvis`, and a separate development tree. These are proposed paths, not instructions to move live files now. Keep private deployment inventory and recovery records outside this public repository.

## Delivery milestones and gates

| Milestone | Deliverables | Gate before proceeding |
| --- | --- | --- |
| 0. Baseline and recovery | Private host/service inventory; current source/image/config fingerprints; dependency versions; tested state backup; CPU/RAM/disk measurements; memory diagnosis | Existing release can be restored with documented commands independent of Jarvis; restore tested to an isolated destination |
| 1. Safe release foundation | Reproducible pinned build; CI; constrained staging; release manifest; deploy lock; external activation/rollback runner | Deliberately unhealthy staging release rolls back automatically; no production changes during rehearsal |
| 2. Persistent task reliability | Native Workboard mapping, checkpoints, leases, recovery reconciler, stop/resume, evidence-backed completion | Restart mid-task resumes or reports a precise blocker without duplicating external effects |
| 3. Developer/operator vertical slice | Issue → isolated worktree → fix → verification → commit/push → reviewable release; bounded read-only operational checks | One synthetic issue completes end to end; deployment follows release gates; no secrets in source/logs |
| 4. Controlled proactive work | Explicit responsibilities, event/schedule filters, quiet hours, budgets and escalation; useful activity view | Duplicate events deduplicate; cancellation and budget limits stop execution; no unsolicited external sends |
| 5. Wider integrations | Add one scoped integration at a time using maintained adapters | Permission boundaries, failure recovery and data disclosure tested per integration |

Ship each milestone as a focused PR; do not bundle runtime upgrades, authentication changes, state migrations and autonomous behavior into one release. Estimate implementation time after milestone 0 exposes actual gaps.

## Git and verification contract

1. Start from a clean, fetched baseline; preserve unrelated work. Use `feat/`, `fix/`, or `docs/` branches and isolated worktrees.
2. Keep application code and sanitized config examples in Git. Keep live profiles, chat history, secrets, database/state, host inventory and backups out of source and build contexts.
3. CI uses synthetic fixtures and fake SMS: run the auth and tool standard-library test suites, configuration generation/validation against the pinned runtime, and checks appropriate to changed security boundaries. Never use live messaging or paid models in CI.
4. Review the diff and dependency changes; commit and push before any deployment. Merge reviewed changes to main under repository policy; release only an explicitly selected, remotely available commit. A push is not a deployment trigger.
5. Build once from that clean commit with pinned dependencies. Record commit, dependency lock digest, runtime version, artifact/image digest, config schema compatibility, test results and migration requirements. Promote that exact artifact from staging to production; do not rebuild it during activation.
6. Record the currently deployed commit/artifact and private config/state backup references as the rollback point before changing production. Never deploy an uncommitted workspace or make production-only source edits.

## Same-VPS capacity and isolation

Measure peak production consumption and free disk before selecting limits; do not invent a safe capacity from the example config. Reserve measured headroom for production plus old/new runtime overlap. Apply explicit CPU, memory, process and log limits to development/staging, low build concurrency and lower I/O priority. Abort builds on low disk/headroom. If overlap cannot fit, use a short controlled stop/start or move builds off-host; do not risk an OOM kill of the live assistant.

Development agents must not receive the Docker socket, production secrets, writable live configuration or unconstrained host administration. A narrow release service may need host privileges, but its allowlisted operation must not accept arbitrary shell. Policy enforcement must live outside agent-editable prompt files. Existing access permissions are inventoried before changes; do not silently break the active agent's tool access.

Avoid broad operations such as restarting Docker, pruning all images/volumes, replacing the live source tree, stopping unrelated services or changing global proxy/firewall rules. Inspect and preserve existing configuration; change only the relevant service or route. Retain at least the previous working artifact and matching config/state recovery material.

## Release runbook

### Prepare without interrupting production

- Acquire a host-side deployment lock and verify expected current revision.
- Check host health, disk headroom, backup freshness, available ports and rollback artifact availability.
- Save the private rollback manifest, including source/image digest, effective configuration fingerprint and schema version. Backups must preserve required ownership and permissions, be protected, and have a tested restore path; plan off-host copies for VPS loss without uploading private data to an unapproved service.
- Run a fresh staging identity on loopback with isolated writable state. Validate startup, authentication, tool access, task lifecycle, memory retrieval and expected proxy/WebSocket behavior using synthetic fixtures. Production tokens and scheduled jobs must not run in staging.

### Activate with an independent controller

- Checkpoint active work, pause new task dispatch and scheduled side effects, and drain existing actions with a bounded timeout. Record uncertain actions rather than replaying them.
- The assistant submits a durable deployment request before its own restart. A host-side runner owns the transaction and final status; it must not depend on the assistant session remaining alive.
- Never run two active writers against the same state. Select fenced single-writer handoff by default. Blue/green is permitted only if OpenClaw's state and scheduler ownership are proven safe and capacity permits overlap.
- For single-writer handoff: stop the old writer, take a consistent checkpoint/backup as appropriate, atomically select the new immutable release and matching configuration, start only the relevant service. Keep the public route stable unless a scoped route switch is actually required.
- Probe local readiness and the real authenticated public path with synthetic checks. Use bounded retries and a deadline; inspect restarts and errors. Settle for neither an open port nor HTTP 200 alone: verify a session, permitted tool execution and persistence across restart. Never send real customer messages as a health probe.
- On success, resume dispatch/schedulers once ownership is established; record revision, evidence, duration and release outcome. Jarvis reads the durable outcome after reconnecting.

### Rollback and recovery

On failed readiness, auth/session regression, crash loop or incompatible state, the host controller stops the new writer, restores the previous artifact/config and compatible state if required, starts the old release and probes it. Database changes must be additive/backward-compatible by default; otherwise require a separately rehearsed migration and restore plan before activation. Blind code rollback after an irreversible migration is not safe.

Reconcile actions issued after the backup before restoring state: a restored queue must not repeat a payment, message, deployment or other external effect. If old-version recovery also fails, stop repeated activation attempts, retain evidence and report the blocker through the available operator path. Never erase current state to force startup. Keep a host-admin recovery path independent of Jarvis, plus a documented procedure for restoring onto another host.

## Persistent-work correctness

Use native task states where possible; map proposed concepts to supported Workboard fields rather than assuming a new API exists: queued, running, waiting for user, blocked, succeeded, failed, cancelled. Persist objective, owner/lease, next action, checkpoint, source revision, evidence, budget and timestamps.

Reconcile expired leases and interrupted tasks on startup. Read-only work can retry with bounded backoff. External actions require a stable action ID, a pre-action intent record and reconciliation against the destination before retrying. If success is uncertain and the destination offers no idempotency/reconciliation, block for review rather than claim exactly-once delivery. Cancellation must stop future dispatch and safely conclude in-flight actions. Persisting a progress card alone is not task recovery.

## Acceptance evidence required before calling Jarvis reliable

- Kill a worker mid-task; recover from its checkpoint without losing the objective.
- Interrupt an external-action response; deduplicate or surface uncertainty without repeating the action.
- Deploy a failing candidate; the external runner restores the working version without needing Jarvis online.
- Restore a backup in isolation and validate representative task/session data.
- Verify staging cannot send production messages, run production schedules or write production state.
- Hit resource and spending limits; stop bounded work without starving production.
- Repair memory configuration separately and verify retrieval with known synthetic facts; do not change embedding providers or incur indexing costs implicitly.
- Complete a developer task with inspectable Git diff, checks, pushed commit and evidence-backed final status.

## First implementation batch

Complete milestone 0, then implement only the release foundation: private inventory and recovery record, generic CI/build checks, release manifest format, staging isolation, narrow host deploy controller and rollback rehearsal. Only after that gate passes should persistent-work changes be deployed. This document alone authorizes no production restart and changes no live configuration.

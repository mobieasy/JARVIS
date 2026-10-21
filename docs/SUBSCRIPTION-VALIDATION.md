# Subscription setup validation

Date: 21 October 2026. Scope: source and disposable local state only. No live user account, production service, private deployment or paid model was used.

## Evidence

- Baseline source was fetched from `mobieasy/JARVIS` commit `a0ed155dcac5902c9b3f8ea6bf42869e7e47a44d`; every source file matched its upstream Git blob hash.
- All 44 offline regression tests pass: 14 subscription setup, 13 existing authentication, 5 invoice reconciliation, 12 release-controller tests.
- `npm ci --ignore-scripts` installed the existing core lockfile. The exact official Codex plugin was then added to the dependency lock; its managed native executable reports `codex-cli 0.160.0`.
- A fresh subscription configuration passed the actual OpenClaw 2026.10.4 schema validator. The old template's disabled `duckduckgo` selection was removed from the new preset because an unavailable provider is rejected even while search is disabled.
- Core installation alone warned that the Codex plugin was unregistered. An explicit pinned official plugin install into disposable state completed successfully. Fresh-state policy checks and native schema validation then passed without that warning.
- `openclaw doctor --lint --only codex/managed-app-server --json` reported `ok: true`, `checksRun: 1`, and no findings. This verifies the managed executable check, not inference or sandbox containment.
- `git diff --check` passed.

One earlier disposable plugin-install state reported `database disk image is malformed` on a subsequent read. Its cause was not established. A separate fresh state completed registration, integrity checks, schema validation, and the managed-binary lint check. No corrupted state was repaired, discarded as a live recovery strategy, or treated as healthy. The launcher now checks an existing runtime database read-only before dispatch; a failure blocks execution and instructs the operator to preserve state.

## Not established

ChatGPT Plus login, account model eligibility, a completed model turn, Docker/native tool containment, task recovery under a running Gateway, browser/device integrations, voice, and full host restore still require staging acceptance. No GitHub Actions run is claimed; the workflow is prepared source. No deployment or repository merge has been performed by this change.

Re-run the documented acceptance sequence on the target host before granting any business tools. A successful schema validation or model login is not enough to claim an operational assistant.

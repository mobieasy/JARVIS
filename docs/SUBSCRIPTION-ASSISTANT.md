# Private JARVIS with ChatGPT Plus

This is the source implementation and staging runbook for a single-owner subscription-backed assistant. It reuses OpenClaw 2026.10.4 and the official `@openclaw/codex` 2026.10.4 plugin. No new model subscription, API balance, or public hosting service is required by this preset. ChatGPT allowance, model availability, and account limits still apply. There is no automatic API-key fallback.

## What changed from the old setup

The existing `config/openclaw.example.json` routes normal reasoning to OpenRouter. `tools/codex_helper.sh` is a separate review helper; its presence does not make OpenClaw's primary reasoning subscription-backed. That legacy helper also redirects home directories and must not be used for this new setup. It remains untouched for existing deployments.

The new `scripts/jarvis.py` creates a separate private configuration, workspace and state directory. It selects the native `codex` agent runtime, enables the official Codex plugin, and routes auth to one named OpenAI OAuth profile. OpenClaw owns the native app-server lifecycle, session continuity, dynamic tools and approvals; no homemade OpenAI-to-CLI proxy is necessary. A separate `codex login` does not automatically authenticate this isolated OpenClaw profile. The new wrapper starts OpenClaw via CLI; the native Codex app-server is the brain behind it.

The old paid template is preserved for backward compatibility. Use the new entry point, not `scripts/configure.py`, when the requirement is subscription-only.

## Architecture and ownership

| Concern | Owner |
| --- | --- |
| Chat, dashboard, session progress and transcripts | OpenClaw Control UI and Gateway |
| Foundation-model reasoning and native compaction | Codex harness using ChatGPT OAuth |
| Persistent tasks and evidence | Existing Workboard plugin |
| Schedules and event-driven follow-up | Native automations, after explicit configuration |
| Memory | Private Markdown plus keyword-only index; no embedding bill |
| Tool policy and sandbox | OpenClaw policy and configured Docker execution boundary |
| Business file example | Existing invoice reconciliation tool |
| Configuration creation and fail-closed launch | New Python entry point |
| Staging/release transaction | Existing release-controller foundation; separate deployment decision |

There is no second queue, scheduler, memory database, or dashboard. Creating those would duplicate the runtime before a missing capability has been demonstrated.

## 1. Preserve the existing installation

Do not format the VPS or copy repository examples over live config. Inventory the existing release, services, ports, source revision, runtime versions and resource use privately. Confirm recovery of the current installation, including its auth state, private workspace and pairing material. Keep that inventory and backup outside this public repository. A repository snapshot alone is not a full server backup.

The live VPS has not been inspected from this development session. Source inspection cannot establish its actual installed configuration or existing CLI integration. See `docs/RELIABLE-JARVIS-PLAN.md` for recovery and capacity gates.

## 2. Isolated staging prerequisites

- A dedicated non-root Linux account with no production credentials, repositories or SSH keys.
- Node.js 24.19.0 and Python 3.11+; the wrapper checks the installed OpenClaw package is exactly 2026.10.4.
- npm dependencies installed from the checked-in lockfile. Review lifecycle scripts before enabling any that are needed by the runtime.
- A functioning isolated Docker backend and the reviewed `jarvis-sandbox:dev` image. Prefer rootless Docker; joining a rootful daemon's Docker group grants broad host control. The launcher does not configure or weaken Docker/namespace policy.
- Outbound access required by official ChatGPT OAuth and the selected runtime. Network failures are blockers, not permission to disable verification or sandboxing.

Use a fresh account/state. The wrapper is not a migration tool. Do not import an old mixed API-key store into this subscription-only state.

## 3. Install the source and generate private state

After the feature branch is available on GitHub:

```sh
git clone https://github.com/mobieasy/JARVIS.git
cd JARVIS
git switch feat/subscription-assistant
npm ci
python3 -m unittest discover -s scripts -p 'test_*.py' -v
docker build -f Dockerfile.sandbox -t jarvis-sandbox:dev .
python3 scripts/jarvis.py --private-dir "$HOME/jarvis-private" init --model openai/gpt-6.1-sol --port 18889
python3 scripts/jarvis.py --private-dir "$HOME/jarvis-private" check
python3 scripts/jarvis.py --private-dir "$HOME/jarvis-private" install-codex
python3 scripts/jarvis.py --private-dir "$HOME/jarvis-private" validate
```

The selected model is an explicit example, not proof that every account exposes it. Use a model confirmed in your Plus/Codex catalog. If unavailable, create another fresh staging setup with a supported exact `openai/<model>`; no silent substitution occurs.

The official plugin and its Codex 0.160.0 dependency are pinned in `package-lock.json`. `install-codex` registers that exact official plugin in the dedicated OpenClaw state with `--pin --no-enable`, preserving configuration-owned activation. Core npm installation alone does not establish managed plugin registration. Do not replace this with an unreviewed local load-path override or broad trust bypass.

Initialization refuses existing directories, symlinks and paths inside source. It creates 0700 private directories, 0600 files, a random gateway token and generic workspace instructions. It never overwrites a live configuration or copies credentials. Run `init` only once for each new staging path.

The source policy check verifies the reviewed preset and privacy of its setup paths. It does not validate upstream schema, authenticate a model, build a sandbox, or prove that native tool access is contained. The next steps do those separately.

See [recorded validation and remaining gates](SUBSCRIPTION-VALIDATION.md). Existing runtime state must also pass a read-only SQLite integrity check before the wrapper dispatches a command. Do not delete or replace state to silence an integrity error; preserve it and use the recovery procedure.

## 4. Sign in directly with your Plus account

```sh
python3 scripts/jarvis.py --private-dir "$HOME/jarvis-private" login
python3 scripts/jarvis.py --private-dir "$HOME/jarvis-private" models
python3 scripts/jarvis.py --private-dir "$HOME/jarvis-private" status
```

The login action calls the pinned runtime's `models auth login --provider openai --profile-id openai:jarvis --agent jarvis --device-code`. Follow the official link and enter its one-time code yourself. Do not paste passwords, refresh/access tokens, state databases or `auth.json` into chat or Git.

The config declares only the named OAuth profile. Startup uses an environment allowlist, not ambient provider API keys, Node injection variables, proxy overrides or unrelated service secrets. `HOME` is inherited, never rewritten; the dedicated operating-system user remains a required boundary. OpenClaw uses its per-agent Codex home and passes subscription auth to the native process. The wrapper does not read an operator's Codex auth cache.

Auth order can also be changed in runtime state, and an owner can edit the configuration or add credentials. This preset is not an account-level billing firewall. Keep the state dedicated, do not add API-key profiles, review `/codex status`, and inspect actual account usage before unattended operation.

## 5. Start, open the dashboard and prove a live turn

```sh
# Terminal A: keep the foreground Gateway running.
python3 scripts/jarvis.py --private-dir "$HOME/jarvis-private" start

# Terminal B: use the same dedicated account and private directory.
python3 scripts/jarvis.py --private-dir "$HOME/jarvis-private" smoke
python3 scripts/jarvis.py --private-dir "$HOME/jarvis-private" dashboard
```

For a remote VPS, forward the staging port from your own computer:

```sh
ssh -N -L 18889:127.0.0.1:18889 your-user@your-vps
```

Open `http://127.0.0.1:18889` locally and complete the native gateway-secret sign-in privately. Use the native dashboard/auth flow; do not paste secret-bearing dashboard URLs into chat. The raw Gateway stays on loopback. Do not enable its operator HTTP endpoints publicly; shared gateway tokens confer broad operator access.

In chat, inspect `/status`, `/codex status` and `/codex models`. A successful login or open port alone is insufficient: confirm the actual Codex runtime, selected subscription account, model availability and a completed synthetic reply. The `smoke` action uses a fixed harmless prompt and no delivery flag. It consumes subscription allowance. CI never performs this step.

## 6. Acceptance tasks before real business access

1. Ask for a Gujarati greeting, then continue in Hindi and English. Review language quality yourself.
2. Ask JARVIS to create and track a Workboard task using only a synthetic objective. Verify a checkpoint survives a controlled Gateway restart.
3. Add a synthetic preference in private memory and retrieve it using a different wording and an exact keyword. Keyword search does not guarantee semantic recall.
4. Reconcile `examples/sample-invoices.csv` using the existing file tool. Confirm reports do not send reminders or payments.
5. Verify the execution sandbox cannot access a host-side canary or write outside the designated workspace. Test native Codex tools as well as OpenClaw dynamic tools. Do not use real secrets for this test. Failures block wider access; do not bypass namespace restrictions.
6. Attempt a denied operation and confirm policy blocks it. Workspace prose alone is not enforcement.
7. Cancel a harmless long task in the native UI; verify future work stops and the outcome is recorded. Test restart recovery without replaying an uncertain action.
8. Verify the absence of API-key fallback by disconnecting model access in an isolated test state; the task should fail visibly. Do not deliberately exhaust a real account's allowance.

## 7. Proactive work, apps and Canvas

Nothing is automatically scheduled. Heartbeats, autonomous skill maintenance, outbound messages, new agent dispatch, and paid search/media are disabled in the starter. After the acceptance tasks pass, configure one native automation at a time with input, owner, schedule/event, Asia/Kolkata timezone, destination, quiet hours, deduplication, allowance and stop rule.

The starter deliberately denies outbound message and device tools. To add a business integration, review a separate staged configuration and exact permission diff, scoped credentials, failure handling and synthetic tests. The strict launcher rejects unreviewed config changes, including newly enabled channels. It is a reviewed starter policy, not a configuration editor; a reviewed source change can define an expanded preset later.

Existing OpenClaw Canvas/widget capabilities are not the same as a full ChatGPT document editor. Canvas is denied in the inherited sandbox preset. Research search providers, private app connectors, document exports, Canvas editing, voice and mobile hardware capabilities require their own integration checks; they are not implemented by these workspace templates. Keep the truthful status map below.

## 8. Background service and recovery

After staging acceptance, review `ops/jarvis-user.service.example`, adjust paths/limits, and install as a user service. Do not enable it during source development. Stop the relevant user unit before configuration changes or offline restore; do not restart Docker, change firewall rules, or touch unrelated services.

`systemctl --user stop jarvis` gracefully stops the process group. Native OpenClaw/Codex owns task/thread recovery. Snapshot/back up the complete dedicated private directory and runtime-specific state only through a consistent stopped-writer or supported online backup procedure. Backups contain credentials: protect and encrypt them outside Git. Rehearse restore to a different isolated directory before deleting the old installation.

No automatic deployment on push is added. Use the existing release-controller plan and explicit release gates. The sample service is not evidence of capacity or host compatibility.

## Status and practical limits

| Capability | Source status | Runtime proof required |
| --- | --- | --- |
| Private config/workspace creation, strict launch policy | Implemented and offline-tested | Host path/OS compatibility |
| Plus-backed Codex runtime selection | Implemented configuration | Actual account login, selected model, completed turn |
| Native chat, tasks, memory and dashboard | Reuses pinned OpenClaw | Acceptance tests on an installed Gateway |
| Proactive schedules | Native runtime available; starter disabled | Separately authorized routine and dedup/cancel tests |
| External apps, WhatsApp, GitHub automation | No new credentials or adapters configured | Scoped integrations and tests |
| Rich Canvas editor and exports | Future work | UI implementation and format validation |
| Voice and Android/Windows companion | Future integration | Supported clients and permissions |
| Live VPS deployment / existing setup migration | Not performed | Read-only inventory, recovery baseline, staging acceptance |

This is a working source setup path, not a claim of complete parity with dots or Grok Bot. Model errors, usage limits and service outages remain possible.

## Pinned official references

Checked against OpenClaw tag `v2026.10.4`:

- [OpenAI subscription setup](https://github.com/openclaw/openclaw/blob/v2026.10.4/docs/providers/openai/setup.md)
- [Codex runtime configuration](https://github.com/openclaw/openclaw/blob/v2026.10.4/docs/plugins/codex-harness/configuration.md)
- [Auth and environment isolation](https://github.com/openclaw/openclaw/blob/v2026.10.4/docs/plugins/codex-harness-reference/auth.md)
- [Models/auth CLI](https://github.com/openclaw/openclaw/blob/v2026.10.4/docs/cli/models.md)
- [Operator HTTP API boundary](https://github.com/openclaw/openclaw/blob/v2026.10.4/docs/gateway/openai-http-api.md)

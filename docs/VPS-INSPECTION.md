# Inspect the existing VPS without changing its login flow

This manual workflow collects connection metadata, not a server backup. It never installs packages on the VPS, executes OpenClaw/Codex, invokes login/status/refresh/probe commands, migrates state, restarts services, or edits the deployment. File reads may update operating-system access timestamps. Preserve the existing installation; do not format the VPS based on this report alone.

## Why a private workflow

The repository is public. Server paths, service metadata and connection details must not be printed in public job logs or uploaded as plaintext artifacts. `Inspect VPS (private, read only)` streams the collector over SSH and immediately encrypts its JSON output on the runner using an operator-supplied X25519 recipient. It uploads only the authenticated AES-256-GCM envelope. The decryption private key never belongs in GitHub Actions.

The SSH account must already be authorized on the VPS and have enough read access. The current connection can prepare source workflows, but it does not have tools to set GitHub secrets or dispatch the manual job. The owner must configure those through GitHub. Adding repository write permission alone does not provide VPS access.

## One-time GitHub setup

1. Review and merge this inspection PR so the workflow exists on `main`. It rejects execution from other branches. Do not merge unrelated deployment changes just to inspect the host.
2. On a trusted local computer with Node 20+, generate a report recipient:

   ```sh
   node ops/report_crypto.mjs keygen ../jarvis-inspection-keys
   ```

   Keep `recipient-private.pem` private and backed up locally. The printed public recipient, also in `recipient-public.txt`, is the only encryption-key value that goes to GitHub. Never generate a decryption key on a public Actions runner. These files are deliberately created outside the repository; an existing output directory is refused.
3. In repository **Settings → Environments**, create **vps-inspection**. Restrict deployment branches to `main`, add a required reviewer where available, and review access to that environment. Do not make inspection automatic on pull requests or arbitrary pushes.
4. Add these **environment secrets**:

   | Name | Value |
   | --- | --- |
   | `VPS_SSH_HOST` | VPS IP/hostname |
   | `VPS_SSH_PORT` | SSH port, normally `22` |
   | `VPS_SSH_USER` | Existing authorized inspection account |
   | `VPS_SSH_PRIVATE_KEY` | Matching SSH private key, entered only in GitHub's secret UI |
   | `VPS_SSH_KNOWN_HOSTS` | Verified known-hosts record for that server and port |

   Use an SSH key you control. Never paste it into chat, an issue, a workflow file or source. A public key in `authorized_keys` does not give GitHub its matching private key. Prefer a narrowly scoped inspection account; a root key in an Actions environment gives anyone who can change approved workflow code broad server authority. Secret masking does not replace environment/branch review.
5. Add the **environment variable** `VPS_REPORT_RECIPIENT` containing the generated public recipient string.

Obtain the host public key from the trusted hosting console and verify its fingerprint. For a standard SSH port, a known-hosts record is the hostname/IP followed by the host key type and base64 public key. Nonstandard ports use `[hostname]:port` as the first field. Do not trust an unverified `ssh-keyscan` result or disable host verification to get the job working.

GitHub environment and artifact features follow the account's available plan and policies. No paid model or external report-storage service is used by this workflow.

## Run once and review privately

In **Actions → Inspect VPS (private, read only) → Run workflow**, select `main` and approve the protected environment job if required. The workflow has a bounded timeout, serializes runs, requires verified SSH host keys, and never requests a password or interactive login.

Download `vps-inspection-encrypted` from the completed run. Decrypt on your trusted local computer:

```sh
umask 077
node ops/report_crypto.mjs open vps-inspection.sealed.json ../jarvis-inspection-keys/recipient-private.pem > vps-inspection.private.json
```

Keep the decrypted report outside the public repository. If sharing it with your assistant, use a private file attachment or a trusted local session; never paste it into a public GitHub issue. Do not upload the decryption private key. Without that key, the encrypted artifact cannot be opened; retain the key or rerun using a newly generated recipient. Artifacts expire after three days.

## What the report can establish

- Matching running OpenClaw/Codex process roles (`gateway`, `app-server`, `exec`, `review`, `login`) without copying their command lines or prompts.
- Selected systemd service state, configuration locations and environment-file presence. Environment files and `/proc/*/environ` are not read.
- Strict-JSON OpenClaw configuration structure: primary model, selected known runtimes, CLI backend executable names, per-agent overrides, provider runtime choice, OAuth/API-key mode metadata, and Codex home scope. Profile IDs and raw provider settings are omitted.
- Static installed package versions where discoverable, without executing application binaries.
- Whether conventional auth/state files exist, their owner/mode, and known helper scripts' device-code/home-override indicators. Credential file contents, token expiry values, chat history and backups are never read.

Use these facts to distinguish:

| Evidence | Likely connection path | What remains to verify |
| --- | --- | --- |
| `codex` runtime and a running `app-server` role | Native Codex harness | Selected account, live tool policy and completed inference |
| `codex-cli` backend and `exec` role | Direct CLI subprocess adapter | Wrapper paths, supported protocol and session continuity |
| OAuth-mode OpenAI profile without native runtime evidence | OpenClaw-managed subscription authentication | Actual selected runtime and account route |
| Paid provider primary plus a Codex helper | Codex may only be an auxiliary review tool | Whether normal chat ever reaches Codex |

Configured settings and file presence do not prove that the existing login is valid, which account is active, or that a model call will succeed. Those checks can refresh/mutate state or spend allowance and require a separate controlled step. No new login should be initiated until the existing connection is understood.

Discovery is bounded. JSON5/includes, custom service wrappers, containers, user-level systemd units, hidden provider routes and nonstandard homes may require a second narrowly targeted private inspection. The script reports unsupported structures rather than invoking `doctor --fix` or importing old auth state.

## Preserve before any future reinstall

Once the connection path is understood, prepare a separate consistent, encrypted recovery backup and test restore. Preserve the original user identity, home/state directories, configuration, auth/pairing stores, service definitions, workspace and any required external credentials. This report intentionally contains none of the credential material needed to restore a login after formatting. Keep the old system running until recovery and staging are proven.

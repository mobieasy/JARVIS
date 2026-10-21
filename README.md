# JARVIS

**An open-source foundation for a personal assistant you host and shape. Built on OpenClaw.**

JARVIS aims to offer a self-hosted alternative for people who like the persistent-assistant approach of ChatGPT dots and the research-oriented experience of Grok assistants. The goal is useful work: remember project context, track tasks, work with code and business files, and connect tools under your control.

**Status: early developer preview.** Feature parity with hosted products is a goal, not a claim. This repository contains configuration, an optional SMS authentication proxy, a small business-file tool, and a roadmap; OpenClaw supplies the assistant runtime. Model providers and optional services have their own costs.

## What is here today

- A private subscription-backed setup path using ChatGPT/Codex OAuth, a pinned official Codex harness, keyword memory, and strict launch checks. See [ChatGPT Plus setup](docs/SUBSCRIPTION-ASSISTANT.md). Live account and host acceptance are separate checks.
- OpenClaw configuration template with explicit model choices, a Docker tool sandbox and Workboard task tracking.
- Optional single-owner SMS login proxy: browser-bound one-time codes, persistent limits, revocable sessions, and HTTP/WebSocket forwarding. The current adapter targets APITXT and Indian mobile numbers.
- An INR invoice CSV reconciliation tool with synthetic sample data and regression tests.
- A Codex helper for optional ChatGPT-authenticated review. Direct nested terminal execution may fail where containers block user namespaces; a login alone does not prove coding execution works.
- Foreground memory/project notes and a roadmap for richer persistent work. Periodic memory dreaming and autonomous skill maintenance are disabled in the example configuration.

## Try the file tool first

Python 3.11+ is sufficient; no API key, SMS account or running assistant is needed:

```sh
python -m unittest discover -s tools -p 'test_*.py' -v
python tools/reconcile_invoices.py examples/sample-invoices.csv --as-of 2026-10-18 --output /tmp/jarvis-sample
python -m unittest discover -s auth -p 'test_*.py' -v
```

The sample is synthetic. Reports do not send reminders or execute payments.

## Start the assistant locally

For **ChatGPT Plus/Codex subscription use with no paid API fallback**, follow [the subscription setup runbook](docs/SUBSCRIPTION-ASSISTANT.md). It creates fresh private state outside this repository, signs in directly with OpenAI, and reuses OpenClaw's dashboard, tasks and memory. Do not replace an existing deployment's configuration.

The legacy example below uses **separately billed OpenRouter models**. It is retained for existing contributors and is not the subscription-only setup.

Requires a compatible Linux environment, Node.js 24, npm 11 and Docker. The reference runtime is pinned to OpenClaw 2026.10.4; review upstream fixes before an internet-facing installation.

```sh
npm ci
# Review Dockerfile.sandbox before building.
docker build -f Dockerfile.sandbox -t jarvis-sandbox:dev .
python scripts/configure.py --workspace "$PWD/workspace" --output config/openclaw.local.json
# Set OPENROUTER_API_KEY and a securely generated OPENCLAW_GATEWAY_TOKEN in your shell.
OPENCLAW_CONFIG_PATH="$PWD/config/openclaw.local.json" ./node_modules/.bin/openclaw config validate
OPENCLAW_CONFIG_PATH="$PWD/config/openclaw.local.json" ./node_modules/.bin/openclaw gateway --bind loopback --port 18789
```

Open the local dashboard and use its gateway-secret sign-in. Never expose the raw gateway port publicly. Add your own profile only to the ignored private workspace. The runtime uses paid remote models; set a provider-side spending limit. The model list is an example, not a promise of availability for every provider or account.

Web search is disabled in the template until you configure a supported provider. Review the [architecture](docs/ARCHITECTURE.md), [optional SMS adapter](auth/README.md), and [roadmap](ROADMAP.md) before adding services. This is a local developer starting point, not a one-command production installer.

## Build it with us

We welcome thoughtful improvements, small fixes and honest testing reports. New contributors are welcome—documentation and reproducible bug reports matter as much as code.

Fork the repository, work on a `feat/...`, `fix/...` or `docs/...` branch, and open a pull request against `main`. Please keep changes focused and include relevant checks. See [CONTRIBUTING.md](CONTRIBUTING.md). Maintainers review proposed changes before merging; running deployments should use reviewed commits.

Good first contributions include clearer setup docs, accessibility/mobile polish, provider adapters, stronger input-validation tests, and reproducible container compatibility diagnostics. Please discuss larger features in an issue first.

MIT licensed. Built on OpenClaw, with gratitude to its maintainers and contributors. Independent from OpenAI and xAI; see [third-party notices](THIRD_PARTY_NOTICES.md).

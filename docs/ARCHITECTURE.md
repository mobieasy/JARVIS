# Architecture

The initial stack is a thin integration around OpenClaw:

- **Access:** local token-protected dashboard by default. Optional remote HTTPS + SMS authentication requires careful proxy configuration.
- **Coordination:** OpenClaw sessions and Workboard records; one expensive task at a time in the example.
- **Execution:** non-root Docker tool sandbox, no Docker socket or host credential mounts in the container.
- **Memory:** private workspace files and supported retrieval tools. Configure and test embeddings separately if needed.
- **Models:** user-provided provider credentials and explicit model allowlists. Provider billing remains external.
- **Subscription setup:** `scripts/jarvis.py` creates fresh private state with one OpenAI OAuth profile, a required native Codex runtime, no model fallbacks, and an allowlisted child environment. It reuses the existing dashboard/Workboard instead of introducing another task engine. See [setup and acceptance](SUBSCRIPTION-ASSISTANT.md).
- **Optional coding assistance:** Codex review can receive bounded source in its prompt. JARVIS applies reviewed patches and runs checks. Direct Codex nested shell support depends on container namespace policy and is not verified by sign-in.

Keep personal deployment data in an ignored workspace outside versioned source. This community repository starts with sanitized history; never publish a private deployment history to it. Extensions should reuse OpenClaw's capabilities before adding duplicate schedulers, databases or dashboards.

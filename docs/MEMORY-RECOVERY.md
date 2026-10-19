# Memory recovery without embedding costs

OpenClaw 2026.10.4 supports `memory.search.provider: "none"` for lexical
full-text search. Use the accompanying config patch only when an existing
`fts-only` index conflicts with an automatically selected embedding provider.
This restores keyword retrieval, not semantic embedding search.

Before applying, inspect effective config and back up config and the agent SQLite
DB using SQLite's online backup API. Validate a merged candidate, then apply the
patch using `openclaw config patch --file config/memory-lexical.patch.json`.
Do not replace the whole live config with a repository example.
Run `openclaw memory status --agent developer`, and verify a known fact using
`memory_search`. Reindex only if necessary, under the corrected configuration.
Keep a private recovery record outside Git. Never edit index identity metadata to
pretend an incompatible embedding index is valid.

# Contributor agent instructions

Read README.md and CONTRIBUTING.md first. Inspect Git status before editing. Use a focused branch, preserve unrelated work, and run the relevant standard-library Python tests. Keep setup examples generic and make no claims of parity with commercial assistants that are not demonstrated.

Never read or publish a user's private deployment, profile, chat history, credentials or backups as part of a source contribution. Use only synthetic fixtures. Test the auth service with fake SMS; do not invoke a live provider or paid model from CI.

Changes to authentication, provider payload validation, headers, CSRF/session behavior or sandbox boundaries need meaningful regression tests and an explanation of the trust boundary. Do not weaken protections to make a test or coding agent run. Separate source changes from deployment and publication approval.

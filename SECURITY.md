# Security

This is an early developer preview with no independent security audit or production-support guarantee. The SMS proxy is single-owner and currently APITXT/India-specific; it is not a multi-tenant identity provider.

Report a suspected vulnerability through the repository's private security advisory flow when available. If it is unavailable, contact the maintainer through the GitHub profile before sharing exploit details. Do not publish credentials, customer data or live attack details in public issues.

Use provider-side budgets, scoped credentials, HTTPS for remote access, loopback-only gateway binding, and reviewed commits. Keep production data out of test fixtures. A Docker-enabled gateway account is trusted orchestration code; a tool container is not a guarantee against every exploit.

Do not work around a sandbox failure by disabling protections. Include the OS, Docker, runtime version and a credential-free reproduction in compatibility reports.

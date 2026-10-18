# Optional SMS authentication adapter

Experimental single-owner HTTPS boundary for an OpenClaw gateway. All approved numbers map to identity `owner`; this is not separate-user isolation.

The Python service listens on localhost:18889, authenticates an opaque session, and forwards to localhost:18789. It strips browser-supplied identity, authorization, scope and forwarding headers before injecting verified identity. Codes are short-lived, browser-bound, single-use and HMAC-protected at rest; rate limits and hashed sessions persist in SQLite. Logout invalidates the session and closes its WebSockets.

Current limitations: Indian +91 phone numbers and APITXT `https://apitxt.com/api/sendMsg`. Configure your own approved sender/entity/template/message; this project supplies no SMS account or DLT registration. Never substitute an unapproved message into a registered template.

Required environment: `PUBLIC_ORIGIN` (exact HTTPS origin without trailing slash), `AUTH_DB`, `AUTH_SECRET` (at least 40 random characters), `ALLOWED_PHONES`, `SMS_API_KEY`, `SMS_MESSAGE` (with `{OTP}`), `SMS_ENDPOINT`, `SMS_SENDER`, `SMS_ROUTE`, `SMS_TEMPLATE_ID`, and `SMS_ENTITY_ID`. Store these outside Git and the assistant workspace. See `send_sms` for the exact current provider payload.

Run the service as a separate non-Docker account with access only to its database directory. Put a trusted HTTPS reverse proxy in front of it, overwrite the real client forwarding headers, and block direct gateway access. Only after this boundary is verified should OpenClaw use trusted-proxy authentication with identity `owner`, loopback-only trusted proxy addresses and required identity/forwarding headers. Consult the installed OpenClaw documentation for the matching schema. Delegated proxy auth, loopback trust and device auto-approval can produce explicit gateway audit notices; review that trust boundary rather than suppressing them.

Do not run this adapter behind an untrusted forwarding proxy or expose the raw gateway. The example local configuration retains token mode and does not automatically activate SMS or pairing. Production deployment and recovery automation are roadmap work for the community edition.

Tests use fake SMS and temporary databases: `python -m unittest discover -s auth -p 'test_*.py' -v`.

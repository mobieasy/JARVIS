# Contributing to JARVIS

Thank you for helping build a useful, understandable assistant. You do not need to be an expert to contribute.

1. Check existing issues and pull requests. For a larger feature, open an issue explaining the user problem and proposed scope.
2. Fork the repository and create a focused branch: `git switch -c feat/your-feature`, `fix/your-fix`, or `docs/your-topic`.
3. Keep one purpose per pull request. Follow nearby conventions and explain any new dependency, permission, recurring job or paid service.
4. Run `python -m unittest discover -s auth -p 'test_*.py' -v` and `python -m unittest discover -s tools -p 'test_*.py' -v` for relevant changes. Use mocks and synthetic data; tests must not send real SMS or call paid models.
5. Open a PR to `main` with the problem, behavior after the change, tests performed and remaining limits. Draft PRs and early questions are welcome.

Never commit profiles, chats, credentials, phone/customer lists, private keys, databases, backups or screenshots containing private information. Do not upload `.env` or runtime workspaces. Report vulnerabilities privately as described in SECURITY.md.

Branches do not imply deployment approval. Contributors use forks or topic branches; changes reach main through reviewed pull requests. Maintain respectful, constructive discussions. Credit upstream projects and preserve their license notices. Contributions are made under the repository's MIT license; submit only material you have the right to contribute.

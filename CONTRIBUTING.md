# Contributing to Spoor

Thanks for helping. This page covers how to set up, what a good pull request looks like, and the rules for contributing labels.

## Setup

Follow the Development section of the [README](README.md), and install the pre-commit hooks:

```bash
uv run pre-commit install
```

The hooks run ruff (lint and format) and gitleaks (secret scanning) on every commit. CI runs the same checks plus the test suite.

## Pull requests

- Keep each pull request to one concern.
- Add or update tests for behaviour you change. Chain adapters are tested against recorded fixtures, never live APIs.
- If you change how tracing or a heuristic works, update [docs/methodology.md](docs/methodology.md) in the same pull request.
- Never commit API keys, `.env` files, or fixtures that contain keys. Fixture recording strips keys automatically; check the diff anyway.

## Sign-off (DCO)

Every commit must be signed off under the [Developer Certificate of Origin](https://developercertificate.org/), which states you have the right to submit the work under this project's license:

```bash
git commit -s
```

## Label policy

Labels say who is behind an address, so they carry real consequences when wrong. Every label pull request must meet all of these:

1. **Entities only.** Exchanges, bridges, mixers, sanctioned addresses, protocols, and publicly reported scam contracts or wallets. **Never label a private individual**, even when you believe you know who controls a wallet.
2. **Public source required.** Each entry cites a public URL that supports the attribution: an official disclosure, a sanctions list, a court document, or a published investigation. "I traced it myself" is not a source.
3. **Honest confidence.** Use the lowest confidence level the source supports.
4. **No private data.** Nothing from behind a login, leaked datasets, or private case work.

Maintainers will close label pull requests that do not meet this policy.

## Read-only rule

Spoor never signs or sends transactions and never handles private keys. Pull requests that add any write path to a chain will not be accepted.

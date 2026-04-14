# Security Policy

## Scope

This repository is internal capability tooling for Seriengrafik / 3D Car QA and integration work.

The repository is governed by the internal proprietary terms in [LICENSE](LICENSE).

> [!IMPORTANT]
> If a finding involves proprietary source data, credentials, tokens, or accidental publication risk, do not open a public issue. Escalate it privately through the owning internal team or technical contact.

Report issues that could expose:

- internal source trees or confidential asset data
- unsafe path handling or destructive local workspace behavior
- credential, token, or environment-variable leakage
- accidental publication of proprietary files or generated evidence

## Reporting

Until a formal company-side security channel is defined for this repository:

1. Do not open a public issue for sensitive findings.
2. Escalate privately through the owning internal team or your direct technical contact.
3. Include reproduction steps, affected files or commands, and the safest known mitigation.

## Handling guidance

- Keep mirrored SVN content out of git by default.
- Prefer sanitized logs or screenshots when discussing issues.
- Rotate or remove any accidentally exposed credentials immediately.

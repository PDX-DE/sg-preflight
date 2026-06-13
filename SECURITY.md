# Security overview

SGFX Quality-Hero is a local desktop QA support tool. This summarizes how it handles data, credentials, and network access.

## Source access

- Read-only over BMW source. It inspects local SVN and BMW Git working copies, for example through `git log` and `svn info` / `svn log`, and never writes, commits, or pushes to either.
- All processing is local to the operator's workstation. No QA data or 3D assets leave the machine.

## Credentials

- Jira access uses each user's own personal access token.
- The token is stored in the Windows Credential Manager, also known as the OS keychain. It is never stored in a file, in source, or in logs. Token values are masked in all output and exported reports.

## Network access

- The only outbound calls are to the configured Jira host over HTTPS with certificate verification enabled, plus an optional user-initiated component download.
- There is no telemetry, analytics, or automatic update check. Nothing leaves the workstation by default.

## Writes to Jira

- Every Jira write, including comments and attachments, is off by default and requires explicit operator confirmation. There is no automatic posting.

## Scope of automation

- The tool surfaces evidence and suggests review order. Delivery and visual verdicts remain human decisions; it supports manual review rather than replacing it.

# Security Policy

## Supported versions

Security fixes are applied on the latest commit of the default branch.

## What this project accesses

| Integration | Permission needed | Data touched |
|-------------|-------------------|--------------|
| OpenAI | API key | Standup transcript excerpts + open ticket summaries |
| Jira Cloud | Email + API token | Read issues (JQL), write comments |
| Google Drive | Service account + domain-wide delegation | Read-only Docs matching the meeting name |

Transcripts and ticket text may contain **personal or confidential work information**. Treat API keys and service-account JSON as production secrets.

## Hardening already in the code

- `DRY_RUN=true` by default; posting requires `--live` or `DRY_RUN=false`
- Jira base URL must be `https://` (no embedded credentials, no localhost)
- Ticket keys validated + restricted to the fetched Jira context allowlist
- Drive query values escaped; folder/file ids format-checked
- Service-account JSON rejected if world-writable; `.env` permission warning
- Transcript length clamped before LLM calls
- Idempotency state written with restrictive file modes when the OS allows
- Jira HTTP errors reported without dumping auth headers

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security bugs.

Email the maintainer (see the GitHub profile / repo owner) with:

1. Description of the issue and impact
2. Steps to reproduce
3. Any suggested fix

You should receive an acknowledgement within a few days. Please give a reasonable window before public disclosure.

## Recommended operator practices

1. Use a **dedicated Jira bot account** with the minimum permissions (browse + comment).
2. Scope Google domain-wide delegation to **Drive readonly** only, impersonating only the standup organizer.
3. Store secrets in `.env` or a secret manager — never in git:

   ```bash
   chmod 600 .env
   chmod 600 /path/to/service-account.json
   ```

4. Run dry-run first; review drafted comments before `--live`.
5. Rotate OpenAI / Jira / Google keys if they are ever committed or shared.
6. Before publishing forks, run:

   ```bash
   ./scripts/oss_check.sh
   ```

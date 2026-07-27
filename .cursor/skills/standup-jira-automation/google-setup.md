# Google Workspace setup (Drive auto-discovery)

Required only when running without `--file`. Document these steps for the user;
do not claim the agent can complete Workspace Admin steps for them.

## 1. Google Cloud project

1. Create/select a project in Google Cloud Console.
2. Enable **Google Drive API**.
3. Create a **service account**.
4. Create a JSON key → store outside git (`service-account*.json` is gitignored).
5. Note the service account **Client ID** (numeric) for domain-wide delegation.

## 2. Domain-wide delegation (Workspace Admin)

1. Admin console → Security → Access and data control → API controls →
   Domain-wide delegation (wording varies slightly by Admin UI version).
2. Add the service account Client ID.
3. Authorize OAuth scope (exactly):

   ```
   https://www.googleapis.com/auth/drive.readonly
   ```

## 3. Impersonation target

Set `GOOGLE_IMPERSONATE_USER` to the standup organizer (or whoever owns /
receives Meet + Gemini notes Docs). The service account acts as that user for
read-only Drive search + Doc export.

## 4. Meeting name + optional folder

- `GOOGLE_MEETING_NAME` must be a substring of the Doc title
  (default `STAND-UP`). Matches:
  - `STAND-UP - Transcript`
  - `STAND-UP - … - Notes by Gemini`
- Optional `GOOGLE_TRANSCRIPT_FOLDER_ID` to restrict search to one Drive folder.
- `MAX_TRANSCRIPT_AGE_HOURS` (default 24) ignores older Docs.

## 5. Verify

```bash
# After .env is filled:
python main.py          # dry-run; should find a recent Doc or print "No new transcript"
```

### Common failures

| Error | Fix |
|-------|-----|
| 403 insufficient permissions | DWD not configured, wrong Client ID, or missing scope |
| 404 / empty results | Wrong impersonated user, meeting name mismatch, Doc outside age window |
| Invalid grant | Impersonate user must be a real user in the same Workspace |

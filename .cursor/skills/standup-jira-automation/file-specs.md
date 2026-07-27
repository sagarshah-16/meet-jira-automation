# File specifications

Implement each file to match these contracts. Prefer clear, small modules —
no frameworks beyond the listed deps.

## `.gitignore`

Ignore: `.env`, `service-account*.json`, `*.pem`, `.venv/`, `__pycache__/`,
`*.pyc`, `.state/`, `logs/`, `*.log`, `.DS_Store`, `.idea/`, `.vscode/`, `.claude/`.

## `.env.example`

```env
# --- LLM (OpenAI) ---
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

# --- Jira Cloud ---
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=standup-bot@yourcompany.com
JIRA_API_TOKEN=...
JIRA_PROJECT_KEY=PROJ
# JQL for ticket context (Kanban: everything not Done). {project} is substituted.
JIRA_CONTEXT_JQL=project = {project} AND statusCategory != Done ORDER BY updated DESC

# --- Google (service account with domain-wide delegation) ---
GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account.json
# The standup organizer whose Drive holds the Meet transcripts
GOOGLE_IMPERSONATE_USER=pm@yourcompany.com
# Optional: restrict search to a specific Drive folder ID (Meet Recordings)
GOOGLE_TRANSCRIPT_FOLDER_ID=
# Meeting name as it appears in the Doc title (matches Gemini notes docs too)
GOOGLE_MEETING_NAME=STAND-UP

# --- Behavior ---
# true = log comments instead of posting to Jira
DRY_RUN=true
# Skip transcripts older than this many hours when auto-discovering
MAX_TRANSCRIPT_AGE_HOURS=24
```

## `standup_notes/validation.py`

Must provide:
- `validate_https_origin(url, name=...)` — https only, no userinfo, no localhost
- `validate_ticket_key(key)` — `^[A-Z][A-Z0-9]+-\d+$`
- `escape_drive_query_value(value)` — escape `\` and `'` for Drive `q`
- `validate_drive_id(...)` / folder id helper
- `validate_service_account_file(path)` — exists; reject world-writable
- `warn_insecure_env_file()` — warn if `.env` is group/world-readable
- `clamp_transcript(text)` — hard cap (~400k chars)

## `standup_notes/config.py`

- `load_dotenv()` at import; call `warn_insecure_env_file()`.
- `@dataclass class Config` with fields mirroring env vars above.
- `__post_init__`: validate Jira URL, service-account path, folder id, age bounds.
- Bool helper: treat `1/true/yes` (case-insensitive) as true; default `DRY_RUN=true`.
- `context_jql` property: `self.jira_context_jql.format(project=self.jira_project_key)`.
- `require(*names)`: if any attribute is falsy, `SystemExit` with a message listing
  missing names and pointing at `.env.example`.

## `standup_notes/models.py`

Dataclasses:

```python
TranscriptTurn(speaker, text, timestamp="")
Ticket(key, summary, status, assignee, description)
  .brief() -> str   # "KEY [status] (assignee: ...): summary\n  desc[:400]"
Segment(ticket_key, confidence, speaker, raw_text, reasoning="")
TicketNote(ticket_key, confidence, status_update="", summary="", blocker="", progress="")
  .is_empty -> bool
  .render(meeting_date) -> str
RunReport(transcript_name="", tickets_updated=[], tickets_skipped=[],
          segments_discarded=0, dry_run=True)
```

`TicketNote.render` rules:
- Header: `🤖 Auto-generated from standup — {date} · please verify`
- For each of Summary, Status, Blocker, Progress: if value non-empty, emit
  `### {Label}` then the value.
- If `confidence == "low"`, append the low-confidence warning line.

## `standup_notes/transcript.py`

Patterns:
- Timestamp line: `^\d{1,2}:\d{2}(:\d{2})?$`
- Speaker line: `^([^:]{1,60}?):\s+(.*)$`

`extract_transcript_section(text)`:
- Search for a line that is exactly `Transcript` starting after the first 200
  chars (`re.search(r"^Transcript\s*$", text[200:], MULTILINE)`).
- If found, return from that match; else return full text.

`parse_transcript(text)`:
- Skip blanks; update `current_ts` on timestamp lines.
- On speaker match: merge into previous turn if same speaker, else append.
- Non-matching non-empty lines append to the previous turn (Doc wrap).

`render_turns(turns)` → `"(i)[ts] Speaker: text"` per line for LLM input.

## `standup_notes/jira_client.py`

- `requests.Session` with Basic auth `(email, api_token)`, `Accept: application/json`.
- `fetch_context_tickets(jql, max_results=100)`:
  - GET `{base}/rest/api/3/search/jql`
  - params: `jql`, `maxResults` (page ≤ 50), `fields=summary,status,assignee,description`
  - paginate with `nextPageToken`
  - Flatten ADF description to plain text recursively.
- `add_comment(ticket_key, body)`:
  - POST `{base}/rest/api/3/issue/{key}/comment` with `{"body": adf_doc}`
- `_text_to_adf(body)`:
  - `### ` lines → heading level 3
  - lines matching `^\*(.+?):\*\s*(.*)$` → paragraph with strong label (legacy)
  - other non-empty lines → paragraph with text
  - skip blank lines

## `standup_notes/llm.py`

- Client: `OpenAI(api_key=...)`, model from config, `temperature=0`,
  `response_format={"type": "json_object"}`.
- System prompts: **copy verbatim from [prompts.md](prompts.md)**.
- `segment(turns, tickets)`:
  - user message = open tickets (`brief()` each) + numbered transcript
  - filter segments to `valid_keys = {t.key for t in tickets}` (uppercase keys)
- `structure(segment, ticket)` → `TicketNote` from JSON fields
  `status_update`, `summary`, `blocker`, `progress` (strip strings).

## `standup_notes/google_drive.py`

```python
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
```

- Build credentials from service account file, `.with_subject(impersonate_user)`.
- `find_latest_transcript(cfg) -> dict | None` with keys `id`, `name`, `createdTime`.
  - Query clauses AND-joined:
    - `mimeType = 'application/vnd.google-apps.document'`
    - `name contains '{meeting_name}'`
    - `createdTime > '{cutoff ISO}'`
    - `trashed = false`
    - optional: `'{folder_id}' in parents`
  - `orderBy=createdTime desc`, `pageSize=5`, shared drives enabled.
- `download_doc_text(cfg, file_id)`: export as `text/plain`.

## `standup_notes/pipeline.py`

```python
STATE_FILE = Path(".state/processed.json")
```

`run(cfg, transcript_text, transcript_id, transcript_name="", meeting_date="")`:
1. Default `meeting_date` to today ISO.
2. If id already processed → print skip message, return empty report.
3. Parse turns; if none → return.
4. Fetch tickets; if none → abort with JQL hint.
5. Pass A → `_merge_segments` (same key concatenates `raw_text`; keep higher confidence).
6. For each segment: Pass B; skip if `is_empty`; fill empty `status_update` from board status;
   dry-run print or `add_comment`; track updated/skipped.
7. If not dry-run: `_mark_processed(transcript_id)`.
8. Print run summary counts.

## `main.py`

Argparse: `--file`, `--live`, `--date`.
- If `--live`: `cfg.dry_run = False`.
- Always `require` OpenAI + Jira fields.
- File path: read text; `transcript_id = "file:" + sha256(text)[:16]`.
- Else: require Google fields; find latest; if None print benign message and return;
  else download and run with Drive file id.

## `run.sh` (zsh, executable)

- `cd` to script dir; `mkdir -p logs`; log to `logs/run-YYYYMMDD-HHMMSS.log`.
- Run `.venv/bin/python main.py --live`, tee to log.
- macOS `osascript` notification on success/failure (optional failure ok if no osascript).

## `samples/sample_transcript.txt`

Use the transcript in [samples.md](samples.md). Project key in the sample is `PROJ`
so dry-runs need `JIRA_PROJECT_KEY=PROJ` **or** swap keys in the sample to the
user's real project and ensure those issues exist / adjust expectations for
matching (Pass A only posts to keys present in Jira context).

For a first dry-run without matching real tickets, the agent should still verify
parsing + Jira fetch + LLM calls run; if Jira has no `PROJ-*` issues, either:
- temporarily use a sample whose keys exist in the user's project, or
- document that attributed segments may be empty when keys don't exist in context.

## README + LICENSE + security docs

- README: product overview, quick start, full OpenAI/Jira/Google setup, config
  table, usage, scheduling, troubleshooting, security, skill pointer.
- LICENSE: MIT, copyright holder from the user (default: ask once if unknown).
- SECURITY.md + CONTRIBUTING.md + `scripts/oss_check.sh` for open-source hygiene.
- Never ship org-specific transcripts (e.g. real employee names / internal keys).

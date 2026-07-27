# Standup → Jira Auto-Notes

Turns your Google Meet standup transcript into structured Jira comments — one per discussed ticket — so the board stays up to date without anyone typing notes by hand.

**What gets posted per ticket**

| Section | Content |
|---------|---------|
| Summary | What was discussed |
| Status | Current state of the work |
| Blocker | Only if someone explicitly mentioned one |
| Progress | What moved forward, if said |

Off-topic chatter is discarded. Unmatched segments are never posted. Low-confidence matches are flagged for a human to verify. Re-runs are idempotent — the same transcript will not be posted twice.

---

## How it works

```
Meet transcript (Drive or local file)
        │
        ▼
  Parse speaker turns
        │
        ▼
  Fetch open Jira tickets (context)
        │
        ▼
  LLM Pass A — segment & match tickets
        │
        ▼
  LLM Pass B — write Status / Summary / Blocker / Progress
        │
        ▼
  Post one comment per ticket (or dry-run print)
```

1. **Transcript** — Fetches the latest Meet / Gemini notes Doc from the organizer’s Drive (service account + domain-wide delegation), or reads a local `.txt` file.
2. **Jira context** — Loads open tickets from your project so the model can match spoken keys and correct speech-to-text garbles.
3. **Pass A** — Segments the transcript, anchors on spoken ticket keys, discards non-ticket talk.
4. **Pass B** — Writes the four-section note; empty sections are omitted; blockers are never invented.
5. **Post** — Comments as your Standup Bot Jira user. Dry-run is the default.

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| Python 3.10+ | Tested on 3.12–3.14 |
| OpenAI API key | `gpt-4o` by default (any JSON-capable chat model works) |
| Jira Cloud | API token for a bot (or human) account with comment permission |
| Google Workspace *(optional for Drive mode)* | Admin access to create a service account with **domain-wide delegation** |

You can develop and validate with a **local transcript file only** — Google Drive setup is only needed for auto-discovery after standup.

---

## Two ways to get this project

### A. Clone the repo (classic)

```bash
git clone https://github.com/<you>/Meet-Jira-Automation.git
cd Meet-Jira-Automation
```

### B. Build from the Cursor skill (no clone required)

This repo ships a Cursor Agent Skill that can **scaffold the entire bot from
specs** in an empty folder — useful if you want an agent to recreate or adapt
the system instead of copying source.

1. Copy the skill into your Cursor skills directory (or keep it in a checkout):

   ```bash
   # From a clone, or after downloading just the skill folder:
   mkdir -p ~/.cursor/skills
   cp -R .cursor/skills/standup-jira-automation ~/.cursor/skills/
   ```

2. In Cursor, ask something like:

   > Use the **standup-jira-automation** skill to scaffold a Meet standup → Jira
   > auto-notes bot in this folder. Stop after a dry-run on the sample transcript.

3. The agent will follow
   [`.cursor/skills/standup-jira-automation/SKILL.md`](.cursor/skills/standup-jira-automation/SKILL.md)
   and its reference files (`file-specs.md`, `prompts.md`, `architecture.md`,
   `google-setup.md`, `samples.md`) to generate the project.

Skill path in this repo:

```text
.cursor/skills/standup-jira-automation/
├── SKILL.md           # Entry point + build checklist
├── architecture.md    # Pipeline & design decisions
├── file-specs.md      # Per-module contracts
├── prompts.md         # Pass A/B LLM prompts (verbatim)
├── google-setup.md    # Domain-wide delegation steps
└── samples.md         # Sample transcript + acceptance checks
```

---

## Quick start (local dry-run)

No Google or live Jira posting required for this path — comments are printed, not posted.

```bash
# after clone (A) or skill scaffold (B):
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
```

Edit `.env` with at least:

```env
OPENAI_API_KEY=sk-...
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=standup-bot@yourcompany.com
JIRA_API_TOKEN=...
JIRA_PROJECT_KEY=PROJ
DRY_RUN=true
```

Then:

```bash
python main.py --file samples/sample_transcript.txt
```

You should see parsed turns, matched tickets, and drafted comments in the terminal. Nothing is written to Jira while `DRY_RUN=true`.

---

## Full setup

### 1. OpenAI

1. Create an API key at [platform.openai.com](https://platform.openai.com/api-keys).
2. Set `OPENAI_API_KEY` (and optionally `OPENAI_MODEL`) in `.env`.

### 2. Jira Cloud

1. Create (or reuse) a dedicated bot user, e.g. `standup-bot@yourcompany.com`.
2. Generate an [API token](https://id.atlassian.com/manage-profile/security/api-tokens) for that user.
3. Ensure the account can **browse** your project and **add comments** on issues.
4. Set in `.env`:

   ```env
   JIRA_BASE_URL=https://yourcompany.atlassian.net
   JIRA_EMAIL=standup-bot@yourcompany.com
   JIRA_API_TOKEN=your-api-token
   JIRA_PROJECT_KEY=PROJ
   ```

5. Optionally tune which tickets are loaded as matching context:

   ```env
   # {project} is replaced with JIRA_PROJECT_KEY
   JIRA_CONTEXT_JQL=project = {project} AND statusCategory != Done ORDER BY updated DESC
   ```

### 3. Google Drive (auto-discover Meet transcripts)

Skip this section if you will always pass `--file`.

Meet / Gemini typically save a Google Doc titled like:

- `STAND-UP - Transcript`, or
- `STAND-UP - … - Notes by Gemini` (transcript embedded inside)

The bot finds the newest matching Doc owned by (or visible to) the standup organizer.

#### 3a. Create a service account

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select a project.
2. Enable the **Google Drive API**.
3. Create a **service account** → download its JSON key.
4. Store the key outside the repo (or at least keep it gitignored — `service-account*.json` is already ignored).

#### 3b. Domain-wide delegation

1. In Google Workspace Admin → **Security** → **API controls** → **Domain-wide delegation**.
2. Add the service account’s **Client ID**.
3. Authorize this OAuth scope:

   ```
   https://www.googleapis.com/auth/drive.readonly
   ```

4. In `.env`, impersonate the organizer whose Drive holds the transcripts:

   ```env
   GOOGLE_SERVICE_ACCOUNT_FILE=/absolute/path/to/service-account.json
   GOOGLE_IMPERSONATE_USER=pm@yourcompany.com
   GOOGLE_MEETING_NAME=STAND-UP
   # Optional: limit search to a specific Drive folder
   GOOGLE_TRANSCRIPT_FOLDER_ID=
   MAX_TRANSCRIPT_AGE_HOURS=24
   ```

`GOOGLE_MEETING_NAME` must appear in the Doc title (case-sensitive substring match).

---

## Configuration reference

Copy from [`.env.example`](.env.example):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | yes | — | OpenAI API key |
| `OPENAI_MODEL` | no | `gpt-4o` | Chat model (must support JSON mode) |
| `JIRA_BASE_URL` | yes | — | e.g. `https://acme.atlassian.net` |
| `JIRA_EMAIL` | yes | — | Jira account email (bot recommended) |
| `JIRA_API_TOKEN` | yes | — | Atlassian API token |
| `JIRA_PROJECT_KEY` | yes | — | Project key, e.g. `PROJ` |
| `JIRA_CONTEXT_JQL` | no | open issues in project | JQL for matching context; `{project}` substituted |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | for Drive mode | — | Path to service account JSON |
| `GOOGLE_IMPERSONATE_USER` | for Drive mode | — | Organizer email to impersonate |
| `GOOGLE_TRANSCRIPT_FOLDER_ID` | no | (all Drive) | Restrict search to one folder |
| `GOOGLE_MEETING_NAME` | no | `STAND-UP` | Substring matched in Doc title |
| `DRY_RUN` | no | `true` | `true` = print only; `false` or `--live` = post |
| `MAX_TRANSCRIPT_AGE_HOURS` | no | `24` | Ignore older Drive docs |

---

## Usage

```bash
# Dry run on a local transcript (nothing posted)
python main.py --file samples/sample_transcript.txt

# Dry run on the latest Drive transcript
python main.py

# Post for real (overrides DRY_RUN)
python main.py --live

# Optional meeting date for the comment header (YYYY-MM-DD)
python main.py --file samples/sample_transcript.txt --date 2026-07-26 --live
```

**Safety defaults**

- `DRY_RUN=true` unless you pass `--live` or set `DRY_RUN=false`.
- Successfully posted transcripts are recorded in `.state/processed.json` so re-runs skip them.
- Dry runs do **not** mark transcripts as processed.

On macOS, [`run.sh`](run.sh) runs a live sync and shows a desktop notification (handy for a one-click shortcut or cron).

---

## Team convention

Ask engineers to say the **ticket key first**:

> “PROJ-123, yesterday I finished the OAuth flow…”

Spoken keys are the primary anchor. Speech-to-text may garble them (`proj one twenty three`); the model normalizes against the real ticket list. Content matching is a fallback when no key is heard.

---

## Scheduling

Run ~10 minutes after standup so the Meet / Gemini Doc has time to appear in Drive.

**cron (weekdays)**

```cron
15 9 * * 1-5  cd /path/to/Meet-Jira-Automation && .venv/bin/python main.py --live >> logs/cron.log 2>&1
```

**macOS launchd / button**

Point a LaunchAgent or Finder `.command` file at `./run.sh`.

If no Doc is found within `MAX_TRANSCRIPT_AGE_HOURS`, the process exits cleanly (weekend / holiday / notes not ready yet).

---

## Example Jira comment

```text
🤖 Auto-generated from standup — 2026-07-26 · please verify

### Summary
Alice finished the OAuth login flow and pushed it for code review.

### Status
In code review — addressing review comments today.

### Progress
OAuth login flow completed and submitted for review.
```

Low-confidence matches append:

```text
⚠️ Low-confidence match — please confirm this note belongs to this ticket.
```

---

## Project layout

```text
.
├── main.py                 # CLI entrypoint
├── run.sh                  # Live sync + macOS notification
├── requirements.txt
├── .env.example            # Template for configuration (no secrets)
├── LICENSE / SECURITY.md / CONTRIBUTING.md
├── scripts/oss_check.sh    # Pre-publish secret / hygiene check
├── samples/                # Synthetic example transcripts
├── .cursor/skills/…        # Skill to recreate this project from specs
├── standup_notes/
│   ├── config.py           # Env-driven settings
│   ├── validation.py       # URL / key / Drive / path hardening
│   ├── google_drive.py     # Find + export Meet Docs
│   ├── jira_client.py      # Jira Cloud REST (JQL + comments)
│   ├── llm.py              # Two-pass OpenAI processing
│   ├── pipeline.py         # Orchestration + idempotency
│   ├── transcript.py       # Meet / Gemini text parsing
│   └── models.py           # Shared types + comment rendering
├── .state/                 # local only (gitignored)
└── logs/                   # local only (gitignored)
```

---

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| `Missing required configuration: …` | Fill the listed keys in `.env` (see `.env.example`). |
| `No open tickets returned by JQL` | `JIRA_PROJECT_KEY` / `JIRA_CONTEXT_JQL`, and that the bot can search the project. |
| `No new transcript in the last Nh` | Meeting name in Doc title, folder ID, organizer email, age window, or wait for Gemini/Meet to finish writing the Doc. |
| Google `403` / auth errors | Drive API enabled, domain-wide delegation scope, Client ID, and `GOOGLE_IMPERSONATE_USER` is a real Workspace user. |
| Jira `401` / `403` | API token + email pair, and comment permission on the project. |
| `already processed — skipping` | Delete the transcript id from `.state/processed.json` only if you intentionally want to re-post. |
| Thin / empty notes | Ensure people say something substantive and preferably speak the ticket key. |

---

## Security

This project is designed to be open-sourced safely:

- Secrets stay in `.env` / service-account JSON (gitignored); `chmod 600` recommended
- Dry-run by default; HTTPS-only Jira URL; ticket-key allowlisting; Drive query escaping
- Local promo folders (`linkedin-*`), logs, and `.state/` are gitignored
- See **[SECURITY.md](SECURITY.md)** for the threat model, reporting process, and operator checklist

Before you publish a fork or the first push:

```bash
chmod +x scripts/oss_check.sh
./scripts/oss_check.sh
```

---

## Contributing

See **[CONTRIBUTING.md](CONTRIBUTING.md)**. Short version: dry-run first, never commit secrets, keep PRs focused.

---

## License

[MIT](LICENSE) © 2026 Sagar Shah

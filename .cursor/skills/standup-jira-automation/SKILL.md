---
name: standup-jira-automation
description: >-
  Scaffold or recreate a Google Meet standup → Jira auto-notes bot from scratch.
  Builds a Python CLI that fetches Meet/Gemini transcripts from Drive (or a local
  file), matches spoken ticket keys via a two-pass OpenAI pipeline, and posts
  structured Jira comments (Summary/Status/Blocker/Progress) with dry-run and
  idempotency. Use when the user asks to build standup-to-Jira automation,
  Meet transcript → Jira notes, standup bot, or to recreate this project without
  cloning the repo.
---

# Standup → Jira Auto-Notes (build from skill)

Use this skill to **implement the full project in the user's workspace** without
requiring them to clone existing source. Prefer generating code from these
specs over inventing a different architecture.

## When invoked

1. Confirm target directory (current workspace or a new folder they name).
2. Ask only for missing essentials if not already known:
   - Jira project key / site URL
   - Whether they need Google Drive auto-discovery or local `--file` only first
3. Follow the **Build checklist** below, reading linked references as needed.
4. Stop after a successful dry-run on the sample transcript (unless they ask for live setup).

## Product contract (do not change)

- Input: Google Meet / Gemini notes transcript (Drive Doc) **or** local `.txt`.
- Context: open Jira tickets via JQL.
- LLM Pass A: segment transcript → attribute to ticket keys; discard off-topic.
- LLM Pass B: write Summary / Status / Blocker / Progress; omit empty sections;
  never invent blockers.
- Output: one Jira comment per ticket, labeled auto-generated.
- Defaults: `DRY_RUN=true`; `--live` required to post.
- Idempotency: after a live post, record transcript id in `.state/processed.json`.
- Hard guardrail: never comment on a ticket key that was not returned by Jira context fetch.
- Team convention: engineers say ticket key first (`"PROJ-123, yesterday I…"`).

## Build checklist

Copy and track:

```
Progress:
- [ ] 1. Repo skeleton + deps + gitignore + LICENSE (MIT) + README
- [ ] 2. config.py + .env.example
- [ ] 3. models.py (types + comment render)
- [ ] 4. transcript.py (Meet/Gemini parse)
- [ ] 5. jira_client.py (JQL search + ADF comments)
- [ ] 6. llm.py (Pass A/B) — use prompts.md verbatim
- [ ] 7. google_drive.py (optional for Drive mode)
- [ ] 8. pipeline.py + main.py + run.sh
- [ ] 9. samples/sample_transcript.txt
- [ ] 10. Dry-run: python main.py --file samples/sample_transcript.txt
```

**Implementation details:** read [file-specs.md](file-specs.md) and write each
module to match. **Prompts:** copy [prompts.md](prompts.md) verbatim into
`llm.py`. **Architecture:** [architecture.md](architecture.md). **Google admin
setup (document for the user):** [google-setup.md](google-setup.md). **Samples /
expected behavior:** [samples.md](samples.md).

## Target tree

```text
.
├── LICENSE
├── SECURITY.md
├── CONTRIBUTING.md
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── main.py
├── run.sh
├── scripts/oss_check.sh
├── samples/
│   └── sample_transcript.txt
└── standup_notes/
    ├── __init__.py
    ├── config.py
    ├── validation.py
    ├── models.py
    ├── transcript.py
    ├── jira_client.py
    ├── llm.py
    ├── google_drive.py
    └── pipeline.py
```

## Dependencies (`requirements.txt`)

```text
openai>=1.40.0
google-api-python-client>=2.140.0
google-auth>=2.30.0
requests>=2.32.0
python-dotenv>=1.0.0
```

Python **3.10+** (uses `dict | None` style hints).

## CLI contract (`main.py`)

```text
python main.py --file path/to/transcript.txt   # local; skips Drive
python main.py                                 # latest Drive transcript
python main.py --live                          # post (overrides DRY_RUN)
python main.py --date YYYY-MM-DD               # comment header date
```

Required always: `openai_api_key`, `jira_base_url`, `jira_email`,
`jira_api_token`, `jira_project_key`.

Required for Drive mode: `google_service_account_file`, `google_impersonate_user`.

## Non-negotiable behaviors

| Behavior | Rule |
|----------|------|
| Dry-run default | Never post unless `--live` or `DRY_RUN=false` |
| Idempotency | Skip if `transcript_id` already in `.state/processed.json`; mark only after successful live run |
| Ticket keys | Uppercase normalize; drop segments whose key ∉ fetched tickets |
| Gemini docs | If a `Transcript` heading exists later in the doc, parse from there |
| Jira API | Use `/rest/api/3/search/jql` (not deprecated `/search`) and ADF for comments |
| Google scope | `https://www.googleapis.com/auth/drive.readonly` + domain-wide delegation |
| Empty notes | Skip posting when all four fields empty |
| Low confidence | Append verification warning to the comment |

## What to ask the user after scaffolding

1. Fill `.env` from `.env.example`.
2. Run dry-run on sample, then on a real transcript file.
3. If using Drive: complete [google-setup.md](google-setup.md).
4. First live run on one known ticket after reviewing dry-run output.
5. Schedule cron ~10 minutes after standup.

## Do not

- Do not invent a different stack (no Node/TS backend for the bot).
- Do not post during scaffolding verification.
- Do not commit `.env`, `service-account*.json`, `.state/`, or `logs/`.
- Do not include LinkedIn / promo video folders unless the user asks.
- Do not weaken the "never invent blockers" or "never guess unknown ticket keys" rules.

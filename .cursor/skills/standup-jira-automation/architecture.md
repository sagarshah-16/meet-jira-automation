# Architecture

## Pipeline

```
transcript text
    → extract_transcript_section (Gemini Notes → Transcript slice)
    → parse_transcript → list[TranscriptTurn]
    → JiraClient.fetch_context_tickets(JQL) → list[Ticket]
    → NotesLLM.segment(turns, tickets)          # Pass A
    → merge segments by ticket_key
    → for each segment:
          NotesLLM.structure(segment, ticket)   # Pass B
          TicketNote.render(meeting_date)
          dry-run print OR JiraClient.add_comment
    → if live: mark transcript_id processed
```

## Design decisions

1. **Two LLM passes** — Segmentation/filtering is separate from note writing so
   off-topic talk is dropped before any comment is drafted.
2. **Spoken key as anchor** — STT often garbles keys; Pass A normalizes against
   the real ticket list. Content match is fallback (`medium` / `low` confidence).
3. **Hard key allowlist** — After Pass A JSON returns, drop any `ticket_key` not
   in the fetched Jira set. The model cannot invent tickets.
4. **Dry-run by default** — Safe for open-source first runs and CI-like checks.
5. **Idempotency by transcript id** — Drive file id, or `file:` + sha256 prefix for
   local files. Only recorded after a successful live post.
6. **ADF comments** — Jira Cloud v3 expects Atlassian Document Format, not wiki
   markup. Map `### Heading` and bold label lines into ADF nodes.
7. **Read-only Drive** — Service account with domain-wide delegation impersonates
   the standup organizer; scope is Drive readonly only.
8. **Benign empty Drive result** — No recent Doc → exit 0 with a message (weekend /
   notes not ready). Not an error.

## Module responsibilities

| Module | Owns |
|--------|------|
| `config.py` | Env loading, defaults, `require()`, `context_jql` property |
| `models.py` | Dataclasses + `TicketNote.render` + `Ticket.brief` |
| `transcript.py` | Gemini slice, speaker/timestamp parse, `render_turns` |
| `jira_client.py` | Basic auth session, JQL pagination, ADF comment POST |
| `llm.py` | OpenAI JSON calls, Pass A/B system prompts, allowlist filter |
| `google_drive.py` | Impersonated Drive client, find latest Doc, export text |
| `pipeline.py` | Orchestration, merge, skip/processed state, reporting |
| `main.py` | Argparse, dry-run override, file vs Drive entry |

## State

- Path: `.state/processed.json`
- Shape: JSON array of transcript id strings
- Create parent dir on write

## Comment shape (rendered text before ADF)

```text
🤖 Auto-generated from standup — {YYYY-MM-DD} · please verify

### Summary
...

### Status
...

### Blocker
...

### Progress
...

⚠️ Low-confidence match — please confirm this note belongs to this ticket.
```

Only include non-empty sections among Summary/Status/Blocker/Progress.
Status should fall back to `"{board status} (from board)"` if Pass B left it empty
but other fields exist.

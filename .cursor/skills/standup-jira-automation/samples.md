# Samples and expected behavior

## `samples/sample_transcript.txt`

Create this file with the following content (or an equivalent Meet-style transcript):

```text
Daily Standup - 2026/07/26 09:30 GMT - Transcript

00:00:05
Priya Nair: Good morning everyone, hope you all watched the match last night.
Bob Jones: Haha yes, what a finish!
Priya Nair: Okay let's get started. Alice, you're up first.

00:00:40
Alice Smith: PROJ-101, yesterday I finished the OAuth login flow and pushed it for code review. Today I'll address review comments. No blockers.

00:01:20
Bob Jones: Proj one oh three. I'm still working on the payment webhook retries. I'm blocked on the staging credentials from the infra team, waiting since Tuesday. Otherwise the retry logic itself is done.

00:02:10
Priya Nair: Thanks Bob, I'll chase infra today. By the way, the office picnic is moved to Friday, don't forget to RSVP.

00:02:30
Carlos Diaz: PROJ-107. Started the dashboard charts. Got the data layer wired up, charts render with mock data. Today switching to the real API. Should be done by Thursday.

00:03:05
Priya Nair: Great. Anything else? No? Okay, see everyone tomorrow.
```

## What a correct dry-run should demonstrate

Assuming Jira context includes `PROJ-101`, `PROJ-103`, `PROJ-107` (or the sample
keys are edited to real open issues):

| Speaker chunk | Expected ticket | Notes |
|---------------|-----------------|-------|
| Alice OAuth | PROJ-101 | high confidence; no blocker |
| Bob webhooks | PROJ-103 | STT-style "Proj one oh three"; blocker = staging credentials |
| Carlos charts | PROJ-107 | high confidence |
| Match talk / picnic / logistics | discarded | must not become a comment |

Bob's comment must include a **Blocker** section. Alice and Carlos should not
get invented blockers.

## Acceptance checks after scaffolding

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # user fills secrets
python main.py --file samples/sample_transcript.txt
```

Must:
- Parse multiple speaker turns
- Fetch Jira tickets (or fail clearly if creds missing)
- Print dry-run comment drafts (when keys match)
- Not write to `.state/processed.json` in dry-run
- Never POST to Jira without `--live`

## Customizing for a real team

1. Change sample ticket keys to the team's project key format.
2. Set `JIRA_PROJECT_KEY` / `JIRA_CONTEXT_JQL` accordingly.
3. Set `GOOGLE_MEETING_NAME` to the Meet title substring used in Docs.
4. Teach the team: say the ticket key first before the update.

"""Orchestrates one run: transcript → context → LLM passes → Jira comments."""

import json
from datetime import date
from pathlib import Path

from .config import Config
from .jira_client import JiraClient
from .llm import NotesLLM
from .models import RunReport, Segment, TicketNote
from .transcript import extract_transcript_section, parse_transcript
from .validation import clamp_transcript, validate_ticket_key

STATE_FILE = Path(".state/processed.json")


def _load_processed() -> set[str]:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            return set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def _mark_processed(transcript_id: str) -> None:
    processed = _load_processed()
    processed.add(transcript_id)
    STATE_FILE.parent.mkdir(mode=0o700, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(processed), indent=2) + "\n")
    tmp.replace(STATE_FILE)
    try:
        STATE_FILE.chmod(0o600)
    except OSError:
        pass


def _merge_segments(segments: list[Segment]) -> list[Segment]:
    """A ticket discussed in multiple chunks gets one combined segment."""
    by_key: dict[str, Segment] = {}
    conf_rank = {"high": 2, "medium": 1, "low": 0}
    for s in segments:
        if s.ticket_key in by_key:
            existing = by_key[s.ticket_key]
            existing.raw_text += "\n" + s.raw_text
            if conf_rank[s.confidence] > conf_rank[existing.confidence]:
                existing.confidence = s.confidence
        else:
            by_key[s.ticket_key] = s
    return list(by_key.values())


def run(cfg: Config, transcript_text: str, transcript_id: str,
        transcript_name: str = "", meeting_date: str = "") -> RunReport:
    report = RunReport(transcript_name=transcript_name or transcript_id,
                       dry_run=cfg.dry_run)
    meeting_date = meeting_date or date.today().isoformat()

    if transcript_id in _load_processed():
        print(f"↷ Transcript {transcript_id} already processed — skipping (idempotency guard).")
        return report

    text = clamp_transcript(transcript_text)
    turns = parse_transcript(extract_transcript_section(text))
    if not turns:
        print("No speaker turns found in transcript — nothing to do.")
        return report
    print(f"Parsed {len(turns)} speaker turns.")

    jira = JiraClient(cfg)
    tickets = jira.fetch_context_tickets(cfg.context_jql)
    if not tickets:
        print("No open tickets returned by JQL — aborting (check JIRA_CONTEXT_JQL).")
        return report
    print(f"Fetched {len(tickets)} open tickets from {cfg.jira_project_key}.")
    ticket_by_key = {t.key: t for t in tickets}

    llm = NotesLLM(cfg)

    # Pass A — segment & filter
    segments = _merge_segments(llm.segment(turns, tickets))
    print(f"Attributed segments: {len(segments)} "
          f"({', '.join(s.ticket_key for s in segments) or 'none'})")

    # Pass B — structure, then post
    for seg in segments:
        try:
            key = validate_ticket_key(seg.ticket_key)
        except ValueError:
            print(f"  ↷ Skipping invalid ticket key from model: {seg.ticket_key!r}")
            continue
        if key not in ticket_by_key:
            # Hard allowlist — never post outside the fetched context set.
            print(f"  ↷ Skipping {key}: not in Jira context allowlist.")
            continue
        seg.ticket_key = key

        note: TicketNote = llm.structure(seg, ticket_by_key[key])
        if note.is_empty:
            report.tickets_skipped.append(key)
            print(f"  ∅ {key}: nothing substantive said — skipping.")
            continue
        if not note.status_update:
            # Status header should always be present; fall back to the board column.
            note.status_update = f"{ticket_by_key[key].status} (from board)"

        body = note.render(meeting_date)
        if cfg.dry_run:
            print(f"\n──── DRY RUN — would comment on {key} ────\n{body}\n")
        else:
            jira.add_comment(key, body)
            print(f"  ✓ Commented on {key} (confidence: {seg.confidence})")
        report.tickets_updated.append(key)

    if not cfg.dry_run:
        _mark_processed(transcript_id)

    print(f"\nRun complete: {len(report.tickets_updated)} note(s) "
          f"{'drafted (dry run)' if cfg.dry_run else 'posted'}, "
          f"{len(report.tickets_skipped)} skipped.")
    return report

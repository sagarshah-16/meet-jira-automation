"""Standup → Jira auto-notes.

Usage:
  # Process a local transcript file (testing / manual runs):
  python main.py --file path/to/transcript.txt

  # Auto-discover the latest Meet transcript in the organizer's Drive:
  python main.py

  # Post for real (default is dry-run unless DRY_RUN=false):
  python main.py --live
"""

import argparse
import hashlib
from pathlib import Path

from standup_notes.config import Config
from standup_notes import pipeline
from standup_notes.validation import clamp_transcript


def main() -> None:
    ap = argparse.ArgumentParser(description="Post standup notes to Jira from a Meet transcript.")
    ap.add_argument("--file", help="Local transcript text file (skips Google Drive).")
    ap.add_argument("--live", action="store_true", help="Actually post to Jira (overrides DRY_RUN).")
    ap.add_argument("--date", help="Meeting date for the note header (YYYY-MM-DD).")
    args = ap.parse_args()

    cfg = Config()
    if args.live:
        cfg.dry_run = False

    cfg.require("openai_api_key", "jira_base_url", "jira_email",
                "jira_api_token", "jira_project_key")

    if cfg.dry_run:
        print("DRY RUN — no Jira comments will be posted. Pass --live to post.\n")
    else:
        print("LIVE MODE — comments will be posted to Jira.\n")

    if args.file:
        path = Path(args.file).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"Transcript file not found: {path}")
        text = clamp_transcript(path.read_text(encoding="utf-8", errors="replace"))
        transcript_id = "file:" + hashlib.sha256(text.encode()).hexdigest()[:16]
        pipeline.run(cfg, text, transcript_id,
                     transcript_name=str(path), meeting_date=args.date or "")
    else:
        cfg.require("google_service_account_file", "google_impersonate_user")
        from standup_notes.google_drive import find_latest_transcript, download_doc_text

        meta = find_latest_transcript(cfg)
        if not meta:
            # Benign: no meeting happened recently (weekend/holiday) or the
            # notes doc hasn't landed yet. Not an error.
            print(f"No new transcript in the last {cfg.max_transcript_age_hours}h — nothing to do.")
            return
        print(f"Found transcript: {meta['name']} (created {meta['createdTime']})")
        text = clamp_transcript(download_doc_text(cfg, meta["id"]))
        pipeline.run(cfg, text, meta["id"],
                     transcript_name=meta["name"], meeting_date=args.date or "")


if __name__ == "__main__":
    main()

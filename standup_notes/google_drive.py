"""Locate and download the latest Google Meet transcript Doc from Drive.

Auth: service account with domain-wide delegation, impersonating the standup
organizer (read-only Drive scope).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build

from .config import Config
from .validation import escape_drive_query_value, validate_drive_id

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _drive_service(cfg: Config):
    creds = service_account.Credentials.from_service_account_file(
        cfg.google_service_account_file, scopes=SCOPES
    ).with_subject(cfg.google_impersonate_user)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def find_latest_transcript(cfg: Config) -> dict | None:
    """Return {id, name, createdTime} of the newest transcript Doc, or None."""
    service = _drive_service(cfg)

    meeting = escape_drive_query_value(cfg.google_meeting_name)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg.max_transcript_age_hours)
    clauses = [
        "mimeType = 'application/vnd.google-apps.document'",
        # Matches both native Meet transcripts ("<name> - Transcript") and
        # Gemini notes docs ("<name> - ... - Notes by Gemini"), which embed
        # the full transcript as a section.
        f"name contains '{meeting}'",
        f"createdTime > '{cutoff.strftime('%Y-%m-%dT%H:%M:%S')}'",
        "trashed = false",
    ]
    folder_id = validate_drive_id(
        cfg.google_transcript_folder_id, field="GOOGLE_TRANSCRIPT_FOLDER_ID")
    if folder_id:
        clauses.append(f"'{folder_id}' in parents")

    resp = service.files().list(
        q=" and ".join(clauses),
        orderBy="createdTime desc",
        pageSize=5,
        fields="files(id, name, createdTime)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()

    files = resp.get("files", [])
    return files[0] if files else None


def download_doc_text(cfg: Config, file_id: str) -> str:
    """Export a Google Doc as plain text."""
    # Defense in depth: only allow Drive-like ids in the export path.
    file_id = validate_drive_id(file_id, field="Google Drive file id")
    if not file_id:
        raise SystemExit("Invalid Google Drive file id.")
    service = _drive_service(cfg)
    data = service.files().export(fileId=file_id, mimeType="text/plain").execute()
    return data.decode("utf-8") if isinstance(data, bytes) else data

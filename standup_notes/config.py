"""Environment-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

from .validation import (
    validate_drive_folder_id,
    validate_https_origin,
    validate_service_account_file,
    warn_insecure_env_file,
)

load_dotenv()
warn_insecure_env_file()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")


@dataclass
class Config:
    # LLM
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o"))

    # Jira
    jira_base_url: str = field(default_factory=lambda: os.getenv("JIRA_BASE_URL", "").rstrip("/"))
    jira_email: str = field(default_factory=lambda: os.getenv("JIRA_EMAIL", ""))
    jira_api_token: str = field(default_factory=lambda: os.getenv("JIRA_API_TOKEN", ""))
    jira_project_key: str = field(default_factory=lambda: os.getenv("JIRA_PROJECT_KEY", ""))
    jira_context_jql: str = field(default_factory=lambda: os.getenv(
        "JIRA_CONTEXT_JQL",
        "project = {project} AND statusCategory != Done ORDER BY updated DESC",
    ))

    # Google
    google_service_account_file: str = field(
        default_factory=lambda: os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", ""))
    google_impersonate_user: str = field(
        default_factory=lambda: os.getenv("GOOGLE_IMPERSONATE_USER", ""))
    google_transcript_folder_id: str = field(
        default_factory=lambda: os.getenv("GOOGLE_TRANSCRIPT_FOLDER_ID", ""))
    # Name of the meeting as it appears in the Doc title (Gemini notes/transcript)
    google_meeting_name: str = field(
        default_factory=lambda: os.getenv("GOOGLE_MEETING_NAME", "STAND-UP"))

    # Behavior
    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", True))
    max_transcript_age_hours: int = field(
        default_factory=lambda: int(os.getenv("MAX_TRANSCRIPT_AGE_HOURS", "24")))

    def __post_init__(self) -> None:
        # Normalize + validate whenever values are present (partial configs OK until require())
        if self.jira_base_url:
            self.jira_base_url = validate_https_origin(
                self.jira_base_url, name="JIRA_BASE_URL")
        if self.jira_project_key:
            self.jira_project_key = self.jira_project_key.strip().upper()
        if self.google_service_account_file:
            self.google_service_account_file = validate_service_account_file(
                self.google_service_account_file)
        if self.google_transcript_folder_id:
            self.google_transcript_folder_id = validate_drive_folder_id(
                self.google_transcript_folder_id)
        if self.google_meeting_name:
            self.google_meeting_name = self.google_meeting_name.strip()
        if self.max_transcript_age_hours < 1 or self.max_transcript_age_hours > 24 * 30:
            raise SystemExit("MAX_TRANSCRIPT_AGE_HOURS must be between 1 and 720.")

    @property
    def context_jql(self) -> str:
        # Only substitute our project key; reject unexpected format keys.
        return self.jira_context_jql.format(project=self.jira_project_key)

    def require(self, *names: str) -> None:
        """Fail fast with a readable message if required settings are missing."""
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise SystemExit(
                "Missing required configuration: "
                + ", ".join(missing)
                + "\nSet them in your environment or .env file (see .env.example)."
            )

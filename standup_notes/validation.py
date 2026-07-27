"""Input validation and sanitization for secrets-adjacent configuration."""

from __future__ import annotations

import re
import stat
from pathlib import Path
from urllib.parse import urlparse

# Jira Cloud / Data Center issue keys: PROJ-123
TICKET_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
# Drive file / folder ids are opaque URL-safe strings
DRIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Cap transcript size to limit prompt injection / cost / memory abuse
MAX_TRANSCRIPT_CHARS = 400_000


def validate_https_origin(url: str, *, name: str) -> str:
    """Require https origin with no userinfo; strip path/query/fragment."""
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise SystemExit(f"{name} must use https:// (got {parsed.scheme or 'empty'}).")
    if not parsed.netloc:
        raise SystemExit(f"{name} is missing a hostname.")
    if parsed.username or parsed.password:
        raise SystemExit(f"{name} must not embed credentials in the URL.")
    host = parsed.netloc.lower()
    if host.startswith("localhost") or host.startswith("127.") or host.endswith(".local"):
        raise SystemExit(f"{name} must not point at a local/loopback host.")
    return f"https://{parsed.netloc}"


def validate_ticket_key(key: str) -> str:
    normalized = (key or "").strip().upper()
    if not TICKET_KEY_RE.match(normalized):
        raise ValueError(f"Invalid Jira ticket key: {key!r}")
    return normalized


def escape_drive_query_value(value: str) -> str:
    """Escape a value for use inside single quotes in a Drive `q` clause."""
    if not value or any(ch in value for ch in "\n\r\x00"):
        raise SystemExit("Drive query value contains invalid characters.")
    # Drive query language: escape backslash and single quote
    return value.replace("\\", "\\\\").replace("'", "\\'")


def validate_drive_id(drive_id: str, *, field: str = "Drive id") -> str:
    drive_id = (drive_id or "").strip()
    if not drive_id:
        return ""
    if not DRIVE_ID_RE.match(drive_id):
        raise SystemExit(f"{field} has an invalid format.")
    return drive_id


# Back-compat alias used by config for the folder setting.
def validate_drive_folder_id(folder_id: str) -> str:
    return validate_drive_id(folder_id, field="GOOGLE_TRANSCRIPT_FOLDER_ID")


def validate_service_account_file(path: str) -> str:
    if not path:
        return ""
    p = Path(path).expanduser()
    if not p.is_file():
        raise SystemExit(f"GOOGLE_SERVICE_ACCOUNT_FILE not found: {p}")
    # Reject world-writable keys (common misconfiguration)
    mode = p.stat().st_mode
    if mode & stat.S_IWOTH:
        raise SystemExit(
            f"GOOGLE_SERVICE_ACCOUNT_FILE is world-writable — fix permissions: chmod 600 {p}"
        )
    return str(p.resolve())


def warn_insecure_env_file(env_path: Path = Path(".env")) -> None:
    """Print a warning if .env is group/world-readable (best-effort, non-fatal)."""
    try:
        if not env_path.is_file():
            return
        mode = env_path.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
            print(
                f"⚠ {env_path} is readable by group/others. "
                f"Restrict it with: chmod 600 {env_path}"
            )
    except OSError:
        return


def clamp_transcript(text: str, *, limit: int = MAX_TRANSCRIPT_CHARS) -> str:
    if len(text) <= limit:
        return text
    print(f"⚠ Transcript truncated from {len(text)} to {limit} characters for safety.")
    return text[:limit]

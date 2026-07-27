"""Minimal Jira Cloud REST client (email + API token, Basic auth).

Uses the v3 API: /rest/api/3/search/jql (the old /search endpoint is retired)
and ADF (Atlassian Document Format) for comment bodies.
"""

from __future__ import annotations

import re

import requests

from .config import Config
from .models import Ticket
from .validation import validate_ticket_key

_BOLD_LINE = re.compile(r"^\*(.+?):\*\s*(.*)$")  # "*Label:* text"


def _adf_to_text(node) -> str:
    """Flatten an ADF document (v3 description field) to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    parts = []
    if isinstance(node, dict):
        if node.get("type") == "text":
            parts.append(node.get("text", ""))
        for child in node.get("content", []) or []:
            parts.append(_adf_to_text(child))
        if node.get("type") in ("paragraph", "heading", "listItem"):
            parts.append("\n")
    return "".join(parts)


def _text_to_adf(body: str) -> dict:
    """Convert our rendered note (lines, '*Label:* text' markers) to ADF."""
    paragraphs = []
    for line in body.splitlines():
        if not line.strip():
            continue
        if line.startswith("### "):
            paragraphs.append({
                "type": "heading", "attrs": {"level": 3},
                "content": [{"type": "text", "text": line[4:]}],
            })
            continue
        m = _BOLD_LINE.match(line)
        if m:
            content = [
                {"type": "text", "text": m.group(1) + ": ",
                 "marks": [{"type": "strong"}]},
            ]
            if m.group(2):
                content.append({"type": "text", "text": m.group(2)})
        else:
            content = [{"type": "text", "text": line}]
        paragraphs.append({"type": "paragraph", "content": content})
    return {"type": "doc", "version": 1, "content": paragraphs}


def _http_error_message(resp: requests.Response) -> str:
    """Safe error text — status + short body, never request auth headers."""
    snippet = (resp.text or "").strip().replace("\n", " ")[:200]
    return f"Jira HTTP {resp.status_code}: {snippet or resp.reason}"


class JiraClient:
    def __init__(self, cfg: Config):
        self.base = cfg.jira_base_url
        self.session = requests.Session()
        self.session.auth = (cfg.jira_email, cfg.jira_api_token)
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def fetch_context_tickets(self, jql: str, max_results: int = 100) -> list[Ticket]:
        """Fetch open tickets (standup context) via the v3 JQL search."""
        tickets: list[Ticket] = []
        next_page_token = None
        while True:
            params = {
                "jql": jql,
                "maxResults": min(max_results - len(tickets), 50),
                "fields": "summary,status,assignee,description",
            }
            if next_page_token:
                params["nextPageToken"] = next_page_token
            resp = self.session.get(
                f"{self.base}/rest/api/3/search/jql", params=params, timeout=30)
            if not resp.ok:
                raise SystemExit(_http_error_message(resp))
            data = resp.json()
            for issue in data.get("issues", []):
                try:
                    key = validate_ticket_key(issue["key"])
                except ValueError:
                    continue
                f = issue["fields"]
                tickets.append(Ticket(
                    key=key,
                    summary=f.get("summary") or "",
                    status=(f.get("status") or {}).get("name", ""),
                    assignee=((f.get("assignee") or {}).get("displayName") or ""),
                    description=_adf_to_text(f.get("description")).strip(),
                ))
            next_page_token = data.get("nextPageToken")
            if not next_page_token or len(tickets) >= max_results:
                break
        return tickets

    def add_comment(self, ticket_key: str, body: str) -> dict:
        key = validate_ticket_key(ticket_key)
        resp = self.session.post(
            f"{self.base}/rest/api/3/issue/{key}/comment",
            json={"body": _text_to_adf(body)},
            timeout=30,
        )
        if not resp.ok:
            raise SystemExit(_http_error_message(resp))
        return resp.json()

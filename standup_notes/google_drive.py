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
# Write access to Docs only — needed to add the "Jira Sync Report" tab to the
# standup doc. Requires the same scope in the domain-wide delegation grant.
DOCS_SCOPES = ["https://www.googleapis.com/auth/documents"]


def _drive_service(cfg: Config):
    creds = service_account.Credentials.from_service_account_file(
        cfg.google_service_account_file, scopes=SCOPES
    ).with_subject(cfg.google_impersonate_user)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _docs_service(cfg: Config):
    creds = service_account.Credentials.from_service_account_file(
        cfg.google_service_account_file, scopes=DOCS_SCOPES
    ).with_subject(cfg.google_impersonate_user)
    return build("docs", "v1", credentials=creds, cache_discovery=False)


def _find_tab_table(doc: dict, tab_id: str) -> tuple[dict, int]:
    """Return (table element, table start index) inside the given tab."""
    for tab in doc.get("tabs", []):
        if tab["tabProperties"]["tabId"] == tab_id:
            for el in tab["documentTab"]["body"]["content"]:
                if "table" in el:
                    return el["table"], el["startIndex"]
    raise ValueError("Report table not found in tab")


def _cell_indexes(table: dict) -> list[list[int]]:
    """Start index of the first paragraph in every cell, row-major."""
    return [[cell["content"][0]["startIndex"] for cell in row["tableCells"]]
            for row in table["tableRows"]]


def _walk_tabs(tabs: list[dict]):
    for t in tabs:
        yield t
        yield from _walk_tabs(t.get("childTabs", []))


def delete_tabs_titled(cfg: Config, doc_id: str, title: str) -> int:
    """Delete all tabs with the given title. Returns how many were removed."""
    svc = _docs_service(cfg)
    # Note: the tabs field is only populated with includeTabsContent=True.
    doc = svc.documents().get(documentId=doc_id, includeTabsContent=True).execute()
    ids = [t["tabProperties"]["tabId"] for t in _walk_tabs(doc.get("tabs", []))
           if t["tabProperties"].get("title") == title]
    if ids:
        svc.documents().batchUpdate(documentId=doc_id, body={
            "requests": [{"deleteTab": {"tabId": i}} for i in ids]}).execute()
    return len(ids)


def write_coverage_tab(cfg: Config, doc_id: str, data: dict) -> str:
    """Add a properly formatted 'Jira Sync Report' tab: real headings, bold
    labels, and the not-updated list as a table.

    data: {date, transcript, statuses, updated: [keys], total: int,
           rows: [(key, status, assignee, summary, reason), ...]}
    """
    doc_id = validate_drive_id(doc_id, field="Google Doc id")
    if not doc_id:
        raise ValueError("Invalid Google Doc id.")
    svc = _docs_service(cfg)

    resp = svc.documents().batchUpdate(documentId=doc_id, body={
        "requests": [{"addDocumentTab": {"tabProperties": {"title": "Jira Sync Report"}}}],
    }).execute()
    tab_id = resp["replies"][0]["addDocumentTab"]["tabProperties"]["tabId"]

    updated_join = ", ".join(data["updated"]) or "(none)"
    t_title = f"Standup Coverage Report — {data['date']}\n"
    t_tr = f"Transcript: {data['transcript']}\n"
    t_st = f"Statuses tracked: {data['statuses']}\n"
    up_label = f"Updated ({len(data['updated'])}):"
    t_up = f"{up_label} {updated_join}\n"
    t_nu = f"Not updated ({len(data['rows'])})\n"
    full = t_title + t_tr + t_st + t_up + t_nu

    def rng(start: int, end: int) -> dict:
        return {"startIndex": start, "endIndex": end, "tabId": tab_id}

    bold = {"textStyle": {"bold": True}, "fields": "bold"}

    def link(key: str) -> dict:
        return {"textStyle": {
            "link": {"url": f"{cfg.jira_base_url}/browse/{key}"},
            "underline": True,
            "foregroundColor": {"color": {"rgbColor": {
                "red": 0.07, "green": 0.33, "blue": 0.8}}},
        }, "fields": "link,underline,foregroundColor"}
    o1 = 1
    o2 = o1 + len(t_title)
    o3 = o2 + len(t_tr)
    o4 = o3 + len(t_st)
    o5 = o4 + len(t_up)
    requests = [
        {"insertText": {"location": {"index": 1, "tabId": tab_id}, "text": full}},
        {"updateParagraphStyle": {"range": rng(o1, o2),
         "paragraphStyle": {"namedStyleType": "HEADING_1"}, "fields": "namedStyleType"}},
        {"updateTextStyle": {"range": rng(o2, o2 + len("Transcript:")), **bold}},
        {"updateTextStyle": {"range": rng(o3, o3 + len("Statuses tracked:")), **bold}},
        {"updateTextStyle": {"range": rng(o4, o4 + len(up_label)), **bold}},
        {"updateParagraphStyle": {"range": rng(o5, o5 + len(t_nu)),
         "paragraphStyle": {"namedStyleType": "HEADING_2"}, "fields": "namedStyleType"}},
    ]
    # Hyperlink each key in the "Updated" line (keys are ", "-joined).
    pos = o4 + len(up_label) + 1
    for key in data["updated"]:
        requests.append({"updateTextStyle": {"range": rng(pos, pos + len(key)), **link(key)}})
        pos += len(key) + 2
    if data["rows"]:
        requests.append({"insertTable": {
            "endOfSegmentLocation": {"tabId": tab_id},
            "rows": len(data["rows"]) + 1, "columns": 3}})
    svc.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}).execute()
    if not data["rows"]:
        return tab_id

    # Fill cells in reverse order so earlier indexes stay valid.
    doc = svc.documents().get(documentId=doc_id, includeTabsContent=True).execute()
    table, table_start = _find_tab_table(doc, tab_id)
    cells = _cell_indexes(table)
    texts = [["Ticket", "Assignee", "Why no note"]]
    texts += [[r[0], r[2], r[4]] for r in data["rows"]]
    flat = [(idx, txt) for row_i, row in enumerate(cells)
            for idx, txt in zip(row, texts[row_i]) if txt]
    svc.documents().batchUpdate(documentId=doc_id, body={"requests": [
        {"insertText": {"location": {"index": idx, "tabId": tab_id}, "text": txt}}
        for idx, txt in sorted(flat, key=lambda p: -p[0])
    ]}).execute()

    # Re-fetch for final styling: bold header row + ticket keys, shade header.
    doc = svc.documents().get(documentId=doc_id, includeTabsContent=True).execute()
    table, table_start = _find_tab_table(doc, tab_id)
    cells = _cell_indexes(table)
    style_reqs = [
        {"updateTableCellStyle": {
            "tableRange": {
                "tableCellLocation": {
                    "tableStartLocation": {"index": table_start, "tabId": tab_id},
                    "rowIndex": 0, "columnIndex": 0},
                "rowSpan": 1, "columnSpan": 3},
            "tableCellStyle": {"backgroundColor": {"color": {"rgbColor": {
                "red": 0.93, "green": 0.93, "blue": 0.93}}}},
            "fields": "backgroundColor"}},
    ]
    for col_i, txt in enumerate(texts[0]):
        start = cells[0][col_i]
        style_reqs.append({"updateTextStyle": {"range": rng(start, start + len(txt)), **bold}})
    for row_i in range(1, len(texts)):
        key = texts[row_i][0]
        start = cells[row_i][0]
        style_reqs.append({"updateTextStyle": {"range": rng(start, start + len(key)), **bold}})
        style_reqs.append({"updateTextStyle": {"range": rng(start, start + len(key)), **link(key)}})
    svc.documents().batchUpdate(
        documentId=doc_id, body={"requests": style_reqs}).execute()
    return tab_id


def append_report_tab(cfg: Config, doc_id: str, tab_title: str, text: str) -> str:
    """Add a new tab to the Doc and fill it with the report text.

    Returns the new tab's id. Needs the documents scope in the DWD grant.
    """
    doc_id = validate_drive_id(doc_id, field="Google Doc id")
    if not doc_id:
        raise ValueError("Invalid Google Doc id.")
    svc = _docs_service(cfg)
    resp = svc.documents().batchUpdate(documentId=doc_id, body={
        "requests": [{"addDocumentTab": {"tabProperties": {"title": tab_title}}}],
    }).execute()
    tab_id = resp["replies"][0]["addDocumentTab"]["tabProperties"]["tabId"]
    svc.documents().batchUpdate(documentId=doc_id, body={
        "requests": [{
            "insertText": {"location": {"index": 1, "tabId": tab_id}, "text": text},
        }],
    }).execute()
    return tab_id


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

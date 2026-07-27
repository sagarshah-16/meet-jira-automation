"""Shared data types for the pipeline."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TranscriptTurn:
    speaker: str
    text: str
    timestamp: str = ""  # e.g. "00:03:12" when present in the source doc


@dataclass
class Ticket:
    key: str
    summary: str
    status: str
    assignee: str
    description: str

    def brief(self) -> str:
        desc = (self.description or "")[:400]
        return f"{self.key} [{self.status}] (assignee: {self.assignee or 'unassigned'}): {self.summary}\n  {desc}"


@dataclass
class Segment:
    """A chunk of standup conversation attributed to one ticket."""
    ticket_key: str
    confidence: str  # "high" | "medium" | "low"
    speaker: str
    raw_text: str
    reasoning: str = ""


def _ddmmmyy(iso_date: str) -> str:
    """2026-07-28 → 28-Jul-26 (falls back to the input on parse failure)."""
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d-%b-%y")
    except ValueError:
        return iso_date


@dataclass
class TicketNote:
    """The structured note to post as a Jira comment."""
    ticket_key: str
    confidence: str
    progress: list[str] = field(default_factory=list)
    discussion: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    eta: str = ""

    @property
    def is_empty(self) -> bool:
        return not any([self.progress, self.discussion, self.blockers,
                        self.next_steps, self.eta])

    def render(self, meeting_date: str) -> str:
        lines = [f"## Daily Update ({_ddmmmyy(meeting_date)})", ""]
        for label, items in [
            ("Progress", self.progress),
            ("Discussion", self.discussion),
            ("Blockers / Dependencies", self.blockers),
            ("Next Steps", self.next_steps),
            ("ETA", [self.eta] if self.eta else []),
        ]:
            if items:
                lines.append(f"**{label}**")
                lines += [f"- {item}" for item in items]
                lines.append("")
        lines.append("🤖 Auto-generated from standup transcript · please verify")
        if self.confidence == "low":
            lines.append("⚠️ Low-confidence match — please confirm this note belongs to this ticket.")
        return "\n".join(lines)


@dataclass
class NotUpdated:
    """An active-work ticket that received no note this run, and why."""
    key: str
    status: str
    assignee: str
    summary: str
    reason: str


@dataclass
class RunReport:
    transcript_name: str = ""
    tickets_updated: list[str] = field(default_factory=list)
    tickets_skipped: list[str] = field(default_factory=list)
    not_updated: list[NotUpdated] = field(default_factory=list)
    segments_discarded: int = 0
    dry_run: bool = True

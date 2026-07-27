"""Shared data types for the pipeline."""

from dataclasses import dataclass, field


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


@dataclass
class TicketNote:
    """The structured note to post as a Jira comment."""
    ticket_key: str
    confidence: str
    status_update: str = ""
    summary: str = ""
    blocker: str = ""
    progress: str = ""
    next_steps: str = ""

    @property
    def is_empty(self) -> bool:
        return not any([self.status_update, self.summary, self.blocker,
                        self.progress, self.next_steps])

    def render(self, meeting_date: str) -> str:
        lines = [f"🤖 Auto-generated from standup — {meeting_date} · please verify", ""]
        for label, value in [
            ("Summary", self.summary),
            ("Status", self.status_update),
            ("Blocker", self.blocker),
            ("Progress", self.progress),
            ("Next Steps", self.next_steps),
        ]:
            if value:
                lines.append(f"### {label}")
                lines.append(value)
        if self.confidence == "low":
            lines += ["", "⚠️ Low-confidence match — please confirm this note belongs to this ticket."]
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

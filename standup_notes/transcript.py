"""Parse Google Meet transcript text into speaker-attributed turns.

Google Meet transcript Docs typically look like:

    Meeting title - 2026/07/26 09:30 GMT - Transcript

    00:00:00
    Alice Smith: PROJ-123, yesterday I finished the login flow...
    Bob Jones: Sounds good.

    00:05:00
    ...

The parser is tolerant: timestamp lines are optional, and consecutive lines
from the same speaker are merged into one turn.
"""

import re

from .models import TranscriptTurn

_TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def extract_transcript_section(text: str) -> str:
    """If the doc is a Gemini notes doc, slice from the embedded Transcript
    section (skipping Gemini's own summary). Otherwise return the text as-is.

    Gemini has used several marker styles ("Transcript", "📖 Transcript",
    "<Meeting> - Transcript"), and the summary above may itself mention
    "Transcript" — so match the LAST marker line in the doc.
    """
    # Our own "Jira Sync Report" tab is exported after the transcript —
    # cut it (and anything following) so a re-read never parses report
    # content as speech (its ticket keys would pollute segmentation).
    cut = re.search(r"^Standup Coverage Report —", text, flags=re.MULTILINE)
    if cut:
        text = text[:cut.start()]
    matches = list(re.finditer(
        r"^\W*Transcript\s*$|^.{0,80}- Transcript\s*$",
        text[200:], flags=re.MULTILINE))
    if matches:
        return text[200 + matches[-1].start():]
    return text
# "Speaker Name: said something" — speaker part kept short to avoid matching
# prose that happens to contain a colon.
_SPEAKER_RE = re.compile(r"^([^:]{1,60}?):\s+(.*)$")


def parse_transcript(text: str) -> list[TranscriptTurn]:
    turns: list[TranscriptTurn] = []
    current_ts = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _TIMESTAMP_RE.match(line):
            current_ts = line
            continue

        m = _SPEAKER_RE.match(line)
        if m:
            speaker, said = m.group(1).strip(), m.group(2).strip()
            if turns and turns[-1].speaker == speaker:
                turns[-1].text += " " + said
            else:
                turns.append(TranscriptTurn(speaker=speaker, text=said, timestamp=current_ts))
        elif turns:
            # Continuation line of the previous turn (Doc line wrapping).
            turns[-1].text += " " + line

    return turns


def spoken_ticket_keys(turns: list[TranscriptTurn], project_key: str) -> set[str]:
    """Ticket keys explicitly spoken in the transcript ("AD-127", "AD127",
    "ticket 127"). Used to pull discussed tickets that the sprint JQL missed."""
    pat = re.compile(
        rf"\b(?:{re.escape(project_key)}[\s-]?"
        rf"|ticket\s+(?:number\s+)?(?:{re.escape(project_key)}[\s-]?)?)"
        r"(\d{1,5})\b", re.IGNORECASE)
    keys = set()
    for t in turns:
        for m in pat.finditer(t.text):
            keys.add(f"{project_key}-{int(m.group(1))}")
    return keys


def render_turns(turns: list[TranscriptTurn], offset: int = 0) -> str:
    """Compact plain-text rendering used as LLM input.

    offset lets a slice of a longer transcript keep its global turn numbers.
    """
    out = []
    for i, t in enumerate(turns, start=offset):
        ts = f" [{t.timestamp}]" if t.timestamp else ""
        out.append(f"({i}){ts} {t.speaker}: {t.text}")
    return "\n".join(out)

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


def strip_report_section(text: str) -> str:
    """Cut our own "Jira Sync Report" tab (exported after the transcript) so
    a re-read never treats report content — full of ticket keys — as input."""
    cut = re.search(r"^Standup Coverage Report —", text, flags=re.MULTILINE)
    return text[:cut.start()] if cut else text


def extract_transcript_section(text: str) -> str:
    """If the doc is a Gemini notes doc, slice from the embedded Transcript
    section (skipping Gemini's own summary). Otherwise return the text as-is.

    Gemini has used several marker styles ("Transcript", "📖 Transcript",
    "<Meeting> - Transcript"), and the summary above may itself mention
    "Transcript" — so match the LAST marker line in the doc.
    """
    text = strip_report_section(text)
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


def ticket_keys_in_text(text: str, project_key: str) -> set[str]:
    """Ticket keys mentioned in text: "AD-127", "AD 127", "AD127", and
    conversational forms like "the ticket number it is 127" (a few filler
    words tolerated). Used to pull discussed tickets the sprint JQL missed —
    scan the WHOLE doc (Gemini's summary normalizes keys nicely) after
    strip_report_section()."""
    p = re.escape(project_key)
    pats = [
        re.compile(rf"\b{p}[\s-]?(\d{{1,5}})\b", re.IGNORECASE),
        re.compile(rf"\bticket\s+(?:number\s+)?(?:\w+\s+){{0,3}}(\d{{1,5}})\b",
                   re.IGNORECASE),
    ]
    keys = set()
    for pat in pats:
        for m in pat.finditer(text):
            keys.add(f"{project_key}-{int(m.group(1))}")
    return keys


def spoken_ticket_keys(turns: list[TranscriptTurn], project_key: str) -> set[str]:
    """Ticket keys explicitly spoken in the parsed transcript turns."""
    return ticket_keys_in_text(
        "\n".join(t.text for t in turns), project_key)


def render_turns(turns: list[TranscriptTurn], offset: int = 0) -> str:
    """Compact plain-text rendering used as LLM input.

    offset lets a slice of a longer transcript keep its global turn numbers.
    """
    out = []
    for i, t in enumerate(turns, start=offset):
        ts = f" [{t.timestamp}]" if t.timestamp else ""
        out.append(f"({i}){ts} {t.speaker}: {t.text}")
    return "\n".join(out)

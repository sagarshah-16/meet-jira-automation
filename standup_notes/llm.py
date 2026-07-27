"""Two-pass LLM processing (OpenAI).

Pass A — segment the transcript and attribute chunks to tickets; discard
         off-topic chatter. Spoken ticket keys are the primary anchor; content
         is cross-checked against the real ticket list to correct mis-heard
         keys.
Pass B — turn each attributed segment into a structured note
         (Status Update / Summary / Blocker / Progress), omitting sections
         that weren't actually discussed.
"""

import json

from openai import OpenAI

from .config import Config
from .models import Segment, Ticket, TicketNote
from .transcript import TranscriptTurn, render_turns
from .validation import validate_ticket_key

_PASS_A_SYSTEM = """\
You process a daily standup transcript. You are given the team's open Jira
tickets and the transcript as numbered speaker turns.

Your job:
1. Split the conversation into segments, each about exactly ONE ticket.
2. Attribute each segment to a ticket key from the provided list ONLY.
   - A spoken ticket key (e.g. "PROJ-123") is the primary anchor. Speech-to-text
     may garble keys ("proj one twenty three", "PROJ 1 2 3") — normalize them.
   - If the spoken key doesn't exist in the list, or none was spoken, match by
     content against ticket summaries/descriptions/assignees.
3. DISCARD everything that is not about a ticket: greetings, jokes, logistics,
   general company talk, meta-discussion about the meeting itself.
4. Confidence: "high" = key spoken and matches list; "medium" = no key spoken
   but content clearly matches one ticket; "low" = plausible but uncertain.
   If you cannot attribute a segment to any listed ticket, discard it — never
   guess a key that wasn't provided.

Return JSON only:
{"segments": [{"ticket_key": "...", "confidence": "high|medium|low",
  "speaker": "...", "turn_indices": [..], "raw_text": "verbatim-ish text of what was said",
  "reasoning": "one short sentence"}],
 "discarded_turn_indices": [..]}
"""

_PASS_B_SYSTEM = """\
You write a concise Jira comment from what an engineer said about one ticket
in standup. You are given the ticket's details and the relevant transcript
excerpt.

Produce JSON only:
{"status_update": "...", "summary": "...", "blocker": "...", "progress": "..."}

Rules:
- summary: 1-3 sentences, plain language, what was discussed.
- status_update: the state of the work as stated or clearly implied by the
  discussion (e.g. "In code review", "Starting today", "Done, pending QA",
  "In progress — ETA Wednesday"). Empty string only if you truly cannot tell.
- blocker: ONLY if a blocker/dependency/impediment was explicitly mentioned.
  Empty string otherwise. Never invent one.
- progress: what moved forward since the last update, if said. Empty otherwise.
- Refer to the engineer by their name as given, or with "they/them" — never
  assume gender from a name.
- Minor impediments that are NOT blockers (e.g. "slowing me down a bit") belong
  in the summary, not the blocker field — but do include them.
- Do not add information that was not said. No speculation.
- If what was said is too thin to be useful (e.g. "no updates"), return all
  empty strings.
"""


class NotesLLM:
    def __init__(self, cfg: Config):
        self.client = OpenAI(api_key=cfg.openai_api_key)
        self.model = cfg.openai_model

    def _json_call(self, system: str, user: str) -> dict:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return json.loads(resp.choices[0].message.content)

    def segment(self, turns: list[TranscriptTurn], tickets: list[Ticket]) -> list[Segment]:
        ticket_block = "\n".join(t.brief() for t in tickets)
        user = (
            f"OPEN TICKETS:\n{ticket_block}\n\n"
            f"TRANSCRIPT (numbered turns):\n{render_turns(turns)}"
        )
        data = self._json_call(_PASS_A_SYSTEM, user)

        valid_keys = {t.key for t in tickets}
        segments = []
        for s in data.get("segments", []):
            try:
                key = validate_ticket_key(s.get("ticket_key") or "")
            except ValueError:
                continue
            if key not in valid_keys:
                continue  # hard guardrail: never post to a ticket we didn't fetch
            segments.append(Segment(
                ticket_key=key,
                confidence=s.get("confidence", "low"),
                speaker=s.get("speaker", ""),
                raw_text=s.get("raw_text", ""),
                reasoning=s.get("reasoning", ""),
            ))
        return segments

    def structure(self, segment: Segment, ticket: Ticket) -> TicketNote:
        user = (
            f"TICKET:\n{ticket.brief()}\n\n"
            f"SPOKEN BY: {segment.speaker}\n"
            f"TRANSCRIPT EXCERPT:\n{segment.raw_text}"
        )
        data = self._json_call(_PASS_B_SYSTEM, user)
        return TicketNote(
            ticket_key=segment.ticket_key,
            confidence=segment.confidence,
            status_update=(data.get("status_update") or "").strip(),
            summary=(data.get("summary") or "").strip(),
            blocker=(data.get("blocker") or "").strip(),
            progress=(data.get("progress") or "").strip(),
        )

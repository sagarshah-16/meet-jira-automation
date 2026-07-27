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
5. raw_text must be VERBATIM: copy the transcript turns word for word. Do NOT
   paraphrase, shorten, or clean up. Losing a phrase like "I will complete
   this today" or "you can test it in the environment" destroys the note that
   is written from this text downstream.
6. A segment includes what EVERY speaker said about that ticket — the
   assignee's update AND any reviewer/PM remarks (observations, approvals,
   requested changes, conditions like "ready after the UI fix").

Return JSON only:
{"segments": [{"ticket_key": "...", "confidence": "high|medium|low",
  "speaker": "...", "turn_indices": [..], "raw_text": "verbatim transcript text, all speakers",
  "reasoning": "one short sentence"}],
 "discarded_turn_indices": [..]}
"""

_PASS_B_SYSTEM = """\
You write a concise Jira comment from what an engineer said about one ticket
in standup. You are given the ticket's details and the relevant transcript
excerpt.

Produce JSON only (each list holds short bullet points; empty list if nothing
was said for that section):
{"progress": ["..."], "discussion": ["..."], "blockers": ["..."],
 "next_steps": ["..."], "eta": "..."}

ACCURACY RULES — these override brevity, and violating them is worse than
writing nothing:

1. STATE FIDELITY. Report the work's state EXACTLY as spoken — never upgrade
   or downgrade it. These are all DIFFERENT states; keep them distinct:
   - already deployed/done
   - approved and ready to deploy, but NOT yet deployed
   - a commitment to finish by some time (NOT done yet)
   - testable/available for testing (NOT approved)
   If someone says "it is ready to move to production", the note must say
   "ready to move to production" — NOT "has been pushed to production".
   Express the state in the SPEAKER'S OWN WORDS — do not copy phrasing from
   these instructions.

2. NEVER DROP COMMITMENTS. Every stated ETA, deadline, or promise ("I will
   complete this today", "targeting Wednesday", "once X is done this can go
   to production") MUST appear in the note — in eta and/or next_steps.
   Omitting a stated "will finish today" makes the note wrong.

3. NEVER INVENT FRAMING. Do not add mechanisms, comparisons, or causes that
   were not spoken. If the speaker said "I changed the approach and named it
   regular loan", do NOT write "replaced the previous logic" — nothing was
   said about what happened to any previous logic. Stay close to the
   speaker's own wording; short quoted phrases are welcome.

4. INCLUDE REVIEWER/PM REMARKS. Observations, review feedback, conditions,
   and requested changes from OTHER speakers about this ticket (e.g. "one
   observation — needs a minor UI improvement, then it's ready") are part of
   the ticket's state and MUST be captured.

Field rules:
- progress: the state of the work — what was completed, what moved forward,
  AND what is actively being worked on, in the speaker's own words
  (e.g. "Reviewed and ready to move to production", "Adding an API for
  bearer token exchange for the desktop app"). The reader must be able to
  tell from these bullets what the engineer is doing. Empty list only if
  the work itself was not described at all.
- discussion: other things discussed — reviewer/PM observations, decisions,
  demo feedback, conditions, minor impediments that are not blockers.
  Do not repeat progress bullets here. Empty list if nothing beyond progress.
- blockers: ONLY blockers/dependencies/impediments explicitly mentioned.
  Empty list otherwise. Never invent one.
- next_steps: what happens next AS STATED (e.g. "Fix the minor UI issue,
  then move to production"). Empty list if none stated.
- eta: the stated completion time/date ONLY if one was spoken, capitalized
  (e.g. "Today", "Wednesday", "End of this week"). Empty string otherwise —
  never infer or invent a date.
- Refer to the engineer by their name as given, or with "they/them" — never
  assume gender from a name.
- Keep bullets short and factual; one fact per bullet.
- If what was said is too thin to be useful (e.g. "no updates"), return all
  sections empty.

Before returning, re-read the excerpt and verify: (a) every claim in your note
was actually said, (b) no stated ETA/commitment/condition is missing, and
(c) the tense/state of each claim matches what was spoken.
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

        def bullets(name: str) -> list[str]:
            v = data.get(name) or []
            if isinstance(v, str):  # tolerate a stray string from the model
                v = [v]
            return [s.strip() for s in v if isinstance(s, str) and s.strip()]

        return TicketNote(
            ticket_key=segment.ticket_key,
            confidence=segment.confidence,
            progress=bullets("progress"),
            discussion=bullets("discussion"),
            blockers=bullets("blockers"),
            next_steps=bullets("next_steps"),
            eta=(data.get("eta") or "").strip()
            if isinstance(data.get("eta"), str) else "",
        )

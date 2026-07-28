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
import re

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
   - Keys are often spoken as bare numbers ("starting with 79, the branding
     ticket", "moving to 122") — match the number against the ticket list.
   - Garbled digits happen: "ticket number 8057" may really be ticket 57, and
     "1020" may be 120. When a spoken number matches no listed ticket, check
     whether the surrounding content clearly matches a listed ticket instead —
     attribute by content, and never invent a key for the garbled number.
   - If the spoken key doesn't exist in the list, or none was spoken, match by
     content against ticket summaries/descriptions/assignees.
3. DISCARD everything that is not about a ticket: greetings, jokes, logistics,
   general company talk, meta-discussion about the meeting itself.
4. Confidence: "high" = key spoken and matches list; "medium" = no key spoken
   but content clearly matches one ticket; "low" = plausible but uncertain.
   If you cannot attribute a segment to any listed ticket, discard it — never
   guess a key that wasn't provided.
5. turn_indices must be COMPLETE: list every turn index in which that ticket
   is discussed — the assignee's update AND any reviewer/PM remarks
   (observations, approvals, requested changes, conditions like "ready after
   the UI fix"). The note is written downstream from exactly these turns, so
   a missing index means lost information. When unsure whether an adjacent
   turn belongs to the discussion, INCLUDE it — extra context is harmless,
   a dropped turn loses information forever.
6. COVER EVERY TICKET DISCUSSED. Return one segment per ticket that was
   discussed, no matter how many that is — never limit or truncate the
   segment list. A long standup can easily cover 8-15 tickets, and a window
   of it may still contain updates for several tickets back to back.
7. Round-robin standups move fast: each engineer may cover 2-4 tickets in
   consecutive turns, and the PM's opening/closing remarks often cover
   several more. Treat EVERY topic shift as a potential new ticket.

Before returning, do a completeness pass: go through the ticket list once
more and ask, for each ticket, "is any part of this window about it —
even without the key being spoken?" Add any segment you missed.

Return JSON only (do NOT copy transcript text into the output — indices only):
{"segments": [{"ticket_key": "...", "confidence": "high|medium|low",
  "speaker": "main speaker name", "turn_indices": [..],
  "reasoning": "one short sentence"}],
 "discarded_turn_indices": [..]}
"""

_PASS_R_SYSTEM = """\
You do a REVERSE LOOKUP over a standup transcript. A first pass already
extracted segments for most tickets; the tickets listed below are the ones it
found NO discussion for. Your job is to double-check: search this transcript
window specifically for each listed ticket.

For each listed ticket, ask: is any part of this window about it? Look for its
feature area, its summary/description keywords, and its assignee giving an
update — the ticket key may never be spoken.

PRECISION over recall in this pass:
- Attribute ONLY when the content clearly relates to that ticket's summary/
  description (same feature, same work). "confidence": "high" or "medium".
- If a match is weak or generic (could be about anything), use "low" — such
  matches are discarded downstream, which is the correct outcome. A wrong
  note on the wrong ticket is worse than no note.
- Finding nothing for most or all listed tickets is a perfectly good result —
  it confirms they were genuinely not discussed.
- turn_indices must be complete for any ticket you do attribute (include the
  assignee's update and any reviewer/PM remarks).

Return JSON only (indices only, no transcript text):
{"segments": [{"ticket_key": "...", "confidence": "high|medium|low",
  "speaker": "main speaker name", "turn_indices": [..],
  "reasoning": "one short sentence"}]}
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

    # Long transcripts are segmented in overlapping windows — a single pass
    # over 300+ turns reliably under-extracts (tickets get silently skipped).
    CHUNK_TURNS = 80
    CHUNK_OVERLAP = 10

    def _chunked_acc(self, turns: list[TranscriptTurn], tickets: list[Ticket],
                     system: str) -> dict[str, dict]:
        """Run a segmentation prompt over overlapping transcript windows.

        Returns ticket_key -> {"indices": set, "confidence", "speaker",
        "reasoning"}, merged across windows.
        """
        ticket_block = "\n".join(t.brief() for t in tickets)
        valid_keys = {t.key for t in tickets}
        conf_rank = {"high": 2, "medium": 1, "low": 0}
        acc: dict[str, dict] = {}

        start = 0
        while start < len(turns):
            end = min(len(turns), start + self.CHUNK_TURNS)
            user = (
                f"OPEN TICKETS:\n{ticket_block}\n\n"
                f"TRANSCRIPT (turns {start}-{end - 1} of {len(turns)} — a window "
                f"of the full standup; indices are global):\n"
                f"{render_turns(turns[start:end], offset=start)}"
            )
            data = self._json_call(system, user)
            for s in data.get("segments", []):
                try:
                    key = validate_ticket_key(s.get("ticket_key") or "")
                except ValueError:
                    continue
                if key not in valid_keys:
                    continue  # hard guardrail: never post outside fetched context
                indices = {int(i) for i in s.get("turn_indices", [])
                           if isinstance(i, (int, float)) and 0 <= int(i) < len(turns)}
                if not indices:
                    continue
                entry = acc.setdefault(key, {
                    "indices": set(), "confidence": "low",
                    "speaker": s.get("speaker", ""),
                    "reasoning": s.get("reasoning", "")})
                entry["indices"] |= indices
                if conf_rank[s.get("confidence", "low")] > conf_rank[entry["confidence"]]:
                    entry["confidence"] = s.get("confidence", "low")
            if end == len(turns):
                break
            start = end - self.CHUNK_OVERLAP
        return acc

    @staticmethod
    def _acc_to_segments(acc: dict[str, dict],
                         turns: list[TranscriptTurn]) -> list[Segment]:
        """One segment per ticket; text reconstructed verbatim from the union
        of referenced turns, so fidelity is guaranteed by code."""
        segments = []
        for key, e in acc.items():
            ordered = sorted(e["indices"])
            segments.append(Segment(
                ticket_key=key,
                confidence=e["confidence"],
                speaker=e["speaker"],
                raw_text="\n".join(
                    f"{turns[i].speaker}: {turns[i].text}" for i in ordered),
                reasoning=e["reasoning"],
            ))
        return segments

    def segment(self, turns: list[TranscriptTurn], tickets: list[Ticket]) -> list[Segment]:
        valid_keys = {t.key for t in tickets}
        acc = self._chunked_acc(turns, tickets, _PASS_A_SYSTEM)

        # Deterministic safety net: turns that explicitly speak a ticket key
        # ("AD122", "ticket 127") are force-included with a small context
        # window, so an LLM miss can never drop an explicitly named ticket.
        prefixes = sorted({k.split("-")[0] for k in valid_keys})
        spoken_key = re.compile(
            r"\b(?:(?:" + "|".join(prefixes) + r")[\s-]?"
            r"|ticket\s+(?:number\s+)?(?:(?:" + "|".join(prefixes) + r")[\s-]?)?)"
            r"(\d{1,5})\b", re.IGNORECASE)
        for i, t in enumerate(turns):
            for m in spoken_key.finditer(t.text):
                key = f"{prefixes[0]}-{int(m.group(1))}" if len(prefixes) == 1 else None
                if key is None:
                    continue
                if key not in valid_keys:
                    continue
                entry = acc.setdefault(key, {
                    "indices": set(), "confidence": "high",
                    "speaker": t.speaker,
                    "reasoning": "Spoken ticket key detected in transcript"})
                entry["indices"] |= set(range(max(0, i - 1), min(len(turns), i + 4)))
                entry["confidence"] = "high"

        return self._acc_to_segments(acc, turns)

    def reverse_lookup(self, turns: list[TranscriptTurn],
                       missed: list[Ticket]) -> list[Segment]:
        """Second, focused sweep: given ONLY the tickets the main pass found
        nothing for, search the transcript again for each. Precision-biased —
        low-confidence matches are dropped rather than risking a wrong note.
        """
        if not missed:
            return []
        acc = self._chunked_acc(turns, missed, _PASS_R_SYSTEM)
        return [s for s in self._acc_to_segments(acc, turns)
                if s.confidence in ("high", "medium")]

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

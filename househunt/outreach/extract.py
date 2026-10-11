"""Turn a call transcript into structured facts with Claude."""

from __future__ import annotations

import logging
import re
from datetime import datetime

import anthropic
from pydantic import BaseModel, Field

from househunt import llm
from househunt.models import Listing, SearchCriteria

log = logging.getLogger(__name__)


class MustHaveCheck(BaseModel):
    item: str
    ok: bool | None = Field(description="true/false if the contact answered, null if not discussed")


class CallSummary(BaseModel):
    reached_person: bool = Field(description="false for voicemail, no answer, or wrong number")
    available: bool | None
    monthly_rent: int | None
    deposit: str | None = Field(description="deposit / move-in costs as stated, e.g. '1 month'")
    lease_terms: str | None
    move_in_ok: bool | None
    must_haves: list[MustHaveCheck]
    tour_booked: bool = Field(description="true only if a specific date AND time was agreed")
    tour_start: str | None = Field(description="agreed viewing start as ISO 8601 local datetime")
    offered_times: list[str] = Field(description="viewing times the contact offered, verbatim")
    do_not_call: bool = Field(description="contact asked not to be called again")
    viable: bool = Field(description="available and no hard criteria clearly violated")
    tradeoffs: list[str] = Field(description="up to 3 short downsides the renter should weigh")
    summary: str = Field(description="two sentences for the renter")


SYSTEM = (
    "You read transcripts of calls an AI assistant made to landlords and letting agents on "
    "behalf of a renter, and extract what was learned. Only record facts the contact actually "
    "stated; use null when something was not discussed. Resolve relative dates like 'Thursday' "
    "against the call date given."
)


def extract(transcript: str, listing: Listing, criteria: SearchCriteria,
            call_date: datetime | None = None) -> CallSummary:
    call_date = call_date or datetime.now()
    if not llm.has_credentials():
        log.warning("No Anthropic credentials; using heuristic transcript extraction")
        return heuristic_extract(transcript, listing, criteria, call_date)

    from househunt.config import settings

    prompt = (
        f"Call date: {call_date:%A %Y-%m-%d %H:%M}\n"
        f"Listing: {listing.title} | advertised ${listing.price} | {listing.address or ''}\n"
        f"Renter's criteria: max ${criteria.max_price}/mo, min {criteria.min_beds} beds, "
        f"must-haves: {', '.join(criteria.must_haves) or 'none'}, "
        f"move in by: {criteria.move_in_by or 'flexible'}\n\n"
        f"<transcript>\n{transcript}\n</transcript>"
    )
    try:
        response = llm.client().beta.messages.parse(
            model=settings.claude_model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=CallSummary,
            output_config={"effort": "low"},
            # Re-run on a fallback model if a safety classifier declines the request.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APIError:
        log.exception("Claude transcript extraction failed; falling back to heuristic")
        return heuristic_extract(transcript, listing, criteria, call_date)
    if response.stop_reason == "refusal" or response.parsed_output is None:
        log.warning("Claude declined/failed transcript extraction; falling back to heuristic")
        return heuristic_extract(transcript, listing, criteria, call_date)
    return response.parsed_output


def heuristic_extract(transcript: str, listing: Listing, criteria: SearchCriteria,
                      call_date: datetime) -> CallSummary:
    """Keyword fallback so dry runs and tests work without an API key."""
    t = transcript.lower()
    contact_lines = " ".join(l for l in t.splitlines() if not l.startswith("agent:"))
    reached = "contact:" in t
    available = None
    if re.search(r"\b(still available|yes, it is|it's available)\b", contact_lines):
        available = True
    elif re.search(r"\b(rented|taken|no longer|not available)\b", contact_lines):
        available = False
    booked = bool(re.search(r"\b(works|see you|confirmed)\b", contact_lines))
    return CallSummary(
        reached_person=reached,
        available=available,
        monthly_rent=listing.price,
        deposit=None,
        lease_terms=None,
        move_in_ok=None,
        must_haves=[MustHaveCheck(item=m, ok=None) for m in criteria.must_haves],
        tour_booked=booked,
        tour_start=None,
        offered_times=[],
        do_not_call="don't call" in contact_lines or "do not call" in contact_lines,
        viable=bool(reached and available),
        tradeoffs=[],
        summary="Heuristic summary (no Claude key configured). Read the transcript for details.",
    )

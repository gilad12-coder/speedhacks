"""What the renter should do next about a place they're interested in.

Rule-based on purpose: it's instant, needs no API credits, and is easy to reason about. The
per-place agent chat is there for anything more nuanced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlencode

from househunt.models import Listing, ListingStatus, Source


@dataclass
class NextStep:
    action: str        # call | email | reveal | book_online | message | log_viewing | prepare | wait | move_on
    label: str
    why: str
    href: str | None = None   # for steps that happen on another site


def recommend(listing: Listing, call=None, email=None, tour=None) -> NextStep:
    phone = listing.contact.phone if listing.contact else None
    addr = listing.contact.email if listing.contact else None
    outcome = json.loads(call["outcome"]) if call and call["outcome"] else None

    if tour:
        when = _when(tour["start"])
        return NextStep("prepare", f"Get ready for your viewing {when}",
                        "Bring ID and proof of income, and check the commute from there at the same "
                        "time of day.", gcal_link(f"Viewing: {listing.title}", tour["start"],
                                                  listing.address, listing.url))

    if call and call["status"] in ("queued", "in_progress"):
        return NextStep("wait", "Wait for the call to finish",
                        "Your agent is on the phone with them now; results show up here.")

    if outcome:
        if outcome.get("booking_warning"):
            return NextStep("wait", "Review the possible booking", outcome["booking_warning"])
        if outcome.get("verification_status") == "ruled_out":
            return NextStep("move_on", "Probably move on",
                            outcome.get("summary") or "The call suggests it isn't a fit.")
        if listing.tour_url:
            return NextStep("book_online", "Book a viewing on their website",
                            "It's available and fits. Their site lets you pick a time yourself; "
                            "log it here once you've booked.", listing.tour_url)
        times = outcome.get("offered_times") or []
        if times:
            return NextStep("log_viewing", f"Pick a viewing time: {', '.join(times[:3])}",
                            "They offered these on the call. Confirm one with them, then log it here.")
        if not outcome.get("viable"):
            return NextStep("wait", "Review the remaining questions", "Unconfirmed requirements are still open questions. Check the call evidence before deciding whether to proceed.")
        return NextStep("call" if phone else "email", "Follow up to book a viewing",
                        "It's available and fits, but no time was set on the call.")

    if call and call["status"] == "failed":
        if addr and not email:
            return NextStep("email", "Email them instead",
                            "The call didn't go through; an email gets a written answer.")
        return NextStep("call", "Try calling again",
                        "The last call didn't connect. Mornings and early evenings work best.")

    if email and email["status"] == "sent":
        if phone:
            return NextStep("call", "Call to speed things up",
                            "You've emailed; a call usually gets an answer the same day.")
        return NextStep("wait", "Wait for their reply",
                        "Replies land in your Gmail; most agents answer within a day.")

    if listing.tour_url:
        return NextStep("book_online", "Book a viewing on their website",
                        "This site has self-scheduled tours, the fastest way to see it.",
                        listing.tour_url)
    if phone:
        return NextStep("call", "Have your agent call",
                        "One call confirms it's still available, the real move-in costs, and can "
                        "book a viewing in your free times.")
    if addr:
        return NextStep("email", "Email the contact",
                        "Ask about availability, move-in costs, and viewing times. You approve "
                        "the draft before it sends.")
    if listing.source == Source.FACEBOOK:
        return NextStep("message", "Message the seller on Facebook",
                        "Marketplace and group posters usually only answer in Messenger. Ask "
                        "if it's available and when you can see it.", listing.url)
    if listing.status == ListingStatus.FILTERED_OUT:
        return NextStep("move_on", "Double-check it fits",
                        "It's outside your search criteria; worth a look only if you'd stretch.")
    return NextStep("reveal", "Get their phone number or email",
                    "Open the listing and reveal the contact, then paste it on the card so your "
                    "agent can call or email.", listing.url)


def _when(start: str) -> str:
    try:
        return datetime.fromisoformat(start).strftime("%a %b %-d, %-I:%M%p").replace(
            "AM", "am").replace("PM", "pm")
    except ValueError:
        return start


def gcal_link(title: str, start: str, location: str | None, details: str | None,
              minutes: int = 30, end: str | None = None) -> str | None:
    """A Google Calendar "add event" link; works without connecting Google."""
    try:
        s = datetime.fromisoformat(start)
    except (TypeError, ValueError):
        return None
    from datetime import timedelta

    e = datetime.fromisoformat(end) if end else s + timedelta(minutes=minutes)
    fmt = "%Y%m%dT%H%M%S"
    if s.utcoffset() is not None:
        from datetime import timezone
        s, e = s.astimezone(timezone.utc), e.astimezone(timezone.utc)
        fmt += "Z"
    return "https://calendar.google.com/calendar/render?" + urlencode({
        "action": "TEMPLATE", "text": title, "dates": f"{s:{fmt}}/{e:{fmt}}",
        "location": location or "", "details": details or "",
    }, quote_via=quote)

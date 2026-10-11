"""Builds the system prompt the Dial voice agent uses on a call to a listing contact."""

from __future__ import annotations

from househunt.models import Listing, SearchCriteria


def build_instruction(listing: Listing, criteria: SearchCriteria, renter_name: str) -> str:
    facts = [f"Listing: {listing.title}"]
    if listing.address:
        facts.append(f"Address: {listing.address}")
    if listing.price:
        facts.append(f"Advertised rent: ${listing.price}/month")
    if listing.beds is not None:
        facts.append(f"Bedrooms: {listing.beds}")
    facts.append(f"Seen on: {listing.source.value} ({listing.url})")

    questions = [
        "Is the unit still available?",
        "What is the monthly rent, and what deposit and move-in costs are required?",
        "What lease terms are offered (for example, is a 12-month lease OK)?",
    ]
    if criteria.move_in_by:
        questions.append(f"Can the renter move in by {criteria.move_in_by}?")
    for m in criteria.must_haves:
        questions.append(f"Confirm: does it have / allow {m}?")

    tour = (
        f"If it is available and fits, try to book an in-person viewing. The renter is free: "
        f"{'; '.join(criteria.tour_availability)}. Agree on one specific date and time, and "
        f"repeat it back to confirm."
        if criteria.tour_availability
        else "If it is available, ask which viewing times they have this week. Do not commit "
             "to a time; say the renter will confirm by text."
    )

    return "\n".join([
        f"You are a friendly assistant calling on behalf of {renter_name}, who is looking to rent. "
        "You are an AI assistant; say so at the start of the call and if asked.",
        "You are calling about this rental listing:",
        *[f"- {f}" for f in facts],
        "",
        "Ask these questions, conversationally and one at a time:",
        *[f"{i}. {q}" for i, q in enumerate(questions, 1)],
        "",
        tour,
        "",
        "Rules:",
        "- Keep the call under 4 minutes. Be polite and concise.",
        "- Never agree to pay anything, sign anything, or share personal financial details.",
        "- If they ask for the renter's contact details, say the renter will follow up by text.",
        "- If you reach voicemail, leave a short message saying you're calling about the "
        "listing and will try again, then hang up.",
        "- If they ask you not to call again, apologize, confirm, and end the call.",
    ])

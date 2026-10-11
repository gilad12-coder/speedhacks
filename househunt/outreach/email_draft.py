"""Draft an inquiry email for a listing. Drafts are only ever sent after the user approves."""

from __future__ import annotations

import logging

import anthropic
from pydantic import BaseModel

from househunt import llm
from househunt.models import Listing, SearchCriteria

log = logging.getLogger(__name__)


class EmailDraft(BaseModel):
    subject: str
    body: str


SYSTEM = (
    "You write short, friendly inquiry emails from a renter to the landlord or agent of a "
    "rental listing. Plain text, no markdown. Under 150 words. Ask only what the renter "
    "needs to decide: availability, total move-in costs, lease terms, anything from their "
    "must-haves the listing doesn't already answer, and when they could view it. Don't "
    "invent facts about the renter beyond what you're given. Sign with the renter's name."
)


def draft_email(listing: Listing, criteria: SearchCriteria, renter_name: str) -> EmailDraft:
    if not llm.has_credentials():
        return template_email(listing, criteria, renter_name)

    from househunt.config import settings

    prompt = (
        f"Renter: {renter_name}\n"
        f"Listing: {listing.title}\n"
        f"Address: {listing.address or 'not given'}\n"
        f"Advertised rent: {'$' + str(listing.price) + '/mo' if listing.price else 'not given'}\n"
        f"Beds/baths: {listing.beds}/{listing.baths}\n"
        f"Link: {listing.url}\n"
        f"Description: {listing.description[:1500] or 'none'}\n\n"
        f"Renter's must-haves: {', '.join(criteria.must_haves) or 'none'}\n"
        f"Move in by: {criteria.move_in_by or 'flexible'}\n"
        f"Free for viewings: {'; '.join(criteria.tour_availability) or 'ask what times they have'}"
    )
    try:
        response = llm.client().beta.messages.parse(
            model=settings.claude_model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=EmailDraft,
            output_config={"effort": "low"},
            **({"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
               if settings.claude_model in llm.FALLBACK_MODELS else {}),
        )
    except anthropic.APIError:
        log.exception("Claude draft failed; using template")
        return template_email(listing, criteria, renter_name)
    if response.stop_reason == "refusal" or response.parsed_output is None:
        return template_email(listing, criteria, renter_name)
    return response.parsed_output


def template_email(listing: Listing, criteria: SearchCriteria, renter_name: str) -> EmailDraft:
    where = listing.address or listing.title
    questions = ["Is it still available?", "What are the total move-in costs and lease terms?"]
    if criteria.move_in_by:
        questions.append(f"Would a move-in by {criteria.move_in_by} work?")
    questions += [f"Does it have / allow {m}?" for m in criteria.must_haves]
    viewing = ("I'm free " + "; ".join(criteria.tour_availability) + " to view it."
               if criteria.tour_availability else "When could I come see it?")
    body = "\n".join([
        "Hi,",
        "",
        f"I'm interested in the rental at {where} ({listing.url}).",
        "",
        *[f"- {q}" for q in questions],
        "",
        viewing,
        "",
        "Thanks,",
        renter_name,
    ])
    return EmailDraft(subject=f"Inquiry about {where}", body=body)

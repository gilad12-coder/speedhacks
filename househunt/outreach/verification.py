"""Evidence extraction contract. Provider output is untrusted until checked here."""
from __future__ import annotations

from datetime import datetime
import re
import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from househunt.models import Listing, SearchCriteria


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Ref(StrictModel):
    turn_index: int = Field(ge=0)
    quote: str = Field(min_length=1)


class Fact(StrictModel):
    key: str
    passed: bool | None
    summary: str
    evidence: list[Ref]


class Amount(StrictModel):
    value: int = Field(gt=0)
    evidence: Ref


class Detail(StrictModel):
    name: str
    value: str
    evidence: Ref


class Window(StrictModel):
    start: str
    end: str
    evidence: list[Ref] = Field(min_length=1)


class Booking(Window):
    meeting_address: str
    agent_acceptance: Ref
    contact_confirmation: Ref
    requires_payment_or_application: bool


class Assessment(StrictModel):
    reached_person: bool
    voicemail: bool
    do_not_call: Ref | None
    facts: list[Fact]
    monthly_rent: Amount | None
    details: list[Detail]
    tour_offers: list[Window]
    confirmed_tour: Booking | None = None


class Evidence(StrictModel):
    callId: str
    t: float
    quote: str


class Check(StrictModel):
    kind: Literal["real", "matches", "fit", "tour"]
    passed: bool | None
    summary: str
    evidence: Evidence | None


def requirements(c: SearchCriteria, listing: Listing | None = None) -> list[dict]:
    result = [
        {"key": "available", "group": "real", "question": "Is this exact rental still available, and are you the landlord or authorized agent?"},
        {"key": "rent", "group": "matches", "question": f"What is the actual total monthly rent? Budget: ${c.min_price}–${c.max_price}."},
        {"key": "qualifications", "group": "fit", "question": "What income, credit, guarantor and application requirements apply? The renter's financial eligibility is unknown; do not assume it."},
    ]
    if c.min_beds:
        result.append({"key": "beds", "group": "matches", "question": f"Are there at least {c.min_beds} bedrooms?"})
    if c.min_baths:
        result.append({"key": "baths", "group": "matches", "question": f"Are there at least {c.min_baths} bathrooms?"})
    if c.move_in_by:
        result.append({"key": "move_in", "group": "matches", "question": f"Can the tenancy start by {c.move_in_by}?"})
    if c.occupants:
        result.append({"key": "occupancy", "group": "fit", "question": f"Can {c.occupants} housemates rent and occupy the unit?"})
    result.extend({"key": f"must:{i}", "group": "matches", "question": f"Required: {item}. Please confirm."} for i, item in enumerate(c.must_haves))
    result.extend({"key": f"avoid:{i}", "group": "matches", "question": f"Deal-breaker to avoid: {item}. Confirm this is NOT present."} for i, item in enumerate(c.deal_breakers))
    if c.move_in_from and c.move_in_by:
        result.append({"key":"move_window", "group":"matches", "question":f"Can the tenancy start between {c.move_in_from} and {c.move_in_by}?"})
    if listing is not None:
        result.extend([
            {"key": "identity", "group": "listing", "question": f"Please repeat the full street address and unit number for {listing.address or 'the advertised listing (address not yet known)'}. Confirm we mean that exact unit, not another apartment in the building."},
            {"key": "authority", "group": "real", "question": "Are you the owner or the authorized leasing agent for this exact unit?"},
            {"key": "tour_requirements", "group": "booking", "question": "Please confirm the required rental fees, and that reserving a viewing does not require any payment or application first."},
        ])
        for key, value in (("beds", listing.beds), ("baths", listing.baths)):
            if value is not None:
                result.append({"key": f"advertised_{key}", "group": "listing", "question": f"The ad says {value} {key}. Is that the exact count for this unit?"})
    return result


def address_matches(expected: str | None, confirmed: str) -> bool:
    """Require street number/name and the advertised unit in a contact's own words."""
    if not expected:
        return False
    def parts(value):
        value = value.lower().replace("#", " unit ")
        unit = re.search(r"\b(?:apt\.?|apartment|unit|suite)\s+([a-z0-9-]+)", value)
        street = value[:unit.start()] if unit else value
        street = street.split(",")[0]
        aliases = {"street":"st", "avenue":"ave", "road":"rd", "boulevard":"blvd", "drive":"dr", "lane":"ln", "court":"ct", "place":"pl", "terrace":"ter", "north":"n", "south":"s", "east":"e", "west":"w"}
        words = [aliases.get(w,w) for w in re.findall(r"[a-z0-9]+", street)]
        return words, unit.group(1) if unit else None
    words, unit = parts(expected)
    quoted, actual_unit = parts(confirmed)
    street_types = {"st","ave","rd","blvd","dr","ln","ct","pl","ter","way"}
    for i, word in enumerate(words):
        if i > 1 and word in street_types:
            words = words[:i+1]
            break
    if len(words) < 2 or not words[0].isdigit() or (unit is not None and unit != actual_unit):
        return False
    return any(quoted[i:i+len(words)] == words for i in range(len(quoted)))


def number_in_quote(value: int, quote: str) -> bool:
    if value in [int(n.replace(',', '')) for n in re.findall(r"\b\d[\d,]*\b", quote)]:
        return True
    numbers = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(), range(20)))
    numbers.update(dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20,100,10))))
    words = re.findall(r"[a-z]+", quote.lower())
    for i in range(len(words)):
        total = current = 0
        for word in words[i:]:
            if word in numbers: current += numbers[word]
            elif word == "hundred": current = max(current,1) * 100
            elif word == "thousand": total += max(current,1) * 1000; current = 0
            elif word != "and": break
            if total + current == value: return True
    return False


def timed_turns(raw: dict) -> list[dict]:
    result = []
    for t in raw.get("transcriptTurns") or []:
        offset = t.get("startMs")
        if t.get("speaker") not in ("agent", "user", "contact") or not isinstance(offset, (int, float)) or not math.isfinite(offset) or offset < 0 or not t.get("text", "").strip():
            continue
        result.append({"t": offset / 1000, "speaker": "agent" if t["speaker"] == "agent" else "contact", "text": t["text"]})
    return result


def validate_assessment(a: Assessment, turns: list[dict], criteria: SearchCriteria, call_id: str, started_at: datetime, listing: Listing | None = None, booking_context: dict | None = None) -> dict:
    def valid(ref: Ref) -> bool:
        return (ref.turn_index < len(turns) and turns[ref.turn_index]["speaker"] == "contact"
                and bool(ref.quote.strip()) and ref.quote in turns[ref.turn_index]["text"])

    def cite(ref: Ref) -> Evidence:
        return Evidence(callId=call_id, t=turns[ref.turn_index]["t"], quote=ref.quote)

    expected = requirements(criteria, listing)
    allowed = {r["key"] for r in expected}
    facts = {}
    for fact in a.facts:
        if fact.key not in allowed or fact.key in facts:
            raise ValueError("Unexpected or duplicate extracted requirement")
        if fact.passed is not None and (not fact.evidence or not all(valid(r) for r in fact.evidence)):
            fact = Fact(key=fact.key, passed=None, summary="Not confirmed on the call", evidence=[])
        facts[fact.key] = fact
    amount = a.monthly_rent if a.monthly_rent and valid(a.monthly_rent.evidence) else None
    if listing is not None and amount and not number_in_quote(amount.value, amount.evidence.quote):
        amount = None
    if listing is not None and (identity := facts.get("identity")) and identity.passed is True:
        if not any(address_matches(listing.address, ref.quote) for ref in identity.evidence):
            facts["identity"] = Fact(key="identity", passed=None, summary="Exact address and unit not repeated by the contact", evidence=[])
    facts["rent"] = Fact(key="rent", passed=criteria.min_price <= amount.value <= criteria.max_price if amount else None,
                         summary=f"Contact stated ${amount.value}/month" if amount else "Monthly rent not confirmed",
                         evidence=[amount.evidence] if amount else [])
    answered = a.reached_person and not a.voicemail
    checks = []
    for group in ("real", "matches", "fit"):
        group_facts = [facts.get(r["key"]) for r in expected if r["group"] == group]
        failed = next((f for f in group_facts if f and f.passed is False), None)
        passed = None if not answered else False if failed else True if all(f and f.passed is True for f in group_facts) else None
        supporting = failed or next((f for f in group_facts if f and f.passed is True), None)
        checks.append(Check(kind=group, passed=passed,
                            summary="Not fully confirmed on the call" if passed is None else "; ".join(f.summary for f in group_facts if f and f.passed == passed),
                            evidence=cite(supporting.evidence[0]) if passed is not None and supporting and supporting.evidence else None))
    failed = any(c.passed is False for c in checks)
    windows, refs = [], []
    for offer in a.tour_offers:
        try:
            start, end = datetime.fromisoformat(offer.start), datetime.fromisoformat(offer.end)
            valid_time = start.utcoffset() is not None and end.utcoffset() is not None and start > started_at and 0 < (end-start).total_seconds() <= 86400
        except (ValueError, TypeError):
            valid_time = False
        if answered and not failed and valid_time and all(valid(r) for r in offer.evidence):
            windows.append({"start": offer.start, "end": offer.end})
            refs.append(offer.evidence[0])
    listing_facts = [facts.get(key) for key in ["identity", "authority", "available", *[f"advertised_{k}" for k in ("beds", "baths") if listing is not None and getattr(listing,k) is not None]]]
    listing_verified = None
    if listing is not None and answered:
        if any(f and f.passed is False for f in listing_facts) or (amount and listing.price is not None and amount.value != listing.price):
            listing_verified = False
        elif amount and listing.price is not None and amount.value == listing.price and all(f and f.passed is True for f in listing_facts):
            listing_verified = True
    confirmed = None
    booking = a.confirmed_tour
    context = booking_context or {}
    needed_for_booking = [r["key"] for r in expected if r["group"] in ("matches", "booking") or r["key"] == "occupancy"]
    ready_to_book = all(facts.get(key) and facts[key].passed is True for key in needed_for_booking)
    if booking and listing_verified is True and ready_to_book and not failed and not a.do_not_call and not booking.requires_payment_or_application:
        try:
            start, end = datetime.fromisoformat(booking.start), datetime.fromisoformat(booking.end)
            checked = datetime.fromisoformat(context["checked_at"])
            authorized = context.get("enabled") is True and 0 <= (started_at - checked).total_seconds() <= 600
            authorized = authorized and start > started_at and 0 < (end-start).total_seconds() <= 7200
            authorized = authorized and any(datetime.fromisoformat(w["start"]) <= start < end <= datetime.fromisoformat(w["end"]) for w in context.get("windows", []))
            agent = booking.agent_acceptance
            contact = booking.contact_confirmation
            agent_valid = agent.turn_index < len(turns) and turns[agent.turn_index]["speaker"] == "agent" and bool(agent.quote.strip()) and agent.quote in turns[agent.turn_index]["text"]
            negative = r"\b(?:not|can't|cannot|tentative|maybe|might|later|check first|cancelled|canceled|if|provided|subject to|pending|once)\b"
            contact_turn = turns[contact.turn_index]["text"] if contact.turn_index < len(turns) else ""
            commitment = bool(re.search(r"\b(?:booked|confirmed|scheduled|reserved|see you)\b", contact.quote, re.I)) and not re.search(negative, contact_turn, re.I)
            cancelled_later = any(re.search(r"\b(?:cancel|cancelled|canceled|cannot make|can't make|won't work|will not work)\b", t["text"], re.I) for t in turns[contact.turn_index+1:])
            acceptance = bool(re.search(r"\b(?:book|confirm|we'll be there|we will be there|see you)\b", agent.quote, re.I)) and not re.search(negative, agent.quote, re.I)
            if (authorized and agent_valid and acceptance and valid(contact) and commitment and not cancelled_later and contact.turn_index > agent.turn_index
                    and all(valid(r) for r in booking.evidence) and address_matches(listing.address, booking.meeting_address)):
                confirmed = {"start": booking.start, "end": booking.end, "meeting_address": booking.meeting_address,
                    "contact_evidence": cite(contact).model_dump(), "agent_evidence": cite(agent).model_dump()}
        except (KeyError, ValueError, TypeError):
            pass
    checks.append(Check(kind="tour", passed=True if confirmed or windows else None,
                        summary="Tour booked and confirmed by the contact" if confirmed else "Viewing offered; confirmation needed" if windows else "No concrete viewing window confirmed",
                        evidence=Evidence(**confirmed["contact_evidence"]) if confirmed else cite(refs[0]) if refs else None))
    verified = all(c.passed is True for c in checks[:3]) and (listing is None or listing_verified is True)
    failed = failed or listing_verified is False
    return {"listing_verified": listing_verified, "confirmed_tour": confirmed,
            "booking_warning": "A possible booking needs review: the exact listing, authorized time or mutual confirmation could not be verified. Review the transcript before arranging another tour." if booking and not confirmed else None,
            "checks": checks, "facts": facts, "monthly_rent": amount.value if answered and amount else None,
            "confirmed_facts": [{"key": f.key, "summary": f.summary, "passed": f.passed,
                                  "evidence": [cite(r).model_dump() for r in f.evidence]}
                                 for f in facts.values() if answered and f.passed is not None and f.evidence and all(valid(r) for r in f.evidence)],
            "details": {d.name: d.value for d in a.details if answered and valid(d.evidence)},
            "offered_windows": windows, "do_not_call": bool(a.do_not_call and valid(a.do_not_call)),
            "verification_status": "verified" if verified else "ruled_out" if failed else "unconfirmed"}

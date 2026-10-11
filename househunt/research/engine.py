"""Discover -> read -> validate -> refine -> cross-search, within explicit budgets."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from statistics import median
from typing import Literal

from pydantic import Field

from househunt.collect import extract_phone, passes_filters
from househunt.manual import identify
from househunt.models import Contact, Listing, SearchCriteria, Source
from househunt.research.provider import Links, Strict, ask, public_criteria
from househunt.research.web import Page, canonical_url, exact_quote, fetch_page, host


class Fact(Strict):
    key: Literal["rent", "beds", "baths", "sqft", "address", "neighborhood", "phone", "email"]
    value: str
    quote: str


class Match(Strict):
    requirement: str
    matched: bool | None
    quote: str


class Rental(Strict):
    url: str
    is_specific_rental: bool
    in_requested_city: bool | None
    availability: Literal["advertised_available", "unavailable", "unknown"]
    availability_quote: str
    facts: list[Fact]
    requirements: list[Match]


class Rentals(Strict):
    rentals: list[Rental]


class Finding(Strict):
    kind: Literal["address_corroborated", "contact_corroborated", "rent_conflict", "contact_conflict",
                  "upfront_payment", "unavailable", "other_concern"]
    url: str
    quote: str
    explanation: str
    same_unit: bool
    supports_finding: bool


class Comparable(Strict):
    url: str
    address: str
    price: int = Field(gt=0)
    beds: int = Field(ge=0)
    neighborhood: str
    same_area: bool
    price_quote: str
    beds_quote: str
    address_quote: str


class Review(Strict):
    findings: list[Finding]
    comparables: list[Comparable]


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def number_in_quote(value: float, quote: str) -> bool:
    numbers = re.findall(r"(?<!\w)\d+(?:,\d{3})*(?:\.\d+)?(?!\w)", quote)
    return any(float(n.replace(",", "")) == value for n in numbers)


def evidence(field: str, quote: str, page: Page) -> dict:
    return {"field": field, "quote": quote, "url": page.url, "checked_at": timestamp()}


def parse_rental(rental: Rental, page: Page, criteria: SearchCriteria) -> Listing | None:
    if not rental.is_specific_rental or rental.in_requested_city is False:
        return None
    source, source_id = identify(page.url)
    listing = Listing(source=source or Source.OTHER, source_id=source_id, url=page.url,
                      title=page.title, provenance=[page.url])
    accepted = []
    for fact in rental.facts:
        if not exact_quote(fact.quote, page):
            continue
        value = fact.value.strip()
        if fact.key in ("rent", "beds", "baths", "sqft"):
            try:
                value_n = float(value.replace(",", "").replace("$", ""))
            except ValueError:
                continue
            if not number_in_quote(value_n, fact.quote) or value_n < 0:
                continue
            attr = "price" if fact.key == "rent" else fact.key
            if attr != "baths" and not value_n.is_integer():
                continue
            setattr(listing, attr, value_n if attr == "baths" else int(value_n))
        elif fact.key == "phone":
            phone = extract_phone(fact.quote)
            if not phone or re.sub(r"\D", "", value)[-10:] != phone[-10:]:
                continue
            listing.contact = listing.contact or Contact()
            listing.contact.phone = phone
        else:
            if not value or value.casefold() not in fact.quote.casefold():
                continue
            if fact.key == "email":
                from househunt.collect import EMAIL_RE
                if not EMAIL_RE.fullmatch(value):
                    continue
                listing.contact = listing.contact or Contact()
                listing.contact.email = value
            else:
                setattr(listing, fact.key, value)
        accepted.append(evidence(fact.key, fact.quote, page))
    matches = []
    for requirement in criteria.must_haves:
        m = next((m for m in rental.requirements if m.requirement == requirement), None)
        matches.append({"requirement": requirement,
                        "matched": m.matched if m and exact_quote(m.quote, page) else None,
                        "quote": m.quote if m and exact_quote(m.quote, page) else ""})
    availability = rental.availability if exact_quote(rental.availability_quote, page) else "unknown"
    listing.research = {"checked_at": timestamp(), "evidence": accepted, "requirements": matches,
        "in_requested_city": rental.in_requested_city, "availability": availability,
        "availability_quote": rental.availability_quote if availability != "unknown" else "",
        "limitations": "Public-page claims; availability and terms still need confirmation by the contact."}
    listing.description = " ".join(dict.fromkeys(f["quote"] for f in accepted))
    if not listing.address or listing.price is None:
        listing.notes.append("Address or monthly rent could not be confirmed from the public page")
    return listing


def read_rentals(pages: list[Page], criteria: SearchCriteria) -> list[Listing]:
    if not pages:
        return []
    result = ask(
        "Extract rentals ONLY from the supplied page text. A specific property/building is allowed; a city search page is not. "
        "For multiple units, choose ONE unit that fits; never mix one unit's rent with another's beds or phone. "
        "Rent is the gross MONTHLY asking rent for the whole unit, never deposit, net-effective concession, per-bedroom price, estimate or sale price. "
        "Return exact contiguous quotes for every fact. Missing fields are omitted. A street address includes apartment/unit when stated. "
        "Phone/email must belong to the property contact, not portal support. No contact guessing. "
        "Check each must-have with true/false/null: absence of a statement is null; 'laundry' doesn't prove in-unit laundry. "
        "Availability unknown unless page explicitly offers it for rent or says no availability. Check city (SF means San Francisco). "
        "Do not infer freshness from today's date. Criteria: " + public_criteria(criteria)
        + "\nPages: " + json.dumps([vars(p) for p in pages]), Rentals)
    by_url = {canonical_url(p.url): p for p in pages}
    listings = []
    for r in result.rentals:
        page = by_url.get(canonical_url(r.url))
        if page:
            listing = parse_rental(r, page, criteria)
            if listing:
                listings.append(listing)
    return listings


def discover(criteria: SearchCriteria, progress=lambda message: None) -> tuple[list[Listing], list[str]]:
    from househunt.config import settings
    from househunt.collect import dedupe
    found, seen, errors = [], set(), []
    # Two bounded rounds; refine only when there are too few grounded matches.
    for round_number in range(2):
        progress(f"Web discovery {round_number + 1}/2: searching portals and property managers")
        links = ask(
            f"Today is {timestamp()[:10]}. Search live public rental listings for " + public_criteria(criteria)
            + ". Find up to 12 specific rental property pages. Prioritize exact criteria, official property managers/leasing pages, "
            "then Zillow, Apartments.com, Realtor, Redfin, Craigslist. Seek source diversity and public contact details. "
            "No general city/search pages, expired listings, vacation stays, rooms/shared housing, sale listings or invented links. "
            "Do not loosen budget/location/must-haves. "
            + ("Try different search terms and direct local property managers. Already examined: " + json.dumps(sorted(seen)) if round_number else ""),
            Links, search=True)
        urls = []
        for link in links.links:
            url = canonical_url(link.url)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        progress(f"Reading {len(urls)} public listing pages; checking quoted rent and requirements")
        with ThreadPoolExecutor(max_workers=4) as pool:
            fetched = list(pool.map(fetch_page, urls))
        pages = [p for p in fetched if p]
        blocked = len(urls) - len(pages)
        if blocked:
            errors.append(f"{blocked} web pages could not be read (blocked, removed or unavailable); no facts inferred")
        for i in range(0, len(pages), 4):
            found = dedupe(found + read_rentals(pages[i:i + 4], criteria))
        usable = [l for l in found if passes_filters(l, criteria)[0] and l.price is not None and l.address]
        if len(usable) >= min(5, settings.search_max_listings):
            break
    from househunt.collect import score
    found.sort(key=lambda l: (passes_filters(l, criteria)[0], score(l, criteria)), reverse=True)
    return found[:settings.search_max_listings], errors


def validate_review(review: Review, pages: list[Page], listing: Listing) -> dict:
    by_url = {canonical_url(p.url): p for p in pages}
    findings = []
    for f in review.findings:
        page = by_url.get(canonical_url(f.url))
        if not f.supports_finding or not page or not exact_quote(f.quote, page):
            continue
        if f.kind == "rent_conflict":
            # A price inside the quoted range or ordinary price drift isn't a fraud flag.
            prices = [float(n.replace(',', '')) for n in re.findall(r'\$\s*(\d[\d,]*(?:\.\d+)?)', f.quote)]
            if not listing.price or not prices:
                continue
            if min(prices) * .85 <= listing.price <= max(prices) * 1.15:
                continue
        if f.kind in ("upfront_payment", "other_concern") and re.search(
                r"do not wire|don't wire|avoid scams|never (?:send|wire|pay)|do not (?:send|pay)|not a (?:flag|concern)|generic (?:platform )?warning", f.quote + ' ' + f.explanation, re.I):
            continue
        if f.kind in ("address_corroborated", "contact_corroborated", "rent_conflict", "contact_conflict", "unavailable") and not f.same_unit:
            continue
        if f.kind.endswith("corroborated") and host(page.url) == host(listing.url):
            continue
        if f.kind == "contact_corroborated":
            contact = listing.contact
            if not contact or not ((contact.phone and extract_phone(f.quote) == contact.phone)
                    or (contact.email and contact.email.casefold() in f.quote.casefold())):
                continue
        findings.append({**f.model_dump(), "url": page.url})
    comps, addresses = [], set()
    for c in review.comparables:
        page = by_url.get(canonical_url(c.url))
        address = re.sub(r"\W", "", c.address.casefold())
        own_address = re.sub(r"\W", "", (listing.address or "").casefold())
        if (not page or not c.same_area or c.beds != listing.beds or not c.neighborhood
                or not address or address == own_address or address in addresses
                or not all(exact_quote(q, page) for q in (c.price_quote, c.beds_quote, c.address_quote))
                or not number_in_quote(c.price, c.price_quote)
                or not number_in_quote(c.beds, c.beds_quote)
                or c.address.casefold() not in c.address_quote.casefold()):
            continue
        comps.append({**c.model_dump(), "url": page.url})
        addresses.add(address)
    market = {"sample_size": len(comps), "median_rent": None, "discount_pct": None,
              "comparables": comps, "note": "Insufficient comparable units; no price conclusion"}
    if len(comps) >= 3 and listing.price:
        mid = median(c["price"] for c in comps)
        discount = round((1 - listing.price / mid) * 100)
        market.update(median_rent=mid, discount_pct=discount,
                      note="Small asking-rent sample, not an appraisal; condition, fees and concessions may differ")
        if discount >= 35:
            findings.append({"kind": "price_outlier", "url": listing.url, "quote": "",
                             "explanation": f"Asking rent is {discount}% below the median of {len(comps)} nearby same-bedroom units. Investigate why; this alone does not establish fraud.", "same_unit": True})
    concerns = [f for f in findings if not f["kind"].endswith("corroborated")]
    kinds = {f["kind"] for f in findings}
    status = "concerns_found" if concerns else ("cross_referenced" if {"address_corroborated", "contact_corroborated"} <= kinds else "unconfirmed")
    return {"status": status, "checked_at": timestamp(), "findings": findings, "market": market,
            "sources": [p.url for p in pages],
            "limitations": "Cross-posts can share the same original claim. This screen does not authenticate ownership, perform reverse-image search or guarantee a fraud-free rental."}


def screen(listing: Listing, criteria: SearchCriteria) -> dict:
    if not listing.address:
        return {"status": "unconfirmed", "checked_at": timestamp(), "findings": [],
                "limitations": "An exact address is needed for a meaningful cross-source check."}
    links = ask(
        "Search independently to screen this rental, not to endorse it. Find the same exact address AND unit on another source, "
        "official manager/owner contact pages, and up to three nearby same-bedroom comparable asking rents WITHOUT a budget cap. "
        "Search the quoted address, then the advertised phone/email with the address, and relevant scam reports if any. "
        "A different leasing agent or phone alone is not proof of fraud. Return up to 7 specific source URLs. "
        "No general advice pages or invented links. Today: " + timestamp()[:10]
        + "\nRental: " + json.dumps({"url": listing.url, "address": listing.address, "city": criteria.city,
            "neighborhood": listing.neighborhood, "beds": listing.beds, "rent": listing.price,
            "phone": listing.contact.phone if listing.contact else None,
            "email": listing.contact.email if listing.contact else None}), Links, search=True)
    urls = list(dict.fromkeys(u for u in [canonical_url(listing.url), *[canonical_url(l.url) for l in links.links]] if u))[:8]
    with ThreadPoolExecutor(max_workers=4) as pool:
        pages = [p for p in pool.map(fetch_page, urls) if p]
    if not pages:
        return {"status": "unconfirmed", "checked_at": timestamp(), "findings": [],
                "limitations": "Cross-search ran, but the returned pages could not be read. No positive verification."}
    result = ask(
        "Compare the target rental to these independent page texts. Quote exact contiguous text for every finding. "
        "Set supports_finding true ONLY if the quote actually establishes the selected kind. Omit non-findings entirely. "
        "A price that matches or falls inside a range is NOT rent_conflict. A generic anti-scam warning is NOT other_concern or upfront_payment. "
        "Distinguish same building from SAME UNIT; a unit mismatch is not a contradiction. Cross-posts are corroboration of advertised facts only, not proof of ownership. "
        "Corroborate a contact only when another property-specific source independently displays that exact phone/email. "
        "Flag meaningful conflicting rent for the same unit; distinguish deposits, concessions, ranges, furnished stays and historic/sold prices. "
        "Flag requests to wire money/pay before seeing the property, remote-owner/key-shipping stories, or explicit unavailability. "
        "Do NOT treat generic scam warnings on a portal as requests by this landlord. Do not accuse anyone of fraud. "
        "Comparables must be distinct currently advertised entire rental units with explicit MONTHLY rent, same bedroom count and nearby neighborhood in the same city; "
        "exclude sale prices, estimates, per-room prices, the target address and duplicates. Fewer than three is okay: insufficient evidence is better than fabrication. "
        "Target: " + json.dumps({"url": listing.url, "address": listing.address, "city": criteria.city,
            "neighborhood": listing.neighborhood, "beds": listing.beds, "price": listing.price,
            "contact": vars(listing.contact) if listing.contact else None})
        + "\nPages: " + json.dumps([vars(p) for p in pages]), Review)
    return validate_review(result, pages, listing)


def auto_call_eligible(listing: Listing) -> bool:
    return listing.screening.get("status") == "cross_referenced"

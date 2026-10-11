"""Normalize, dedupe, filter, and score raw listings from all sources."""

from __future__ import annotations

import re

from househunt.models import Contact, Listing, ListingStatus, SearchCriteria

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"\(?\b([2-9]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})\b")


def extract_phone(text: str) -> str | None:
    m = PHONE_RE.search(text or "")
    return f"+1{m.group(1)}{m.group(2)}{m.group(3)}" if m else None


def normalize(listing: Listing) -> Listing:
    """Fill gaps some sources leave empty (e.g. a phone or email buried in the description)."""
    if not (listing.contact and listing.contact.phone):
        phone = extract_phone(listing.description)
        if phone:
            listing.contact = listing.contact or Contact()
            listing.contact.phone = phone
    if not (listing.contact and listing.contact.email):
        m = EMAIL_RE.search(listing.description or "")
        if m:
            listing.contact = listing.contact or Contact()
            listing.contact.email = m.group(0)
    return listing


def dedupe(listings: list[Listing]) -> list[Listing]:
    """Keep distinct units; a shared leasing-office phone never identifies a property."""
    seen: dict[str, Listing] = {}
    for l in listings:
        if l.address:
            address = re.sub(r"\b(apartment|apt|unit|suite)\b|#", " unit ", l.address.lower())
            address = re.sub(r"\W+", " ", address).strip()
            # Building-only addresses often contain multiple available floorplans.
            k = address if " unit " in f" {address} " else f"{address}:{l.beds}:{l.price}"
        else:
            k = l.key
        if k in seen:
            seen[k].notes.append(f"also listed at {l.url}")
            original = seen[k]
            original.provenance = list(dict.fromkeys([original.url, *original.provenance, l.url, *l.provenance]))
            if not original.research and l.research:
                original.research = l.research
            if original.price != l.price and l.price is not None:
                original.notes.append(f"Cross-post rent differs: ${l.price} at {l.url}; verify the unit and date")
        else:
            seen[k] = l
    return list(seen.values())


def passes_filters(l: Listing, c: SearchCriteria) -> tuple[bool, str | None]:
    if l.research.get("availability") == "unavailable":
        return False, "Public page explicitly says this rental is unavailable"
    if l.research.get("in_requested_city") is False:
        return False, "Outside the requested city"
    for match in l.research.get("requirements", []):
        if match.get("matched") is False and match.get("quote"):
            return False, f"Does not meet {match['requirement']}: {match['quote']}"
    if l.price is not None and not (c.min_price <= l.price <= c.max_price):
        return False, f"price ${l.price} outside ${c.min_price}-${c.max_price}"
    if l.beds is not None and l.beds < c.min_beds:
        return False, f"{l.beds} beds < {c.min_beds}"
    if l.baths is not None and l.baths < c.min_baths:
        return False, f"{l.baths} baths < {c.min_baths}"
    if c.neighborhoods and l.neighborhood:
        if not any(n.lower() in l.neighborhood.lower() for n in c.neighborhoods):
            return False, f"neighborhood {l.neighborhood} not wanted"
    return True, None


def score(l: Listing, c: SearchCriteria) -> float:
    """Rank evidence coverage and fit, without rewarding implausibly cheap rents."""
    s = 0.0
    if l.price is not None and c.min_price <= l.price <= c.max_price:
        s += 0.25
    s += 0.15 if l.beds is not None and l.beds >= c.min_beds else 0
    s += 0.1 if l.baths is not None and l.baths >= c.min_baths else 0
    s += 0.1 if l.address else 0
    if c.must_haves:
        hits = sum(m.get("matched") is True for m in l.research.get("requirements", []))
        s += 0.3 * min(1, hits / len(c.must_haves))
    if l.contact and l.contact.phone:
        s += 0.1  # callable listings are more actionable
    if l.screening.get("status") == "concerns_found":
        s = max(0, s - 0.4)
    return round(min(s, 1.0), 3)


def collect(raw: list[Listing], criteria: SearchCriteria) -> list[Listing]:
    listings = dedupe([normalize(l) for l in raw])
    for l in listings:
        ok, reason = passes_filters(l, criteria)
        if not ok:
            l.status = ListingStatus.FILTERED_OUT
            l.notes.append(reason)
            continue
        l.status = ListingStatus.CANDIDATE
        l.score = score(l, criteria)
    return sorted(listings, key=lambda l: l.score, reverse=True)

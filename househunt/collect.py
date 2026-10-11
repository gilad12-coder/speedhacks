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
    """Drop cross-posted duplicates, keyed on address, else phone+price, else source id."""
    seen: dict[str, Listing] = {}
    for l in listings:
        if l.address:
            k = re.sub(r"\W+", " ", l.address.lower()).strip()
        elif l.contact and l.contact.phone:
            k = f"{l.contact.phone}:{l.price}"
        else:
            k = l.key
        if k in seen:
            seen[k].notes.append(f"also listed at {l.url}")
        else:
            seen[k] = l
    return list(seen.values())


def mentions_neighborhood(l: Listing, neighborhoods: list[str]) -> bool:
    """Sites label locations loosely ("San Francisco, CA"), so look everywhere it might be named."""
    text = " ".join(x for x in [l.neighborhood, l.address, l.title, l.description] if x).lower()
    # "Mission" shouldn't match "1045 Mission St" in SoMa.
    street = r"(?!\s+(?:st|street|ave|avenue|blvd|rd|road|dr|way)\b)"
    return any(re.search(rf"\b{re.escape(n.strip().lower())}\b{street}", text)
               for n in neighborhoods if n.strip())


def passes_filters(l: Listing, c: SearchCriteria) -> tuple[bool, str | None]:
    if l.price is not None and not (c.min_price <= l.price <= c.max_price):
        return False, f"price ${l.price} outside ${c.min_price}-${c.max_price}"
    if l.beds is not None and l.beds < c.min_beds:
        return False, f"{l.beds} beds < {c.min_beds}"
    if l.baths is not None and l.baths < c.min_baths:
        return False, f"{l.baths} baths < {c.min_baths}"
    if c.neighborhoods and not mentions_neighborhood(l, c.neighborhoods):
        return False, f"not in {', '.join(c.neighborhoods)}"
    return True, None


def score(l: Listing, c: SearchCriteria) -> float:
    """Rough 0-1 heuristic. TODO: replace with a Claude ranker over the description + commutes."""
    s = 0.0
    if l.price:
        s += 0.4 * max(0.0, 1 - l.price / c.max_price) + 0.2
    text = f"{l.title} {l.description}".lower()
    if c.must_haves:
        hits = sum(1 for m in c.must_haves if m.lower() in text)
        s += 0.3 * hits / len(c.must_haves)
    if l.contact and l.contact.phone:
        s += 0.1  # callable listings are more actionable
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

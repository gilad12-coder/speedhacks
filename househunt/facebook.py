"""Links that open Facebook and Zillow searches in the renter's own browser.

Meta offers no API for searching Marketplace or groups, and automating a logged-in account
breaks their terms, so we hand the renter pre-filled searches instead. Posts they like come
back in via "Add a listing you found", or via group notification emails in Gmail.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote, urlencode

from househunt.models import SearchCriteria


def links(c: SearchCriteria) -> list[tuple[str, str]]:
    slug = re.sub(r"[^a-z]", "", c.city.lower())
    price = {k: v for k, v in (("minPrice", c.min_price), ("maxPrice", c.max_price)) if v}
    out = [("Marketplace rentals",
            f"https://www.facebook.com/marketplace/{slug}/propertyrentals?{urlencode(price)}")]
    for n in c.neighborhoods[:3]:
        q = urlencode({"query": f"{n} apartment", **price})
        out.append((f"Marketplace: {n}", f"https://www.facebook.com/marketplace/{slug}/search?{q}"))
    for place in [c.city, *c.neighborhoods[:2]]:
        out.append((f"Groups: {place} housing",
                    f"https://www.facebook.com/search/groups/?q={quote(place + ' housing')}"))
    return out


def zillow_links(c: SearchCriteria) -> list[tuple[str, str]]:
    """Pre-filtered Zillow rental searches. Zillow blocks automated access, so the renter
    opens these, clicks "Save search" with instant alerts, and alerts arrive via Gmail."""
    filters = {"fr": {"value": True}, "fsba": {"value": False}, "fsbo": {"value": False},
               "nc": {"value": False}, "cmsn": {"value": False}, "auc": {"value": False},
               "fore": {"value": False}}
    if c.min_price or c.max_price:
        filters["mp"] = {k: v for k, v in (("min", c.min_price), ("max", c.max_price)) if v}
    if c.min_beds:
        filters["beds"] = {"min": c.min_beds}
    if c.min_baths:
        filters["baths"] = {"min": c.min_baths}
    out = []
    for place in [f"{n}, {c.city}" for n in c.neighborhoods[:3]] or [c.city]:
        state = json.dumps({"usersSearchTerm": place, "filterState": filters,
                            "isListVisible": True}, separators=(",", ":"))
        slug = re.sub(r"[^\w]+", "-", place).strip("-")
        out.append((f"Zillow: {place}",
                    f"https://www.zillow.com/homes/for_rent/{slug}_rb/?searchQueryState={quote(state)}"))
    return out

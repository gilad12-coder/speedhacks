"""Structured listing details from arbitrary listing pages via Firecrawl (firecrawl.dev).

Used for links the renter pastes from sites we have no parser for (property managers,
Apartments.com, ...). Deliberately conservative:
- `proxy: "basic"` only. Firecrawl's enhanced/auto proxies exist to get past bot
  protection; sites that block automated access stay blocked for us.
- No `actions` (scripted clicks), so nothing clicks "show contact info"-style buttons.
- Sites that forbid or block automated access are skipped entirely.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from househunt.config import settings

log = logging.getLogger(__name__)

API_URL = "https://api.firecrawl.dev/v2/scrape"

SKIP_DOMAINS = ("zillow.com", "trulia.com", "hotpads.com", "facebook.com", "instagram.com",
                "craigslist.org")  # craigslist: public pages we already parse directly

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "monthly_rent": {"type": "integer", "description": "USD per month; null if not stated"},
        "bedrooms": {"type": "number", "description": "0 for a studio"},
        "bathrooms": {"type": "number"},
        "sqft": {"type": "integer"},
        "address": {"type": "string"},
        "neighborhood": {"type": "string"},
        "available_date": {"type": "string"},
        "summary": {"type": "string", "description": "2-3 sentences: unit, amenities, terms"},
        "contact_name": {"type": "string"},
        "contact_phone": {"type": "string", "description": "only if shown on the page"},
        "contact_email": {"type": "string", "description": "only if shown on the page"},
    },
}

PROMPT = ("Extract the rental listing on this page. Only include contact details that are "
          "visibly published on the page; leave fields empty when not stated.")


def configured() -> bool:
    return bool(settings.firecrawl_api_key)


def supported(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return not any(host == d or host.endswith("." + d) for d in SKIP_DOMAINS)


def extract_listing(url: str) -> dict | None:
    """Return the extracted fields, or None if not configured / unsupported / failed."""
    if not (configured() and supported(url)):
        return None
    try:
        res = httpx.post(
            API_URL,
            headers={"Authorization": f"Bearer {settings.firecrawl_api_key}"},
            json={
                "url": url,
                "formats": [{"type": "json", "schema": SCHEMA, "prompt": PROMPT}],
                "onlyMainContent": True,
                "proxy": "basic",
                "timeout": 60000,
            },
            timeout=90,
        )
        res.raise_for_status()
        return (res.json().get("data") or {}).get("json") or None
    except (httpx.HTTPError, ValueError) as e:
        log.warning("firecrawl failed for %s: %s", url, e)
        return None

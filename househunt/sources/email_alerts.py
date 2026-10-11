"""Listings from saved-search alert emails (Zillow, Redfin, ...) in the connected Gmail.

The renter sets up saved searches with instant alerts on each site; we read the alerts
instead of scraping the sites. Parsing is heuristic: each alert is a block of HTML with a
link to the listing, a price, and usually beds/baths/address nearby.
"""

from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from househunt.models import Listing, SearchCriteria, Source
from househunt.sources.base import ListingSource

log = logging.getLogger(__name__)

# sender domain -> how to recognise a listing link on that site
SITES = {
    "zillow.com": (Source.ZILLOW, re.compile(r"zillow\.com/(homedetails|b|apartments)/|_zpid")),
    "trulia.com": (Source.ZILLOW, re.compile(r"trulia\.com/(p|home|building)/")),
    "hotpads.com": (Source.ZILLOW, re.compile(r"hotpads\.com/.+/(pad|building)")),
    "redfin.com": (Source.REDFIN, re.compile(r"redfin\.com/.+/(home|apartment)/\d+")),
    "apartments.com": (Source.APARTMENTS, re.compile(r"apartments\.com/[\w-]+/\w+/?$")),
    "streeteasy.com": (Source.STREETEASY, re.compile(r"streeteasy\.com/(rental|building)/")),
    # Group-post and Marketplace notification emails; parsed by parse_facebook().
    "facebookmail.com": (Source.FACEBOOK, re.compile(r"facebook\.com/")),
}

FB_LINK = re.compile(r"facebook\.com/(?:groups/[\w.]+/(?:posts|permalink)/(\d+)|marketplace/item/(\d+))")
HOUSING = re.compile(r"\b(rent|rental|room|sublet|sublease|bedroom|\d\s*br|studio|apartment|apt|"
                     r"lease|housing|roommate|flat|in-law|available)\b", re.I)

PRICE = re.compile(r"\$\s?(\d{1,2},?\d{3})(?:\s*(?:/|per\s*)\s*mo)?", re.I)
BEDS = re.compile(r"(\d+)\s*(?:bd|bds|beds?|br)\b", re.I)
BATHS = re.compile(r"(\d+(?:\.\d)?)\s*(?:ba|baths?)\b", re.I)
SQFT = re.compile(r"([\d,]{3,6})\s*(?:sq\.?\s?ft|sqft)", re.I)
ADDRESS = re.compile(r"\d+[\w .#'-]{2,60},\s*[\w .'-]{2,40},\s*[A-Z]{2}(?:\s+\d{5})?")
ZPID = re.compile(r"(\d+)_zpid")


def unwrap(href: str) -> str:
    """Pull the real destination out of a tracking redirect when it's in the query string."""
    q = parse_qs(urlparse(href).query)
    for key in ("url", "u", "target", "redirect", "dest", "destination"):
        for v in q.get(key, []):
            v = unquote(v)
            if v.startswith("http"):
                return v
    return href


def _site_for(sender: str) -> tuple[Source, re.Pattern] | None:
    for domain, site in SITES.items():
        if domain in sender.lower():
            return site
    return None


def _block_text(a) -> str:
    """Text of the smallest ancestor that looks like one listing card (has a price)."""
    node = a
    for _ in range(8):
        node = node.parent
        if node is None:
            break
        text = node.get_text(" ", strip=True)
        if len(text) > 700:
            break
        if PRICE.search(text):
            return text
    return a.get_text(" ", strip=True)


def parse_facebook(html: str) -> list[Listing]:
    """Posts from Facebook group / Marketplace notification emails that look like housing."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Listing] = {}
    for a in soup.find_all("a", href=True):
        url = unwrap(a["href"])
        m = FB_LINK.search(url)
        if not m:
            continue
        post_id = m.group(1) or m.group(2)
        # The smallest ancestor with enough text to be the post itself.
        node, text = a, a.get_text(" ", strip=True)
        for _ in range(6):
            if len(text) >= 60 or node.parent is None:
                break
            parent = node.parent
            # Stop before swallowing a neighbouring post.
            ids = {g for l in parent.find_all("a", href=True)
                   if (fm := FB_LINK.search(unwrap(l["href"]))) for g in fm.groups() if g}
            if ids - {post_id}:
                break
            node, text = parent, parent.get_text(" ", strip=True)
        if len(text) > 1500 or not HOUSING.search(text):
            continue
        listing = found.get(post_id)
        if listing is None or len(text) > len(listing.description):
            price = PRICE.search(text)
            beds = 0 if re.search(r"\bstudio\b", text, re.I) else (
                int(b.group(1)) if (b := BEDS.search(text)) else None)
            found[post_id] = Listing(
                source=Source.FACEBOOK, source_id=post_id, url=url.split("?")[0],
                title=re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0][:90],
                price=int(price.group(1).replace(",", "")) if price else None,
                beds=beds,
                baths=float(b.group(1)) if (b := BATHS.search(text)) else None,
                address=(m2.group(0).strip() if (m2 := ADDRESS.search(text)) else None),
                description=text,
            )
    return list(found.values())


def parse_alert(html: str, sender: str, resolve_redirects: bool = True) -> list[Listing]:
    site = _site_for(sender)
    if not site or not html:
        return []
    if "facebookmail.com" in sender.lower():
        return parse_facebook(html)
    source, link_re = site
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Listing] = {}
    unresolved = 0
    for a in soup.find_all("a", href=True):
        url = unwrap(a["href"])
        text = _block_text(a)
        price = PRICE.search(text)
        if not link_re.search(url):
            # Opaque tracking link: only worth following if it sits on a listing card.
            if not (resolve_redirects and price and unresolved < 15):
                continue
            unresolved += 1
            try:
                url = str(httpx.head(url, follow_redirects=True, timeout=10).url)
            except httpx.HTTPError:
                continue
            if not link_re.search(url):
                continue
        url = url.split("?")[0]
        zpid = ZPID.search(url)
        source_id = zpid.group(1) if zpid else hashlib.sha1(url.encode()).hexdigest()[:12]
        listing = found.get(source_id)
        if listing is None:
            listing = found[source_id] = Listing(source=source, source_id=source_id, url=url,
                                                 title="")
        # Several links point at the same card (photo, title, button); merge what each has.
        if price and listing.price is None:
            listing.price = int(price.group(1).replace(",", ""))
        if listing.beds is None:
            if re.search(r"\bstudio\b", text, re.I):
                listing.beds = 0
            elif m := BEDS.search(text):
                listing.beds = int(m.group(1))
        if listing.baths is None and (m := BATHS.search(text)):
            listing.baths = float(m.group(1))
        if listing.sqft is None and (m := SQFT.search(text)):
            listing.sqft = int(m.group(1).replace(",", ""))
        anchor = a.get_text(" ", strip=True)
        # Prefer a link whose whole text is the address; card text can run numbers together.
        if ADDRESS.fullmatch(anchor):
            listing.address = anchor
        elif listing.address is None and (m := ADDRESS.search(text)):
            listing.address = m.group(0).strip()
        if not listing.title and anchor and not PRICE.fullmatch(anchor) and len(anchor) > 6:
            listing.title = anchor[:120]
    for l in found.values():
        l.title = l.title or l.address or f"{l.source.value} listing"
    # Drop links that never had any listing details next to them (nav, footer, logos).
    return [l for l in found.values() if l.price or l.address]


class GmailAlertsSource(ListingSource):
    name = "gmail_alerts"
    days = 7

    def search(self, criteria: SearchCriteria) -> list[Listing]:
        # Reads the renter's own inbox, so it runs for real even when other sources are mocked.
        return self.fetch(criteria)

    def fetch(self, criteria: SearchCriteria) -> list[Listing]:
        from househunt.connectors import google

        if not google.connection():
            return []
        senders = " OR ".join(SITES)
        listings = []
        for msg in google.search_messages(f"from:({senders}) newer_than:{self.days}d"):
            parsed = parse_alert(msg["html"], msg["from"])
            for l in parsed:
                l.notes.append(f"from alert email: {msg['subject']}")
            log.info("alert %r: %d listings", msg["subject"], len(parsed))
            listings.extend(parsed)
        return listings

    def mock_results(self, criteria: SearchCriteria) -> list[Listing]:
        return []

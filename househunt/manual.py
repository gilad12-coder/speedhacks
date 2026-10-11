"""Listings and contact details the renter adds by hand.

Craigslist hides contact info behind an hCaptcha and Zillow/Facebook block automated
access, so the renter reveals a contact (or finds a listing) themselves and pastes it here;
everything after that (calls, emails, booking) stays automated.
"""

from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urlparse

import httpx

from househunt.collect import EMAIL_RE, normalize, passes_filters, score
from househunt.models import Contact, Listing, ListingStatus, SearchCriteria, Source

log = logging.getLogger(__name__)

# domain -> (source, regex whose group 1 is the site's listing id)
SITES = [
    ("zillow.com", Source.ZILLOW, re.compile(r"(\d+)_zpid")),
    ("trulia.com", Source.ZILLOW, re.compile(r"/(\d+)")),
    ("hotpads.com", Source.ZILLOW, re.compile(r"/([\w-]+)/?$")),
    ("facebook.com", Source.FACEBOOK,
     re.compile(r"/(?:marketplace/item|groups/[\w.]+/(?:posts|permalink))/(\d+)")),
    ("craigslist.org", Source.CRAIGSLIST, re.compile(r"/([\w]+?)(?:\.html)?/?$")),
    ("redfin.com", Source.REDFIN, re.compile(r"/(?:home|apartment)/(\d+)")),
    ("apartments.com", Source.APARTMENTS, re.compile(r"/(\w+)/?$")),
    ("streeteasy.com", Source.STREETEASY, re.compile(r"/(?:rental|building)/([\w-]+)")),
]


class InvalidInput(ValueError):
    pass


def normalize_phone(raw: str) -> str | None:
    """'(415) 555-0199' -> '+14155550199'. Assumes US for 10-digit numbers."""
    raw = (raw or "").strip()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    raise InvalidInput(f"'{raw}' doesn't look like a phone number")


def normalize_email(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if not EMAIL_RE.fullmatch(raw):
        raise InvalidInput(f"'{raw}' doesn't look like an email address")
    return raw


def parse_pasted(text: str) -> tuple[str, str]:
    """Pull a phone and/or email out of whatever the renter copied from the listing."""
    from househunt.collect import extract_phone

    text = text or ""
    email = EMAIL_RE.search(text)
    phone = extract_phone(text) or ""
    if not phone and (m := re.search(r"\+\d[\d\s().-]{7,}", text)):
        phone = m.group(0)
    return phone, email.group(0) if email else ""


def set_contact(listing: Listing, phone: str = "", email: str = "", name: str = "",
                pasted: str = "") -> Listing:
    """Apply what the renter typed or pasted. Blank fields leave existing values alone."""
    if pasted.strip():
        p_phone, p_email = parse_pasted(pasted)
        if not (p_phone or p_email):
            raise InvalidInput("Couldn't find a phone number or email in what you pasted")
        phone, email = phone or p_phone, email or p_email
    phone_n, email_n = normalize_phone(phone), normalize_email(email)
    if not (phone_n or email_n or name.strip()):
        raise InvalidInput("Enter a phone number or email")
    c = listing.contact or Contact()
    c.phone = phone_n or c.phone
    c.email = email_n or c.email
    c.name = name.strip() or c.name
    listing.contact = c
    listing.screening = {}  # Contact changes invalidate the previous identity check.
    return listing


def identify(url: str) -> tuple[Source | None, str]:
    """Which site a listing URL is from, and a stable id for it."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    for domain, source, id_re in SITES:
        if host == domain or host.endswith("." + domain):
            m = id_re.search(parsed.path)
            if m:
                return source, m.group(1)
            break
    return None, hashlib.sha1(url.split("?")[0].encode()).hexdigest()[:12]


def listing_from_url(url: str, criteria: SearchCriteria, *, title: str = "",
                     price: int | None = None, beds: int | None = None,
                     baths: float | None = None, address: str = "", description: str = "",
                     phone: str = "", email: str = "", contact_name: str = "") -> Listing:
    url = (url or "").strip()
    if not re.match(r"https?://[^\s/]+\.[^\s/]+", url):
        raise InvalidInput("Paste the full listing link, starting with https://")
    source, source_id = identify(url)
    listing = Listing(source=source or Source.OTHER, source_id=source_id, url=url,
                      title=title.strip(), price=price, beds=beds, baths=baths,
                      address=address.strip() or None, description=description.strip())

    # Craigslist pages are public; fill in whatever the renter left blank.
    if source == Source.CRAIGSLIST:
        _fill_from_craigslist(listing)
    else:
        _fill_from_firecrawl(listing)

    if phone or email or contact_name:
        set_contact(listing, phone, email, contact_name)
    listing = normalize(listing)
    listing.title = listing.title or listing.address or f"{listing.source.value} listing"
    listing.notes.append("added by you")

    # You picked it, so it stays in play; just flag anything outside your criteria.
    ok, reason = passes_filters(listing, criteria)
    if not ok:
        listing.notes.append(f"outside your search: {reason}")
    listing.status = ListingStatus.CANDIDATE
    listing.score = score(listing, criteria)
    return listing


def _fill_from_craigslist(listing: Listing) -> None:
    """Fill only the fields the renter left blank from the public posting page."""
    from bs4 import BeautifulSoup

    from househunt.sources.craigslist import UA, _money

    try:
        with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=20) as http:
            page = BeautifulSoup(http.get(listing.url).text, "html.parser")
    except httpx.HTTPError:
        log.warning("could not fetch %s; using what was entered", listing.url)
        return
    text = page.get_text(" ")
    if not listing.title and (t := page.select_one("#titletextonly")):
        listing.title = t.get_text(strip=True)
    if listing.price is None and (p := page.select_one(".price")):
        listing.price = _money(p.get_text())
    if listing.beds is None and (m := re.search(r"(\d+)\s*BR\b", text)):
        listing.beds = int(m.group(1))
    if listing.baths is None and (m := re.search(r"(\d+(?:\.\d)?)\s*Ba\b", text)):
        listing.baths = float(m.group(1))
    if listing.sqft is None and (m := re.search(r"(\d{3,5})\s*ft2", text)):
        listing.sqft = int(m.group(1))
    if not listing.address and (a := page.select_one(".mapaddress")):
        listing.address = a.get_text(strip=True)
    if not listing.description and (body := page.find("section", id="postingbody")):
        for junk in body.select(".print-information"):
            junk.decompose()
        listing.description = body.get_text(" ", strip=True)


def _fill_from_firecrawl(listing: Listing) -> None:
    """Fill blanks from Firecrawl's extraction (no-op unless FIRECRAWL_API_KEY is set)."""
    from househunt import firecrawl

    data = firecrawl.extract_listing(listing.url)
    if not data:
        return

    def num(key, cast):
        try:
            return cast(data[key]) if data.get(key) not in (None, "") else None
        except (TypeError, ValueError):
            return None

    listing.title = listing.title or (data.get("title") or "").strip()
    listing.price = listing.price if listing.price is not None else num("monthly_rent", int)
    listing.beds = listing.beds if listing.beds is not None else num("bedrooms", lambda v: int(float(v)))
    listing.baths = listing.baths if listing.baths is not None else num("bathrooms", float)
    listing.sqft = listing.sqft if listing.sqft is not None else num("sqft", int)
    listing.address = listing.address or (data.get("address") or "").strip() or None
    listing.neighborhood = listing.neighborhood or (data.get("neighborhood") or "").strip() or None
    if not listing.description:
        extra = f" Available: {data['available_date']}." if data.get("available_date") else ""
        listing.description = ((data.get("summary") or "") + extra).strip()
    if not (listing.contact and (listing.contact.phone or listing.contact.email)):
        try:
            if data.get("contact_phone") or data.get("contact_email"):
                set_contact(listing, data.get("contact_phone") or "",
                            data.get("contact_email") or "", data.get("contact_name") or "")
        except InvalidInput:
            pass  # extraction returned something that isn't a usable number/email
    tour = (data.get("tour_booking_url") or "").strip()
    if tour.startswith("http"):
        listing.tour_url = tour
    listing.notes.append("details read by Firecrawl")

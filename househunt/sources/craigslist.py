from __future__ import annotations

import json
import re

import httpx
from bs4 import BeautifulSoup

from househunt.models import Listing, SearchCriteria, Source
from househunt.sources.base import ListingSource

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko)"

# city -> (Craigslist site, subarea). A subarea keeps e.g. "San Francisco" from returning
# the whole Bay Area; None searches the full site.
SITE_ALIASES = {
    "san francisco": ("sfbay", "sfc"),
    "sf": ("sfbay", "sfc"),
    "bay area": ("sfbay", None),
    "oakland": ("sfbay", "eby"),
    "berkeley": ("sfbay", "eby"),
    "east bay": ("sfbay", "eby"),
    "san jose": ("sfbay", "sby"),
    "south bay": ("sfbay", "sby"),
    "peninsula": ("sfbay", "pen"),
    "north bay": ("sfbay", "nby"),
    "new york": ("newyork", None),
    "nyc": ("newyork", None),
    "manhattan": ("newyork", "mnh"),
    "brooklyn": ("newyork", "brk"),
    "queens": ("newyork", "que"),
    "los angeles": ("losangeles", None),
    "la": ("losangeles", None),
    "washington": ("washingtondc", None),
    "dc": ("washingtondc", None),
}


def site_for(city: str) -> tuple[str, str | None]:
    c = city.lower().strip()
    return SITE_ALIASES.get(c, (re.sub(r"[^a-z]", "", c), None))


def neighborhood_query(neighborhoods: list[str]) -> str | None:
    """Craigslist full-text OR query, e.g. mission|"noe valley"."""
    terms = [f'"{n}"' if " " in n else n for n in (n.strip().lower() for n in neighborhoods) if n]
    return "|".join(terms) or None


class CraigslistSource(ListingSource):
    """Scrapes the no-JS search page, then each posting for description + address.

    The no-JS page carries both a <ol class="cl-static-search-results"> (title, price,
    url) and a JSON-LD ItemList (beds, baths, lat/lng) in the same order.
    """

    name = "craigslist"
    max_postings = 40

    def fetch(self, criteria: SearchCriteria) -> list[Listing]:
        params = {"max_price": criteria.max_price}
        if criteria.min_price:
            params["min_price"] = criteria.min_price
        if criteria.min_beds:
            params["min_bedrooms"] = criteria.min_beds
        if q := neighborhood_query(criteria.neighborhoods):
            params["query"] = q
        site, subarea = site_for(criteria.city)
        path = f"{subarea}/apa" if subarea else "apa"
        url = f"https://{site}.craigslist.org/search/{path}"
        with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=20) as http:
            soup = BeautifulSoup(http.get(url, params=params).text, "html.parser")
            ld = soup.find("script", id="ld_searchpage_results")
            ld_items = json.loads(ld.string)["itemListElement"] if ld else []
            results = soup.select("li.cl-static-search-result")
            aligned = len(ld_items) == len(results)

            listings = []
            for i, li in enumerate(results[: self.max_postings]):
                a = li.find("a")
                href = a["href"]
                price = li.select_one(".price")
                item = ld_items[i]["item"] if aligned else {}
                listing = Listing(
                    source=Source.CRAIGSLIST,
                    source_id=href.rstrip("/").rsplit("/", 1)[-1],
                    url=href,
                    title=li.get("title") or a.get_text(strip=True),
                    price=_money(price.get_text()) if price else None,
                    beds=item.get("numberOfBedrooms"),
                    baths=item.get("numberOfBathroomsTotal"),
                    lat=_float(item.get("latitude")),
                    lng=_float(item.get("longitude")),
                    neighborhood=(li.select_one(".location").get_text(strip=True)
                                  if li.select_one(".location") else None),
                )
                self._enrich(http, listing)
                listings.append(listing)
        return listings

    def _enrich(self, http: httpx.Client, listing: Listing) -> None:
        try:
            post = BeautifulSoup(http.get(listing.url).text, "html.parser")
        except httpx.HTTPError:
            return
        if post.select_one("a.show-contact"):
            listing.contact_hint = "show_contact"   # phone/email hidden in the description
        elif post.select_one(".reply-button-row, button.reply-button"):
            listing.contact_hint = "reply"
        body = post.find("section", id="postingbody")
        if body:
            for junk in body.select(".print-information"):
                junk.decompose()
            listing.description = body.get_text(" ", strip=True)
        addr = post.select_one(".mapaddress")
        if addr:
            listing.address = addr.get_text(strip=True)
        sqft = re.search(r"(\d{3,5})\s*ft2", post.get_text(" "))
        if sqft:
            listing.sqft = int(sqft.group(1))

    def mock_results(self, criteria: SearchCriteria) -> list[Listing]:
        return [
            Listing(
                source=Source.CRAIGSLIST,
                source_id="cl-7781",
                url="https://craigslist.org/apa/d/cl-7781.html",
                title="1BR + den, laundry in unit, pets welcome",
                price=criteria.max_price - 500,
                beds=max(criteria.min_beds, 1),
                baths=1,
                description="Call or text (555) 555-0199 to see it. Pets welcome. In-unit laundry.",
            ),
        ]


def _money(s: str) -> int | None:
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

import httpx
from bs4 import BeautifulSoup

from househunt.models import Listing, SearchCriteria, Source
from househunt.sources.base import ListingSource

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko)"

# Craigslist subdomains for cities whose name doesn't map directly.
SITE_ALIASES = {
    "san francisco": "sfbay",
    "sf": "sfbay",
    "bay area": "sfbay",
    "oakland": "sfbay",
    "new york": "newyork",
    "nyc": "newyork",
    "los angeles": "losangeles",
    "la": "losangeles",
    "washington": "washingtondc",
    "dc": "washingtondc",
}


def site_for(city: str) -> str:
    c = city.lower().strip()
    return SITE_ALIASES.get(c, re.sub(r"[^a-z]", "", c))


class CraigslistSource(ListingSource):
    """Scrapes the no-JS search page, then each posting for description + address.

    The no-JS page carries both a <ol class="cl-static-search-results"> (title, price,
    url) and a JSON-LD ItemList (beds, baths, lat/lng) in the same order.
    """

    name = "craigslist"
    max_postings = 12

    def fetch(self, criteria: SearchCriteria) -> list[Listing]:
        params = {"max_price": criteria.max_price}
        if criteria.min_price:
            params["min_price"] = criteria.min_price
        if criteria.min_beds:
            params["min_bedrooms"] = criteria.min_beds
        area = "sfc/" if criteria.city.lower().strip() in ("san francisco", "sf") else ""
        url = f"https://{site_for(criteria.city)}.craigslist.org/search/{area}apa"
        with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=20) as http:
            response = http.get(url, params=params)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
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
                listings.append(listing)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda listing: self._enrich(http, listing), listings))
        return listings

    def _enrich(self, http: httpx.Client, listing: Listing) -> None:
        try:
            response = http.get(listing.url)
            response.raise_for_status()
            post = BeautifulSoup(response.text, "html.parser")
        except httpx.HTTPError:
            return
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
        # Ephemeral source text: the research stage extracts quoted facts before storage.
        for junk in post.select('script, style, nav, footer, header, .avoid-scams'):
            junk.decompose()
        listing.research = {"page_text": re.sub(r"\s+", " ", post.get_text(" ", strip=True))[:50000]}

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

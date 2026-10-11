from __future__ import annotations

from househunt.models import Contact, Listing, SearchCriteria, Source
from househunt.sources.base import ListingSource


class ZillowSource(ListingSource):
    name = "zillow"

    def fetch(self, criteria: SearchCriteria) -> list[Listing]:
        # TODO: Zillow blocks naive scraping. Options:
        #   - third-party API (RapidAPI "zillow-com1", Apify actor, Bright Data)
        #   - headless browser (Playwright) against the search page, parse the
        #     embedded __NEXT_DATA__ / searchQueryState JSON
        # Agent phone is on the listing detail page ("Contact agent" block).
        raise NotImplementedError("Zillow fetch not implemented yet")

    def mock_results(self, criteria: SearchCriteria) -> list[Listing]:
        return [
            Listing(
                source=Source.ZILLOW,
                source_id="z-1001",
                url="https://www.zillow.com/homedetails/z-1001",
                title="Sunny 2BR near the park",
                price=criteria.max_price - 200,
                beds=2,
                baths=1,
                sqft=850,
                address=f"123 Main St, {criteria.city}",
                description="In-unit laundry, cats OK, hardwood floors.",
                contact=Contact(name="Jordan Agent", phone="+15555550101"),
            ),
            Listing(
                source=Source.ZILLOW,
                source_id="z-1002",
                url="https://www.zillow.com/homedetails/z-1002",
                title="Luxury 3BR penthouse",
                price=criteria.max_price + 2000,
                beds=3,
                baths=2,
                address=f"9 High St, {criteria.city}",
                contact=Contact(name="Sam Broker", phone="+15555550102"),
            ),
        ]

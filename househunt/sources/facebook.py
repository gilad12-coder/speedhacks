from __future__ import annotations

from househunt.models import Contact, Listing, SearchCriteria, Source
from househunt.sources.base import ListingSource


class FacebookSource(ListingSource):
    name = "facebook"

    def fetch(self, criteria: SearchCriteria) -> list[Listing]:
        # TODO: Marketplace requires a logged-in session. Likely approach:
        #   Playwright with a persisted browser profile ->
        #   https://www.facebook.com/marketplace/{city}/propertyrentals?maxPrice=..
        # Contact is usually Messenger-only, so many FB listings won't have a phone;
        # they can still be surfaced in the report for manual follow-up.
        raise NotImplementedError("Facebook Marketplace fetch not implemented yet")

    def mock_results(self, criteria: SearchCriteria) -> list[Listing]:
        return [
            Listing(
                source=Source.FACEBOOK,
                source_id="fb-42",
                url="https://www.facebook.com/marketplace/item/42",
                title="Room in 3BR, utilities incl.",
                price=criteria.max_price - 900,
                beds=1,
                baths=1,
                description="Message me for details.",
                contact=Contact(name="FB Seller", is_agent=False),
            ),
        ]

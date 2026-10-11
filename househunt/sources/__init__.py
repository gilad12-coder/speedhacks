from househunt.sources.base import ListingSource
from househunt.sources.craigslist import CraigslistSource
from househunt.sources.email_alerts import GmailAlertsSource
from househunt.sources.facebook import FacebookSource
from househunt.sources.zillow import ZillowSource

ALL_SOURCES: list[type[ListingSource]] = [
    ZillowSource, CraigslistSource, FacebookSource, GmailAlertsSource,
]

__all__ = ["ListingSource", "ZillowSource", "CraigslistSource", "FacebookSource", "GmailAlertsSource",
           "ALL_SOURCES"]

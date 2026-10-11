"""Core data types passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum


class Source(str, Enum):
    ZILLOW = "zillow"
    CRAIGSLIST = "craigslist"
    FACEBOOK = "facebook"
    REDFIN = "redfin"
    APARTMENTS = "apartments"
    STREETEASY = "streeteasy"
    OTHER = "other"


class ListingStatus(str, Enum):
    NEW = "new"                  # just sourced
    FILTERED_OUT = "filtered"    # failed hard criteria
    CANDIDATE = "candidate"      # passed filters, worth calling about
    CONTACTED = "contacted"      # call placed
    VIABLE = "viable"            # agent confirmed it's available & fits
    NOT_VIABLE = "not_viable"    # agent said no / unavailable
    TOUR_SCHEDULED = "tour_scheduled"


@dataclass
class SearchCriteria:
    city: str
    max_price: int
    min_price: int = 0
    min_beds: int = 0
    min_baths: float = 0
    neighborhoods: list[str] = field(default_factory=list)
    must_haves: list[str] = field(default_factory=list)   # e.g. "in-unit laundry", "pets"
    move_in_by: str | None = None                          # ISO date
    tour_availability: list[str] = field(default_factory=list)  # e.g. "weekdays after 6pm"
    occupants: int | None = None
    renter_name: str = ""
    deal_breakers: list[str] = field(default_factory=list)
    nice_to_haves: list[str] = field(default_factory=list)
    move_in_from: str | None = None
    commute: dict = field(default_factory=dict)


@dataclass
class Contact:
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    is_agent: bool = True


@dataclass
class Listing:
    source: Source
    source_id: str
    url: str
    title: str
    price: int | None = None
    beds: int | None = None
    baths: float | None = None
    sqft: int | None = None
    address: str | None = None
    neighborhood: str | None = None
    lat: float | None = None
    lng: float | None = None
    # How to reveal a contact the site hides, e.g. "show_contact" / "reply" on Craigslist.
    contact_hint: str | None = None
    tour_url: str | None = None      # the site's own "schedule a tour" page, when it has one
    description: str = ""
    contact: Contact | None = None
    status: ListingStatus = ListingStatus.NEW
    score: float = 0.0
    notes: list[str] = field(default_factory=list)
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())
    provenance: list[str] = field(default_factory=list)
    research: dict = field(default_factory=dict)
    screening: dict = field(default_factory=dict)
    photo_urls: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.source.value}:{self.source_id}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Listing":
        d = dict(d)
        d["source"] = Source(d["source"])
        d["status"] = ListingStatus(d["status"])
        d["contact"] = Contact(**d["contact"]) if d.get("contact") else None
        return cls(**d)


class AppStage(str, Enum):
    """Where an application stands, from first interest to a signed lease."""
    INTERESTED = "interested"
    VIEWING = "viewing"            # viewing booked
    VIEWED = "viewed"
    APPLIED = "applied"
    APPROVED = "approved"
    LEASE_SIGNED = "lease_signed"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"

    @property
    def label(self) -> str:
        return {"viewing": "Viewing booked", "lease_signed": "Lease signed"}.get(
            self.value, self.value.capitalize())

    @property
    def closed(self) -> bool:
        return self in (AppStage.REJECTED, AppStage.WITHDRAWN)

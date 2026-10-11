"""Core data types passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum


class Source(str, Enum):
    ZILLOW = "zillow"
    CRAIGSLIST = "craigslist"
    FACEBOOK = "facebook"


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
    description: str = ""
    contact: Contact | None = None
    status: ListingStatus = ListingStatus.NEW
    score: float = 0.0
    notes: list[str] = field(default_factory=list)
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

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


class CallStatus(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    ENDED = "ended"
    FAILED = "failed"

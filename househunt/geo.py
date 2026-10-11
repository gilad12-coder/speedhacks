"""Put listings on the map: geocode addresses with OpenStreetMap Nominatim, cached in SQLite."""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time

import httpx

from househunt import db
from househunt.config import settings
from househunt.models import Listing, SearchCriteria

log = logging.getLogger(__name__)

NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "KeyHunt/0.1 (rental search assistant)"

# Nominatim's usage policy allows at most 1 request per second.
_lock = threading.Lock()
_last_request = 0.0


def lookup(query: str) -> tuple[float, float] | None:
    """Geocode one query. Misses are cached too, so each query hits the network once."""
    query = " ".join(query.split())
    hit = db.get_geocode(query)
    if hit:
        return (hit["lat"], hit["lng"]) if hit["lat"] is not None else None
    if not settings.geocode:
        return None
    global _last_request
    with _lock:
        time.sleep(max(0.0, 1.0 - (time.monotonic() - _last_request)))
        try:
            r = httpx.get(NOMINATIM, params={"q": query, "format": "json", "limit": 1},
                          headers={"User-Agent": UA}, timeout=10)
            r.raise_for_status()
            results = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("geocode %r failed: %s", query, e)
            return None  # not cached, so a later search retries
        finally:
            _last_request = time.monotonic()
    point = (float(results[0]["lat"]), float(results[0]["lon"])) if results else None
    db.save_geocode(query, *(point or (None, None)))
    return point


def cached(query: str) -> tuple[float, float] | None:
    """Cache-only lookup for page renders, which should never wait on the network."""
    hit = db.get_geocode(" ".join(query.split()))
    return (hit["lat"], hit["lng"]) if hit and hit["lat"] is not None else None


def _jitter(key: str, center: tuple[float, float]) -> tuple[float, float]:
    """A stable spot 0.5-2.5 km from center, so mock listings spread around the city."""
    h = int(hashlib.sha1(key.encode()).hexdigest(), 16)
    angle = (h % 360) * math.pi / 180
    km = 0.5 + (h >> 9) % 2000 / 1000
    lat = center[0] + km / 111 * math.sin(angle)
    lng = center[1] + km / (111 * math.cos(math.radians(center[0]))) * math.cos(angle)
    return lat, lng


def locate(listings: list[Listing], criteria: SearchCriteria) -> None:
    """Fill lat/lng in place. Sources that give coordinates (Craigslist) are left alone."""
    if not settings.geocode:
        return
    center = lookup(criteria.city)
    for l in listings:
        if l.lat is not None and l.lng is not None:
            continue
        if settings.mock_sources:
            # Mock addresses are made up; scatter them around the real city instead.
            point = _jitter(l.key, center) if center else None
        else:
            point = None
            if l.address:
                addr = l.address if criteria.city.lower() in l.address.lower() \
                    else f"{l.address}, {criteria.city}"
                point = lookup(addr)
            if not point and l.neighborhood:
                point = lookup(f"{l.neighborhood.strip('() ')}, {criteria.city}")
        if point:
            l.lat, l.lng = point

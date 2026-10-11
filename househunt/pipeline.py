"""End-to-end flow: source -> collect -> call -> extract -> tour -> notify."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx

from househunt import db, geo
from househunt.collect import collect
from househunt.config import CallMode, settings
from househunt.models import AppStage, Listing, ListingStatus, SearchCriteria
from househunt.outreach.dial import DialClient, FakeDialClient
from househunt.outreach.extract import CallSummary, extract
from househunt.outreach.script import build_instruction
from househunt.sources import ALL_SOURCES

log = logging.getLogger(__name__)

# Free Dial accounts allow 2 concurrent calls.
_call_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dial")


def dial_client():
    # Mock listings carry fake 555 numbers, so never dial for real against them.
    if settings.call_mode == CallMode.DRY_RUN or settings.mock_sources:
        return FakeDialClient()
    return DialClient(settings)


def source_listings(criteria: SearchCriteria) -> tuple[list[Listing], list[str]]:
    raw, errors = [], []
    for cls in ALL_SOURCES:
        src = cls(mock=settings.mock_sources)
        try:
            found = src.search(criteria)
            log.info("%s: %d listings", src.name, len(found))
            raw.extend(found)
        except NotImplementedError:  # no live scraper for this site (see README)
            log.info("%s: skipped, no live source", src.name)
        except (httpx.HTTPError, RuntimeError) as e:
            errors.append(f"{src.name}: {e}")
    return raw, errors


def calendar_availability() -> list[str]:
    """Free slots from the connected Google Calendar, or [] if not connected."""
    from househunt.connectors import google

    if not google.connection():
        return []
    try:
        return google.free_windows()
    except Exception:
        log.exception("could not read calendar availability")
        return []


def run_search(search_id: int) -> None:
    criteria, _ = db.get_search(search_id)
    try:
        db.set_search_status(search_id, "sourcing")
        raw, errors = source_listings(criteria)
        listings = collect(raw, criteria)
        try:
            geo.locate(listings, criteria)
        except Exception:  # the map is a nice-to-have; never fail the search over it
            log.exception("geocoding failed")
        listings = merge_with_existing(search_id, listings, criteria)
        for l in listings:
            db.upsert_listing(search_id, l)

        callable_ = [l for l in listings
                     if l.status == ListingStatus.CANDIDATE and l.contact and l.contact.phone]
        if settings.call_mode in (CallMode.AUTO, CallMode.DRY_RUN):
            db.set_search_status(search_id, "calling")
            futures = [_call_pool.submit(call_listing, search_id, l.key)
                       for l in callable_[: settings.max_auto_calls]]
            for f in futures:
                f.result()

        db.set_search_status(search_id, "done", "; ".join(errors) or None)
        notify_summary(search_id)
    except Exception as e:  # surface in the UI rather than dying silently in a worker
        log.exception("search %s failed", search_id)
        db.set_search_status(search_id, "error", repr(e))


# Notes collect.passes_filters() writes; dropped and recomputed when criteria change.
FILTER_NOTE = re.compile(r"^(price \$|not in |neighborhood |outside your search|[\d.]+ (beds|baths) <)")

# Statuses that mean the renter or agent has acted; a re-run never resets these.
PROGRESSED = {ListingStatus.CONTACTED, ListingStatus.VIABLE, ListingStatus.NOT_VIABLE,
              ListingStatus.TOUR_SCHEDULED}


def merge_with_existing(search_id: int, fresh: list[Listing],
                        criteria: SearchCriteria) -> list[Listing]:
    """Re-running a (possibly edited) search keeps everything already learned about a place.

    Fresh scrape data fills gaps, but contacts, notes and progressed statuses survive.
    Listings from earlier runs that aren't in this run are re-checked against the criteria.
    """
    from househunt.collect import passes_filters, score

    old = {l.key: l for l in db.list_listings(search_id)}
    interested = set(db.applications_for_search(search_id))
    out = []
    for l in fresh:
        prev = old.pop(l.key, None)
        if prev:
            if prev.contact and (prev.contact.phone or prev.contact.email):
                l.contact = prev.contact
            kept = [n for n in prev.notes if not FILTER_NOTE.match(n)]
            l.notes = kept + [n for n in l.notes if n not in kept]
            for attr in ("lat", "lng", "contact_hint", "tour_url"):
                if getattr(l, attr, None) is None:
                    setattr(l, attr, getattr(prev, attr, None))
            if prev.status in PROGRESSED or (l.key in interested and l.status == ListingStatus.FILTERED_OUT):
                l.status = prev.status
        out.append(l)
    for prev in old.values():  # not found this time: re-judge unless already in progress
        if prev.status not in PROGRESSED and prev.key not in interested \
                and "added by you" not in prev.notes:
            ok, reason = passes_filters(prev, criteria)
            prev.status = ListingStatus.CANDIDATE if ok else ListingStatus.FILTERED_OUT
            prev.notes = [n for n in prev.notes if not FILTER_NOTE.match(n)]
            if ok:
                prev.score = score(prev, criteria)
            else:
                prev.notes.append(reason)
        out.append(prev)
    return out


def call_listing(search_id: int, key: str) -> None:
    criteria, _ = db.get_search(search_id)
    listing = db.get_listing(search_id, key)
    if not (listing and listing.contact and listing.contact.phone):
        return
    call_id = db.create_call(search_id, key)
    try:
        dial = dial_client()
        if not criteria.tour_availability:
            criteria.tour_availability = calendar_availability()
        instruction = build_instruction(listing, criteria, settings.renter_name,
                                        db.place_notes(search_id, key))
        placed = dial.place_call(listing.contact.phone, instruction, max_seconds=300,
                                 idempotency_key=f"search{search_id}-{key}-{call_id}")
        db.update_call(call_id, dial_call_id=placed.id, status="in_progress")
        listing.status = ListingStatus.CONTACTED
        db.upsert_listing(search_id, listing)

        ended = dial.wait_for_call(placed.id)
        if not ended.transcript:
            db.update_call(call_id, status="failed", error=f"no transcript ({ended.label})")
            return
        summary = extract(ended.transcript, listing, criteria, call_date=datetime.now())
        db.update_call(call_id, status="ended", transcript=ended.transcript,
                       outcome=summary.model_dump())
        apply_outcome(search_id, listing, summary)
    except Exception as e:
        log.exception("call for %s failed", key)
        db.update_call(call_id, status="failed", error=repr(e))


def apply_outcome(search_id: int, listing: Listing, s: CallSummary) -> None:
    listing.notes.append(s.summary)
    listing.status = ListingStatus.VIABLE if s.viable else ListingStatus.NOT_VIABLE
    if s.viable and s.tour_booked and s.tour_start:
        try:
            datetime.fromisoformat(s.tour_start)
            db.create_tour(search_id, listing.key, s.tour_start, listing.address,
                           listing.contact.name if listing.contact else None,
                           listing.contact.phone if listing.contact else None)
            listing.status = ListingStatus.TOUR_SCHEDULED
            track_viewing(search_id, listing, s.tour_start)
            add_to_calendar(listing, s)
        except ValueError:
            listing.notes.append(f"tour time unparseable: {s.tour_start}")
    db.upsert_listing(search_id, listing)


def track_viewing(search_id: int, listing: Listing, start: str) -> None:
    """A booked viewing goes straight onto the applications board."""
    existing = db.find_application(search_id, listing.key)
    if existing:
        if existing["stage"] == AppStage.INTERESTED.value:
            db.update_application(existing["id"], stage=AppStage.VIEWING.value,
                                  next_step="Viewing", next_date=start)
        return
    db.create_application(search_id=search_id, listing_key=listing.key, title=listing.title,
                          url=listing.url, address=listing.address, price=listing.price,
                          stage=AppStage.VIEWING.value, next_step="Viewing", next_date=start)


def add_to_calendar(listing: Listing, s: CallSummary) -> None:
    from househunt.connectors import google

    if not google.connection():
        return
    contact = listing.contact
    desc = "\n".join(x for x in [
        s.summary,
        f"Contact: {contact.name or ''} {contact.phone or ''}".strip() if contact else None,
        listing.url,
    ] if x)
    try:
        link = google.add_event(s.tour_start, f"Viewing: {listing.title}", listing.address, desc)
        listing.notes.append(f"added to Google Calendar: {link}")
    except Exception:
        log.exception("could not add viewing to calendar")
        listing.notes.append("could not add viewing to Google Calendar")


def notify_summary(search_id: int) -> None:
    """Text the renter the viable listings (no-op without NOTIFY_NUMBER)."""
    if not settings.notify_number:
        return
    listings = db.list_listings(search_id)
    tours = db.tours_for_search(search_id)
    good = [l for l in listings if l.status in (ListingStatus.VIABLE, ListingStatus.TOUR_SCHEDULED)]
    if not good:
        return
    lines = [f"KeyHunt: {len(good)} viable listing(s)"]
    for l in good[:5]:
        tour = tours.get(l.key)
        when = f" - viewing {tour['start']}" if tour else ""
        lines.append(f"- ${l.price} {l.title[:60]}{when}\n  {l.url}")
    try:
        dial_client().send_message(settings.notify_number, "\n".join(lines))
    except Exception:
        log.exception("notify failed")

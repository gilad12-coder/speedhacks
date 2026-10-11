"""End-to-end flow: source -> collect -> call -> extract -> tour -> notify."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx

from househunt import db
from househunt.collect import collect
from househunt.config import CallMode, settings
from househunt.models import Listing, ListingStatus, SearchCriteria
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
        except NotImplementedError:
            errors.append(f"{src.name}: not implemented yet (skipped)")
        except httpx.HTTPError as e:
            errors.append(f"{src.name}: {e}")
    return raw, errors


def run_search(search_id: int) -> None:
    criteria, _ = db.get_search(search_id)
    try:
        db.set_search_status(search_id, "sourcing")
        raw, errors = source_listings(criteria)
        listings = collect(raw, criteria)
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


def call_listing(search_id: int, key: str) -> None:
    criteria, _ = db.get_search(search_id)
    listing = db.get_listing(search_id, key)
    if not (listing and listing.contact and listing.contact.phone):
        return
    call_id = db.create_call(search_id, key)
    try:
        dial = dial_client()
        instruction = build_instruction(listing, criteria, settings.renter_name)
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
        except ValueError:
            listing.notes.append(f"tour time unparseable: {s.tour_start}")
    db.upsert_listing(search_id, listing)


def notify_summary(search_id: int) -> None:
    """Text the renter the viable listings (no-op without NOTIFY_NUMBER)."""
    if not settings.notify_number:
        return
    listings = db.list_listings(search_id)
    tours = db.tours_for_search(search_id)
    good = [l for l in listings if l.status in (ListingStatus.VIABLE, ListingStatus.TOUR_SCHEDULED)]
    if not good:
        return
    lines = [f"househunt: {len(good)} viable listing(s)"]
    for l in good[:5]:
        tour = tours.get(l.key)
        when = f" - viewing {tour['start']}" if tour else ""
        lines.append(f"- ${l.price} {l.title[:60]}{when}\n  {l.url}")
    try:
        dial_client().send_message(settings.notify_number, "\n".join(lines))
    except Exception:
        log.exception("notify failed")

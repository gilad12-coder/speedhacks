"""End-to-end flow: source -> collect -> call -> extract -> tour -> notify."""

from __future__ import annotations

import logging
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dataclasses import asdict, replace

import httpx

from househunt import db, geo
from househunt.collect import collect, score
from househunt.config import CallMode, settings
from househunt.models import AppStage, Listing, ListingStatus, SearchCriteria
from househunt.outreach.dial import DialClient, FakeDialClient, _parse_call
from househunt.outreach.extract import CallSummary, extract, has_credentials
from househunt.outreach.script import build_instruction
from househunt.sources import ALL_SOURCES

log = logging.getLogger(__name__)

# One call at a time in the single-worker deployment.
_call_lock = threading.Lock()
_call_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dial")


def dial_client():
    # Mock listings carry fake 555 numbers, so never dial for real against them.
    if settings.call_mode == CallMode.DRY_RUN or settings.mock_sources:
        return FakeDialClient()
    return DialClient(settings)


def source_listings(criteria: SearchCriteria, progress=lambda message: None) -> tuple[list[Listing], list[str]]:
    raw, errors = [], []

    def read_source(cls):
        src = cls(mock=settings.mock_sources)
        try:
            found = src.search(criteria)
            if not settings.mock_sources and settings.web_research and src.name == "craigslist":
                from househunt.research.engine import read_rentals
                from househunt.research.web import Page
                pages = [Page(l.url, l.title, l.research["page_text"], images=l.photo_urls) for l in found if l.research.get("page_text")]
                progress(f"Checking city, unit, rent and requirements on {len(pages)} Craigslist pages")
                originals = {l.url:l for l in found}
                found = [l for i in range(0, len(pages), 4) for l in read_rentals(pages[i:i+4], criteria)]
                for listing in found:
                    if original := originals.get(listing.url):
                        listing.contact_hint = original.contact_hint
                        listing.lat, listing.lng = original.lat, original.lng
            for listing in found:
                listing.research.pop("page_text", None)
            progress(f"{src.name}: found {len(found)} listings")
            return found, []
        except NotImplementedError:
            return [], []  # Web discovery covers public portal pages when readable.
        except (httpx.HTTPError, RuntimeError):
            return [], [f"{src.name}: source unavailable; other sources still searched"]

    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = [pool.submit(read_source, cls) for cls in ALL_SOURCES]
        if not settings.mock_sources and settings.web_research:
            from househunt.research.engine import discover
            jobs.append(pool.submit(discover, criteria, progress))
        for job in jobs:
            try:
                found, warnings = job.result()
                raw.extend(found)
                errors.extend(warnings)
            except RuntimeError as e:
                errors.append(str(e))
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


_running_lock = threading.Lock()
_running_searches: set[int] = set()


def run_search(search_id: int, on_update=lambda: None) -> None:
    """Run a search; a second request for a search that's already running is a no-op."""
    with _running_lock:
        if search_id in _running_searches:
            return
        _running_searches.add(search_id)
    try:
        _run_search(search_id, on_update)
    finally:
        with _running_lock:
            _running_searches.discard(search_id)


def _run_search(search_id: int, on_update=lambda: None) -> None:
    criteria, _ = db.get_search(search_id)
    def publish():
        try:
            on_update()
        except Exception:
            log.warning('Search %s publication delayed; local evidence is saved',search_id)
    try:
        db.set_search_status(search_id, "sourcing")
        raw, errors = source_listings(criteria, lambda message: db.search_event(search_id, message))
        listings = collect(raw, criteria)
        try:
            geo.locate(listings, criteria)
        except Exception:  # the map is a nice-to-have; never fail the search over it
            log.exception("geocoding failed")
        listings = merge_with_existing(search_id, listings, criteria)
        for l in listings:
            db.upsert_listing(search_id, l)
        publish()

        if not settings.mock_sources and settings.web_research:
            db.set_search_status(search_id, "screening")
            candidates = [l for l in listings if l.status == ListingStatus.CANDIDATE][:settings.screen_top_n]
            db.search_event(search_id, f"Cross-checking {len(candidates)} top candidates: address, contact, conflicting terms and comparable rents")
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda l: screen_listing(search_id, l.key), candidates))
            listings = db.list_listings(search_id)
            publish()

        callable_ = [l for l in listings
                     if l.status == ListingStatus.CANDIDATE and l.contact and l.contact.phone]
        if settings.call_mode == CallMode.AUTO and not settings.mock_sources:
            from househunt.outreach.scheduler import enqueue
            candidates = [l for l in listings if l.status == ListingStatus.CANDIDATE]
            for listing in candidates[:settings.max_auto_calls]:
                enqueue(search_id, listing.key)
                publish()
            if len(candidates) > settings.max_auto_calls:
                db.search_event(search_id, f'Automatic call limit: {settings.max_auto_calls}. Additional listings need a manual call request.')
        elif settings.call_mode in (CallMode.AUTO, CallMode.DRY_RUN):
            db.set_search_status(search_id, "calling")
            futures = [_call_pool.submit(call_listing, search_id, l.key)
                       for l in callable_[: settings.max_auto_calls]]
            for f in futures:
                f.result()
                publish()

        db.set_search_status(search_id, "done", "; ".join(errors) or None)
        db.search_event(search_id, f"Search complete: {len(listings)} listings. Unconfirmed facts and risk flags require review.")
        publish()
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
            for attr in ("lat", "lng", "contact_hint", "tour_url", "screening"):
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


_screen_lock = threading.Lock()
_screen_running: set[tuple[int, str]] = set()


def screen_listing(search_id: int, key: str) -> None:
    from househunt.research.engine import screen, timestamp
    with _screen_lock:
        if (search_id, key) in _screen_running:
            return
        _screen_running.add((search_id, key))
    try:
        listing = db.get_listing(search_id, key)
        found = db.get_search(search_id)
        if not listing or not found:
            return
        fingerprint = (listing.address, listing.price, repr(listing.contact))
        listing.screening = {"status": "checking"}
        db.upsert_listing(search_id, listing)
        try:
            result = screen(listing, found[0])
        except Exception:
            result = {"status": "error", "checked_at": timestamp(), "findings": [],
                      "limitations": "Cross-source research could not complete. Retry; this listing is not cleared for automatic calls."}
        current = db.get_listing(search_id, key)
        if current and (current.address, current.price, repr(current.contact)) == fingerprint:
            current.screening = result
            current.score = score(current, found[0])
            db.upsert_listing(search_id, current)
            db.search_event(search_id, f"{current.title[:90]}: {result['status'].replace('_', ' ')}")
    finally:
        with _screen_lock:
            _screen_running.discard((search_id, key))


def call_listing(search_id: int, key: str) -> None:
    with _call_lock:
        _call_listing(search_id, key)


def request_call(search_id: int, key: str) -> None:
    """All UI requests use the same durable office-hours queue as autonomous searches."""
    if settings.call_mode == CallMode.DRY_RUN or settings.mock_sources:
        return call_listing(search_id, key)
    existing = db.calls_for_search(search_id).get(key)
    if existing and existing['status'] in ('attention', 'failed') and existing['dial_call_id']:
        if existing['direction'] == 'inbound':
            from househunt.outreach.callbacks import process
            process(json.loads(existing['raw']))
            return
        return call_listing(search_id, key)  # Processing saved evidence never makes a new call.
    from househunt.outreach.scheduler import enqueue, run_due
    enqueue(search_id, key)
    run_due(search_id, key)


def _call_listing(search_id: int, key: str, follow_up_after: int | None = None) -> None:
    found = db.get_search(search_id)
    listing = db.get_listing(search_id, key)
    if not found or not listing or not listing.contact or not listing.contact.phone:
        return
    if listing.status == ListingStatus.FILTERED_OUT:
        return
    criteria, _ = found
    dry_run = settings.call_mode == CallMode.DRY_RUN or settings.mock_sources
    row = db.claim_call(search_id, key, listing.contact.phone, "dry_run" if dry_run else "live", follow_up_after)
    if row is None:
        return
    call_id = row["id"]
    if row['search_context']:
        snapshot = json.loads(row['search_context'])
        listing = Listing.from_dict(snapshot['listing'])
        criteria = SearchCriteria(**snapshot['criteria'])
    booking_context = json.loads(row["booking_context"]) if row["booking_context"] else {"enabled": False, "windows": []}
    try:
        if not dry_run and not has_credentials():
            raise RuntimeError("Set OPENAI_API_KEY or ANTHROPIC_API_KEY before live calls")
        dial = dial_client()
        # Saved terminal transcripts can be re-extracted without a new call or poll.
        saved = _parse_call(json.loads(row["raw"])) if row["raw"] else None
        if saved and saved.ended and saved.raw.get("transcriptTurns"):
            ended = saved
        else:
            provider_id = row["dial_call_id"]
            if not provider_id:
                voice_profile = None
                if not dry_run:
                    from househunt.voice import store as voice_store
                    if voice_store.enabled():
                        voice_profile = voice_store.preflight(search_id)
                    phone = listing.contact.phone
                    if not re.fullmatch(r"\+1[2-9]\d{9}", phone) or re.fullmatch(r"\+1\d{3}55501\d{2}", phone):
                        raise RuntimeError("A real US E.164 contact number is required")
                    from househunt.outreach.scheduler import permitted
                    if not permitted(listing, settings):
                        raise RuntimeError("Contact is not approved or independently corroborated for automatic calling")
                    if db.contact_blocked(phone):
                        raise RuntimeError("Contact requested no further calls")
                    if db.contact_called_today(phone, call_id):
                        raise RuntimeError("Daily call limit reached for this contact")
                from househunt.outreach import booking
                # A retry with a saved provider call never changes its original authorization.
                if not row["instruction"]:
                    booking_context = booking.prepare(search_id, key, criteria) if not dry_run else {"enabled": False, "windows": []}
                    if not dry_run and settings.callback_enabled:
                        from househunt import phone as callback_phone
                        callback_phone.ensure_callbacks()
                call_criteria = replace(criteria, renter_name=voice_profile["speaker_name"]) if voice_profile else criteria
                instruction = row["instruction"] or build_instruction(listing, call_criteria, call_criteria.renter_name,
                    db.place_notes(search_id,key), booking_context=booking_context)
                db.update_call(call_id, instruction=instruction, booking_context=booking_context,
                    search_context={'criteria': asdict(call_criteria), 'listing': listing.to_dict()})
                placed = dial.place_call(listing.contact.phone, instruction,
                    max_seconds=settings.call_max_seconds, idempotency_key=row["attempt_key"])
                provider_id = placed.id
                db.update_call(call_id, dial_call_id=provider_id, raw=placed.raw)
                listing.status = ListingStatus.CONTACTED
                db.upsert_listing(search_id, listing)
            ended = dial.wait_for_call(provider_id)
        transcript = ended.transcript or "\n".join(f'{t.get("speaker", "unknown")}: {t.get("text", "")}' for t in ended.raw.get("transcriptTurns") or [])
        # Save evidence BEFORE model work, so extraction failures never lose the call.
        ended.raw["booking_context"] = booking_context
        ended.raw.setdefault('callback_number', db.get_state('phone_number') or settings.dial_from_number)
        db.update_call(call_id, raw=ended.raw, transcript=transcript, status="extracting")
        contact_text = " ".join(t.get("text", "") for t in ended.raw.get("transcriptTurns") or [] if t.get("speaker") in ("user", "contact"))
        if re.search(r"\b(do not|don't|stop) call(ing)?|remove (me|my number)|never call", contact_text, re.I):
            db.block_contact(listing.contact.phone)
        if not transcript:
            if re.search(r'no.?answer|busy|unanswered', ended.label + ' ' + str(ended.termination), re.I):
                from househunt.outreach.extract import unanswered
                summary = unanswered('No answer; listing details remain unconfirmed.')
                db.update_call(call_id, status='ended', outcome=summary.model_dump(), error=None)
                return
            raise RuntimeError(f"No transcript available ({ended.label}); inspect the saved call")
        started_at = datetime.fromisoformat(ended.raw["createdAt"]) if ended.raw.get("createdAt") else datetime.fromisoformat(row["created_at"])
        summary = extract(transcript, listing, criteria, call_date=started_at, raw=ended.raw, dry_run=dry_run)
        if summary.do_not_call:
            db.block_contact(listing.contact.phone)
        from househunt.outreach.recording import recording_path
        recording = recording_path(call_id)
        if recording and recording.is_file():
            summary.audio_url = f"/calls/{call_id}/recording"
        db.update_call(call_id, status="ended", outcome=summary.model_dump(), error=None)
        apply_outcome(search_id, listing, summary, call_id=call_id)
    except Exception as e:
        # Provider bodies, credentials and arbitrary model outputs never enter UI errors.
        message = str(e) if isinstance(e, RuntimeError) else f"Call processing failed ({type(e).__name__}); saved evidence can be retried"
        log.warning("Call %s needs attention (%s)", call_id, type(e).__name__)
        db.update_call(call_id, status="attention", error=message)


def apply_outcome(search_id: int, listing: Listing, s: CallSummary, call_id: int | None = None) -> None:
    # Don't overwrite edits made to the listing while the call was in flight.
    listing = db.get_listing(search_id, listing.key) or listing
    if s.summary not in listing.notes:
        listing.notes.append(s.summary)
    listing.status = (ListingStatus.VIABLE if s.viable else
                      ListingStatus.NOT_VIABLE if s.verification_status == "ruled_out" else ListingStatus.CONTACTED)
    if call_id is not None:
        from househunt.outreach import booking
        tour_id = booking.record(search_id, listing, s, call_id)
        if tour_id is not None:
            listing.status = ListingStatus.TOUR_SCHEDULED
            track_viewing(search_id, listing, s.tour_start)
            booking.sync_local_calendar(tour_id, listing, s)
    if db.tours_for_search(search_id).get(listing.key):
        listing.status = ListingStatus.TOUR_SCHEDULED
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

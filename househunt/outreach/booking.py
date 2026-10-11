"""Pre-call calendar authorization and idempotent persistence of confirmed tours."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from househunt import db


def prepare(search_id: int, listing_key: str, criteria) -> dict:
    from househunt.config import settings
    from househunt.connectors import google
    result = {"enabled": False, "windows": [], "checked_at": datetime.now(timezone.utc).isoformat(), "reason": "Calendar availability is not connected"}
    if db.tours_for_search(search_id).get(listing_key):
        return {**result, "reason": "A viewing is already recorded for this listing; do not book another"}
    listing = db.get_listing(search_id, listing_key)
    if listing and listing.screening.get("status") == "concerns_found":
        return {**result, "reason": "Cross-source research found unresolved concerns; clarify them and collect offers only"}
    with db.conn() as conn:
        job = conn.execute("SELECT household_id FROM household_jobs WHERE search_id=?", (search_id,)).fetchone()
    try:
        if job:
            from househunt.platform import PlatformClient
            client = PlatformClient()
            try:
                from urllib.parse import quote
                response = client.http.get(f"/api/agent/availability/{quote(job['household_id'], safe='')}", params={"timezone": settings.call_timezone})
                if not response.is_success:
                    return {**result, "reason": "Household calendars could not be checked; collect offers only"}
                result.update(response.json())
            finally:
                client.http.close()
        elif google.connection():
            result.update(enabled=True, windows=google.free_intervals(), source="primary_calendar", reason="Primary calendar checked")
        if criteria.tour_availability:
            # Free text is useful for questions but cannot authorize a calendar commitment.
            result.update(enabled=False, windows=[], reason="Renter's written viewing preferences need confirmation; collect offers only")
        now = datetime.now(timezone.utc)
        windows = []
        reserved = db.tours_for_search(search_id).values()
        for window in result.get("windows", []):
            start, end = datetime.fromisoformat(window["start"]), datetime.fromisoformat(window["end"])
            if start.utcoffset() is None or end.utcoffset() is None or not now < start < end:
                continue
            fragments = [(start, end)]
            for tour in reserved:
                ts = datetime.fromisoformat(tour["start"])
                te = datetime.fromisoformat(tour["end"]) if tour["end"] else ts.replace(tzinfo=ts.tzinfo)
                if ts.tzinfo is None:
                    from zoneinfo import ZoneInfo
                    ts = ts.replace(tzinfo=ZoneInfo(settings.call_timezone)); te = te.replace(tzinfo=ts.tzinfo)
                if te <= ts:
                    from datetime import timedelta
                    te = ts + timedelta(minutes=60)
                fragments = [(a,b) for lo,hi in fragments for a,b in ((lo,min(hi,ts)),(max(lo,te),hi)) if a < b] if start < te and ts < end else fragments
            windows.extend({"start": lo.isoformat(), "end": hi.isoformat()} for lo,hi in fragments if (hi-lo).total_seconds() >= 1800)
        result["windows"] = windows
        result["enabled"] = result.get("enabled") is True and bool(windows)
    except Exception:
        result.update(enabled=False, windows=[], reason="Calendar availability could not be verified; collect offers only")
    return result


def record(search_id: int, listing, summary, call_id: int) -> int | None:
    if summary.mode != "live" or summary.listing_verified is not True or not summary.tour_booked or not summary.confirmed_tour:
        return None
    booked = summary.confirmed_tour
    contact = listing.contact
    return db.create_tour(search_id, listing.key, booked["start"], booked["meeting_address"],
        contact.name if contact else None, contact.phone if contact else None, end=booked["end"], source_call_id=call_id)


def sync_local_calendar(tour_id: int, listing, summary) -> None:
    from househunt.connectors import google
    tour = db.get_tour(tour_id)
    if tour["calendar_status"] == "synced":
        return
    with db.conn() as conn:
        household = conn.execute("SELECT 1 FROM household_jobs WHERE search_id=?", (tour["search_id"],)).fetchone()
    if household:
        return  # Shared household API adds this booking to every housemate's calendar.
    try:
        if not google.connection():
            db.update_tour_calendar(tour_id, "not_connected", "Tour booked; add the downloaded invite to your calendar")
            return
        link = google.add_confirmed_event(str(tour["source_call_id"]), tour["start"], tour["end"],
            f"Viewing: {listing.title}", tour["address"], summary.summary + "\n" + listing.url)
        db.update_tour_calendar(tour_id, "synced", None, link)
    except Exception:
        db.update_tour_calendar(tour_id, "pending", "Tour is booked; calendar sync needs attention. Retrying will not redial or create another booking.")


def retry_sync(tour_id: int) -> None:
    """Retry only the calendar handoff; never rerun extraction or call a contact."""
    from househunt.outreach.extract import CallSummary
    tour = db.get_tour(tour_id)
    if not tour or tour["source_call_id"] is None:
        raise RuntimeError("No call-confirmed tour to sync")
    with db.conn() as conn:
        job = conn.execute("SELECT household_id FROM household_jobs WHERE search_id=?", (tour["search_id"],)).fetchone()
        call = conn.execute("SELECT outcome FROM calls WHERE id=?", (tour["source_call_id"],)).fetchone()
    if job:
        from househunt.platform import PlatformClient
        client = PlatformClient()
        try:
            client.publish(job["household_id"], tour["search_id"])
        finally:
            client.http.close()
    elif call and call["outcome"]:
        sync_local_calendar(tour_id, db.get_listing(tour["search_id"], tour["listing_key"]), CallSummary.model_validate_json(call["outcome"]))

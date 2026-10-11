"""Private JSON API the household dashboard (Next.js) uses to show and work a search.

Every route is under /agent/households/{household_id}/..., so `require_auth` in app.py
requires the shared AGENT_API_KEY. The Next.js server checks the housemate belongs to the
household before calling; browsers never talk to this API directly.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from househunt import db, pipeline
from househunt.config import settings
from househunt.models import AppStage, Listing, ListingStatus
from househunt.next_step import gcal_link, recommend

log = logging.getLogger(__name__)
router = APIRouter(prefix="/agent/households/{household_id}")


def _search(household_id: str) -> tuple[int, object, object]:
    search_id = db.household_search(household_id)
    if search_id is None:
        raise HTTPException(404, "This household's search hasn't started yet")
    criteria, row = db.get_search(search_id)
    return search_id, criteria, row


def _listing(search_id: int, key: str) -> Listing:
    listing = db.get_listing(search_id, key)
    if not listing:
        raise HTTPException(404, "Listing not found")
    return listing


def _card(listing: Listing, call, email, tour, app) -> dict:
    outcome = json.loads(call["outcome"]) if call and call["outcome"] else None
    ns = recommend(listing, call, email, tour) if app else None
    c = listing.contact
    return {
        "id": listing.key,
        "title": listing.title,
        "url": listing.url,
        "source": listing.source.value,
        "price": listing.price,
        "beds": listing.beds,
        "baths": listing.baths,
        "sqft": listing.sqft,
        "address": listing.address,
        "neighborhood": listing.neighborhood,
        "lat": listing.lat,
        "lng": listing.lng,
        "status": listing.status.value,
        "score": listing.score,
        "notes": [n for n in listing.notes if n and n != (outcome or {}).get("summary")],
        "contact": {"name": c.name, "phone": c.phone, "email": c.email} if c else None,
        "contactHint": listing.contact_hint,
        "tourUrl": listing.tour_url,
        "call": {
            "id": str(call["id"]),
            "listingVerified": (outcome or {}).get("listing_verified") if call["mode"] == "live" else None,
            "verificationEvidence": [f for f in (outcome or {}).get("confirmed_facts", []) if f["key"] in ("identity", "authority", "available", "rent", "advertised_beds", "advertised_baths")],
            "bookingWarning": (outcome or {}).get("booking_warning"),
            "status": call["status"],
            "error": call["error"],
            "summary": (outcome or {}).get("summary"),
            "viable": (outcome or {}).get("viable"),
            "tradeoffs": (outcome or {}).get("tradeoffs") or [],
            "transcript": call["transcript"],
        } if call else None,
        "email": {"id": email["id"], "status": email["status"], "to": email["to_addr"],
                  "subject": email["subject"], "body": email["body"]} if email else None,
        "viewing": {"start": tour["start"],
                    "end": tour["end"], "confirmedOnCall": tour["source_call_id"] is not None,
                    "calendarStatus": tour["calendar_status"], "calendarError": tour["calendar_error"],
                    "calendarUrl": gcal_link(f"Viewing: {listing.title}", tour["start"],
                                             listing.address, listing.url, end= tour["end"])} if tour else None,
        "interested": app["stage"] if app else None,
        "nextStep": dataclasses.asdict(ns) if ns else None,
    }


@router.get("/workspace")
def workspace(household_id: str):
    search_id, criteria, row = _search(household_id)
    calls = db.calls_for_search(search_id)
    emails = db.emails_for_search(search_id)
    tours = db.tours_for_search(search_id)
    apps = db.applications_for_search(search_id)
    listings = [_card(l, calls.get(l.key), emails.get(l.key), tours.get(l.key), apps.get(l.key))
                for l in db.list_listings(search_id)]
    from househunt.outreach.scheduler import jobs
    outreach = {j['listing_key']:j for j in jobs(search_id)}
    for listing in listings:
        job = outreach.get(listing['id'])
        listing['outreach'] = {'state':job['state'], 'scheduledAt':job['scheduled_at'], 'reason':job['reason'],
            'hoursSource':job['hours'].get('source'), 'hoursQuote':job['hours'].get('quote'),
            'timezone':job['hours'].get('timezone'), 'attempts':job['attempts']} if job else None
    return {
        "search": {"id": search_id, "status": row["status"], "error": row["error"],
                   "criteria": dataclasses.asdict(criteria)},
        "listings": listings,
        "callingEnabled": settings.call_mode.value != "dry_run" and not settings.mock_sources,
        "autonomousCalling": settings.call_mode.value == 'auto' and settings.outreach_worker and not settings.mock_sources,
        "callbackReady": settings.callback_enabled and bool(db.get_state('inbound_synced_at')),
    }


class ContactIn(BaseModel):
    pasted: str = ""
    phone: str = ""
    email: str = ""
    name: str = ""


@router.post("/listings/{key}/contact")
def save_contact(household_id: str, key: str, body: ContactIn):
    from househunt.manual import InvalidInput, set_contact

    search_id, _, _ = _search(household_id)
    listing = _listing(search_id, key)
    try:
        set_contact(listing, body.phone, body.email, body.name, pasted=body.pasted)
    except InvalidInput as e:
        raise HTTPException(400, str(e))
    db.upsert_listing(search_id, listing)
    return {"ok": True}


@router.post("/listings/{key}/interested")
def mark_interested(household_id: str, key: str):
    search_id, _, _ = _search(household_id)
    listing = _listing(search_id, key)
    if not db.find_application(search_id, key):
        tour = db.tours_for_search(search_id).get(key)
        db.create_application(
            search_id=search_id, listing_key=key, title=listing.title, url=listing.url,
            address=listing.address, price=listing.price,
            stage=AppStage.VIEWING.value if tour else AppStage.INTERESTED.value,
            next_step="Viewing" if tour else None, next_date=tour["start"] if tour else None)
    return {"ok": True}


class ViewingIn(BaseModel):
    start: str


@router.post("/listings/{key}/calendar-sync")
def retry_calendar(household_id: str, key: str):
    from househunt.outreach.booking import retry_sync
    search_id, _, _ = _search(household_id)
    tour = db.tours_for_search(search_id).get(key)
    if not tour or tour["source_call_id"] is None:
        raise HTTPException(404, "No call-confirmed tour")
    try:
        retry_sync(tour["id"])
    except Exception:
        raise HTTPException(503, "Calendar sync needs attention; the contact booking is saved") from None
    updated = db.get_tour(tour["id"])
    if updated["calendar_status"] != "synced":
        raise HTTPException(409, updated["calendar_error"] or "Calendar sync is pending")
    return {"ok": True}


@router.post("/listings/{key}/viewing")
def log_viewing(household_id: str, key: str, body: ViewingIn):
    search_id, _, _ = _search(household_id)
    listing = _listing(search_id, key)
    try:
        start = datetime.fromisoformat(body.start).isoformat(timespec="minutes")
    except ValueError:
        raise HTTPException(400, "Pick a date and time")
    c = listing.contact
    db.create_tour(search_id, key, start, listing.address, c.name if c else None, c.phone if c else None)
    listing.status = ListingStatus.TOUR_SCHEDULED
    pipeline.track_viewing(search_id, listing, start)
    db.upsert_listing(search_id, listing)
    return {"ok": True}


@router.post("/listings/{key}/email")
def draft_email(household_id: str, key: str):
    """Claude drafts it; the housemate edits it and sends it from their own Gmail."""
    from househunt.outreach.email_draft import draft_email as draft

    search_id, criteria, _ = _search(household_id)
    listing = _listing(search_id, key)
    existing = db.emails_for_search(search_id).get(key)
    if existing:
        return {"id": existing["id"]}
    d = draft(listing, criteria, criteria.renter_name or settings.renter_name)
    to = (listing.contact.email if listing.contact else None) or ""
    return {"id": db.create_email(search_id, key, to, d.subject, d.body)}


class EmailIn(BaseModel):
    action: Literal["save", "sent", "discard"]
    to: str = ""
    subject: str = ""
    body: str = ""


@router.post("/emails/{email_id}")
def update_email(household_id: str, email_id: int, body: EmailIn):
    search_id, _, _ = _search(household_id)
    email = db.get_email(email_id)
    if not email or email["search_id"] != search_id:
        raise HTTPException(404)
    if body.action == "discard":
        db.update_email(email_id, status="discarded")
    elif body.action == "save":
        db.update_email(email_id, to_addr=body.to.strip(), subject=body.subject, body=body.body)
    else:  # the housemate sent it from Gmail
        db.update_email(email_id, to_addr=body.to.strip(), subject=body.subject, body=body.body,
                        status="sent", sent_at=db.now())
    return {"ok": True}


class ListingIn(BaseModel):
    url: str
    price: str = ""
    beds: str = ""
    baths: str = ""
    address: str = ""
    pasted: str = ""


@router.post("/listings")
def add_listing(household_id: str, body: ListingIn):
    from househunt import geo
    from househunt.manual import InvalidInput, identify, listing_from_url, parse_pasted, set_contact

    search_id, criteria, _ = _search(household_id)

    def num(s, cast):
        s = "".join(ch for ch in s if ch.isdigit() or ch == ".")
        try:
            return cast(float(s)) if s else None
        except ValueError:
            return None

    phone, email = parse_pasted(body.pasted) if body.pasted.strip() else ("", "")
    source, source_id = identify(body.url.strip())
    existing = db.get_listing(search_id, f"{source.value if source else 'other'}:{source_id}")
    try:
        if existing:
            if phone or email:
                db.upsert_listing(search_id, set_contact(existing, phone, email))
            return {"id": existing.key}
        listing = listing_from_url(body.url, criteria, price=num(body.price, int),
                                   beds=num(body.beds, int), baths=num(body.baths, float),
                                   address=body.address, phone=phone, email=email)
    except InvalidInput as e:
        raise HTTPException(400, str(e))
    try:
        geo.locate([listing], criteria)
    except Exception:
        log.exception("geocoding pasted listing failed")
    db.upsert_listing(search_id, listing)
    return {"id": listing.key}


class CriteriaIn(BaseModel):
    neighborhoods: list[str] = Field(default_factory=list)
    must_haves: list[str] = Field(default_factory=list)
    max_price: int = Field(gt=0)
    min_beds: int = Field(ge=0)
    rerun: bool = True


@router.post("/criteria")
def refine_search(household_id: str, body: CriteriaIn, background: BackgroundTasks):
    """Refine the search after onboarding; listings keep their progress on a re-run."""
    search_id, criteria, row = _search(household_id)
    if row["status"] in ("pending", "sourcing", "screening", "calling"):
        raise HTTPException(409, "The search is still running; refine it when it's done")
    criteria = dataclasses.replace(
        criteria, neighborhoods=[n.strip() for n in body.neighborhoods if n.strip()],
        must_haves=[m.strip() for m in body.must_haves if m.strip()],
        max_price=body.max_price, min_beds=body.min_beds)
    db.update_search_criteria(search_id, criteria)
    if body.rerun:
        db.set_search_status(search_id, "pending")
        background.add_task(_rerun, household_id, search_id)
    return {"ok": True}


def _rerun(household_id: str, search_id: int) -> None:
    from househunt import platform

    def publish():  # keep the household's AgentRun in sync when the platform is configured
        try:
            platform.PlatformClient().publish(household_id, search_id)
        except RuntimeError:
            pass

    pipeline.run_search(search_id, on_update=publish)


@router.post("/start")
def start(household_id: str):
    """Onboarding just requested this household's search: create it from the brief now and
    wake the worker, instead of waiting for its next poll."""
    from househunt import platform

    sid = db.household_search(household_id)
    if sid is None:
        try:
            client = platform.PlatformClient()
            brief = next((b for b in client.briefs() if b["householdId"] == household_id), None)
        except (RuntimeError, ValueError) as e:
            raise HTTPException(503, f"Couldn't read the household brief: {e}")
        if not brief:
            raise HTTPException(404, "No search has been requested for this household")
        sid = platform.ensure_search(client, brief)
    platform.wake.set()
    return {"searchId": sid}

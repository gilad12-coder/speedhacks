"""FastAPI web app: create a search, watch it run, approve calls, download tour invites."""

from __future__ import annotations

import json
import re
import logging
import secrets
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from househunt import chat as agent, db, geo, pipeline
from househunt.connectors import google
from househunt.config import settings
from househunt.models import AppStage, ListingStatus, SearchCriteria
from househunt.sources.email_alerts import GmailAlertsSource
from househunt.tours import to_ics

logging.basicConfig(level=logging.INFO)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
security = HTTPBasic(auto_error=False)


def require_auth(request: Request,
                 creds: HTTPBasicCredentials | None = Depends(security)) -> None:
    """Basic auth when APP_PASSWORD is set: the app can place real phone calls."""
    if request.url.path.startswith('/agent/'):
        key = os.environ.get('AGENT_API_KEY', '')
        if not key or not secrets.compare_digest(request.headers.get('authorization',''), 'Bearer '+key):
            raise HTTPException(401, 'Unauthorized agent request')
        return
    if not settings.app_password or request.url.path == "/healthz":
        return
    if not (creds and secrets.compare_digest(creds.password, settings.app_password)):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


@asynccontextmanager
async def lifespan(_: FastAPI):
    from househunt import phone

    db.init()
    db.recover_calls()
    from househunt import platform
    platform.start_background_worker()
    stop = phone.start_background()   # keeps the call-in briefing fresh, when switched on
    yield
    stop.set()


app = FastAPI(title="KeyHunt", lifespan=lifespan, dependencies=[Depends(require_auth)])

# Sidebar tabs: (path, label, icon). A tab shows up once its route exists.
NAV = [("/", "Searches", "list"), ("/leads", "Leads", "star"), ("/calls", "Calls", "phone"), ("/viewings", "Viewings", "calendar"),
       ("/applications", "Applications", "clipboard"), ("/chats/agent", "Ask your agent", "chat"),
       ("/phone", "Phone briefing", "mic"),
       ("/connections", "Connections", "plug")]


def nav_items() -> list[tuple[str, str, str]]:
    paths = {getattr(r, "path", None) for r in app.routes}
    return [n for n in NAV if n[0] in paths]


def recent_searches() -> list[tuple[int, str, str]]:
    return [(r["id"], json.loads(r["criteria"])["city"], r["status"])
            for r in db.list_searches()[:6]]


def when(value: str | None, fmt: str | None = None) -> str:
    """Friendly date for ISO strings: 'Thu Oct 15, 6:00 PM', or just 'Thu Oct 15'."""
    if not value:
        return ""
    try:
        d = datetime.fromisoformat(value)
    except ValueError:
        return value
    if fmt:
        return d.strftime(fmt)
    timed = "T" in value and (d.hour or d.minute)
    return d.strftime("%a %b %-d, %-I:%M %p" if timed else "%a %b %-d")


templates.env.filters["when"] = when


def short_error(value: str | None) -> str:
    """Turn a stored exception repr into the API's own message, when there is one."""
    import re

    if not value:
        return ""
    m = re.search(r"'message': ['\"](.+?)['\"][,}]", value)
    return m.group(1) if m else value


templates.env.filters["short_error"] = short_error
def recent_chats() -> list:
    return [c for c in db.list_chats(8) if c["listing_key"]][:5]


def needs_you_count() -> int:
    from househunt import flags

    try:
        return sum(1 for f in flags.compute() if f.severity in ("urgent", "todo"))
    except Exception:  # never let a flag bug break every page's sidebar
        logging.getLogger(__name__).exception("computing flags failed")
        return 0


templates.env.globals["needs_you_count"] = needs_you_count
templates.env.globals.update(nav_items=nav_items, recent_searches=recent_searches,
                             recent_chats=recent_chats, settings=settings)


def _split(s: str) -> list[str]:
    return [x.strip() for x in s.replace("\n", ",").split(",") if x.strip()]


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    counts = db.listing_counts()
    searches = [(r, json.loads(r["criteria"]), counts.get(r["id"], {}))
                for r in db.list_searches()]
    from househunt import flags

    return templates.TemplateResponse(request, "index.html", {
        "searches": searches, "settings": settings, "flags": flags.compute(),
    })


@app.get("/searches/new", response_class=HTMLResponse)
def new_search(request: Request):
    return templates.TemplateResponse(request, "new.html", {"settings": settings})


@app.post("/searches")
def create_search(
    background: BackgroundTasks,
    city: str = Form(...),
    max_price: int = Form(...),
    min_price: int = Form(0),
    min_beds: int = Form(0),
    min_baths: float = Form(0),
    neighborhoods: str = Form(""),
    must_haves: str = Form(""),
    move_in_by: str = Form(""),
    tour_availability: str = Form(""),
    occupants: int | None = Form(None, ge=1, le=20),
    renter_name: str = Form("", max_length=80),
):
    if max_price <= 0 or min_price < 0 or min_price > max_price or min_beds < 0 or min_baths < 0:
        raise HTTPException(400, "Enter a positive budget and valid bedroom/bathroom minimums")
    criteria = SearchCriteria(
        city=city, max_price=max_price, min_price=min_price, min_beds=min_beds,
        min_baths=min_baths, neighborhoods=_split(neighborhoods),
        must_haves=_split(must_haves), move_in_by=move_in_by or None,
        tour_availability=_split(tour_availability),
        occupants=occupants,
        renter_name=renter_name.strip() or settings.renter_name,
    )
    search_id = db.create_search(criteria)
    background.add_task(pipeline.run_search, search_id)
    return RedirectResponse(f"/searches/{search_id}", status_code=303)


@app.get("/searches/{search_id}", response_class=HTMLResponse)
def show_search(request: Request, search_id: int):
    found = db.get_search(search_id)
    if not found:
        raise HTTPException(404)
    criteria, row = found
    listings = db.list_listings(search_id)
    calls = db.calls_for_search(search_id)
    outcomes = {k: json.loads(c["outcome"]) for k, c in calls.items() if c["outcome"]}
    tours = db.tours_for_search(search_id)
    tracked = db.applications_for_search(search_id)
    place_notes = db.notes_for_search(search_id)
    chats = db.chats_for_search(search_id)
    emails = db.emails_for_search(search_id)
    in_flight = row["status"] in ("pending", "sourcing", "screening", "calling") or any(
        c["status"] in ("queued", "in_progress", "extracting") for c in calls.values()) or any(
        l.screening.get("status") == "checking" for l in listings)
    order = [ListingStatus.TOUR_SCHEDULED, ListingStatus.VIABLE, ListingStatus.CONTACTED,
             ListingStatus.CANDIDATE, ListingStatus.NOT_VIABLE, ListingStatus.FILTERED_OUT]
    listings.sort(key=lambda l: (order.index(l.status) if l.status in order else 99, -l.score))
    pins = [{"key": l.key, "lat": l.lat, "lng": l.lng, "price": l.price, "title": l.title,
             "status": l.status.value, "beds": l.beds, "baths": l.baths}
            for l in listings if l.lat is not None and l.lng is not None]
    counts = {s.value: 0 for s in ListingStatus}
    for l in listings:
        counts[l.status.value] += 1
    return templates.TemplateResponse(request, "search.html", {
        "search": row, "criteria": criteria, "listings": listings, "calls": calls,
        "outcomes": outcomes, "tours": tours, "emails": emails, "refresh": in_flight,
        "settings": settings, "pins": pins, "center": geo.cached(criteria.city),
        "counts": counts, "tracked": tracked, "stages": AppStage,
        "research_events": db.search_events(search_id),
        "place_notes": place_notes, "chats": chats,
    })


@app.post("/searches/{search_id}/listings/{key}/call")
def call_listing(background: BackgroundTasks, search_id: int, key: str, next: str = Form("")):
    listing = db.get_listing(search_id, key)
    if not listing:
        raise HTTPException(404, "Listing not found")
    if listing.status == ListingStatus.FILTERED_OUT:
        raise HTTPException(400, "Listing is already ruled out")
    existing = db.calls_for_search(search_id).get(key)
    if existing and existing["status"] not in ("attention", "failed"):
        raise HTTPException(409, "Call already exists; no replacement call was started")
    background.add_task(pipeline.call_listing, search_id, key)
    # Only same-site paths, so the form can't bounce anyone to another site.
    back = next if next.startswith("/") and not next.startswith("//") else f"/searches/{search_id}"
    return RedirectResponse(back, status_code=303)


@app.post("/searches/{search_id}/listings/{key}/screen")
def screen_listing(background: BackgroundTasks, search_id: int, key: str):
    listing = db.get_listing(search_id, key)
    if not listing:
        raise HTTPException(404)
    if settings.mock_sources:
        raise HTTPException(400, "Switch to live sources to research a real listing")
    if not settings.openai_api_key:
        raise HTTPException(400, "Web research requires the server's OpenAI API key")
    background.add_task(pipeline.screen_listing, search_id, key)
    return RedirectResponse(f"/searches/{search_id}#{key}", status_code=303)


@app.get("/calls/{call_id}/recording")
def call_recording(call_id: int):
    from househunt.outreach.recording import recording_path
    path = recording_path(call_id)
    if path is None or not path.is_file():
        raise HTTPException(404, "Recording not imported")
    return FileResponse(path, media_type="audio/mpeg" if path.suffix == ".mp3" else "audio/wav",
                        headers={"Cache-Control": "private, no-store"})


@app.post('/agent/households/{household_id}/listings/{key}/call')
def household_call(background: BackgroundTasks, household_id: str, key: str):
    search_id = db.household_search(household_id)
    if search_id is None:
        raise HTTPException(404, 'Household search not found')
    listing = db.get_listing(search_id, key)
    if not listing or not listing.contact or not listing.contact.phone:
        raise HTTPException(400, 'A listing contact phone is required')
    if not settings.mock_sources and settings.call_mode.value != 'dry_run' and listing.contact.phone not in settings.dial_allowed_numbers:
        raise HTTPException(400, 'This contact has not been enabled for calling by the operator')
    call_listing(background, search_id, key)
    return {'ok':True}


@app.get('/agent/households/{household_id}/calls/{call_id}/recording')
def household_recording(household_id: str, call_id: int):
    search_id = db.household_search(household_id)
    if search_id is None or not any(c['id'] == call_id for c in db.calls_for_search(search_id).values()):
        raise HTTPException(404)
    return call_recording(call_id)


@app.post("/searches/{search_id}/listings/{key}/track")
def track_listing(search_id: int, key: str):
    listing = db.get_listing(search_id, key)
    if not listing:
        raise HTTPException(404)
    tour = db.tours_for_search(search_id).get(key)
    db.create_application(
        search_id=search_id, listing_key=key, title=listing.title, url=listing.url,
        address=listing.address, price=listing.price,
        stage=AppStage.VIEWING.value if tour else AppStage.INTERESTED.value,
        next_step="Viewing" if tour else None, next_date=tour["start"] if tour else None,
    )
    return RedirectResponse(f"/searches/{search_id}", status_code=303)


# --- calls & viewings -------------------------------------------------------

def _listing_info(cache: dict, search_id: int, key: str):
    if (search_id, key) not in cache:
        found = db.get_search(search_id)
        cache[(search_id, key)] = (db.get_listing(search_id, key), found[0] if found else None)
    return cache[(search_id, key)]


@app.get("/calls", response_class=HTMLResponse)
def calls_page(request: Request):
    cache: dict = {}
    calls = []
    for c in db.all_calls():
        listing, criteria = _listing_info(cache, c["search_id"], c["listing_key"])
        calls.append({"call": c, "listing": listing, "city": criteria.city if criteria else "",
                      "outcome": json.loads(c["outcome"]) if c["outcome"] else None})
    return templates.TemplateResponse(request, "calls.html", {"settings": settings, "calls": calls})


@app.get("/viewings", response_class=HTMLResponse)
def viewings_page(request: Request):
    cache: dict = {}
    now = datetime.now().isoformat(timespec="minutes")
    items = []
    booked = set()
    for t in db.all_tours():
        listing, criteria = _listing_info(cache, t["search_id"], t["listing_key"])
        booked.add((t["search_id"], t["listing_key"]))
        items.append({"start": t["start"], "title": listing.title if listing else "Viewing",
                      "address": t["address"], "contact": t["contact_name"] or t["contact_phone"],
                      "url": listing.url if listing else None, "ics": f"/tours/{t['id']}.ics",
                      "search_id": t["search_id"], "key": t["listing_key"],
                      "city": criteria.city if criteria else "", "source": "Booked by your agent"})
    # Viewings you track by hand on the applications board.
    for a in db.list_applications():
        if a["stage"] == AppStage.VIEWING.value and a["next_date"] and \
                (a["search_id"], a["listing_key"]) not in booked:
            items.append({"start": a["next_date"], "title": a["title"], "address": a["address"],
                          "contact": None, "url": a["url"], "ics": None, "search_id": a["search_id"],
                          "key": a["listing_key"], "city": "", "source": "From your board",
                          "app_id": a["id"]})
    items.sort(key=lambda i: i["start"])
    return templates.TemplateResponse(request, "viewings.html", {
        "settings": settings, "upcoming": [i for i in items if i["start"] >= now],
        "past": [i for i in items if i["start"] < now][::-1],
    })


# --- leads ------------------------------------------------------------------

@app.get("/leads", response_class=HTMLResponse)
def leads_page(request: Request):
    from househunt import leads, next_step

    items, removed = [], []
    for a in db.list_applications():
        if a["stage"] == AppStage.WITHDRAWN.value and "Removed from leads" in (a["notes"] or ""):
            removed.append(a)
        if a["stage"] != AppStage.INTERESTED.value:
            continue
        sid, key = a["search_id"], a["listing_key"]
        listing = db.get_listing(sid, key) if sid else None
        call = db.calls_for_search(sid).get(key) if listing else None
        email = db.emails_for_search(sid).get(key) if listing else None
        items.append({
            "app": a, "listing": listing, "outreach": leads.outreach(sid, key),
            "notes": db.place_notes(sid, key) if listing else [],
            "step": next_step.recommend(listing, call, email) if listing else None,
            "can_call": bool(listing and listing.contact and listing.contact.phone
                             and not (call and call["status"] in ("queued", "in_progress"))),
            "email": email,
        })
    order = {"action": 0, "new": 1, "waiting": 2}
    items.sort(key=lambda i: (order[i["outreach"].status], -(i["outreach"].days_since or 0)))
    return templates.TemplateResponse(request, "leads.html", {
        "settings": settings, "items": items, "removed": removed[:10],
        "reasons": leads.DROP_REASONS,
    })


@app.post("/leads/{app_id}/remove")
def remove_lead(app_id: int, reason: str = Form("no_response"), detail: str = Form("")):
    from househunt import leads

    if not db.get_application(app_id):
        raise HTTPException(404)
    leads.drop(app_id, reason, detail)
    return RedirectResponse("/leads", status_code=303)


@app.post("/leads/{app_id}/restore")
def restore_lead(app_id: int):
    from househunt import leads

    if not db.get_application(app_id):
        raise HTTPException(404)
    leads.restore(app_id)
    return RedirectResponse(f"/leads#lead-{app_id}", status_code=303)


# --- phone briefing -----------------------------------------------------------

@app.get("/phone", response_class=HTMLResponse)
def phone_page(request: Request, msg: str | None = None, error: str | None = None):
    from househunt import briefing, flags, phone

    return templates.TemplateResponse(request, "phone.html", {
        "settings": settings, "msg": msg, "error": error, "configured": phone.configured(),
        "enabled": phone.enabled(), "number": db.get_state("phone_number"),
        "synced_at": db.get_state("inbound_synced_at"), "facts": briefing.facts(),
        "flags": flags.compute(), "inbound": db.inbound_calls(),
    })


def _phone_action(fn, ok: str):
    try:
        fn()
    except Exception as e:  # surface Dial errors on the page instead of a 500
        logging.getLogger(__name__).exception("phone action failed")
        return RedirectResponse(f"/phone?error={quote_plus(f'{ok.split()[0]} failed: {e}')}", 303)
    return RedirectResponse(f"/phone?msg={quote_plus(ok)}", 303)


@app.post("/phone/call-me")
def phone_call_me():
    from househunt import phone

    return _phone_action(phone.call_me, "Calling you now with your update")


@app.post("/phone/enable")
def phone_enable():
    from househunt import phone

    return _phone_action(phone.enable, "Your KeyHunt number now answers with your briefing")


@app.post("/phone/disable")
def phone_disable():
    from househunt import phone

    return _phone_action(phone.disable, "Call-in briefings are off; your number's old greeting is back")


@app.post("/phone/sync")
def phone_sync():
    from househunt import phone

    def run():
        phone.sync(force=True)
        phone.poll_inbound()
    return _phone_action(run, "Briefing refreshed and new calls checked")


@app.post("/phone/calls/{call_id}/handled")
def phone_call_handled(call_id: str):
    db.mark_inbound_handled(call_id)
    return RedirectResponse("/phone", 303)


# --- agent chats & place notes ----------------------------------------------

@app.get("/chats/agent")
def agent_chat():
    return RedirectResponse(f"/chats/{db.get_or_create_chat(None, None, 'Your search')}", 303)


@app.post("/searches/{search_id}/listings/{key}/chat")
def start_place_chat(search_id: int, key: str):
    listing = db.get_listing(search_id, key)
    if not listing:
        raise HTTPException(404)
    return RedirectResponse(f"/chats/{db.get_or_create_chat(search_id, key, listing.title)}", 303)


@app.get("/chats/{chat_id}", response_class=HTMLResponse)
def chat_page(request: Request, chat_id: int):
    chat = db.get_chat(chat_id)
    if not chat:
        raise HTTPException(404)
    ctx = {"settings": settings, "chat": chat, "has_key": agent.llm.has_credentials(),
           "messages": [m for m in db.chat_messages(chat_id) if m["display"]]}
    if chat["listing_key"]:
        sid, key = chat["search_id"], chat["listing_key"]
        call = db.calls_for_search(sid).get(key)
        ctx.update(listing=db.get_listing(sid, key), notes=db.place_notes(sid, key),
                   call=call, outcome=json.loads(call["outcome"]) if call and call["outcome"] else None,
                   tour=db.tours_for_search(sid).get(key), app=db.find_application(sid, key))
    return templates.TemplateResponse(request, "chat.html", ctx)


@app.post("/chats/{chat_id}/messages")
def chat_send(chat_id: int, message: str = Form(...)):
    if not db.get_chat(chat_id):
        raise HTTPException(404)
    if not message.strip():
        raise HTTPException(400, "empty message")
    events = (json.dumps(e) + "\n" for e in agent.respond(chat_id, message.strip()))
    return StreamingResponse(events, media_type="application/x-ndjson")


@app.post("/places/{search_id}/{key}/notes")
def save_place_notes(request: Request, search_id: int, key: str, notes: str = Form(""),
                     next: str = Form("")):
    if not db.get_listing(search_id, key):
        raise HTTPException(404)
    db.set_place_notes(search_id, key, notes.splitlines())
    if request.headers.get("x-requested-with") == "fetch":
        return {"notes": db.place_notes(search_id, key)}
    return RedirectResponse(next if next.startswith("/") else f"/searches/{search_id}#{key}", 303)


@app.post("/places/{search_id}/{key}/notes/add")
def add_place_note(search_id: int, key: str, note: str = Form(...)):
    if not db.get_listing(search_id, key):
        raise HTTPException(404)
    added = db.add_place_note(search_id, key, note[:400])
    return {"added": added, "notes": db.place_notes(search_id, key)}


# --- applications -----------------------------------------------------------

# The journey through a search, furthest step reached wins.
JOURNEY = [("search", "Search"), ("calls", "Calls"), ("viewings", "Viewings"),
           ("apply", "Applications"), ("lease", "Lease signed")]


def _journey_step(counts: dict[str, int], stages: list[AppStage]) -> int:
    if AppStage.LEASE_SIGNED in stages:
        return 5  # all done
    if any(s in (AppStage.APPLIED, AppStage.APPROVED) for s in stages):
        return 3
    if counts["tours"] or any(s in (AppStage.VIEWING, AppStage.VIEWED) for s in stages):
        return 2
    if counts["calls"]:
        return 1
    return 0


@app.get("/applications", response_class=HTMLResponse)
def applications(request: Request):
    apps = db.list_applications()
    stages = [AppStage(a["stage"]) for a in apps]
    counts = db.journey_counts()
    board = {s: [a for a in apps if a["stage"] == s.value] for s in AppStage}
    upcoming = sorted((a for a in apps if a["next_date"] and not AppStage(a["stage"]).closed),
                      key=lambda a: a["next_date"])
    return templates.TemplateResponse(request, "applications.html", {
        "settings": settings, "apps": apps, "board": board, "stages": AppStage,
        "counts": counts, "journey": JOURNEY, "step": _journey_step(counts, stages),
        "upcoming": upcoming[:5],
    })


def _price(v: str) -> int | None:
    digits = "".join(ch for ch in v if ch.isdigit())
    return int(digits) if digits else None


@app.post("/applications")
def add_application(title: str = Form(...), url: str = Form(""), address: str = Form(""),
                    price: str = Form(""), stage: AppStage = Form(AppStage.INTERESTED),
                    notes: str = Form("")):
    db.create_application(title=title, url=url or None, address=address or None,
                          price=_price(price), stage=stage.value, notes=notes or None,
                          applied_at=db.now() if stage == AppStage.APPLIED else None)
    return RedirectResponse("/applications", status_code=303)


@app.post("/applications/{app_id}")
def edit_application(request: Request, app_id: int, stage: AppStage | None = Form(None),
                     next_step: str | None = Form(None), next_date: str | None = Form(None),
                     notes: str | None = Form(None), price: str | None = Form(None)):
    row = db.get_application(app_id)
    if not row:
        raise HTTPException(404)
    fields = {}
    if stage:
        fields["stage"] = stage.value
        if stage == AppStage.APPLIED and not row["applied_at"]:
            fields["applied_at"] = db.now()
    for k, v in (("next_step", next_step), ("next_date", next_date), ("notes", notes)):
        if v is not None:
            fields[k] = v.strip() or None
    if price is not None:
        fields["price"] = _price(price)
    db.update_application(app_id, **fields)
    if request.headers.get("x-requested-with") == "fetch":
        return {"ok": True}
    return RedirectResponse(f"/applications#app-{app_id}", status_code=303)


@app.post("/applications/{app_id}/delete")
def remove_application(app_id: int):
    db.delete_application(app_id)
    return RedirectResponse("/applications", status_code=303)


@app.get("/tours/{tour_id}.ics")
def tour_ics(tour_id: int):
    tour = db.get_tour(tour_id)
    if not tour:
        raise HTTPException(404)
    listing = db.get_listing(tour["search_id"], tour["listing_key"])
    body = to_ics(tour_id, tour["start"], listing.title if listing else "Viewing",
                  tour["address"], tour["contact_name"] or tour["contact_phone"],
                  listing.url if listing else None)
    return Response(body, media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="tour-{tour_id}.ics"'})


# --- connections ------------------------------------------------------------

def _redirect_uri(request: Request) -> str:
    base = settings.public_base_url or str(request.base_url)
    return base.rstrip("/") + "/auth/google/callback"


@app.get("/connections", response_class=HTMLResponse)
def connections(request: Request, msg: str | None = None, error: str | None = None):
    return templates.TemplateResponse(request, "connections.html", {
        "settings": settings, "msg": msg, "error": error,
        "google_configured": google.configured(),
        "google": google.connection(),
        "can_send": google.has_scope(google.SEND_SCOPE),
        "redirect_uri": _redirect_uri(request),
        "alert_sites": ["Zillow", "Trulia", "HotPads", "Redfin", "Apartments.com", "StreetEasy"],
    })


@app.get("/auth/google/start")
def google_start(request: Request):
    if not google.configured():
        raise HTTPException(400, "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first")
    return RedirectResponse(google.authorize_url(_redirect_uri(request)))


@app.get("/auth/google/callback")
def google_callback(request: Request, state: str = "", code: str | None = None,
                    error: str | None = None):
    if error:
        return RedirectResponse(f"/connections?error={quote_plus(f'Google sign-in cancelled ({error})')}", 303)
    if not (code and google.check_state(state)):
        return RedirectResponse("/connections?error=Sign-in+expired,+try+again", 303)
    try:
        email = google.exchange_code(code, _redirect_uri(request))
    except Exception as e:
        return RedirectResponse(f"/connections?error={quote_plus(f'Google sign-in failed: {e}')}", 303)
    return RedirectResponse(f"/connections?msg={quote_plus(f'Connected {email}')}", 303)


@app.post("/connections/google/disconnect")
def google_disconnect():
    google.disconnect()
    return RedirectResponse("/connections?msg=Google+disconnected", 303)


@app.get("/connections/google/alerts", response_class=HTMLResponse)
def google_alerts_preview(request: Request):
    """Show what we parse out of recent alert emails, without starting a search."""
    try:
        listings = GmailAlertsSource().fetch(None)
        error = None
    except Exception as e:
        listings, error = [], str(e)
    return templates.TemplateResponse(request, "alerts.html", {
        "settings": settings, "listings": listings, "error": error, "days": GmailAlertsSource.days,
    })


@app.post("/connections/dial/test-call")
def dial_test_call():
    if not (settings.dial_api_key and settings.notify_number):
        return RedirectResponse("/connections?error=Set+DIAL_API_KEY+and+NOTIFY_NUMBER+first", 303)
    try:
        from househunt.outreach.dial import DialClient

        call = DialClient(settings).place_call(
            settings.notify_number,
            "You are the househunt calling assistant making a test call to the person who set "
            "you up. Introduce yourself as an AI assistant, say this is a test call from "
            "househunt, ask if they can hear you clearly, answer any questions briefly, then "
            "say goodbye. Keep it under one minute.",
            max_seconds=90,
        )
    except Exception as e:
        return RedirectResponse(f"/connections?error={quote_plus(f'Dial call failed: {e}')}", 303)
    return RedirectResponse(f"/connections?msg=Calling+you+now+(call+{call.id})", 303)


# --- email drafts: nothing is sent without an explicit "Approve & send" --------

EMAIL_ADDR = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


@app.post("/searches/{search_id}/listings/{key}/email")
def draft_listing_email(search_id: int, key: str):
    from househunt.outreach.email_draft import draft_email

    criteria, _ = db.get_search(search_id)
    listing = db.get_listing(search_id, key)
    if not listing:
        raise HTTPException(404)
    draft = draft_email(listing, criteria, settings.renter_name)
    to = (listing.contact.email if listing.contact else None) or ""
    email_id = db.create_email(search_id, key, to, draft.subject, draft.body)
    return RedirectResponse(f"/emails/{email_id}", status_code=303)


@app.get("/emails/{email_id}", response_class=HTMLResponse)
def show_email(request: Request, email_id: int, error: str | None = None):
    email = db.get_email(email_id)
    if not email:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "email.html", {
        "settings": settings, "email": email, "error": error,
        "listing": db.get_listing(email["search_id"], email["listing_key"]),
        "google": google.connection(), "can_send": google.has_scope(google.SEND_SCOPE),
    })


@app.post("/emails/{email_id}")
def update_email(email_id: int, action: str = Form(...), to_addr: str = Form(""),
                 subject: str = Form(""), body: str = Form("")):
    email = db.get_email(email_id)
    if not email:
        raise HTTPException(404)
    back = f"/searches/{email['search_id']}"
    if email["status"] != "draft":
        return RedirectResponse(back, 303)
    to_addr = to_addr.strip()

    if action == "discard":
        db.update_email(email_id, status="discarded")
        return RedirectResponse(back, 303)

    db.update_email(email_id, to_addr=to_addr, subject=subject, body=body)
    if action != "send":
        return RedirectResponse(f"/emails/{email_id}", 303)

    if not EMAIL_ADDR.match(to_addr):
        return RedirectResponse(f"/emails/{email_id}?error={quote_plus('Enter one valid To address')}", 303)
    if not (subject.strip() and body.strip()):
        return RedirectResponse(f"/emails/{email_id}?error={quote_plus('Subject and body are required')}", 303)
    try:
        sent = google.send_email(to_addr, subject, body)
    except Exception as e:
        db.update_email(email_id, error=str(e))
        return RedirectResponse(f"/emails/{email_id}?error={quote_plus(f'Not sent: {e}')}", 303)
    db.update_email(email_id, status="sent", sent_at=db.now(), error=None,
                    gmail_message_id=sent.get("id"), gmail_thread_id=sent.get("threadId"))
    return RedirectResponse(back, 303)


# --- listings and contacts the renter adds by hand ----------------------------

def _opt_int(s: str) -> int | None:
    s = re.sub(r"[^\d]", "", s or "")
    return int(s) if s else None


def _opt_float(s: str) -> float | None:
    try:
        return float(s) if (s or "").strip() else None
    except ValueError:
        return None


@app.post("/searches/{search_id}/listings")
def add_listing(search_id: int, url: str = Form(...), title: str = Form(""),
                price: str = Form(""), beds: str = Form(""), baths: str = Form(""),
                address: str = Form(""), description: str = Form(""), phone: str = Form(""),
                email: str = Form(""), contact_name: str = Form("")):
    from househunt import geo
    from househunt.manual import InvalidInput, identify, listing_from_url, set_contact

    found = db.get_search(search_id)
    if not found:
        raise HTTPException(404)
    criteria, _ = found
    source, source_id = identify(url.strip())
    existing = db.get_listing(search_id, f"{(source.value if source else 'other')}:{source_id}")
    try:
        if existing:  # already in this search: just add whatever contact was given
            if phone or email or contact_name:
                db.upsert_listing(search_id, set_contact(existing, phone, email, contact_name))
            return RedirectResponse(f"/searches/{search_id}#{existing.key}", 303)
        listing = listing_from_url(
            url, criteria, title=title, price=_opt_int(price), beds=_opt_int(beds),
            baths=_opt_float(baths), address=address, description=description,
            phone=phone, email=email, contact_name=contact_name)
    except InvalidInput as e:
        raise HTTPException(400, str(e))
    try:
        geo.locate([listing], criteria)
    except Exception:
        logging.getLogger(__name__).exception("geocoding manual listing failed")
    db.upsert_listing(search_id, listing)
    return RedirectResponse(f"/searches/{search_id}#{listing.key}", 303)


@app.post("/searches/{search_id}/listings/{key}/contact")
def add_contact(search_id: int, key: str, phone: str = Form(""), email: str = Form(""),
                name: str = Form(""), pasted: str = Form("")):
    from househunt.manual import InvalidInput, set_contact

    listing = db.get_listing(search_id, key)
    if not listing:
        raise HTTPException(404)
    try:
        set_contact(listing, phone, email, name, pasted=pasted)
    except InvalidInput as e:
        raise HTTPException(400, str(e))
    if listing.status == ListingStatus.FILTERED_OUT:
        listing.notes.append("contact added by you")
    db.upsert_listing(search_id, listing)
    return RedirectResponse(f"/searches/{search_id}#{key}", 303)


# Pre-filled Facebook searches for the search page (see househunt/facebook.py).
from househunt import facebook as _facebook  # noqa: E402

templates.env.globals["facebook_links"] = _facebook.links
templates.env.globals["zillow_links"] = _facebook.zillow_links


# --- editing a search ---------------------------------------------------------

@app.get("/searches/{search_id}/edit", response_class=HTMLResponse)
def edit_search_form(request: Request, search_id: int):
    found = db.get_search(search_id)
    if not found:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "new.html", {
        "settings": settings, "c": found[0], "edit_id": search_id})


@app.post("/searches/{search_id}/edit")
def edit_search(background: BackgroundTasks, search_id: int, city: str = Form(...),
                max_price: int = Form(...), min_price: int = Form(0), min_beds: int = Form(0),
                min_baths: float = Form(0), neighborhoods: str = Form(""),
                must_haves: str = Form(""), tour_availability: str = Form(""),
                occupants: int | None = Form(None, ge=1, le=20),
                renter_name: str = Form("", max_length=80), rerun: str = Form("1")):
    import dataclasses

    found = db.get_search(search_id)
    if not found:
        raise HTTPException(404)
    old, row = found
    if row["status"] in ("pending", "sourcing", "calling"):
        raise HTTPException(409, "This search is still running; edit it when it's done")
    # Fields the form doesn't show (deal-breakers, commute, ... from onboarding) carry over.
    criteria = dataclasses.replace(
        old, city=city, max_price=max_price, min_price=min_price, min_beds=min_beds,
        min_baths=min_baths, neighborhoods=_split(neighborhoods), must_haves=_split(must_haves),
        tour_availability=_split(tour_availability), occupants=occupants,
        renter_name=renter_name.strip() or old.renter_name)
    db.update_search_criteria(search_id, criteria)
    if rerun == "1":
        db.set_search_status(search_id, "pending")
        background.add_task(pipeline.run_search, search_id)
    return RedirectResponse(f"/searches/{search_id}", status_code=303)


# --- next steps & viewings you book yourself ------------------------------------

from househunt import next_step as _next_step  # noqa: E402

templates.env.globals["next_step"] = _next_step.recommend
templates.env.globals["gcal_link"] = _next_step.gcal_link


@app.post("/searches/{search_id}/listings/{key}/viewing")
def log_viewing(search_id: int, key: str, start: str = Form(...)):
    """A viewing the renter booked themselves (on the listing's site, by phone, ...)."""
    listing = db.get_listing(search_id, key)
    if not listing:
        raise HTTPException(404)
    try:
        start = datetime.fromisoformat(start).isoformat(timespec="minutes")
    except ValueError:
        raise HTTPException(400, "Pick a date and time")
    contact = listing.contact
    db.create_tour(search_id, key, start, listing.address,
                   contact.name if contact else None, contact.phone if contact else None)
    listing.status = ListingStatus.TOUR_SCHEDULED
    pipeline.track_viewing(search_id, listing, start)
    if google.connection():
        try:
            link = google.add_event(start, f"Viewing: {listing.title}", listing.address,
                                    "\n".join(x for x in [listing.url, contact.phone if contact else None] if x))
            listing.notes.append(f"added to Google Calendar: {link}")
        except Exception:
            logging.getLogger(__name__).exception("calendar add failed")
            listing.notes.append("could not add viewing to Google Calendar")
    db.upsert_listing(search_id, listing)
    return RedirectResponse(f"/searches/{search_id}#{key}", 303)



# --- handoff from onboarding (the Next.js app) ----------------------------------

@app.get("/households/{household_id}", response_class=HTMLResponse)
def open_household(request: Request, household_id: str):
    """Where "Start search" in onboarding sends the household: their search in KeyHunt."""
    from househunt import platform

    sid = db.household_search(household_id)
    if sid is None:
        try:
            client = platform.PlatformClient()
            brief = next((b for b in client.briefs() if b["householdId"] == household_id), None)
            if brief:
                sid = platform.ensure_search(client, brief)
                platform.wake.set()  # start sourcing now rather than at the next poll
        except (RuntimeError, ValueError) as e:
            logging.getLogger(__name__).warning("household handoff failed: %s", e)
    if sid is not None:
        return RedirectResponse(f"/searches/{sid}", status_code=303)
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<meta http-equiv=refresh content=5><title>Starting your search · KeyHunt</title>"
        "<body style='font:16px system-ui;max-width:520px;margin:15vh auto;padding:0 16px'>"
        "<h1 style='font-size:22px'>Starting your search…</h1><p>KeyHunt is picking up your "
        "household's brief. This page refreshes on its own.</p><p style='color:#666;font-size:14px'>"
        "If it doesn't start, make sure everyone confirmed the brief and clicked Start search.</p>",
        status_code=202)

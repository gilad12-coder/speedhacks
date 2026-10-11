"""FastAPI web app: create a search, watch it run, approve calls, download tour invites."""

from __future__ import annotations

import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from househunt import db, geo, pipeline
from househunt.config import settings
from househunt.models import AppStage, ListingStatus, SearchCriteria
from househunt.tours import to_ics

logging.basicConfig(level=logging.INFO)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
security = HTTPBasic(auto_error=False)


def require_auth(request: Request,
                 creds: HTTPBasicCredentials | None = Depends(security)) -> None:
    """Basic auth when APP_PASSWORD is set: the app can place real phone calls."""
    if not settings.app_password or request.url.path == "/healthz":
        return
    if not (creds and secrets.compare_digest(creds.password, settings.app_password)):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    yield


app = FastAPI(title="KeyHunt", lifespan=lifespan, dependencies=[Depends(require_auth)])

# Sidebar tabs: (path, label, icon). A tab shows up once its route exists.
NAV = [("/", "Searches", "list"), ("/searches/new", "New search", "plus"),
       ("/applications", "Applications", "clipboard"), ("/connections", "Connections", "plug")]


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
templates.env.globals.update(nav_items=nav_items, recent_searches=recent_searches,
                             settings=settings)


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
    return templates.TemplateResponse(request, "index.html", {
        "searches": searches, "settings": settings,
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
):
    criteria = SearchCriteria(
        city=city, max_price=max_price, min_price=min_price, min_beds=min_beds,
        min_baths=min_baths, neighborhoods=_split(neighborhoods),
        must_haves=_split(must_haves), move_in_by=move_in_by or None,
        tour_availability=_split(tour_availability),
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
    in_flight = row["status"] in ("pending", "sourcing", "calling") or any(
        c["status"] in ("queued", "in_progress") for c in calls.values())
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
        "outcomes": outcomes, "tours": tours, "refresh": in_flight, "settings": settings,
        "pins": pins, "center": geo.cached(criteria.city), "counts": counts,
        "tracked": tracked, "stages": AppStage,
    })


@app.post("/searches/{search_id}/listings/{key}/call")
def call_listing(background: BackgroundTasks, search_id: int, key: str):
    existing = db.calls_for_search(search_id).get(key)
    if existing and existing["status"] in ("queued", "in_progress"):
        raise HTTPException(409, "call already in progress")
    background.add_task(pipeline.call_listing, search_id, key)
    return RedirectResponse(f"/searches/{search_id}", status_code=303)


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

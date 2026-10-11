"""FastAPI web app: create a search, watch it run, approve calls, download tour invites."""

from __future__ import annotations

import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from househunt import db, pipeline
from househunt.config import settings
from househunt.models import ListingStatus, SearchCriteria
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


app = FastAPI(title="househunt", lifespan=lifespan, dependencies=[Depends(require_auth)])


def _split(s: str) -> list[str]:
    return [x.strip() for x in s.replace("\n", ",").split(",") if x.strip()]


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    searches = [(r, json.loads(r["criteria"])) for r in db.list_searches()]
    return templates.TemplateResponse(request, "index.html", {
        "searches": searches, "settings": settings,
    })


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
    in_flight = row["status"] in ("pending", "sourcing", "calling") or any(
        c["status"] in ("queued", "in_progress") for c in calls.values())
    order = [ListingStatus.TOUR_SCHEDULED, ListingStatus.VIABLE, ListingStatus.CONTACTED,
             ListingStatus.CANDIDATE, ListingStatus.NOT_VIABLE, ListingStatus.FILTERED_OUT]
    listings.sort(key=lambda l: (order.index(l.status) if l.status in order else 99, -l.score))
    return templates.TemplateResponse(request, "search.html", {
        "search": row, "criteria": criteria, "listings": listings, "calls": calls,
        "outcomes": outcomes, "tours": tours, "refresh": in_flight, "settings": settings,
    })


@app.post("/searches/{search_id}/listings/{key}/call")
def call_listing(background: BackgroundTasks, search_id: int, key: str):
    existing = db.calls_for_search(search_id).get(key)
    if existing and existing["status"] in ("queued", "in_progress"):
        raise HTTPException(409, "call already in progress")
    background.add_task(pipeline.call_listing, search_id, key)
    return RedirectResponse(f"/searches/{search_id}", status_code=303)


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

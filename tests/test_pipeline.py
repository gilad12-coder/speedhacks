import os

import pytest


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CALL_MODE", "dry_run")
    monkeypatch.setenv("MOCK_SOURCES", "1")
    monkeypatch.setenv("GEOCODE", "0")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    import importlib
    import househunt.config
    importlib.reload(househunt.config)
    for mod in ["househunt.db", "househunt.geo", "househunt.pipeline", "househunt.web.app"]:
        import sys
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])


def test_extract_phone():
    from househunt.collect import extract_phone
    assert extract_phone("Call (415) 555-0199 today") == "+14155550199"
    assert extract_phone("no number here") is None


def test_collect_filters_and_scores():
    from househunt.collect import collect
    from househunt.models import ListingStatus, SearchCriteria
    from househunt.sources import ALL_SOURCES

    c = SearchCriteria(city="sf", max_price=3000, min_beds=1, must_haves=["laundry"])
    raw = [l for cls in ALL_SOURCES for l in cls(mock=True).search(c)]
    out = collect(raw, c)
    statuses = {l.key: l.status for l in out}
    assert statuses["zillow:z-1002"] == ListingStatus.FILTERED_OUT  # over budget
    assert statuses["craigslist:cl-7781"] == ListingStatus.CANDIDATE
    cl = next(l for l in out if l.key == "craigslist:cl-7781")
    assert cl.contact.phone == "+15555550199"  # pulled from description


def test_end_to_end_dry_run():
    from househunt import db, pipeline
    from househunt.models import ListingStatus, SearchCriteria

    db.init()
    sid = db.create_search(SearchCriteria(city="sf", max_price=3000, min_beds=1,
                                          tour_availability=["Thursday evening"]))
    pipeline.run_search(sid)

    _, row = db.get_search(sid)
    assert row["status"] == "done"
    listings = {l.key: l for l in db.list_listings(sid)}
    calls = db.calls_for_search(sid)
    assert calls, "dry run should place fake calls"
    for key, call in calls.items():
        assert call["status"] == "ended"
        assert listings[key].status in (ListingStatus.VIABLE, ListingStatus.TOUR_SCHEDULED)


def test_web_flow():
    from fastapi.testclient import TestClient
    from househunt.web.app import app

    with TestClient(app) as client:
        r = client.post("/searches", data={"city": "sf", "max_price": 3000, "min_beds": 1},
                        follow_redirects=False)
        assert r.status_code == 303
        page = client.get(r.headers["location"])
        assert page.status_code == 200
        assert "Sunny 2BR" in page.text


def test_ics():
    from househunt.tours import to_ics
    ics = to_ics(1, "2026-10-15T18:00:00", "2BR, sunny", "1 Main St", "Jo", "http://x")
    assert "DTSTART:20261015T180000" in ics and "SUMMARY:Viewing: 2BR\\, sunny" in ics

"""The private API the household dashboard (Next.js) uses to work a household's search."""

import importlib
import sys

import pytest

KEY = "test-agent-key"
AUTH = {"Authorization": f"Bearer {KEY}"}
BASE = "/agent/households/hh_1"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CALL_MODE", "dry_run")
    monkeypatch.setenv("MOCK_SOURCES", "1")
    monkeypatch.setenv("GEOCODE", "0")
    monkeypatch.setenv("AGENT_API_KEY", KEY)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("RUN_PLATFORM_WORKER", raising=False)
    import househunt.config
    importlib.reload(househunt.config)
    for mod in ["househunt.db", "househunt.geo", "househunt.chat", "househunt.briefing",
                "househunt.phone", "househunt.pipeline", "househunt.web.household_api",
                "househunt.web.app"]:
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from househunt import db, pipeline
    from househunt.models import SearchCriteria
    from househunt.web.app import app

    with TestClient(app) as c:
        sid = db.create_search(SearchCriteria(city="sf", max_price=3000, min_beds=1))
        with db.conn() as conn:
            conn.execute("INSERT INTO household_jobs(household_id, search_id) VALUES (?, ?)",
                         ("hh_1", sid))
        pipeline.run_search(sid)
        yield c


def cards(client):
    r = client.get(f"{BASE}/workspace", headers=AUTH)
    assert r.status_code == 200
    return {l["id"]: l for l in r.json()["listings"]}


def test_requires_agent_key(client):
    assert client.get(f"{BASE}/workspace").status_code == 401
    assert client.get(f"{BASE}/workspace", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/agent/households/hh_other/workspace", headers=AUTH).status_code == 404


def test_workspace_shape(client):
    r = client.get(f"{BASE}/workspace", headers=AUTH).json()
    assert r["search"]["status"] == "done" and r["search"]["criteria"]["max_price"] == 3000
    fb = {l["id"]: l for l in r["listings"]}["facebook:fb-42"]
    assert fb["source"] == "facebook" and fb["interested"] is None and fb["nextStep"] is None
    assert r["callingEnabled"] is False  # dry run


def test_contact_interest_next_step_and_viewing(client):
    r = client.post(f"{BASE}/listings/facebook:fb-42/contact", headers=AUTH,
                    json={"pasted": "show contact info (510) 513-6710"})
    assert r.status_code == 200
    assert cards(client)["facebook:fb-42"]["contact"]["phone"] == "+15105136710"
    assert client.post(f"{BASE}/listings/facebook:fb-42/contact", headers=AUTH,
                       json={"pasted": "nothing here"}).status_code == 400

    client.post(f"{BASE}/listings/facebook:fb-42/interested", headers=AUTH)
    card = cards(client)["facebook:fb-42"]
    assert card["interested"] == "interested"
    assert card["nextStep"]["action"] == "call"

    client.post(f"{BASE}/listings/facebook:fb-42/viewing", headers=AUTH,
                json={"start": "2026-10-20T18:30"})
    card = cards(client)["facebook:fb-42"]
    assert card["status"] == "tour_scheduled" and card["interested"] == "viewing"
    assert card["viewing"]["start"] == "2026-10-20T18:30"
    assert "calendar.google.com" in card["viewing"]["calendarUrl"]
    assert card["nextStep"]["action"] == "prepare"


def test_email_draft_edit_and_mark_sent(client):
    r = client.post(f"{BASE}/listings/zillow:z-1001/email", headers=AUTH)
    email_id = r.json()["id"]
    assert client.post(f"{BASE}/listings/zillow:z-1001/email", headers=AUTH).json()["id"] == email_id
    email = cards(client)["zillow:z-1001"]["email"]
    assert email["status"] == "draft" and "123 Main St" in email["subject"]

    client.post(f"{BASE}/emails/{email_id}", headers=AUTH,
                json={"action": "sent", "to": "agent@x.com", "subject": "Hi", "body": "Edited"})
    email = cards(client)["zillow:z-1001"]["email"]
    assert (email["status"], email["to"], email["body"]) == ("sent", "agent@x.com", "Edited")
    # Another household can't touch this email.
    assert client.post(f"/agent/households/hh_other/emails/{email_id}", headers=AUTH,
                       json={"action": "discard"}).status_code == 404


def test_add_listing_and_refine(client):
    r = client.post(f"{BASE}/listings", headers=AUTH, json={
        "url": "https://www.zillow.com/homedetails/9-Elm-St/777_zpid/", "price": "$2,900",
        "beds": "2", "pasted": "Agent: 415.555.0188"})
    assert r.json()["id"] == "zillow:777"
    z = cards(client)["zillow:777"]
    assert (z["price"], z["beds"], z["contact"]["phone"]) == (2900, 2, "+14155550188")

    r = client.post(f"{BASE}/criteria", headers=AUTH, json={
        "neighborhoods": ["Mission"], "must_haves": ["laundry"], "max_price": 3200, "min_beds": 1})
    assert r.status_code == 200
    ws = client.get(f"{BASE}/workspace", headers=AUTH).json()
    assert ws["search"]["criteria"]["neighborhoods"] == ["Mission"]
    assert ws["search"]["criteria"]["max_price"] == 3200
    assert ws["search"]["status"] == "done"          # re-ran in the background task
    assert "zillow:777" in {l["id"] for l in ws["listings"]}   # pasted listing kept


def test_start_creates_search_from_brief(client, monkeypatch):
    from househunt import db, platform

    brief = {"householdId": "hh_2", "occupants": 2, "location": "San Francisco",
             "maxTotalRentUsd": 5200, "moveInFrom": "2026-11-01", "moveInTo": "2026-12-01",
             "commute": {}, "mustHaves": [], "dealBreakers": [], "niceToHaves": [],
             "householdIncomeBandUsd": {"min": 0, "max": 0}, "wishes": []}

    class FakeClient:
        def briefs(self):
            return [brief]

        def publish(self, household_id, search_id):
            pass

    monkeypatch.setattr(platform, "PlatformClient", FakeClient)
    r = client.post("/agent/households/hh_2/start", headers=AUTH)
    assert r.status_code == 200 and db.household_search("hh_2") == r.json()["searchId"]
    assert client.post("/agent/households/hh_2/start", headers=AUTH).json() == r.json()
    assert client.post("/agent/households/hh_none/start", headers=AUTH).status_code == 404

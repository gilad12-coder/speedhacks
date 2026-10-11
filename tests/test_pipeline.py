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


def test_pages_and_application_board():
    from fastapi.testclient import TestClient

    from househunt import db, pipeline
    from househunt.models import SearchCriteria
    from househunt.web.app import app

    with TestClient(app) as client:
        sid = db.create_search(SearchCriteria(city="sf", max_price=3000, min_beds=1))
        pipeline.run_search(sid)
        for path in ["/", "/searches/new", f"/searches/{sid}", "/applications"]:
            r = client.get(path)
            assert r.status_code == 200, path
            assert "KeyHunt" in r.text

        key = db.list_listings(sid)[0].key
        client.post(f"/searches/{sid}/listings/{key}/track")
        client.post(f"/searches/{sid}/listings/{key}/track")  # tracking twice is a no-op
        apps = db.list_applications()
        assert len(apps) == 1 and apps[0]["stage"] == "interested"

        r = client.post(f"/applications/{apps[0]['id']}", data={"stage": "applied"},
                        headers={"x-requested-with": "fetch"})
        assert r.json() == {"ok": True}
        row = db.get_application(apps[0]["id"])
        assert row["stage"] == "applied" and row["applied_at"]

        client.post("/applications", data={"title": "Place from a friend", "price": "$2,900",
                                           "stage": "viewing"})
        assert {a["title"]: a["price"] for a in db.list_applications()}["Place from a friend"] == 2900
        page = client.get("/applications").text
        assert "Place from a friend" in page and "You are here" in page
        assert f"/applications#app-{apps[0]['id']}" in client.get(f"/searches/{sid}").text


def test_viewing_booked_lands_on_board():
    from househunt import db, pipeline
    from househunt.models import Listing, SearchCriteria, Source

    db.init()
    sid = db.create_search(SearchCriteria(city="sf", max_price=3000))
    l = Listing(source=Source.ZILLOW, source_id="1", url="https://x", title="Nice 1BR", price=2500)
    db.upsert_listing(sid, l)
    pipeline.track_viewing(sid, l, "2026-10-15T18:00")
    (a,) = db.list_applications()
    assert a["stage"] == "viewing" and a["next_date"] == "2026-10-15T18:00"


ZILLOW_ALERT = """
<table>
  <tr><td>
    <a href="https://www.zillow.com/homedetails/123-Main-St-San-Francisco-CA-94110/15012345_zpid/?utm=x"><img src="p.jpg"></a>
    <div>$2,950/mo</div><div>2 bds | 1 ba | 850 sqft</div>
    <a href="https://www.zillow.com/homedetails/123-Main-St-San-Francisco-CA-94110/15012345_zpid/">123 Main St, San Francisco, CA 94110</a>
  </td></tr>
  <tr><td>
    <a href="https://click.mail.zillow.com/x?url=https%3A%2F%2Fwww.zillow.com%2Fhomedetails%2FStudio%2F999_zpid%2F">View</a>
    <div>$1,800/mo</div><div>Studio | 1 ba</div>
  </td></tr>
  <tr><td><a href="https://www.zillow.com/myzillow/">Manage alerts</a></td></tr>
</table>
"""


def test_parse_zillow_alert():
    from househunt.sources.email_alerts import parse_alert

    out = {l.source_id: l for l in parse_alert(ZILLOW_ALERT, "Zillow <alerts@mail.zillow.com>",
                                               resolve_redirects=False)}
    assert set(out) == {"15012345", "999"}
    a = out["15012345"]
    assert (a.price, a.beds, a.baths, a.sqft) == (2950, 2, 1.0, 850)
    assert a.address == "123 Main St, San Francisco, CA 94110"
    assert out["999"].beds == 0 and out["999"].price == 1800
    assert parse_alert(ZILLOW_ALERT, "someone@gmail.com") == []


def test_connections_page():
    from fastapi.testclient import TestClient
    from househunt.web.app import app

    with TestClient(app) as client:
        page = client.get("/connections")
        assert page.status_code == 200
        assert "isn't set up on this server" in page.text  # no GOOGLE_CLIENT_ID in tests
        assert "/auth/google/callback" in page.text


def test_email_requires_approval(monkeypatch):
    from fastapi.testclient import TestClient
    from househunt import db
    from househunt.connectors import google
    from househunt.web.app import app

    sent = []
    monkeypatch.setattr(google, "has_scope", lambda scope: True)
    monkeypatch.setattr(google, "send_email",
                        lambda to, subject, body: sent.append(to) or {"id": "m1", "threadId": "t1"})

    with TestClient(app) as client:
        r = client.post("/searches", data={"city": "sf", "max_price": 3000, "min_beds": 1})
        sid = int(r.url.path.rsplit("/", 1)[-1])
        r = client.post(f"/searches/{sid}/listings/zillow:z-1001/email", follow_redirects=False)
        email_id = int(r.headers["location"].rsplit("/", 1)[-1])
        draft = db.get_email(email_id)
        assert draft["status"] == "draft" and "123 Main St" in draft["subject"]

        # Saving never sends.
        client.post(f"/emails/{email_id}", data={"action": "save", "to_addr": "a@b.com",
                                                  "subject": "Hi", "body": "Edited"})
        assert sent == [] and db.get_email(email_id)["body"] == "Edited"

        # Sending without a valid address is refused.
        client.post(f"/emails/{email_id}", data={"action": "send", "to_addr": "nope",
                                                  "subject": "Hi", "body": "Edited"})
        assert sent == [] and db.get_email(email_id)["status"] == "draft"

        client.post(f"/emails/{email_id}", data={"action": "send", "to_addr": "agent@x.com",
                                                  "subject": "Hi", "body": "Edited"})
        assert sent == ["agent@x.com"]
        e = db.get_email(email_id)
        assert e["status"] == "sent" and e["gmail_thread_id"] == "t1"

        # A sent email can't be sent again.
        client.post(f"/emails/{email_id}", data={"action": "send", "to_addr": "agent@x.com",
                                                  "subject": "Hi", "body": "Edited"})
        assert sent == ["agent@x.com"]


def test_email_extracted_from_description():
    from househunt.collect import normalize
    from househunt.models import Listing, Source

    l = normalize(Listing(source=Source.CRAIGSLIST, source_id="1", url="u", title="t",
                          description="Email jo.agent+rent@realty.co for showings"))
    assert l.contact.email == "jo.agent+rent@realty.co"


def test_normalize_phone_and_email():
    import pytest as _pytest
    from househunt.manual import InvalidInput, normalize_email, normalize_phone

    assert normalize_phone("(415) 555-0199") == "+14155550199"
    assert normalize_phone("1-415-555-0199") == "+14155550199"
    assert normalize_phone("") is None
    with _pytest.raises(InvalidInput):
        normalize_phone("555-01")
    assert normalize_email(" a@b.co ") == "a@b.co"
    with _pytest.raises(InvalidInput):
        normalize_email("not-an-email")


def test_add_contact_and_listing_by_hand():
    from fastapi.testclient import TestClient
    from househunt import db
    from househunt.models import ListingStatus, Source
    from househunt.web.app import app

    with TestClient(app) as client:
        r = client.post("/searches", data={"city": "sf", "max_price": 3000, "min_beds": 1})
        sid = int(r.url.path.rsplit("/", 1)[-1])

        # Contact added to a listing that had none makes it callable/emailable.
        fb = db.get_listing(sid, "facebook:fb-42")
        assert not (fb.contact and fb.contact.phone)
        r = client.post(f"/searches/{sid}/listings/facebook:fb-42/contact",
                        data={"phone": "(415) 555-0123", "email": "seller@x.com"},
                        follow_redirects=False)
        assert r.status_code == 303
        fb = db.get_listing(sid, "facebook:fb-42")
        assert (fb.contact.phone, fb.contact.email) == ("+14155550123", "seller@x.com")
        assert "Call" in client.get(f"/searches/{sid}").text

        bad = client.post(f"/searches/{sid}/listings/facebook:fb-42/contact",
                          data={"phone": "12"}, follow_redirects=False)
        assert bad.status_code == 400

        # Paste a Zillow link with details; it's kept even when outside the criteria.
        url = "https://www.zillow.com/homedetails/9-Elm-St-San-Francisco-CA/777_zpid/"
        r = client.post(f"/searches/{sid}/listings", data={
            "url": url, "price": "$3,400", "beds": "2", "address": "9 Elm St, San Francisco, CA",
            "phone": "415.555.0188"}, follow_redirects=False)
        assert r.status_code == 303
        z = db.get_listing(sid, "zillow:777")
        assert z.source == Source.ZILLOW and z.price == 3400 and z.beds == 2
        assert z.status == ListingStatus.CANDIDATE and z.contact.phone == "+14155550188"
        assert any("outside your search" in n for n in z.notes)

        # Pasting the same link again only updates the contact.
        client.post(f"/searches/{sid}/listings", data={"url": url, "email": "agent@z.com"})
        z = db.get_listing(sid, "zillow:777")
        assert z.contact.email == "agent@z.com" and z.price == 3400

        assert client.post(f"/searches/{sid}/listings", data={"url": "not a link"},
                           follow_redirects=False).status_code == 400

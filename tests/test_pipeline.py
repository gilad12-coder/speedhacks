import os

import pytest


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CALL_MODE", "dry_run")
    monkeypatch.setenv("MOCK_SOURCES", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    import importlib
    import househunt.config
    importlib.reload(househunt.config)
    for mod in ["househunt.db", "househunt.pipeline", "househunt.web.app"]:
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

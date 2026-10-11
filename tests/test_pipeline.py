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
    for mod in ["househunt.db", "househunt.geo", "househunt.chat", "househunt.briefing", "househunt.phone", "househunt.pipeline", "househunt.web.app"]:
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


def test_neighborhood_matching():
    from househunt.collect import mentions_neighborhood
    from househunt.models import Listing, Source

    def l(**kw):
        return Listing(source=Source.CRAIGSLIST, source_id="x", url="u", title=kw.pop("title", ""), **kw)

    assert mentions_neighborhood(l(neighborhood="mission district"), ["Mission"])
    assert mentions_neighborhood(l(neighborhood="San Francisco, CA",
                                   description="Sunny flat in the heart of the Mission"), ["mission"])
    assert not mentions_neighborhood(l(address="1045 Mission St", neighborhood="SOMA"), ["Mission"])
    assert mentions_neighborhood(l(title="Noe Valley 1BR"), ["Mission", "Noe Valley"])
    assert not mentions_neighborhood(l(title="Oakland loft"), ["Mission"])


def test_craigslist_site_and_query():
    from househunt.sources.craigslist import neighborhood_query, site_for

    assert site_for("San Francisco") == ("sfbay", "sfc")
    assert site_for("Portland") == ("portland", None)
    assert neighborhood_query(["Mission", "Noe Valley"]) == 'mission|"noe valley"'
    assert neighborhood_query([]) is None


FB_EMAIL = """
<table><tr><td>
  <a href="https://www.facebook.com/groups/sfhousing/posts/987654321/?ref=notif">
    Jane posted in SF Housing</a>
  <div>Room available in 2BR in the Mission, $1,650/mo, utilities included. Available Nov 1.
    Text 415-555-0142.</div>
</td></tr><tr><td>
  <a href="https://www.facebook.com/groups/sfhousing/posts/111/">Selling my couch, great condition!</a>
</td></tr></table>
"""


def test_parse_facebook_group_email():
    from househunt.collect import normalize
    from househunt.sources.email_alerts import parse_alert

    out = parse_alert(FB_EMAIL, "Facebook <notification@facebookmail.com>")
    assert [l.source_id for l in out] == ["987654321"]  # the couch isn't housing
    post = normalize(out[0])
    assert post.price == 1650 and post.beds == 2
    assert post.url == "https://www.facebook.com/groups/sfhousing/posts/987654321/"
    assert post.contact.phone == "+14155550142"


def test_facebook_links():
    from househunt.facebook import links
    from househunt.models import SearchCriteria

    out = dict(links(SearchCriteria(city="San Francisco", max_price=3500, neighborhoods=["Mission"])))
    assert out["Marketplace rentals"] == \
        "https://www.facebook.com/marketplace/sanfrancisco/propertyrentals?maxPrice=3500"
    assert "query=Mission+apartment" in out["Marketplace: Mission"]
    assert out["Groups: San Francisco housing"].endswith("q=San%20Francisco%20housing")


def test_zillow_links():
    import json
    from urllib.parse import parse_qs, urlparse

    from househunt.facebook import zillow_links
    from househunt.models import SearchCriteria

    [(label, url)] = zillow_links(SearchCriteria(city="San Francisco", max_price=3500,
                                                 min_beds=1, neighborhoods=["Mission"]))
    assert label == "Zillow: Mission, San Francisco"
    assert urlparse(url).path == "/homes/for_rent/Mission-San-Francisco_rb/"
    state = json.loads(parse_qs(urlparse(url).query)["searchQueryState"][0])
    assert state["filterState"]["fr"] == {"value": True}           # rentals only
    assert state["filterState"]["mp"] == {"max": 3500}
    assert state["filterState"]["beds"] == {"min": 1}
    assert len(zillow_links(SearchCriteria(city="Oakland", max_price=3000))) == 1


def test_paste_contact_from_listing():
    from fastapi.testclient import TestClient
    from househunt import db
    from househunt.web.app import app

    with TestClient(app) as client:
        r = client.post("/searches", data={"city": "sf", "max_price": 3000, "min_beds": 1})
        sid = int(r.url.path.rsplit("/", 1)[-1])
        page = client.get(f"/searches/{sid}").text
        assert "Get the number to call" in page and "Reveal on Facebook" in page

        client.post(f"/searches/{sid}/listings/facebook:fb-42/contact",
                    data={"pasted": "show contact info\n(510) 513-6710 ask for Jo"})
        fb = db.get_listing(sid, "facebook:fb-42")
        assert fb.contact.phone == "+15105136710"
        assert "Get the number to call" not in client.get(f"/searches/{sid}").text.split(
            'id="facebook:fb-42"')[1].split("</article>")[0]

        bad = client.post(f"/searches/{sid}/listings/facebook:fb-42/contact",
                          data={"pasted": "no contact here"}, follow_redirects=False)
        assert bad.status_code == 400


def test_firecrawl_fills_pasted_listing(monkeypatch):
    import httpx
    from househunt import firecrawl
    from househunt.manual import listing_from_url
    from househunt.models import SearchCriteria, Source

    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(json)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"data": {"json": {
            "title": "Bright 1BR at The Valencia", "monthly_rent": 3100, "bedrooms": 1,
            "bathrooms": 1, "address": "1 Valencia St, San Francisco, CA",
            "summary": "Top floor, in-unit laundry.", "available_date": "Nov 1",
            "contact_phone": "(415) 555-0177", "contact_email": "leasing@valencia.example"}}})

    monkeypatch.setattr(firecrawl, "configured", lambda: True)
    monkeypatch.setattr(firecrawl.httpx, "post", fake_post)

    c = SearchCriteria(city="San Francisco", max_price=3500, min_beds=1)
    l = listing_from_url("https://valenciaapts.example/units/4b", c)
    assert l.source == Source.OTHER
    assert (l.title, l.price, l.beds, l.address) == (
        "Bright 1BR at The Valencia", 3100, 1, "1 Valencia St, San Francisco, CA")
    assert l.contact.phone == "+14155550177" and l.contact.email == "leasing@valencia.example"
    assert "Available: Nov 1" in l.description
    # Only basic proxies, no scripted clicks.
    assert sent[0]["proxy"] == "basic" and "actions" not in sent[0]

    # What the renter typed wins over the extraction.
    l2 = listing_from_url("https://valenciaapts.example/units/4b", c, price=2900, phone="4155550100")
    assert l2.price == 2900 and l2.contact.phone == "+14155550100"

    # Zillow / Facebook are never sent to Firecrawl.
    sent.clear()
    listing_from_url("https://www.zillow.com/homedetails/x/1_zpid/", c)
    listing_from_url("https://www.facebook.com/marketplace/item/9/", c)
    assert sent == []
class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}


class _FakeStream:
    def __init__(self, final, chunks):
        self.final, self.text_stream = final, iter(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.final


class _FakeClaude:
    """Turn 1: save a note via the tool. Turn 2 (after the tool result): reply in text."""

    def __init__(self):
        self.requests = []
        self.beta = self
        self.messages = self

    def stream(self, **kw):
        self.requests.append(kw)
        if len(self.requests) == 1:
            final = _Block(stop_reason="tool_use", content=[
                _Block(type="text", text="Noted."),
                _Block(type="tool_use", id="tu1", name="save_note",
                       input={"note": "Ask whether street noise is a problem at night"})])
            return _FakeStream(final, ["Noted."])
        final = _Block(stop_reason="end_turn",
                       content=[_Block(type="text", text="I'll raise it on the next call.")])
        return _FakeStream(final, ["I'll raise it ", "on the next call."])


def _events(resp):
    import json
    return [json.loads(line) for line in resp.text.splitlines() if line]


def test_place_chat_saves_notes_that_calls_use(monkeypatch):
    from fastapi.testclient import TestClient

    from househunt import chat, db, llm, pipeline
    from househunt.models import SearchCriteria
    from househunt.outreach.script import build_instruction
    from househunt.web.app import app

    fake = _FakeClaude()
    monkeypatch.setattr(llm, "has_credentials", lambda: True)
    monkeypatch.setattr(llm, "client", lambda: fake)

    with TestClient(app) as client:
        sid = db.create_search(SearchCriteria(city="sf", max_price=3000, min_beds=1))
        pipeline.run_search(sid)
        key = "zillow:z-1001"
        r = client.post(f"/searches/{sid}/listings/{key}/chat", follow_redirects=False)
        chat_id = int(r.headers["location"].rsplit("/", 1)[-1])
        # Same place, same chat.
        r2 = client.post(f"/searches/{sid}/listings/{key}/chat", follow_redirects=False)
        assert r2.headers["location"] == r.headers["location"]

        events = _events(client.post(f"/chats/{chat_id}/messages",
                                     data={"message": "I'm worried it's noisy at night"}))
        assert {"t": "note", "v": "Ask whether street noise is a problem at night"}.items() <= \
            next(e for e in events if e["t"] == "note").items()
        assert events[-1] == {"t": "done"}
        assert "on the next call." in "".join(e["v"] for e in events if e["t"] == "text")

        # The first request carried the user's message followed by a fresh context snapshot.
        first = fake.requests[0]["messages"]
        assert [m["role"] for m in first] == ["user", "system"]
        assert "Sunny 2BR near the park" in first[1]["content"]
        # The second request echoed the tool call and its result.
        second = fake.requests[1]["messages"]
        assert second[-1]["content"][0]["type"] == "tool_result"

        notes = db.place_notes(sid, key)
        assert notes == ["Ask whether street noise is a problem at night"]
        listing, (criteria, _) = db.get_listing(sid, key), db.get_search(sid)
        assert "street noise" in build_instruction(listing, criteria, "Lucy", notes)

        # Notes show on the card, the chat page, and can be edited.
        assert "street noise" in client.get(f"/searches/{sid}").text
        assert "street noise" in client.get(f"/chats/{chat_id}").text
        r = client.post(f"/places/{sid}/{key}/notes/add", data={"note": "Parking included?"})
        assert r.json()["added"] and len(r.json()["notes"]) == 2
        client.post(f"/places/{sid}/{key}/notes", data={"notes": "Parking included?"},
                    headers={"x-requested-with": "fetch"})
        assert db.place_notes(sid, key) == ["Parking included?"]

        # A second turn only re-sends context when it changed (the notes did).
        client.post(f"/chats/{chat_id}/messages", data={"message": "thanks"})
        roles = [m["role"] for m in fake.requests[-1]["messages"]]
        assert roles.count("system") == 2 and roles[-1] == "system"


def test_chat_without_key_keeps_history_valid(monkeypatch):
    from fastapi.testclient import TestClient

    from househunt import db, llm
    from househunt.web.app import app

    monkeypatch.setattr(llm, "has_credentials", lambda: False)
    with TestClient(app) as client:
        r = client.get("/chats/agent", follow_redirects=False)
        chat_id = int(r.headers["location"].rsplit("/", 1)[-1])
        events = _events(client.post(f"/chats/{chat_id}/messages", data={"message": "hi"}))
        assert events[0]["t"] == "error" and "ANTHROPIC_API_KEY" in events[0]["v"]
        assert [m["role"] for m in db.chat_messages(chat_id)] == ["user", "system", "assistant"]
        assert client.get(f"/chats/{chat_id}").status_code == 200


def test_calls_and_viewings_pages():
    from fastapi.testclient import TestClient

    from househunt import db, pipeline
    from househunt.models import SearchCriteria
    from househunt.web.app import app

    with TestClient(app) as client:
        assert "No calls yet" in client.get("/calls").text
        sid = db.create_search(SearchCriteria(city="sf", max_price=3000, min_beds=1))
        pipeline.run_search(sid)
        page = client.get("/calls").text
        assert "Sunny 2BR near the park" in page and "Discuss" in page
        assert client.get("/viewings").status_code == 200
        apps = client.get("/applications").text
        assert 'href="/calls"' in apps and 'href="/viewings"' in apps


def test_next_step_rules():
    import json as _json

    from househunt.models import Contact, Listing, Source
    from househunt.next_step import gcal_link, recommend

    def l(**kw):
        return Listing(source=kw.pop("source", Source.CRAIGSLIST), source_id="1", url="https://x/1",
                       title="1BR", **kw)

    assert recommend(l()).action == "reveal"
    assert recommend(l(source=Source.FACEBOOK)).action == "message"
    assert recommend(l(contact=Contact(phone="+14155550100"))).action == "call"
    assert recommend(l(contact=Contact(email="a@b.co"))).action == "email"
    assert recommend(l(tour_url="https://x/tour")).action == "book_online"

    viable = {"status": "ended", "outcome": _json.dumps(
        {"viable": True, "offered_times": ["Thu 6pm"], "summary": "ok"})}
    assert recommend(l(contact=Contact(phone="+1")), call=viable).action == "log_viewing"
    dead = {"status": "ended", "outcome": _json.dumps({"viable": False, "verification_status": "ruled_out", "summary": "Rented."})}
    ns = recommend(l(), call=dead)
    assert ns.action == "move_on" and ns.why == "Rented."
    unknown = {"status": "ended", "outcome": _json.dumps({"viable": False, "verification_status": "unconfirmed", "summary": "Financial qualifications unknown."})}
    assert recommend(l(), call=unknown).action == "wait"
    assert recommend(l(), call={"status": "in_progress", "outcome": None}).action == "wait"
    tour = {"start": "2026-10-15T18:30"}
    ns = recommend(l(address="1 Main St"), tour=tour)
    assert ns.action == "prepare" and "dates=20261015T183000%2F20261015T190000" in ns.href
    assert gcal_link("x", "not a date", None, None) is None


def test_edit_search_keeps_progress():
    from fastapi.testclient import TestClient
    from househunt import db
    from househunt.models import ListingStatus
    from househunt.web.app import app

    with TestClient(app) as client:
        r = client.post("/searches", data={"city": "sf", "max_price": 3000, "min_beds": 1})
        sid = int(r.url.path.rsplit("/", 1)[-1])
        # Dry run already "called" the callable ones; add a contact + interest to another.
        client.post(f"/searches/{sid}/listings/facebook:fb-42/contact", data={"pasted": "a@b.co"})
        client.post(f"/searches/{sid}/listings/facebook:fb-42/track")
        before = {l.key: l for l in db.list_listings(sid)}
        called = [k for k, l in before.items() if l.status == ListingStatus.VIABLE]
        assert called

        assert client.get(f"/searches/{sid}/edit").status_code == 200
        # Tighten to 3+ beds and re-run: unprogressed 1-2 bed places drop out, progress stays.
        client.post(f"/searches/{sid}/edit", data={
            "city": "sf", "max_price": 3000, "min_beds": 3, "rerun": "1"})
        crit, row = db.get_search(sid)
        assert crit.min_beds == 3 and row["status"] == "done"
        after = {l.key: l for l in db.list_listings(sid)}
        unprogressed = [k for k, l in before.items() if l.status == ListingStatus.CANDIDATE
                        and k != "facebook:fb-42"]
        for k in unprogressed:
            assert after[k].status == ListingStatus.FILTERED_OUT
            assert any("beds <" in n for n in after[k].notes)
        for k in called:
            assert after[k].status == ListingStatus.VIABLE                 # progress kept
        assert after["facebook:fb-42"].contact.email == "a@b.co"
        assert db.find_application(sid, "facebook:fb-42")


def test_interested_next_step_and_log_viewing():
    from fastapi.testclient import TestClient
    from househunt import db
    from househunt.models import ListingStatus
    from househunt.web.app import app

    with TestClient(app) as client:
        r = client.post("/searches", data={"city": "sf", "max_price": 3000, "min_beds": 1})
        sid = int(r.url.path.rsplit("/", 1)[-1])
        assert "I&#39;m interested" in client.get(f"/searches/{sid}").text \
            or "I'm interested" in client.get(f"/searches/{sid}").text
        client.post(f"/searches/{sid}/listings/facebook:fb-42/track")
        card = client.get(f"/searches/{sid}").text.split('id="facebook:fb-42"')[1].split("</article>")[0]
        assert "Recommended next step" in card and "Message the seller on Facebook" in card

        client.post(f"/searches/{sid}/listings/facebook:fb-42/viewing", data={"start": "2026-10-20T18:30"})
        assert db.get_listing(sid, "facebook:fb-42").status == ListingStatus.TOUR_SCHEDULED
        assert db.tours_for_search(sid)["facebook:fb-42"]["start"] == "2026-10-20T18:30"
        assert db.find_application(sid, "facebook:fb-42")["stage"] == "viewing"
        page = client.get("/viewings").text
        assert "calendar.google.com/calendar/render" in page


def test_leads_track_outreach_and_can_be_removed():
    from fastapi.testclient import TestClient

    from househunt import db, leads, pipeline
    from househunt.models import SearchCriteria
    from househunt.web.app import app

    with TestClient(app) as client:
        assert "No leads right now" in client.get("/leads").text
        sid = db.create_search(SearchCriteria(city="sf", max_price=3000, min_beds=1))
        pipeline.run_search(sid)
        # Interested in a place nobody has called, and one the dry run already called.
        client.post(f"/searches/{sid}/listings/facebook:fb-42/track")
        client.post(f"/searches/{sid}/listings/zillow:z-1001/track")
        assert leads.outreach(sid, "facebook:fb-42").status == "new"
        called = leads.outreach(sid, "zillow:z-1001")
        assert called.attempts and called.attempts[0].kind == "call"

        page = client.get("/leads").text
        assert "Room in 3BR" in page and "Sunny 2BR" in page and "Remove from leads" in page

        # A failed call reads as "no response yet", with the API's message on the Calls page.
        cid = db.create_call(sid, "facebook:fb-42")
        db.update_call(cid, status="failed", error="""BadRequestError("Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Your credit balance is too low.'}}")""")
        o = leads.outreach(sid, "facebook:fb-42")
        assert o.status == "waiting" and "no response yet" in o.label
        assert "Your credit balance is too low." in client.get("/calls").text

        # Calling from Leads comes back to Leads.
        # (fb-42's last call failed, so a new one is allowed.)
        r = client.post(f"/searches/{sid}/listings/facebook:fb-42/call",
                        data={"next": "/leads"}, follow_redirects=False)
        assert r.headers["location"] == "/leads"
        r = client.post(f"/searches/{sid}/listings/facebook:fb-42/call",
                        data={"next": "https://evil.example"}, follow_redirects=False)
        assert r.headers["location"] == f"/searches/{sid}"

        app_id = db.find_application(sid, "facebook:fb-42")["id"]
        client.post(f"/leads/{app_id}/remove", data={"reason": "no_response", "detail": "3 tries"})
        row = db.get_application(app_id)
        assert row["stage"] == "withdrawn" and "No response (3 tries)" in row["notes"]
        page = client.get("/leads").text
        assert "Removed leads (1)" in page and 'id="lead-%d"' % app_id not in page

        client.post(f"/leads/{app_id}/restore")
        assert db.get_application(app_id)["stage"] == "interested"


class _FakeDialNumbers:
    def __init__(self):
        self.instruction = "Original greeting"
        self.patches, self.placed = [], []
        self.calls = []

    def own_number(self):
        return {"id": "pn_1", "number": "+14155550000", "inboundInstruction": self.instruction}

    def set_inbound_instruction(self, number_id, instruction):
        assert number_id == "pn_1"
        self.instruction = instruction
        self.patches.append(instruction)

    def inbound_calls(self, number_id=None, since=None):
        return self.calls

    def place_call(self, to, instruction, **kw):
        self.placed.append((to, instruction))
        return type("C", (), {"id": "call_x"})()


def test_flags_briefing_and_phone(monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    monkeypatch.setenv("BRIEFING_PIN", "4821")
    monkeypatch.setenv("NOTIFY_NUMBER", "+14155559999")
    monkeypatch.setenv("DIAL_API_KEY", "test")
    import househunt.config
    importlib.reload(househunt.config)
    import sys
    for mod in ["househunt.db", "househunt.flags", "househunt.briefing", "househunt.phone",
                "househunt.pipeline", "househunt.web.app"]:
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
    from househunt import briefing, db, flags, phone, pipeline
    from househunt.models import SearchCriteria
    from househunt.web.app import app

    fake = _FakeDialNumbers()
    monkeypatch.setattr(phone, "_client", lambda: fake)

    with TestClient(app) as client:
        sid = db.create_search(SearchCriteria(city="sf", max_price=3000, min_beds=1))
        pipeline.run_search(sid)
        # Interested in a place the dry-run call confirmed is available, but with no viewing.
        key = "craigslist:cl-7781"
        client.post(f"/searches/{sid}/listings/{key}/track")
        with db.conn() as c:
            c.execute("DELETE FROM tours WHERE listing_key = ?", (key,))
        client.post(f"/searches/{sid}/listings/zillow:z-1001/email")   # leaves a draft

        titles = [f.title for f in flags.compute()]
        assert any("is available: book a viewing" in t for t in titles)
        assert any(t.startswith("Approve your email") for t in titles)
        home = client.get("/").text
        assert "Needs you" in home and "book a viewing" in home

        facts = briefing.facts()
        assert "Search in sf" in facts and "Leads:" in facts and "Needs the renter's attention" in facts

        # Call me: an outbound call to the renter's phone with the briefing.
        client.post("/phone/call-me")
        assert fake.placed[0][0] == "+14155559999" and "FACTS:" in fake.placed[0][1]

        # Call-in: the passcode guards the facts; landlords only get a message-taker.
        client.post("/phone/enable")
        assert phone.enabled() and "4 8 2 1" in fake.instruction and "FACTS" in fake.instruction
        assert "take a message" in fake.instruction
        n = len(fake.patches)
        assert phone.sync() is False and len(fake.patches) == n   # unchanged facts, no re-push

        # A landlord calls back from the listing's number: it becomes a flag.
        listing = db.get_listing(sid, "zillow:z-1001")
        fake.calls = [{"id": "in1", "from": listing.contact.phone, "createdAt": "2026-10-11T15:00:00",
                       "transcript": "Caller: Hi, it's Jordan about 123 Main St, it's still available."},
                      {"id": "in2", "from": "+14155559999", "createdAt": "2026-10-11T15:05:00",
                       "transcript": "Renter checking in."}]
        assert phone.poll_inbound() == 2
        assert phone.poll_inbound() == 0                       # no duplicates
        flag = next(f for f in flags.compute() if "called back" in f.title)
        assert "Sunny 2BR" in flag.title and flag.href == "/phone#call-in1"
        page = client.get("/phone").text
        assert "about 123 Main St" in page and "Mark handled" in page
        client.post("/phone/calls/in1/handled")
        assert not any("called back" in f.title for f in flags.compute())

        client.post("/phone/disable")
        assert not phone.enabled() and fake.instruction == "Original greeting"


def test_inbound_without_pin_only_takes_messages():
    from househunt import briefing

    assert briefing.settings.briefing_pin is None   # not set in the test env
    text = briefing.inbound_instruction()
    assert "take a message" in text and "FACTS" not in text


def test_household_handoff_from_onboarding(monkeypatch):
    from fastapi.testclient import TestClient
    from househunt import db, platform
    from househunt.web.app import app

    brief = {"householdId": "hh_1", "occupants": 2, "location": "San Francisco",
             "maxTotalRentUsd": 5200, "moveInFrom": "2026-11-01", "moveInTo": "2026-12-01",
             "commute": {"destination": "SoMa", "mode": "bike", "modes": ["bike"], "maxMinutes": 30},
             "mustHaves": ["laundry"], "dealBreakers": [], "niceToHaves": [],
             "householdIncomeBandUsd": {"min": 150000, "max": 200000}, "wishes": []}
    published = []

    class FakeClient:
        def briefs(self):
            return [brief]

        def publish(self, household_id, search_id):
            published.append((household_id, search_id))

    monkeypatch.setattr(platform, "PlatformClient", FakeClient)
    with TestClient(app) as client:
        r = client.get("/households/hh_1", follow_redirects=False)
        assert r.status_code == 303
        sid = int(r.headers["location"].rsplit("/", 1)[-1])
        crit, row = db.get_search(sid)
        assert (crit.city, crit.max_price, crit.min_beds, crit.must_haves) == (
            "San Francisco", 5200, 2, ["laundry"])
        assert row["status"] == "pending"            # the worker runs it, not the handoff
        assert published == [("hh_1", sid)] and platform.wake.is_set()

        # Coming back goes to the same search; no duplicate is created.
        r2 = client.get("/households/hh_1", follow_redirects=False)
        assert r2.headers["location"] == f"/searches/{sid}"
        assert db.household_search("hh_1") == sid

        # A household whose brief isn't requested yet gets a waiting page.
        r3 = client.get("/households/hh_unknown", follow_redirects=False)
        assert r3.status_code == 202 and "Starting your search" in r3.text


def test_platform_client_vercel_bypass(monkeypatch):
    import httpx
    import pytest as _pytest
    from househunt import platform

    monkeypatch.setenv("APP_URL", "https://keyhunt.example.vercel.app")
    monkeypatch.setenv("AGENT_API_KEY", "k")
    monkeypatch.setenv("VERCEL_PROTECTION_BYPASS", "s3cret")
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(302, headers={"location": "https://vercel.com/sso-api?url=x"})

    client = platform.PlatformClient()
    assert client.http.headers["x-vercel-protection-bypass"] == "s3cret"
    client.http = httpx.Client(base_url=client.url, headers=client.http.headers,
                               transport=httpx.MockTransport(handler))
    with _pytest.raises(RuntimeError, match="VERCEL_PROTECTION_BYPASS"):
        client.briefs()
    assert seen["x-vercel-protection-bypass"] == "s3cret"

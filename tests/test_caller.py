import importlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone

import pytest


@pytest.fixture
def caller(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH', str(tmp_path / 'caller.db'))
    monkeypatch.setenv('CALL_MODE', 'approve')
    monkeypatch.setenv('MOCK_SOURCES', '0')
    monkeypatch.setenv('GEOCODE', '0')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-not-a-real-key')
    monkeypatch.setenv('DIAL_API_KEY', 'test-not-a-real-key')
    monkeypatch.setenv('DIAL_FROM_NUMBER', '+12025550000')
    monkeypatch.delenv('APP_PASSWORD', raising=False)
    import househunt.config
    importlib.reload(househunt.config)
    for name in ('househunt.db', 'househunt.pipeline', 'househunt.web.app'):
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    from househunt import db, pipeline
    from househunt.models import Contact, Listing, ListingStatus, SearchCriteria, Source
    db.init()
    criteria = SearchCriteria(city='SF', max_price=3000, must_haves=['laundry'])
    sid = db.create_search(criteria)
    listing = Listing(source=Source.ZILLOW, source_id='test', url='https://example.com', title='Test rental',
                      price=2900, contact=Contact(phone='+12025552222'), status=ListingStatus.CANDIDATE)
    db.upsert_listing(sid, listing)
    return db, pipeline, sid, listing, criteria


def fixture_assessment():
    from househunt.outreach.verification import Assessment
    texts = ['I am the manager; this apartment is available.', 'The rent is $2900 per month.',
             'Laundry is included.', 'There are no additional screening requirements.',
             'October 15, 2026 from 6 to 6:30 PM Pacific is an option.']
    turns = [{'speaker': 'contact', 'text': text, 't': (i+1)*10.0} for i, text in enumerate(texts)]
    def ref(i): return {'turn_index': i, 'quote': texts[i]}
    assessment = Assessment.model_validate({
        'reached_person': True, 'voicemail': False, 'do_not_call': None,
        'facts': [{'key': key, 'passed': True, 'summary': texts[i], 'evidence': [ref(i)]}
                  for i, key in enumerate(['available', 'rent', 'must:0', 'qualifications'])],
        'monthly_rent': {'value': 2900, 'evidence': ref(1)}, 'details': [],
        'tour_offers': [{'start': '2026-10-15T18:00:00-07:00', 'end': '2026-10-15T18:30:00-07:00', 'evidence': [ref(4)]}],
    })
    return assessment, turns


def test_evidence_and_unknowns(caller):
    from househunt.outreach.verification import validate_assessment
    criteria = caller[4]
    a, turns = fixture_assessment()
    when = datetime(2026, 10, 11, tzinfo=timezone.utc)
    result = validate_assessment(a, turns, criteria, 'dial-test', when)
    assert result['verification_status'] == 'verified'
    assert result['checks'][0].evidence.t == 10
    assert len(result['offered_windows']) == 1
    a.facts[2].evidence[0].quote = 'invented'
    assert validate_assessment(a, turns, criteria, 'dial-test', when)['verification_status'] == 'unconfirmed'
    a, turns = fixture_assessment()
    turns[0]['speaker'] = 'agent'
    assert validate_assessment(a, turns, criteria, 'dial-test', when)['checks'][0].passed is None
    a, turns = fixture_assessment()
    a.facts = [f for f in a.facts if f.key != 'qualifications']
    assert validate_assessment(a, turns, criteria, 'dial-test', when)['checks'][2].passed is None


def test_price_and_tour_validation(caller):
    from househunt.outreach.verification import validate_assessment
    a, turns = fixture_assessment()
    when = datetime(2026, 10, 11, tzinfo=timezone.utc)
    a.monthly_rent.value = 3500
    result = validate_assessment(a, turns, caller[4], 'dial-test', when)
    assert result['verification_status'] == 'ruled_out' and not result['offered_windows']
    a, turns = fixture_assessment()
    a.tour_offers[0].end = a.tour_offers[0].start
    assert not validate_assessment(a, turns, caller[4], 'dial-test', when)['offered_windows']
    a.voicemail = True
    assert all(c.passed is None for c in validate_assessment(a, turns, caller[4], 'dial-test', when)['checks'])


def test_concurrent_reservation_is_idempotent(caller):
    db, _, sid, listing, _ = caller
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: db.claim_call(sid, listing.key, listing.contact.phone, 'live'), range(4)))
    assert sum(c is not None for c in claims) == 1
    row = next(c for c in claims if c)
    db.update_call(row['id'], status='attention')
    resumed = db.claim_call(sid, listing.key, listing.contact.phone, 'live')
    assert resumed['id'] == row['id'] and resumed['attempt_key'] == row['attempt_key']


def test_failed_extraction_reuses_saved_transcript_without_redial(caller, monkeypatch):
    db, pipeline, sid, listing, _ = caller
    from househunt.outreach.dial import _parse_call
    from househunt.outreach.extract import CallSummary
    placed = []
    raw = {'id': 'dial-one', 'status': {'state': 'Terminated'}, 'createdAt': '2026-10-11T20:00:00Z',
           'transcript': 'Contact: Available', 'transcriptTurns': [{'speaker': 'user', 'text': "Please don't call me again", 'startMs': 1000}]}
    class Dial:
        def place_call(self, *args, **kwargs):
            placed.append(kwargs['idempotency_key'])
            return _parse_call(raw)
        def wait_for_call(self, *args): return _parse_call(raw)
    monkeypatch.setattr(pipeline, 'dial_client', lambda: Dial())
    monkeypatch.setattr(pipeline, 'calendar_availability', lambda: [])
    monkeypatch.setattr(pipeline, 'extract', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('Model unavailable')))
    pipeline.call_listing(sid, listing.key)
    row = db.calls_for_search(sid)[listing.key]
    assert row['status'] == 'attention' and row['transcript'] and row['raw']
    assert db.contact_blocked(listing.contact.phone)
    summary = CallSummary(reached_person=True, available=None, monthly_rent=None, deposit=None,
        lease_terms=None, move_in_ok=None, must_haves=[], offered_times=[], do_not_call=True,
        viable=False, tradeoffs=[], summary='Unknown', offered_windows=[{'start': '2026-10-15T18:00:00-07:00', 'end': '2026-10-15T18:30:00-07:00'}])
    monkeypatch.setattr(pipeline, 'extract', lambda *a, **kw: summary)
    pipeline.call_listing(sid, listing.key)
    pipeline.call_listing(sid, listing.key)
    assert len(placed) == 1
    assert db.calls_for_search(sid)[listing.key]['status'] == 'ended'
    assert not db.tours_for_search(sid)
    assert db.get_listing(sid, listing.key).status.value == 'contacted'


def test_live_model_failure_never_falls_back(caller, monkeypatch):
    from househunt.outreach import extract
    import httpx
    monkeypatch.setattr(httpx.Client, 'post', lambda *a, **kw: httpx.Response(401))
    with pytest.raises(RuntimeError, match='OpenAI extraction HTTP 401'):
        extract._assessment({})


def test_timed_transcript_required(caller):
    from househunt.outreach.extract import extract
    with pytest.raises(RuntimeError, match='Timed contact transcript unavailable'):
        extract('Contact: yes', caller[3], caller[4], raw={'transcript': 'Contact: yes'})


def test_ui_displays_citations_without_booking(caller):
    from fastapi.testclient import TestClient
    from househunt.web.app import app
    db, _, sid, listing, _ = caller
    with TestClient(app) as client:
        row = db.claim_call(sid, listing.key, listing.contact.phone, 'live')
        db.update_call(row['id'], status='ended', transcript='Contact: Available.', outcome={
            'summary': 'Availability confirmed', 'viable': False, 'verification_status': 'unconfirmed',
            'checks': [{'kind': 'real', 'passed': True, 'summary': 'Available', 'evidence': {'callId': 'dial-one', 't': 10, 'quote': 'Available.'}}],
            'offered_windows': [{'start': '2026-10-15T18:00:00-07:00', 'end': '2026-10-15T18:30:00-07:00'}],
            'transcript_turns': [{'t': 10, 'speaker': 'contact', 'text': 'Available.'}],
        })
        response = client.get(f'/searches/{sid}')
        assert response.status_code == 200 and 'confirmation needed' in response.text
        assert '10s' in response.text and 'Real · Confirmed' in response.text
        assert 'Call again' not in response.text
        assert client.post(f'/searches/{sid}/listings/{listing.key}/call').status_code == 409
        assert not db.tours_for_search(sid)


def test_private_recording_import_and_authenticated_playback(caller, tmp_path, monkeypatch):
    import wave
    from fastapi.testclient import TestClient
    from househunt.outreach.recording import import_recording
    from househunt.web import app as web
    db, _, sid, listing, _ = caller
    row = db.claim_call(sid, listing.key, listing.contact.phone, 'live')
    db.update_call(row['id'], dial_call_id='provider-test', status='ended', outcome={'summary':'Test'})
    source = tmp_path / 'download.wav'
    with wave.open(str(source), 'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\0\0'*8000)
    path = import_recording(row['id'], source)
    assert path.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(web, 'settings', replace(web.settings, app_password='test-password'))
    with TestClient(web.app) as client:
        url=f'/calls/{row["id"]}/recording'
        assert client.get(url).status_code == 401
        response = client.get(url, auth=('demo','test-password'), headers={'Range':'bytes=0-11'})
        assert response.status_code == 206
        assert response.content[:4] == b'RIFF'
        assert response.headers['cache-control'] == 'private, no-store'
        assert client.get('/calls/9999/recording', auth=('demo','test-password')).status_code == 404


def test_recording_import_rejects_non_audio(caller, tmp_path):
    from househunt.outreach.recording import import_recording
    db, _, sid, listing, _ = caller
    row=db.claim_call(sid,listing.key,listing.contact.phone,'live')
    db.update_call(row['id'],dial_call_id='provider-test')
    source=tmp_path/'not-audio.wav';source.write_text('<script>not a recording</script>')
    with pytest.raises(ValueError,match='Expected a WAV'):
        import_recording(row['id'],source)

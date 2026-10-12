import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from test_caller import caller  # shared isolated SQLite/live-call fixture

from househunt.outreach.verification import Assessment, validate_assessment


def scenario(listing):
    listing.address, listing.price, listing.beds, listing.baths = '123 Main St, Unit 4', 2900, 2, 1
    messages = [
        ('contact', 'This is 123 Main Street, unit 4. I am the authorized leasing agent and it is available.'),
        ('contact', 'Rent is $2,900 a month, two bedrooms and one bathroom. Laundry is included.'),
        ('contact', 'Deposit is one month of rent, no other rental fees. No payment or application is needed to book a viewing.'),
        ('contact', 'October 15, 2026 from 6 to 6:30 PM Pacific is an option.'),
        ('agent', 'Please book October 15, 2026 from 6 to 6:30 PM Pacific for Reed at 123 Main Street, unit 4.'),
        ('contact', 'Confirmed, you are booked for October 15, 2026 from 6 to 6:30 PM Pacific at 123 Main Street, unit 4.'),
    ]
    turns = [{'speaker': s, 'text': text, 't': i*10.0} for i,(s,text) in enumerate(messages)]
    def ref(i): return {'turn_index': i, 'quote': turns[i]['text']}
    facts = [{'key': key, 'passed': True, 'summary': turns[i]['text'], 'evidence': [ref(i)]}
             for key,i in [('identity',0), ('authority',0), ('available',0), ('advertised_beds',1),
                           ('advertised_baths',1), ('must:0',1), ('tour_requirements',2)]]
    window = {'start':'2026-10-15T18:00:00-07:00', 'end':'2026-10-15T18:30:00-07:00', 'evidence':[ref(3),ref(5)]}
    a = Assessment.model_validate({'reached_person':True, 'voicemail':False, 'do_not_call':None,
        'facts':facts, 'monthly_rent':{'value':2900, 'evidence':ref(1)}, 'details':[], 'tour_offers':[window],
        'confirmed_tour':{**window, 'meeting_address':listing.address, 'agent_acceptance':ref(4),
            'contact_confirmation':ref(5), 'requires_payment_or_application':False}})
    context = {'enabled':True, 'checked_at':'2026-10-11T19:59:30Z', 'windows':[{'start':'2026-10-15T17:00:00-07:00','end':'2026-10-15T20:00:00-07:00'}]}
    return a, turns, context


def assess(caller, a, turns, context):
    return validate_assessment(a, turns, caller[4], 'provider-test', datetime.fromisoformat('2026-10-11T20:00:00Z'), caller[3], context)


def test_listing_and_booking_verified_without_inventing_financial_eligibility(caller):
    a, turns, context = scenario(caller[3])
    result = assess(caller,a,turns,context)
    assert result['listing_verified'] is True
    assert result['checks'][2].passed is None  # financial fit is a separate question
    assert result['confirmed_tour']['start'] == a.confirmed_tour.start
    assert result['confirmed_tour']['contact_evidence']['t'] == 50


@pytest.mark.parametrize('change', ['wrong_unit','wrong_street','missing_address','agent_only','invented_rent','changed_rent','different_beds','voicemail'])
def test_no_false_green(caller, change):
    a, turns, context = scenario(caller[3])
    if change in ('wrong_unit','wrong_street','missing_address'):
        turns[0]['text'] = {'wrong_unit':'123 Main Street, unit 9', 'wrong_street':'124 Main Street, unit 4','missing_address':'Yes, that is correct.'}[change]
        for f in a.facts:
            if f.evidence[0].turn_index == 0: f.evidence[0].quote = turns[0]['text']
    if change == 'agent_only': turns[0]['speaker'] = 'agent'
    if change == 'invented_rent':
        turns[1]['text'] = 'Rent is reasonable, laundry is included.'
        a.monthly_rent.evidence.quote = turns[1]['text']
    if change == 'changed_rent': caller[3].price = 2800
    if change == 'different_beds': next(f for f in a.facts if f.key == 'advertised_beds').passed = False
    if change == 'voicemail': a.voicemail = True
    result = assess(caller,a,turns,context)
    assert result['listing_verified'] is not True
    assert result['confirmed_tour'] is None


@pytest.mark.parametrize('change', ['offer_only','disabled','stale','outside','wrong_time_within_window','wrong_duration','naive','wrong_location','payment','unknown_fees','unknown_must_have','agent_quote','no_acceptance','partial_confirmation','cancelled_later','opt_out'])
def test_offer_or_unsafe_time_never_becomes_booking(caller, change):
    a, turns, context = scenario(caller[3])
    b = a.confirmed_tour
    if change == 'offer_only': a.confirmed_tour = None
    if change == 'disabled': context['enabled'] = False
    if change == 'stale': context['checked_at'] = '2026-10-11T19:40:00Z'
    if change == 'outside': b.start = '2026-10-16T18:00:00-07:00'; b.end = '2026-10-16T18:30:00-07:00'
    if change == 'wrong_time_within_window': b.start = '2026-10-15T19:00:00-07:00'; b.end = '2026-10-15T19:30:00-07:00'
    if change == 'wrong_duration': b.end = '2026-10-15T19:00:00-07:00'
    if change == 'naive': b.start = '2026-10-15T18:00:00'
    if change == 'wrong_location': b.meeting_address = '123 Main Street, unit 9'
    if change == 'payment': b.requires_payment_or_application = True
    if change in ('unknown_fees','unknown_must_have'):
        a.facts = [f for f in a.facts if f.key != ('tour_requirements' if change == 'unknown_fees' else 'must:0')]
    if change == 'agent_quote': b.contact_confirmation.turn_index = 4; b.contact_confirmation.quote = turns[4]['text']
    if change == 'no_acceptance': b.agent_acceptance.quote = 'Imagined acceptance'
    if change == 'partial_confirmation':
        turns[5]['text'] = 'You are not confirmed, please check first.'
        b.contact_confirmation.quote = 'confirmed'  # quoting a positive fragment must not remove negation
        b.evidence[-1].quote = turns[5]['text']
    if change == 'cancelled_later': turns.append({'speaker':'contact','t':60,'text':'Sorry, I must cancel that viewing.'})
    if change == 'opt_out': a.do_not_call = b.contact_confirmation
    result = assess(caller,a,turns,context)
    assert result['confirmed_tour'] is None
    assert bool(result['booking_warning']) == (change != 'offer_only')


def test_completed_call_recovery_records_one_tour_and_one_calendar_event(caller, monkeypatch):
    db, pipeline, sid, listing, _ = caller
    from househunt.outreach import booking, extract
    from househunt.outreach.dial import _parse_call
    from househunt.connectors import google
    from househunt.voice import store
    a, turns, context = scenario(listing)
    db.upsert_listing(sid,listing)
    monkeypatch.setattr(store, 'enabled', lambda: False)
    monkeypatch.setattr(booking, 'prepare', lambda *args: context)
    monkeypatch.setattr(extract, '_assessment', lambda *args: a)
    placed, events = [], []
    raw = {'id':'provider-test','createdAt':'2026-10-11T20:00:00Z','status':{'state':'Terminated'},
        'transcriptTurns':[{'speaker':t['speaker'],'text':t['text'],'startMs':t['t']*1000} for t in turns]}
    class Dial:
        def place_call(self, *args, **kw): placed.append(kw); return _parse_call(raw)
        def wait_for_call(self, *args): return _parse_call(raw)
    monkeypatch.setattr(pipeline,'dial_client',lambda:Dial())
    monkeypatch.setattr(google,'connection',lambda:True)
    def add(*args): events.append(args); return 'https://calendar.example/event'
    monkeypatch.setattr(google,'add_confirmed_event',add)
    pipeline.call_listing(sid,listing.key)
    call = db.calls_for_search(sid)[listing.key]
    assert call['status'] == 'ended', call['error']
    assert json.loads(call['outcome'])['tour_booked']
    assert db.tours_for_search(sid)[listing.key]['calendar_status'] == 'synced'
    db.update_call(call['id'],status='attention')
    monkeypatch.setattr(booking,'prepare',lambda *args: pytest.fail('Retry must use original authorization'))
    pipeline.call_listing(sid,listing.key)
    assert len(placed) == len(events) == 1
    with db.conn() as conn: assert conn.execute('SELECT COUNT(*) FROM tours').fetchone()[0] == 1
    assert db.get_listing(sid,listing.key).status.value == 'tour_scheduled'
    assert db.find_application(sid,listing.key)['stage'] == 'viewing'


def test_calendar_failure_preserves_contact_booking(caller,monkeypatch):
    from househunt.outreach import booking, extract
    from househunt.connectors import google
    db, pipeline, sid, listing, criteria = caller
    a, turns, context = scenario(listing)
    monkeypatch.setattr(extract,'_assessment',lambda *args:a)
    summary = extract.extract('test',listing,criteria,call_date=datetime.fromisoformat('2026-10-11T20:00:00Z'),
        raw={'booking_context':context,'transcriptTurns':[{'speaker':t['speaker'],'text':t['text'],'startMs':t['t']*1000} for t in turns]})
    monkeypatch.setattr(google,'connection',lambda:True)
    monkeypatch.setattr(google,'add_confirmed_event',lambda *args: (_ for _ in ()).throw(TimeoutError()))
    pipeline.apply_outcome(sid,listing,summary,call_id=1)
    tour = db.tours_for_search(sid)[listing.key]
    assert tour['calendar_status'] == 'pending' and 'booked' in tour['calendar_error']
    assert db.get_listing(sid, listing.key).status.value == 'tour_scheduled'
    assert booking.record(sid,listing,summary,1) == tour['id']
    summary.confirmed_tour['end'] = '2026-10-15T19:00:00-07:00'
    with pytest.raises(RuntimeError,match='differs'): booking.record(sid,listing,summary,1)


def test_google_retry_reads_stable_event_without_writing_or_conflicting(caller,monkeypatch):
    from househunt.connectors import google
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == 'GET'
        return httpx.Response(200,json={'start':{'dateTime':'2026-10-15T18:00:00-07:00'},'end':{'dateTime':'2026-10-15T18:30:00-07:00'},'htmlLink':'event'})
    monkeypatch.setattr(google,'_client',lambda:httpx.Client(transport=httpx.MockTransport(handler)))
    for _ in range(2): assert google.add_confirmed_event('1','2026-10-15T18:00:00-07:00','2026-10-15T18:30:00-07:00','Tour','123 Main St','') == 'event'
    assert requests[0].url == requests[1].url


def test_freebusy_errors_never_authorize_booking(caller,monkeypatch):
    from househunt.connectors import google
    from househunt.outreach import booking
    monkeypatch.setattr(google,'connection',lambda:True)
    monkeypatch.setattr(google,'_client',lambda:httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'calendars':{'primary':{'errors':[{'reason':'notFound'}]}}}))))
    assert booking.prepare(caller[2],caller[3].key,caller[4])['enabled'] is False


def test_ics_keeps_confirmed_duration_and_timezone():
    from househunt.tours import to_ics
    ics = to_ics(1,'2026-10-15T18:00:00-07:00','Main St',None,None,None,end_iso='2026-10-15T18:45:00-07:00')
    assert 'DTSTART:20261016T010000Z' in ics and 'DTEND:20261016T014500Z' in ics


def test_native_dashboard_workspace_and_export_share_booked_truth(caller,monkeypatch):
    from fastapi.testclient import TestClient
    from househunt.web.app import app
    from househunt.web.household_api import _card
    from househunt.outreach import extract
    from househunt import platform
    db, pipeline, sid, listing, criteria = caller
    a, turns, context = scenario(listing)
    monkeypatch.setattr(extract,'_assessment',lambda *args:a)
    raw = {'id':'provider','createdAt':'2026-10-11T20:00:00Z','booking_context':context,
        'transcriptTurns':[{'speaker':t['speaker'],'text':t['text'],'startMs':t['t']*1000} for t in turns]}
    summary = extract.extract('test',listing,criteria,call_date=datetime.fromisoformat(raw['createdAt']),raw=raw)
    with TestClient(app) as client:
        call = db.claim_call(sid,listing.key,listing.contact.phone,'live')
        db.upsert_listing(sid,listing)
        db.update_call(call['id'],status='ended',dial_call_id='provider',outcome=summary.model_dump(),raw=raw)
        tour_id = db.create_tour(sid,listing.key,summary.tour_start,listing.address,None,None,end=summary.tour_end,source_call_id=call['id'])
        db.update_tour_calendar(tour_id,'pending','Calendar sync pending')
        call = db.calls_for_search(sid)[listing.key]
        card = _card(listing,call,None,db.get_tour(tour_id),None)
        assert card['call']['listingVerified'] is True
        assert card['viewing']['confirmedOnCall'] is True and card['viewing']['calendarStatus'] == 'pending'
        for url in ('/calls',f'/searches/{sid}'):
            response = client.get(url)
            assert response.status_code == 200
            assert '✓ Listing verified' in response.text and 'Calendar sync pending' in response.text
            assert 'Tour booked' in response.text or 'Tour confirmed on call' in response.text
        run = platform.export_run('household',sid)
        tour = run['bookedTours'][0]
        assert tour['contactEvidence']['callId'] == tour['agentEvidence']['callId'] == run['calls'][0]['id']
        assert run['offeredWindows'] == []
        db.update_call(call['id'],mode='dry_run')
        assert _card(listing,db.calls_for_search(sid)[listing.key],None,None,None)['call']['listingVerified'] is None


def test_saved_availability_subtracts_unsynced_tours(caller,monkeypatch):
    from househunt.connectors import google
    from househunt.outreach import booking
    db, _, sid, listing, criteria = caller
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=16,minute=0,second=0,microsecond=0)
    end = start + timedelta(hours=4)
    ts,te = start+timedelta(hours=1),start+timedelta(hours=2)
    db.create_tour(sid,'other:rental',ts.isoformat(),'Other',None,None,end=te.isoformat(),source_call_id=99)
    monkeypatch.setattr(google,'connection',lambda:True)
    monkeypatch.setattr(google,'free_intervals',lambda:[{'start':start.isoformat(),'end':end.isoformat()}])
    context = booking.prepare(sid,listing.key,criteria)
    assert context['enabled'] is True
    assert context['windows'] == [{'start':start.isoformat(),'end':ts.isoformat()},{'start':te.isoformat(),'end':end.isoformat()}]

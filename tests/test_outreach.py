import importlib
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from test_caller import caller


@pytest.fixture
def outreach(caller, monkeypatch):
    from househunt.outreach import hours, scheduler, callbacks
    from househunt import phone
    for module in (hours, scheduler, callbacks, phone):
        importlib.reload(module)
    db, pipeline, sid, listing, criteria = caller
    listing.address = '900 Pine Street, Unit 6'
    listing.description = 'Sunny upper floor. Office hours Monday-Friday 9am-5pm.'
    db.upsert_listing(sid, listing)
    policy = {**hours.fallback(), 'periods': [{'day': d, 'opens': '00:00', 'closes': '23:59'} for d in range(7)]}
    monkeypatch.setattr(hours, 'discover', lambda listing: policy)
    monkeypatch.setattr(hours, 'parse_evidence', lambda *args: None)
    return caller, hours, scheduler, callbacks, policy


def test_closed_evenings_weekends_closures_and_dst(outreach):
    _, hours, _, _, _ = outreach
    policy = hours.fallback()
    assert hours.next_open(policy, datetime.fromisoformat('2026-10-10T03:00:00+00:00')).isoformat() == '2026-10-12T16:00:00+00:00'
    policy['closed_dates'] = ['2026-10-12']
    assert hours.next_open(policy, datetime.fromisoformat('2026-10-10T03:00:00+00:00')).isoformat() == '2026-10-13T16:00:00+00:00'
    assert hours.next_open(hours.fallback(), datetime.fromisoformat('2026-11-01T18:00:00+00:00')).isoformat() == '2026-11-02T17:00:00+00:00'
    # Leave enough time to finish before the office closes.
    assert hours.next_open(hours.fallback(), datetime.fromisoformat('2026-10-09T23:59:00+00:00')).day == 12


def test_published_weekend_hours_and_quote_validation(outreach, monkeypatch):
    _, hours, _, _, _ = outreach
    importlib.reload(hours)  # Use real parser; replace its external model boundary.
    result = hours.HoursEvidence(source='https://office.example', quote='Open Saturday 10am to 2pm; closed all other days.', timezone=None,
        periods=[hours.Period(day=5, opens='10:00', closes='14:00')], closed_dates=[])
    monkeypatch.setattr(hours, 'ask', lambda *a: result)
    policy = hours.parse_evidence({'https://office.example': result.quote})
    assert hours.next_open(policy, datetime.fromisoformat('2026-10-10T18:00:00+00:00')).hour == 18
    assert hours.parse_evidence({'https://office.example': 'No posted operating hours'}) is None
    result.periods[0].opens = '25:00'
    assert hours.parse_evidence({'https://office.example': result.quote}) is None


def test_auto_search_queues_then_calls_with_full_context(outreach, monkeypatch):
    caller, hours, scheduler, _, _ = outreach
    db, pipeline, sid, listing, criteria = caller
    from househunt.config import CallMode
    from househunt.outreach.dial import _parse_call
    criteria.wishes = ['Quiet street']
    criteria.commute = {'destination': 'Downtown', 'maxMinutes': 30}
    db.update_search_criteria(sid, criteria)
    monkeypatch.setattr(pipeline, 'settings', replace(pipeline.settings, call_mode=CallMode.AUTO, web_research=False))
    monkeypatch.setattr(pipeline, 'source_listings', lambda *a: ([listing], []))
    monkeypatch.setattr(pipeline.geo, 'locate', lambda *a: None)
    sent = []
    raw = {'id': 'auto-one', 'status': 'no-answer', 'transcriptTurns': []}
    class Dial:
        def place_call(self, phone, instruction, **kw):
            sent.append((phone, instruction, kw))
            return _parse_call(raw)
        def wait_for_call(self, *a): return _parse_call(raw)
    monkeypatch.setattr(pipeline, 'dial_client', Dial)
    pipeline.run_search(sid)
    assert not sent and scheduler.jobs(sid)[0]['state'] == 'scheduled'
    scheduler.run_due()
    assert len(sent) == 1
    assert all(s in sent[0][1] for s in ('900 Pine Street', 'Sunny upper floor', 'Quiet street', 'Downtown', 'Wait for the beep', 'callback_number'))
    row = db.calls_for_search(sid)[listing.key]
    assert row['status'] == 'ended' and json.loads(row['search_context'])['criteria']['wishes'] == ['Quiet street']
    job = scheduler.jobs(sid)[0]
    assert job['state'] == 'scheduled' and job['attempts'] == 1
    assert datetime.fromisoformat(job['scheduled_at']).date() > datetime.now(timezone.utc).date()
    scheduler.run_due()
    assert len(sent) == 1  # No same-day redial.


def test_followup_claim_is_bounded_and_unique(outreach):
    caller, _, _, _, _ = outreach
    db, _, sid, listing, _ = caller
    first = db.claim_call(sid, listing.key, listing.contact.phone, 'live')
    db.update_call(first['id'], status='ended', outcome={'reached_person': False, 'voicemail': True})
    assert db.claim_call(sid, listing.key, listing.contact.phone, 'live') is None
    second = db.claim_call(sid, listing.key, listing.contact.phone, 'live', first['id'])
    assert first['attempt_key'] != second['attempt_key']
    assert db.claim_call(sid, listing.key, listing.contact.phone, 'live', first['id']) is None
    db.update_call(second['id'], status='ended', outcome={'reached_person': False})
    assert db.claim_call(sid, listing.key, listing.contact.phone, 'live', second['id']) is None


def test_edited_phone_loses_research_clearance(outreach, monkeypatch):
    caller, _, scheduler, _, _ = outreach
    listing = caller[3]
    monkeypatch.setattr(scheduler, 'settings', replace(scheduler.settings, dial_allowed_numbers=(), call_verified_contacts=True))
    listing.screening = {'status': 'cross_referenced', 'findings': [{'kind': 'contact_corroborated', 'quote': 'Office phone: (202) 555-2222'}]}
    assert scheduler.permitted(listing)
    listing.contact.phone = '+12025552223'
    assert not scheduler.permitted(listing)


def test_voicemail_does_not_verify_and_grounded_message(outreach, monkeypatch):
    caller, _, _, _, _ = outreach
    from househunt.outreach import extract
    from househunt.outreach.verification import Assessment
    from test_caller import fixture_assessment
    a, _ = fixture_assessment()
    a.voicemail = True
    greeting = 'Our office is closed. Please leave a message.'
    message = "Hi, this is Reed's AI assistant about 900 Pine Street Unit 6. Please call us back at 202 555 0000. Thank you."
    from househunt.outreach.verification import Ref
    a.voicemail_message = Ref(turn_index=1, quote=message)
    a = Assessment.model_validate(a.model_dump())
    monkeypatch.setattr(extract, '_assessment', lambda *a: a_model)
    a_model = a
    raw = {'callback_number': '+12025550000', 'transcriptTurns': [{'speaker': 'user', 'text': greeting, 'startMs': 0}, {'speaker': 'agent', 'text': message, 'startMs': 8000}]}
    outcome = extract.extract('test', caller[3], caller[4], raw=raw)
    assert outcome.voicemail_left and outcome.voicemail and not outcome.reached_person and outcome.listing_verified is not True
    a.voicemail_message.quote = 'Invented voicemail'
    assert not extract.extract('test', caller[3], caller[4], raw=raw).voicemail_left


def test_callback_requires_exact_unit_and_cancels_retry(outreach, monkeypatch):
    caller, _, scheduler, callbacks, _ = outreach
    db, pipeline, sid, listing, criteria = caller
    from househunt.outreach import extract
    first = db.claim_call(sid, listing.key, listing.contact.phone, 'live')
    db.update_call(first['id'], status='ended', dial_call_id='outbound-1', outcome={'reached_person': False})
    scheduler.enqueue(sid, listing.key)
    raw = {'id': 'incoming-1', 'from': listing.contact.phone, 'status': 'completed', 'createdAt': datetime.now(timezone.utc).isoformat(),
        'transcriptTurns': [{'speaker': 'user', 'startMs': 0, 'text': 'Calling about 900 Pine Street Unit 7.'}]}
    assert callbacks.match(listing.contact.phone, raw) is None
    raw['transcriptTurns'][0]['text'] = 'Calling about 900 Pine Street Unit 6.'
    def extracted(*a, **kw):
        assert not kw['raw']['booking_context']['enabled']
        result = extract.unanswered('Callback received; offers require calendar confirmation.')
        result.reached_person = True
        return result
    monkeypatch.setattr(extract, 'extract', extracted)
    assert callbacks.process(raw)
    assert not callbacks.process(raw)
    assert scheduler.jobs(sid)[0]['state'] == 'complete'
    assert db.calls_for_search(sid)[listing.key]['direction'] == 'inbound'
    assert len(db.all_calls()) == 2


def test_custom_inbound_uses_message_taker_without_household_profile(outreach):
    from househunt.voice.bridge import initiation
    data = initiation({'direction': 'inbound', 'instruction': 'Take rental callback'}, None)
    assert 'tts' not in data['conversation_config_override']
    assert 'Which property' in data['conversation_config_override']['agent']['first_message']


def test_voicemail_office_hours_replace_fallback(outreach, monkeypatch):
    caller, hours, scheduler, _, policy = outreach
    db, _, sid, listing, _ = caller
    scheduler.enqueue(sid, listing.key)
    row = db.claim_call(sid, listing.key, listing.contact.phone, 'live')
    learned = {**hours.fallback(), 'source': f'call:{row["id"]}', 'quote': 'Our office is open Monday-Friday 10am-4pm.',
        'periods': [{'day': d, 'opens': '10:00', 'closes': '16:00'} for d in range(5)]}
    monkeypatch.setattr(hours, 'parse_evidence', lambda sources: learned)
    db.update_call(row['id'], status='ended', dial_call_id='voicemail', outcome={'voicemail': True, 'reached_person': False,
        'transcript_turns': [{'speaker': 'contact', 't': 0, 'text': learned['quote']}]})
    scheduler.finish(sid, listing.key, policy)
    job = scheduler.jobs(sid)[0]
    assert job['hours']['source'] == f'call:{row["id"]}'
    assert datetime.fromisoformat(job['scheduled_at']).astimezone(hours.ZoneInfo('America/Los_Angeles')).hour == 10


def test_two_households_same_unit_callback_stays_unassigned(outreach):
    caller, _, _, callbacks, _ = outreach
    db, _, sid, listing, criteria = caller
    for search in (sid, db.create_search(criteria)):
        db.upsert_listing(search, listing)
        row = db.claim_call(search, listing.key, listing.contact.phone, 'live')
        db.update_call(row['id'], status='ended', dial_call_id=f'outbound-{search}')
    raw = {'transcriptTurns': [{'speaker': 'user', 'startMs': 0, 'text': '900 Pine Street Unit 6'}]}
    assert callbacks.match(listing.contact.phone, raw) is None


def test_daily_contact_limit_uses_property_day_not_utc_day(outreach, monkeypatch):
    caller, _, _, _, _ = outreach
    db, _, sid, listing, _ = caller
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime.fromisoformat('2026-10-13T00:30:00+00:00')
            return current.astimezone(tz) if tz else current.replace(tzinfo=None)
    monkeypatch.setattr(db, 'datetime', Clock)
    row = db.claim_call(sid, listing.key, listing.contact.phone, 'live')
    db.update_call(row['id'], dial_call_id='earlier', created_at='2026-10-12T22:00:00+00:00', status='ended')
    assert db.contact_called_today(listing.contact.phone, -1)  # Both Monday in Pacific time.
    db.update_call(row['id'], created_at='2026-10-12T01:00:00+00:00')
    assert not db.contact_called_today(listing.contact.phone, -1)  # Sunday in Pacific time.

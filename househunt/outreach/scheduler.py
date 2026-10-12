"""Durable, bounded outreach. A single worker owns each claimed job."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone

from househunt import db
from househunt.config import settings
from househunt.outreach import hours

log = logging.getLogger(__name__)


def permitted(listing, config=None) -> bool:
    config = config or settings
    phone = listing.contact.phone if listing.contact else None
    if phone in config.dial_allowed_numbers:
        return True
    if not phone or not config.call_verified_contacts or listing.screening.get('status') != 'cross_referenced':
        return False
    # An edited contact must not inherit the previous number's clearance.
    from househunt.collect import extract_phone
    return any(f.get('kind') == 'contact_corroborated' and extract_phone(f.get('quote', '')) == phone
               for f in listing.screening.get('findings', []))


def jobs(search_id: int) -> list[dict]:
    with db.conn() as c:
        rows = c.execute('SELECT * FROM outreach_jobs WHERE search_id=? ORDER BY scheduled_at', (search_id,)).fetchall()
    return [{**dict(r), 'hours': json.loads(r['hours'])} for r in rows]


def update(sid: int, key: str, **fields):
    if 'hours' in fields:
        fields['hours'] = json.dumps(fields['hours'])
    fields['updated_at'] = db.now()
    with db.conn() as c:
        c.execute('UPDATE outreach_jobs SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE search_id=? AND listing_key=?', (*fields.values(), sid, key))


def enqueue(sid: int, key: str) -> None:
    listing = db.get_listing(sid, key)
    if not listing or listing.status.value in ('filtered', 'not_viable', 'tour_scheduled'):
        return
    with db.conn() as c:
        db.lock(c, "outreach-jobs")
        row = c.execute('SELECT * FROM outreach_jobs WHERE search_id=? AND listing_key=?', (sid, key)).fetchone()
        if row and row['state'] not in ('needs_attention', 'blocked'):
            return
        c.execute("INSERT INTO outreach_jobs(search_id,listing_key,state,reason,updated_at) VALUES (?,?,'checking_hours','Checking office hours',?) ON CONFLICT(search_id,listing_key) DO UPDATE SET state='checking_hours',reason='Checking office hours',updated_at=excluded.updated_at", (sid, key, db.now()))
    try:
        if not listing.contact or not listing.contact.phone:
            update(sid, key, state='blocked', reason='A verified phone number is needed', scheduled_at=None)
            return
        if not permitted(listing) or db.contact_blocked(listing.contact.phone):
            update(sid, key, state='blocked', reason='Contact needs review or has opted out', scheduled_at=None)
            return
        policy = hours.discover(listing)
        due = hours.next_open(policy)
        update(sid, key, state='scheduled', hours=policy, scheduled_at=due.isoformat(), reason='Call queued for office hours')
        db.search_event(sid, f'Call scheduled for {listing.address or listing.title}: {due.astimezone(hours.ZoneInfo(policy["timezone"])).strftime("%a %b %d, %-I:%M %p %Z")}. {policy["quote"]}')
    except Exception:
        update(sid, key, state='needs_attention', reason='Office hours could not be scheduled; retry', scheduled_at=None)


def finish(sid: int, key: str, policy: dict):
    row = db.calls_for_search(sid).get(key)
    if not row:
        update(sid, key, state='needs_attention', reason='Call could not start', scheduled_at=None)
        return
    outcome = json.loads(row['outcome'] or '{}')
    with db.conn() as c:
        count = c.execute("SELECT COUNT(*) FROM calls WHERE search_id=? AND listing_key=? AND direction='outbound'", (sid, key)).fetchone()[0]
    update(sid, key, last_call_id=row['id'], attempts=count)
    if row['status'] != 'ended':
        update(sid, key, state='needs_attention', reason=row['error'] or 'Saved call needs processing', scheduled_at=None)
        return
    if outcome.get('do_not_call') or (outcome.get('reached_person') and not outcome.get('callback_requested')):
        update(sid, key, state='complete', reason='Contact opted out' if outcome.get('do_not_call') else 'Call complete; details saved', scheduled_at=None)
        return
    if count >= settings.max_contact_attempts:
        update(sid, key, state='waiting_callback', reason='Attempt limit reached; waiting for callback', scheduled_at=None)
        return
    # Contact-only evidence can replace inferred hours, including voicemail greetings.
    contact = '\n'.join(t['text'] for t in outcome.get('transcript_turns', []) if t['speaker'] == 'contact')
    if re.search(r'hours|open|closed|monday|tuesday|wednesday|thursday|friday|saturday|sunday', contact, re.I):
        try:
            learned = hours.parse_evidence({f'call:{row["id"]}': contact})
            if learned:
                policy = learned
        except Exception:
            pass
    due = hours.next_open(policy, next_day=True)
    update(sid, key, state='scheduled', scheduled_at=due.isoformat(), hours=policy,
        reason='Voicemail reached; waiting for callback before retry' if outcome.get('voicemail') else 'No answer; retry next business day')


def run_due(sid: int | None = None, key: str | None = None) -> None:
    from househunt import pipeline
    if settings.mock_sources or settings.call_mode.value == 'dry_run':
        return  # Never turn persisted live jobs into synthetic "completed" calls.
    # Re-read and claim after acquiring the same lock as manual calls.
    with pipeline._call_lock:
        with db.conn() as c:
            db.lock(c, "outreach-jobs")
            query = "SELECT * FROM outreach_jobs WHERE state='scheduled' AND scheduled_at<=?"
            args = [datetime.now(timezone.utc).isoformat()]
            if sid is not None:
                query += ' AND search_id=? AND listing_key=?'
                args += [sid, key]
            row = c.execute(query + ' ORDER BY scheduled_at LIMIT 1', args).fetchone()
            if not row:
                return
            sid, key = row['search_id'], row['listing_key']
            c.execute("UPDATE outreach_jobs SET state='calling',reason='Calling the listing contact',updated_at=? WHERE search_id=? AND listing_key=?", (db.now(), sid, key))
        policy = json.loads(row['hours'])
        try:
            saved = db.calls_for_search(sid).get(key)
            if saved and saved['status'] == 'ended' and saved['id'] != row['last_call_id']:
                finish(sid, key, policy)
                return
            if saved and saved['dial_call_id'] and saved['status'] in ('attention', 'failed'):
                pipeline._call_listing(sid, key)
                finish(sid, key, policy)
                return
            now = datetime.now(timezone.utc)
            due = hours.next_open(policy, now)
            if due > now:
                update(sid, key, state='scheduled', scheduled_at=due.isoformat(), reason='Office is closed; next open window')
                return
            listing = db.get_listing(sid, key)
            if not listing or listing.status.value in ('filtered','not_viable','tour_scheduled') or not listing.contact or not permitted(listing) or db.contact_blocked(listing.contact.phone):
                update(sid, key, state='blocked', reason='Listing or contact changed; review needed', scheduled_at=None)
                return
            if db.contact_called_today(listing.contact.phone, saved['id'] if saved and saved['status'] in ('attention','failed') else -1):
                due = hours.next_open(policy, next_day=True)
                update(sid, key, state='scheduled', scheduled_at=due.isoformat(), reason='Contact already called today; next business day')
                return
            pipeline._call_listing(sid, key, follow_up_after=row['last_call_id'])
            finish(sid, key, policy)
        except Exception as error:
            log.warning('Outreach %s needs attention (%s)', sid, type(error).__name__)
            update(sid, key, state='needs_attention', reason='Saved call needs attention; retry safely', scheduled_at=None)


def start_background() -> threading.Event:
    stop = threading.Event()
    if not settings.outreach_worker or os.environ.get('VERCEL'):
        return stop
    # The single-process deployment restarts interrupted jobs with their saved call id/key.
    with db.conn() as c:
        c.execute("UPDATE outreach_jobs SET state='scheduled', scheduled_at=?, reason='Resuming saved call' WHERE state='calling'", (datetime.now(timezone.utc).isoformat(),))
        c.execute("UPDATE outreach_jobs SET state='needs_attention', reason='Hours check interrupted; retry' WHERE state='checking_hours'")
    def loop():
        while not stop.is_set():
            try:
                run_due()
                db.set_state('outreach_heartbeat', datetime.now(timezone.utc).isoformat())
            except Exception as error:
                log.warning('Outreach worker needs attention (%s)', type(error).__name__)
            stop.wait(15)
    threading.Thread(target=loop, daemon=True, name='outreach-worker').start()
    return stop

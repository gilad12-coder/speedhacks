"""Bridge the Python worker to the team's Next.js SearchBrief / AgentRun contract."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import httpx

from househunt import db
from househunt.config import settings
from househunt.models import ListingStatus, SearchCriteria
from househunt.outreach.verification import requirements


def criteria_from_brief(brief: dict) -> SearchCriteria:
    location = str(brief.get('location', '')).strip()
    if not location:
        raise ValueError('The household brief needs a search location')
    budget, occupants = int(brief['maxTotalRentUsd']), int(brief['occupants'])
    if budget <= 0 or not 1 <= occupants <= 6:
        raise ValueError('Invalid household budget or size')
    # One bedroom per housemate; someone searching alone can take a studio.
    return SearchCriteria(city=location, max_price=budget, min_beds=max(0, int(brief.get('minBedrooms', occupants if occupants > 1 else 0))),
        neighborhoods=list(brief.get('neighborhoods', [])),
        occupants=occupants, renter_name=str(brief.get('renterName') or 'my client')[:80],
        must_haves=list(brief.get('mustHaves', [])), deal_breakers=list(brief.get('dealBreakers', [])),
        nice_to_haves=list(brief.get('niceToHaves', [])), move_in_from=brief.get('moveInFrom') or None,
        move_in_by=brief.get('moveInTo') or None, commute=brief.get('commute', {}) if (brief.get('commute') or {}).get('destination') else {},
        wishes=[str(w)[:200] for w in brief.get('wishes', [])][:12],
        household_income_band=brief.get('householdIncomeBandUsd'))


def call_answers(criteria: SearchCriteria, outcome: dict, call_id: str) -> list[dict]:
    """One row per question the call asked, with the contact's quoted answer when it was confirmed."""
    confirmed = {f['key']: f for f in outcome.get('confirmed_facts', [])}
    items = {**{f'must:{i}':m for i,m in enumerate(criteria.must_haves)}, **{f'avoid:{i}':f'No {d.lower()}' for i,d in enumerate(criteria.deal_breakers)},
             **{f'nice:{i}':n for i,n in enumerate(criteria.nice_to_haves)}, **{f'wish:{i}':w for i,w in enumerate(criteria.wishes)}}
    names = {'available':'Still available','rent':'Monthly rent','qualifications':'What it takes to apply','beds':'Bedrooms',
             'baths':'Bathrooms','move_in':'Move-in date','move_window':'Move-in date','occupancy':'Household size','commute':'Commute'}
    rows = []
    for r in requirements(criteria):
        f = confirmed.get(r['key'], {})
        ev = (f.get('evidence') or [None])[0]
        rows.append({'key':r['key'],'group':r['group'],'label':names.get(r['key']) or items.get(r['key'], r['key']),'passed':f.get('passed'),
            'summary':f.get('summary') or 'Not confirmed on the call',
            'evidence':{'callId':call_id,'t':ev['t'],'quote':ev['quote']} if ev else None})
    return rows


def iso(value: str) -> str:
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        date = date.replace(tzinfo=ZoneInfo(settings.call_timezone))
    return date.isoformat()


def export_run(household_id: str, search_id: int, app_url: str = '') -> dict:
    from househunt.outreach.scheduler import jobs
    criteria, row = db.get_search(search_id)
    listings, calls, checks, windows, bookings = [], [], [], [], []
    call_rows = db.calls_for_search(search_id)
    in_flight = row['status'] not in ('done', 'error') or any(c['status'] in ('queued','in_progress','extracting') for c in call_rows.values()) or any(j['state'] in ('checking_hours','calling','scheduled') for j in jobs(search_id))
    for listing in db.list_listings(search_id):
        c = call_rows.get(listing.key)
        outcome = json.loads(c['outcome']) if c and c['outcome'] else {}
        status = 'found'
        if c:
            status = 'called'
        if outcome.get('verification_status') == 'verified':
            status = 'verified'
        if outcome.get('offered_windows') or outcome.get('tour_booked'):
            status = 'tour_offered'
        if listing.status in (ListingStatus.FILTERED_OUT, ListingStatus.NOT_VIABLE):
            status = 'ruled_out'
        risk = listing.screening
        market = risk.get('market', {})
        result = {'id':listing.key, 'source':'curated' if settings.mock_sources else 'live_search',
            'sourceUrl':listing.url, 'address':listing.address or listing.title, 'neighborhood':listing.neighborhood or '',
            'rentUsd':listing.price, 'bedrooms':listing.beds, 'bathrooms':listing.baths, 'photoUrls':listing.photo_urls,
            'contact':{'name':listing.contact.name or '' if listing.contact else '', 'role':'property_manager',
                       'phone':listing.contact.phone or '' if listing.contact else ''},
            'commuteMinutes':None, 'status':status,
            'research':{'status':risk.get('status','not_checked'), 'checkedAt':risk.get('checked_at'),
                'findings':[{'kind':f['kind'],'summary':f['explanation'],'quote':f['quote'],'sourceUrl':f['url']} for f in risk.get('findings', [])],
                'facts':[{'field':f['field'],'quote':f['quote'],'sourceUrl':f['url']} for f in listing.research.get('evidence',[])],
                'limitations':risk.get('limitations','Public-source screening has not completed. Ownership is not authenticated.'),
                'medianComparableRent':market.get('median_rent'), 'comparableCount':market.get('sample_size',0)}}
        if status == 'ruled_out':
            result.update(ruledOutReason='taken' if outcome.get('available') is False else 'breaks_must_have',
                          ruledOutNote=outcome.get('summary') or '; '.join(listing.notes[-2:]) or 'Does not meet the search requirements')
        if criteria.commute and result['status'] == 'verified':
            result['status'] = 'called'
        listings.append(result)
        if not c or not c['dial_call_id']:
            continue
        if not outcome and c['status'] in ('queued','in_progress','extracting'):
            continue  # No outcome exists yet; don't label a ringing call "no answer".
        raw = json.loads(c['raw']) if c['raw'] else {}
        call_id = str(c['id'])
        audio = (f"{app_url.rstrip('/')}/api/h/{quote(household_id, safe='')}/calls/{call_id}/recording"
                 if app_url and outcome.get('audio_url') else None)
        calls.append({'id':call_id,'listingId':listing.key,'dialCallId':c['dial_call_id'],
            'startedAt':iso(raw.get('createdAt') or c['created_at']), 'durationSec':float(raw.get('duration') or 0),
            'outcome':'voicemail' if outcome.get('voicemail') else 'answered' if outcome.get('reached_person') else 'failed' if c['status'] in ('failed','attention') else 'no_answer',
            'direction':c['direction'], 'voicemailLeft':outcome.get('voicemail_left', False),
            'audioUrl':audio,'transcript':outcome.get('transcript_turns',[]),
            'listingVerified': outcome.get('listing_verified') if outcome.get('mode') != 'dry_run' else None,
            'statedRentUsd':outcome.get('monthly_rent'),'deposit':outcome.get('deposit'),'leaseTerms':outcome.get('lease_terms'),
            'answers':call_answers(criteria, outcome, call_id) if outcome.get('reached_person') else []})
        booked = outcome.get('confirmed_tour')
        if booked and outcome.get('tour_booked') and outcome.get('listing_verified') is True and outcome.get('mode') == 'live':
            bookings.append({'listingId':listing.key, 'callId':call_id, 'start':booked['start'], 'end':booked['end'],
                'meetingAddress':booked['meeting_address'],
                'contactEvidence':{**booked['contact_evidence'], 'callId':call_id},
                'agentEvidence':{**booked['agent_evidence'], 'callId':call_id}})
        for check in outcome.get('checks',[]):
            ev = check.get('evidence')
            if check['kind'] == 'matches' and check['passed'] is True and criteria.commute:
                check = {**check,'passed':None,'summary':'Call requirements confirmed; requested commute duration has not been measured'}
                ev = None
            checks.append({**check,'listingId':listing.key,'evidence':{**ev,'callId':call_id} if ev else None})
        if not outcome.get('tour_booked'):
            windows.extend({**w,'listingId':listing.key} for w in outcome.get('offered_windows',[]))
    warnings = [row['error']] if row['error'] else []
    if criteria.commute:
        warnings.append('Commute duration has not been measured; commute limits remain unconfirmed.')
    for c in call_rows.values():
        if c['error']:
            warnings.append(c['error'])
        outcome = json.loads(c['outcome']) if c['outcome'] else {}
        if outcome.get('booking_warning'):
            warnings.append(outcome['booking_warning'])
    events = db.search_events(search_id)
    finished = max([row['created_at'], *[e['created_at'] for e in events],
                    *[c['updated_at'] for c in call_rows.values()]])
    return {'householdId':household_id,'startedAt':iso(row['created_at']),
        'finishedAt':None if in_flight else iso(finished),
        'listings':listings,'calls':calls,'checks':checks,'offeredWindows':windows,'bookedTours':bookings,
        'outreach':[{'listingId':j['listing_key'], 'state':j['state'], 'scheduledAt':j['scheduled_at'],
            'reason':j['reason'], 'hoursSource':j['hours'].get('source'), 'hoursQuote':j['hours'].get('quote'),
            'timezone':j['hours'].get('timezone'), 'attempts':j['attempts']} for j in jobs(search_id)],
        'progress':[e['message'] for e in events], 'warnings':warnings}


class PlatformClient:
    def __init__(self):
        self.url = os.environ.get('APP_URL','').rstrip('/')
        key = os.environ.get('AGENT_API_KEY','')
        p = urlsplit(self.url)
        if not key or not p.hostname or p.username or p.password or (p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in ('localhost','127.0.0.1'))):
            raise RuntimeError('Set APP_URL (HTTPS, or localhost) and the shared AGENT_API_KEY')
        headers = {'Authorization':'Bearer '+key}
        # Vercel Deployment Protection: the project's "Protection Bypass for Automation" secret.
        bypass = os.environ.get('VERCEL_PROTECTION_BYPASS','').strip()
        if bypass:
            headers['x-vercel-protection-bypass'] = bypass
        self.http = httpx.Client(base_url=self.url, headers=headers, timeout=30, follow_redirects=False)

    def briefs(self):
        r = self.http.get('/api/agent/briefs')
        if r.is_redirect and 'vercel.com/sso' in r.headers.get('location',''):
            raise RuntimeError('The app is behind Vercel Deployment Protection; set VERCEL_PROTECTION_BYPASS')
        if not r.is_success:
            raise RuntimeError(f'Household brief API returned HTTP {r.status_code}')
        return r.json()['briefs']

    def publish(self, household_id: str, search_id: int) -> None:
        run = export_run(household_id, search_id, self.url)
        digest = hashlib.sha256(json.dumps(run,sort_keys=True).encode()).hexdigest()
        with db.conn() as conn:
            job = conn.execute('SELECT published_hash FROM household_jobs WHERE household_id=?',(household_id,)).fetchone()
        if job and job['published_hash'] == digest:
            return
        r = self.http.post('/api/agent/runs',json=run)
        if not r.is_success:
            raise RuntimeError(f'AgentRun publish returned HTTP {r.status_code}; local evidence is saved')
        sync_results = {item['callId']:item for item in r.json().get('calendarSync', [])}
        pending = False
        for tour in db.tours_for_search(search_id).values():
            if tour['source_call_id'] is None:
                continue
            result = sync_results.get(str(tour['source_call_id']))
            if result:
                db.update_tour_calendar(tour['id'], result['status'], result.get('error'))
            pending = pending or not result or result['status'] != 'synced'
        with db.conn() as conn:
            conn.execute('UPDATE household_jobs SET published_hash=? WHERE household_id=?',(None if pending else digest,household_id))


def ensure_search(client: PlatformClient, brief: dict) -> int:
    """The search for a household's brief, created once. Safe to call from the web app
    (when a housemate is handed over from onboarding) and from the worker loop."""
    household_id = brief['householdId']
    sid = db.household_search(household_id)
    if sid is None:
        criteria = criteria_from_brief(brief)
        with _ensure_lock:
            sid = db.household_search(household_id)
            if sid is None:
                sid = db.create_search(criteria)
                with db.conn() as conn:
                    conn.execute('INSERT INTO household_jobs(household_id,search_id) VALUES (?,?)',(household_id,sid))
        client.publish(household_id,sid)
    return sid


_ensure_lock = threading.Lock()
# Set to run the worker loop now instead of waiting for the next poll.
wake = threading.Event()


def start_background_worker(interval: float = 15) -> threading.Thread | None:
    """Run the worker loop inside the web app (single-process deploys and local dev).
    Enabled with RUN_PLATFORM_WORKER=1; otherwise run `python -m househunt.platform`."""
    if os.environ.get('RUN_PLATFORM_WORKER') != '1' or os.environ.get('VERCEL'):
        return None
    client = PlatformClient()

    def loop():
        while True:
            try:
                run_once(client)
            except (RuntimeError, ValueError, httpx.HTTPError) as e:
                print(f'Worker needs attention: {type(e).__name__}: {e}', flush=True)
            wake.wait(interval)
            wake.clear()

    t = threading.Thread(target=loop, name='platform-worker', daemon=True)
    t.start()
    return t


def tick(lease_seconds: int = 800) -> bool:
    """One worker pass for serverless hosts (Vercel Cron runs it every minute) in place of
    the background loop. Returns False when another pass is still running."""
    if not db.claim_lease('platform-worker', lease_seconds):
        return False
    try:
        # A pass that hit the function time limit leaves its calls mid-flight; one untouched
        # for 20 minutes is treated like a restart and waits for an explicit resume.
        db.recover_calls(older_than=(datetime.now() - timedelta(minutes=20)).isoformat(timespec='seconds'))
        from househunt import phone
        from househunt.outreach import scheduler
        if settings.callback_enabled:
            phone.ensure_callbacks()
            phone.poll_inbound()
        run_once(PlatformClient())
        if settings.outreach_worker:
            scheduler.run_due()
            with db.conn() as c:
                jobs = c.execute('SELECT household_id, search_id FROM household_jobs').fetchall()
            client = PlatformClient()
            for job in jobs:
                client.publish(job['household_id'], job['search_id'])
    finally:
        db.release_lease('platform-worker')
    return True


def run_once(client: PlatformClient) -> None:
    from househunt.pipeline import run_search
    for brief in client.briefs():
        household_id = brief['householdId']
        sid = ensure_search(client, brief)
        _, row = db.get_search(sid)
        if row['status'] in ('pending','sourcing','screening','calling'):
            run_search(sid, on_update=lambda: client.publish(household_id,sid))
    with db.conn() as conn:
        jobs = conn.execute('SELECT * FROM household_jobs').fetchall()
    for job in jobs:
        client.publish(job['household_id'],job['search_id'])


def main():
    import argparse
    import time
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    db.init()
    db.recover_calls()
    from househunt.outreach import scheduler
    from househunt import phone
    scheduler.start_background()
    phone.start_background()
    client = PlatformClient()
    while True:
        try:
            run_once(client)
        except (RuntimeError, ValueError, httpx.HTTPError) as e:
            print(f'Worker needs attention: {type(e).__name__}. Check app URL, credentials and saved search status.',flush=True)
            if args.once:
                raise SystemExit(1) from None
        if args.once:
            return
        time.sleep(5)


if __name__ == '__main__':
    # Settings are read on import; launch with `dotenv run -- ...`.
    main()

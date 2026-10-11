"""Bridge the Python worker to the team's Next.js SearchBrief / AgentRun contract."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import httpx

from househunt import db
from househunt.config import settings
from househunt.models import ListingStatus, SearchCriteria


def criteria_from_brief(brief: dict) -> SearchCriteria:
    location = str(brief.get('location', '')).strip()
    if not location:
        raise ValueError('The household brief needs a search location')
    budget, occupants = int(brief['maxTotalRentUsd']), int(brief['occupants'])
    if budget <= 0 or not 1 <= occupants <= 6:
        raise ValueError('Invalid household budget or size')
    return SearchCriteria(city=location, max_price=budget, min_beds=occupants,
        occupants=occupants, renter_name=str(brief.get('renterName') or settings.renter_name or 'my client')[:80],
        must_haves=list(brief.get('mustHaves', [])), deal_breakers=list(brief.get('dealBreakers', [])),
        nice_to_haves=list(brief.get('niceToHaves', [])), move_in_from=brief.get('moveInFrom'),
        move_in_by=brief.get('moveInTo'), commute=brief.get('commute', {}))


def iso(value: str) -> str:
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        date = date.replace(tzinfo=ZoneInfo(settings.call_timezone))
    return date.isoformat()


def export_run(household_id: str, search_id: int, app_url: str = '') -> dict:
    criteria, row = db.get_search(search_id)
    listings, calls, checks, windows = [], [], [], []
    call_rows = db.calls_for_search(search_id)
    in_flight = row['status'] not in ('done', 'error') or any(c['status'] in ('queued','in_progress','extracting') for c in call_rows.values())
    for listing in db.list_listings(search_id):
        c = call_rows.get(listing.key)
        outcome = json.loads(c['outcome']) if c and c['outcome'] else {}
        status = 'found'
        if c:
            status = 'called'
        if outcome.get('verification_status') == 'verified':
            status = 'verified'
        if outcome.get('offered_windows'):
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
            'outcome':'answered' if outcome.get('reached_person') else 'failed' if c['status'] in ('failed','attention') else 'no_answer',
            'audioUrl':audio,'transcript':outcome.get('transcript_turns',[])})
        for check in outcome.get('checks',[]):
            ev = check.get('evidence')
            if check['kind'] == 'matches' and check['passed'] is True and criteria.commute:
                check = {**check,'passed':None,'summary':'Call requirements confirmed; requested commute duration has not been measured'}
                ev = None
            checks.append({**check,'listingId':listing.key,'evidence':{**ev,'callId':call_id} if ev else None})
        windows.extend({**w,'listingId':listing.key} for w in outcome.get('offered_windows',[]))
    warnings = [row['error']] if row['error'] else []
    if criteria.commute:
        warnings.append('Commute duration has not been measured; commute limits remain unconfirmed.')
    for c in call_rows.values():
        if c['error']:
            warnings.append(c['error'])
    events = db.search_events(search_id)
    finished = max([row['created_at'], *[e['created_at'] for e in events],
                    *[c['updated_at'] for c in call_rows.values()]])
    return {'householdId':household_id,'startedAt':iso(row['created_at']),
        'finishedAt':None if in_flight else iso(finished),
        'listings':listings,'calls':calls,'checks':checks,'offeredWindows':windows,
        'progress':[e['message'] for e in events], 'warnings':warnings}


class PlatformClient:
    def __init__(self):
        self.url = os.environ.get('APP_URL','').rstrip('/')
        key = os.environ.get('AGENT_API_KEY','')
        p = urlsplit(self.url)
        if not key or not p.hostname or p.username or p.password or (p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in ('localhost','127.0.0.1'))):
            raise RuntimeError('Set APP_URL (HTTPS, or localhost) and the shared AGENT_API_KEY')
        self.http = httpx.Client(base_url=self.url, headers={'Authorization':'Bearer '+key}, timeout=30, follow_redirects=False)

    def briefs(self):
        r = self.http.get('/api/agent/briefs')
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
        with db.conn() as conn:
            conn.execute('UPDATE household_jobs SET published_hash=? WHERE household_id=?',(digest,household_id))


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
    if os.environ.get('RUN_PLATFORM_WORKER') != '1':
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

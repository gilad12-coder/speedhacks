import importlib
import json
import sys

import pytest


@pytest.fixture
def platform(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'worker.db'))
    monkeypatch.setenv('CALL_MODE','approve')
    monkeypatch.setenv('MOCK_SOURCES','0')
    monkeypatch.setenv('GEOCODE','0')
    monkeypatch.setenv('AGENT_API_KEY','test-worker-secret')
    monkeypatch.delenv('APP_PASSWORD',raising=False)
    import househunt.config
    importlib.reload(househunt.config)
    for name in ('househunt.db','househunt.pipeline','househunt.platform','househunt.web.app'):
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    from househunt import db,platform
    db.init()
    return db,platform


def test_brief_identity_constraints_and_null_export(platform):
    db,p = platform
    from househunt.models import Listing,Source
    c = p.criteria_from_brief({'location':'SF','maxTotalRentUsd':4500,'occupants':2,'renterName':'Reed',
        'mustHaves':['laundry'],'dealBreakers':['shared bedroom'],'moveInFrom':'2026-11-01','moveInTo':'2026-11-15',
        'commute':{'destination':'Office','maxMinutes':30}})
    assert c.renter_name == 'Reed' and c.min_beds == 2 and c.deal_breakers == ['shared bedroom']
    sid=db.create_search(c)
    l=Listing(source=Source.OTHER,source_id='1',url='https://example.com/listing',title='Rental')
    db.upsert_listing(sid,l)
    db.set_search_status(sid,'done')
    run=p.export_run('household',sid)
    assert run['listings'][0]['rentUsd'] is None and run['listings'][0]['bedrooms'] is None
    assert run['checks'] == [] and run['calls'] == []
    assert run['finishedAt'].endswith('-07:00') and 'Commute' in run['warnings'][0]


def test_polling_never_repeats_completed_search(platform,monkeypatch):
    db,p=platform
    from househunt import pipeline
    searches=[]
    def run_search(sid,on_update):
        searches.append(sid)
        db.set_search_status(sid,'done')
        on_update()
    monkeypatch.setattr(pipeline,'run_search',run_search)
    class Client:
        def briefs(self): return [{'householdId':'h1','location':'SF','maxTotalRentUsd':4500,'occupants':2}]
        def publish(self,*args): pass
    p.run_once(Client())
    p.run_once(Client())
    assert len(searches)==1 and db.household_search('h1')==searches[0]


def test_worker_api_requires_secret_and_household_owns_recording(platform):
    from fastapi.testclient import TestClient
    from househunt.web.app import app
    with TestClient(app) as client:
        path='/agent/households/unknown/calls/1/recording'
        assert client.get(path).status_code==401
        assert client.get(path,headers={'Authorization':'Bearer wrong'}).status_code==401
        assert client.get(path,headers={'Authorization':'Bearer test-worker-secret'}).status_code==404


def test_call_evidence_ids_map_to_local_call_and_audio_proxy(platform):
    db,p=platform
    from househunt.models import Contact,Listing,SearchCriteria,Source
    sid=db.create_search(SearchCriteria(city='SF',max_price=4000))
    l=Listing(source=Source.OTHER,source_id='1',url='https://example.com/1',title='Rental',contact=Contact(phone='+12025550123'))
    db.upsert_listing(sid,l)
    c=db.claim_call(sid,l.key,l.contact.phone,'live')
    db.update_call(c['id'],dial_call_id='provider-id',status='ended',raw={'id':'provider-id','duration':10},
       outcome={'reached_person':True,'audio_url':f"/calls/{c['id']}/recording",'checks':[
        {'kind':'real','passed':True,'summary':'Available','evidence':{'callId':'provider-id','t':2,'quote':'Available'}}]})
    run=p.export_run('h1',sid,'https://app.example.com')
    assert run['checks'][0]['evidence']['callId']==run['calls'][0]['id']==str(c['id'])
    assert run['calls'][0]['audioUrl']==f"https://app.example.com/api/h/h1/calls/{c['id']}/recording"
    assert 'provider-id' not in run['calls'][0]['audioUrl']


def test_call_hears_wishes_and_exports_quoted_answers(platform):
    _,p = platform
    from househunt.outreach.script import build_instruction
    from househunt.models import Listing,Source
    c = p.criteria_from_brief({'location':'SF','maxTotalRentUsd':3000,'occupants':1,'renterName':'Dana',
        'mustHaves':['Pets allowed'],'niceToHaves':['In-unit laundry'],'wishes':['A quiet street'],
        'commute':{'destination':'Office','modes':['transit'],'maxMinutes':30}})
    text = build_instruction(Listing(source=Source.OTHER,source_id='1',url='https://e.com',title='Rental'),c,'Dana')
    must, prefs = text.index('Pets allowed'), text.index('preferences')
    assert must < prefs < text.index('In-unit laundry') and text.index('A quiet street') > prefs and 'Office' in text
    outcome = {'confirmed_facts':[{'key':'must:0','passed':True,'summary':'Cats are fine','evidence':[{'callId':'dial-x','t':12.5,'quote':'cats are fine'}]}]}
    rows = {r['key']:r for r in p.call_answers(c,outcome,'7')}
    assert rows['must:0'] == {'key':'must:0','group':'matches','label':'Pets allowed','passed':True,'summary':'Cats are fine',
                              'evidence':{'callId':'7','t':12.5,'quote':'cats are fine'}}
    assert rows['wish:0']['group'] == 'nice' and rows['wish:0']['passed'] is None and rows['wish:0']['evidence'] is None
    assert rows['occupancy']['label'] == 'Household size' and rows['commute']['group'] == 'nice'

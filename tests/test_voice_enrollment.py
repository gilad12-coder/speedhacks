import importlib
import io
import math
import sys
from array import array
from types import SimpleNamespace
import wave

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope='module')
def sample():
    cycle = array('h', (int(5000 * math.sin(i * 2 * math.pi / 80)) for i in range(80)))
    samples = cycle * 24000
    if sys.byteorder != 'little': samples.byteswap()
    out = io.BytesIO()
    with wave.open(out, 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000); f.writeframes(samples.tobytes())
    return out.getvalue()


@pytest.fixture
def enrollment(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH', str(tmp_path / 'test.db'))
    monkeypatch.setenv('APP_PASSWORD', 'test-password')
    monkeypatch.setenv('AGENT_API_KEY', 'test-agent-key')
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-provider-key')
    monkeypatch.setenv('VOICE_MODE', 'managed')
    monkeypatch.setenv('CALL_MODE', 'dry_run')
    monkeypatch.setenv('MOCK_SOURCES', '1')
    monkeypatch.setenv('RUN_PLATFORM_WORKER', '0')
    monkeypatch.delenv('BRIEFING_PIN', raising=False)
    import househunt.config
    import househunt.db
    importlib.reload(househunt.config)
    importlib.reload(househunt.db)
    from househunt.web import app as web
    importlib.reload(web)
    from househunt.voice import enrollment as api
    from househunt.models import SearchCriteria
    db = househunt.db
    db.init()
    sid = db.create_search(SearchCriteria(city='SF', max_price=4500, renter_name='Reed'))
    other = db.create_search(SearchCriteria(city='SF', max_price=4500))
    with db.conn() as conn:
        conn.execute('INSERT INTO household_jobs(household_id,search_id) VALUES (?,?)', ('home-a', sid))
        conn.execute('INSERT INTO household_jobs(household_id,search_id) VALUES (?,?)', ('home-b', other))
    calls = []
    def create(**kwargs):
        calls.append('create')
        assert kwargs['files'][0][0] == 'sample.wav'
        assert kwargs['request_options'] == {'max_retries': 0}
        return SimpleNamespace(voice_id='private-clone', requires_verification=False)
    def delete(voice_id): calls.append(('delete', voice_id))
    provider = SimpleNamespace(voices=SimpleNamespace(ivc=SimpleNamespace(create=create), delete=delete),
        text_to_speech=SimpleNamespace(convert=lambda **_: iter([b'ID3' + b'\0' * 200])))
    monkeypatch.setattr(api, 'ElevenLabs', lambda **_: provider)
    with TestClient(web.app) as client:
        client.auth = ('operator', 'test-password')
        yield client, sid, api, calls


def upload_headers():
    return {'X-KeyHunt-Voice': '1', 'X-Voice-Consent': 'true', 'X-Voice-Name': 'Reed', 'Content-Type': 'audio/wav'}


def test_two_minute_enrollment_preview_approval_removal(enrollment, sample):
    client, sid, api, calls = enrollment
    path = f'/api/searches/{sid}/voice'
    result = client.post(path, content=sample, headers=upload_headers())
    assert result.status_code == 202
    current = client.get(path).json()
    assert current['phase'] == 'audition' and current['approved'] is False
    assert current['callingEnabled'] is False
    assert 'private-clone' not in str(current)
    assert client.get(path + '/preview').headers['cache-control'] == 'private, no-store'
    assert not api.store.read('profiles', str(sid))
    assert client.post(path + '/approve', headers={'X-KeyHunt-Voice':'1'}, json={'approved':True,'enrollmentId':'wrong'}).status_code == 400
    approved = client.post(path + '/approve', headers={'X-KeyHunt-Voice':'1'}, json={'approved':True,'enrollmentId':current['enrollmentId']})
    assert approved.status_code == 200 and approved.json()['approved']
    assert api.store.profile(sid)['speaker_name'] == 'Reed'
    assert client.post(path, content=sample, headers=upload_headers()).status_code == 409
    assert calls == ['create']
    assert client.delete(path, headers={'X-KeyHunt-Voice':'1'}).status_code == 200
    assert calls == ['create', ('delete','private-clone')]
    assert not api.store.read('profiles', str(sid))
    assert not list(api.store.private_path('enrollments',str(sid)).parent.glob('*.mp3'))
    assert not list(api.store.private_path('enrollments',str(sid)).parents[1].rglob('*.wav'))


def test_enrollment_requires_auth_consent_and_same_site(enrollment, sample):
    client, sid, _, calls = enrollment
    path = f'/api/searches/{sid}/voice'
    assert client.get(path, auth=('operator','wrong')).status_code == 401
    for header, status in [({'Content-Type':'audio/wav'},403),
                           ({'X-KeyHunt-Voice':'1'},400),
                           ({**upload_headers(),'Sec-Fetch-Site':'cross-site'},403)]:
        assert client.post(path, content=sample, headers=header).status_code == status
    assert calls == []


def test_enrollment_rejects_short_silent_and_oversized_before_provider(enrollment, sample):
    client, sid, _, calls = enrollment
    path = f'/api/searches/{sid}/voice'
    assert client.post(path, content=sample[:1000], headers=upload_headers()).status_code == 422
    silent = sample[:44] + b'\0' * (len(sample) - 44)
    assert client.post(path, content=silent, headers=upload_headers()).status_code == 422
    assert client.post(path, content=b'x' * 4_000_001, headers=upload_headers()).status_code == 413
    assert client.post(path, content=b'not audio', headers={**upload_headers(),'Content-Type':'audio/mpeg'}).status_code == 415
    assert calls == []


def test_household_api_scopes_voice_and_hides_provider_ids(enrollment, sample):
    client, sid, _, _ = enrollment
    headers = {**upload_headers(), 'Authorization':'Bearer test-agent-key'}
    path = '/agent/households/home-a/voice'
    assert client.post(path, content=sample, headers=headers, auth=None).status_code == 202
    auth = {'Authorization':'Bearer test-agent-key'}
    assert client.get('/agent/households/home-b/voice', headers=auth, auth=None).json()['phase'] == 'empty'
    assert client.get('/agent/households/home-b/voice/preview', headers=auth, auth=None).status_code == 404
    assert client.get('/agent/households/missing/voice', headers=auth, auth=None).status_code == 404
    assert client.get(path, auth=None).status_code == 401


def test_voice_page_includes_script_and_two_minute_controls(enrollment):
    client, sid, api, _ = enrollment
    response = client.get(f'/searches/{sid}/voice')
    assert response.status_code == 200
    assert 'Record two minutes' in response.text and 'ElevenLabs' in response.text
    assert 'two thousand eight hundred dollars' in response.text
    assert len(' '.join(api.SCRIPT).split()) > 280
    assert client.get('/voice-assets/voice-capture.js').status_code == 200


def test_provider_failure_never_approves_or_exposes_provider_body(enrollment, sample, monkeypatch):
    client, sid, api, _ = enrollment
    def fail(**kwargs): raise RuntimeError('secret provider body')
    monkeypatch.setattr(api, 'ElevenLabs', fail)
    path = f'/api/searches/{sid}/voice'
    assert client.post(path, content=sample, headers=upload_headers()).status_code == 202
    status = client.get(path).json()
    assert status['phase'] == 'error' and not status['approved']
    assert 'secret provider body' not in str(status)


def test_preview_retry_reuses_clone_without_uploading_again(enrollment, sample, monkeypatch):
    client, sid, api, calls = enrollment
    path = f'/api/searches/{sid}/voice'
    client.post(path, content=sample, headers=upload_headers())
    record = api.state(sid)
    record.update(phase='error', error='Preview interrupted')
    api.store.save('enrollments', str(sid), record)
    assert client.post(path+'/preview', headers={'X-KeyHunt-Voice':'1'}).status_code == 202
    assert client.get(path).json()['phase'] == 'audition'
    assert calls == ['create']


def test_restart_turns_incomplete_enrollment_into_recoverable_error(enrollment):
    _, sid, api, _ = enrollment
    api.store.save('enrollments', str(sid), {'id':'a'*32,'phase':'creating_preview','voice_id':'private-clone'})
    api.recover_pending()
    assert api.state(sid)['phase'] == 'error'
    assert api.status(sid)['canRetryPreview']

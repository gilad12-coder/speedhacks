import asyncio
import hashlib
import hmac
import importlib
import json
import time

import pytest


@pytest.fixture
def voice_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "voice.db"))
    monkeypatch.setenv("VOICE_MODE", "elevenlabs")
    monkeypatch.setenv("DIAL_AUDIO_SIGNING_SECRET", "test-signing-secret")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "test-agent")
    import househunt.config
    import househunt.db
    importlib.reload(househunt.config)
    importlib.reload(househunt.db)
    from househunt.voice import bridge, store
    importlib.reload(bridge)
    househunt.db.init()
    return househunt.db, bridge, store


def test_relay_interrupt_discards_late_audio_and_forwards_ping():
    from househunt.voice.bridge import Relay
    async def run():
        dial, provider, metadata = [], [], []
        async def d(frame): dial.append(frame.model_dump())
        async def p(frame): provider.append(frame)
        relay = Relay(d, p, metadata.append)
        await relay.provider_event({"type": "conversation_initiation_metadata", "conversation_initiation_metadata_event": {
            "conversation_id": "c1", "agent_output_audio_format": "pcm_16000", "user_input_audio_format": "pcm_16000"}})
        await relay.provider_event({"type": "interruption", "interruption_event": {"event_id": 2}})
        for event_id in [1, 2, 3]:
            await relay.provider_event({"type": "audio", "audio_event": {"event_id": event_id, "audio_base_64": "AAA="}})
        await relay.provider_event({"type": "ping", "ping_event": {"event_id": 8}})
        assert [x['type'] for x in dial] == ["clear", "media"]
        assert provider == [{"type": "pong", "event_id": 8}]
        assert metadata == ["c1"]
    asyncio.run(run())


def test_relay_refuses_mismatched_codec_and_pre_metadata_audio():
    from househunt.voice.bridge import Relay
    async def noop(*args): pass
    async def run():
        relay = Relay(noop, noop, lambda _: None)
        with pytest.raises(RuntimeError, match="format"):
            await relay.provider_event({"type": "conversation_initiation_metadata", "conversation_initiation_metadata_event": {
                "conversation_id": "c1", "agent_output_audio_format": "ulaw_8000", "user_input_audio_format": "pcm_16000"}})
        with pytest.raises(RuntimeError, match="negotiation"):
            await relay.provider_event({"type": "audio", "audio_event": {"event_id": 1, "audio_base_64": "AAA="}})
    asyncio.run(run())


def test_private_enrollment_is_scoped_and_requires_audition(voice_env):
    _, _, store = voice_env
    store.save("profiles", "1", {"voice_id": "v1", "speaker_name": "Reed", "consented_at": "now"})
    with pytest.raises(RuntimeError, match="audition"):
        store.profile(1)
    with pytest.raises(RuntimeError):
        store.profile(2)
    assert store.private_path("profiles", "1").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        store.private_path("sessions", "../../.env")


def test_identity_uses_enrollment_and_saved_instruction():
    from househunt.voice.bridge import initiation
    message = initiation({"instruction": "Saved authorized instruction"}, {"speaker_name": "Reed", "voice_id": "private-clone"})
    overrides = message["conversation_config_override"]
    assert "Reed's AI assistant" in overrides["agent"]["first_message"]
    assert overrides["agent"]["prompt"]["prompt"] == "Saved authorized instruction"
    assert overrides["tts"]["voice_id"] == "private-clone"


def test_authoritative_transcript_preserves_offsets_and_rejects_invented_times():
    from househunt.voice.evidence import transcript_turns
    assert transcript_turns({"transcript": [{"role": "user", "message": "Rent is 3000", "time_in_call_secs": 1.25}]}) == [
        {"speaker": "user", "startMs": 1250, "text": "Rent is 3000"}]
    for offset in [None, -1, float("nan"), float("inf"), True]:
        with pytest.raises(RuntimeError):
            transcript_turns({"transcript": [{"role": "user", "message": "Claim", "time_in_call_secs": offset}]})


def test_recording_import_is_private_and_rejects_html(voice_env):
    from househunt.voice.evidence import save_audio
    _, _, store = voice_env
    with pytest.raises(RuntimeError):
        save_audio([b"<html>login required</html>"], "call-1")
    save_audio([b"ID3" + b"\0" * 30], "call-1")
    folder = store.private_path("sessions", "call-1").parents[2]
    assert (folder / "recordings" / "call-1.mp3").stat().st_mode & 0o777 == 0o600


def signature(call_id, timestamp=None):
    t = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(b"test-signing-secret", f"{t}.{call_id}".encode(), hashlib.sha256).hexdigest()
    return {"x-dial-signature": f"t={t},v1={digest}"}


def test_socket_auth_rejects_missing_stale_and_wrong_call_signatures(voice_env):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    _, bridge, _ = voice_env
    with TestClient(bridge.app) as client:
        for headers in [{}, signature("different-call"), signature("call-1", int(time.time()) - 90)]:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/audio/call-1", headers=headers):
                    pass


def test_socket_rejects_mismatched_call_before_provider_connect(voice_env):
    from fastapi.testclient import TestClient
    _, bridge, _ = voice_env
    with TestClient(bridge.app) as client:
        with client.websocket_connect("/audio/call-1", headers=signature("call-1")) as ws:
            ws.send_json({"type": "call_connected", "call_id": "wrong-call", "direction": "outbound", "from": "+12025550124", "to": "+12025550123",
                          "formats": {"inbound": "l16_16000", "outbound": "l16_16000"}})
            assert ws.receive_json() == {"type": "end_call"}


def test_agent_setup_auth_and_only_needed_overrides():
    from househunt.voice.setup import agent_config
    from elevenlabs.types import ConversationalConfig, AgentPlatformSettingsRequestModel
    config = agent_config("enrolled-clone")
    ConversationalConfig.model_validate(config["conversation_config"])
    AgentPlatformSettingsRequestModel.model_validate(config["platform_settings"])
    assert config["platform_settings"]["auth"]["enable_auth"]
    assert "Reed" not in json.dumps(config)
    assert config["conversation_config"]["agent"]["prompt"]["built_in_tools"].keys() == {"end_call"}


@pytest.mark.parametrize("hangup", ["call_ended", "dtmf"])
def test_full_socket_relay_keeps_dial_alive_and_clears_interrupted_audio(voice_env, monkeypatch, hangup):
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from househunt.models import Listing, Contact, SearchCriteria, Source
    db, bridge, store = voice_env
    sid = db.create_search(SearchCriteria(city="SF", max_price=4500))
    listing = Listing(source=Source.OTHER, source_id="voice-test", url="https://example.com/1", title="Test rental", contact=Contact(phone="+12025550123"))
    db.upsert_listing(sid, listing)
    row = db.claim_call(sid, listing.key, listing.contact.phone, "live")
    db.update_call(row["id"], dial_call_id="call-1", instruction="Saved rental instruction")
    store.save("profiles", str(sid), {"voice_id": "test-clone", "speaker_name": "Reed", "consented_at": "test", "audition_approved_at": "test"})
    sent = []

    class Provider:
        async def __aenter__(self):
            self.events = asyncio.Queue()
            return self
        async def __aexit__(self, *args): pass
        def __aiter__(self): return self
        async def __anext__(self): return json.dumps(await self.events.get())
        async def send(self, raw):
            event = json.loads(raw)
            sent.append(event)
            if event.get("type") == "conversation_initiation_client_data":
                await self.events.put({"type": "conversation_initiation_metadata", "conversation_initiation_metadata_event": {
                    "conversation_id": "test-conv", "agent_output_audio_format": "pcm_16000", "user_input_audio_format": "pcm_16000"}})
                await self.events.put({"type": "audio", "audio_event": {"event_id": 1, "audio_base_64": "AAA="}})
            if "user_audio_chunk" in event:
                await self.events.put({"type": "interruption", "interruption_event": {"event_id": 1}})
                await self.events.put({"type": "audio", "audio_event": {"event_id": 1, "audio_base_64": "AAA="}})
                await self.events.put({"type": "audio", "audio_event": {"event_id": 2, "audio_base_64": "AQE="}})

    async def signed(**kwargs): return SimpleNamespace(signed_url="wss://api.elevenlabs.io/test")
    monkeypatch.setattr(bridge, "AsyncElevenLabs", lambda **kwargs: SimpleNamespace(conversational_ai=SimpleNamespace(conversations=SimpleNamespace(get_signed_url=signed))))
    monkeypatch.setattr(bridge, "connect", lambda *args, **kwargs: Provider())
    with TestClient(bridge.app) as client:
        with client.websocket_connect("/audio/call-1", headers=signature("call-1")) as ws:
            ws.send_json({"type": "call_connected", "call_id": "call-1", "direction": "outbound", "from": "+12025550124", "to": "+12025550123",
                          "formats": {"inbound": "l16_16000", "outbound": "l16_16000"}})
            assert ws.receive_json() == {"type": "media", "payload": "AAA="}
            ws.send_json({"type": "ping_pong", "timestamp": 123})
            assert ws.receive_json() == {"type": "ping_pong", "timestamp": 123}
            ws.send_json({"type": "media", "payload": "AAA=", "seq": 1})
            assert ws.receive_json() == {"type": "clear"}
            assert ws.receive_json() == {"type": "media", "payload": "AQE="}
            assert store.read("sessions", "call-1")["conversation_id"] == "test-conv"
            if hangup == "dtmf":
                ws.send_json({"type": "dtmf", "digit": "#"})
                assert ws.receive_json() == {"type": "end_call"}
            else:
                ws.send_json({"type": "call_ended", "reason": "caller_hangup"})
    assert sent[0]["conversation_config_override"]["tts"]["voice_id"] == "test-clone"


def test_custom_voice_never_silently_falls_back_to_managed_call(monkeypatch):
    import httpx
    from dataclasses import replace
    from househunt.config import settings
    from househunt.outreach.dial import DialClient
    monkeypatch.setenv("VOICE_MODE", "elevenlabs")
    dial = DialClient(replace(settings, dial_api_key="test", dial_from_number="+12025550123"))
    dial.http.close()
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"enabled": False, "activeMode": None})
    with httpx.Client(transport=httpx.MockTransport(handle), base_url="https://api.getdial.ai") as http:
        dial.http = http
        with pytest.raises(RuntimeError, match="inactive"):
            dial.place_call("+12025550124", "Test")
    assert [(r.method, r.url.path) for r in requests] == [("GET", "/api/v1/self-hosted")]

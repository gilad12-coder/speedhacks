"""Explicit operator setup; importing this module never uploads, activates or calls."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


def agent_config(voice_id: str, model: str = "eleven_v4_turbo") -> dict:
    return {
        "name": "KeyHunt rental voice assistant",
        "conversation_config": {
            "agent": {"first_message": "Hi, I'm an AI assistant with KeyHunt.", "language": "en",
                "prompt": {"prompt": "You are KeyHunt's disclosed AI rental assistant. Use the authorized per-call instruction. Book a tour only within its explicit calendar authorization and after confirming the exact unit. Never pay or submit applications.",
                    "llm": "gpt-4.1-mini", "temperature": .25, "max_tokens": 180,
                    "built_in_tools": {"end_call": {"type": "system", "name": "end_call", "params": {"system_tool_type": "end_call"}}}}},
            "asr": {"quality": "high", "provider": "scribe_realtime", "user_input_audio_format": "pcm_16000"},
            "tts": {"voice_id": voice_id, "model_id": model, "agent_output_audio_format": "pcm_16000",
                    "stability": .5, "similarity_boost": .8, "speed": 1.0},
            "turn": {"turn_eagerness": "normal", "turn_timeout": 7, "silence_end_call_timeout": 20},
            "conversation": {"max_duration_seconds": 180, "client_events": ["audio", "interruption", "user_transcript", "agent_response", "agent_response_correction"]}},
        "platform_settings": {
            "auth": {"enable_auth": True},
            "privacy": {"record_voice": True, "retention_days": 7, "delete_audio": True, "delete_transcript_and_pii": True},
            "overrides": {"conversation_config_override": {"agent": {"first_message": True, "prompt": {"prompt": True}}, "tts": {"voice_id": True}}}}}


def private_env(name: str, value: str):
    from dotenv import set_key
    path = Path(".env")
    if not path.exists():
        path.touch(mode=0o600)
    path.chmod(0o600)
    set_key(str(path), name, value)
    path.chmod(0o600)
    os.environ[name] = value


def secure_ws_url(value: str) -> str:
    url = urlsplit(value)
    if url.scheme != "wss" or not url.hostname or url.username or url.password or url.query or url.fragment or not url.path.endswith("/audio"):
        raise ValueError("Use the bridge's public wss://host/audio URL, without credentials or query parameters")
    return value.rstrip("/")


def main():
    from dotenv import load_dotenv
    load_dotenv(".env")
    from elevenlabs.client import ElevenLabs
    from househunt import db
    from househunt.voice import store
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    clone = sub.add_parser("clone")
    clone.add_argument("--sample", required=True, type=Path)
    clone.add_argument("--name", required=True)
    clone.add_argument("--consent", action="store_true", help="Speaker explicitly consented to upload and cloning in this ElevenLabs account")
    preview = sub.add_parser("preview")
    preview.add_argument("--voice-id", required=True)
    preview.add_argument("--speaker-name", default="my client")
    preview.add_argument("--model", default=os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_v4_turbo"))
    enroll = sub.add_parser("enroll")
    enroll.add_argument("--search-id", type=int, required=True)
    enroll.add_argument("--voice-id", required=True)
    enroll.add_argument("--speaker-name", required=True)
    enroll.add_argument("--consent", action="store_true")
    enroll.add_argument("--approve-audition", action="store_true")
    prepare = sub.add_parser("prepare-agent")
    prepare.add_argument("--voice-id", required=True)
    for action in ("configure-dial", "activate"):
        p = sub.add_parser(action)
        p.add_argument("--ws-url", required=True, type=secure_ws_url)
        if action == "activate":
            p.add_argument("--search-id", required=True, type=int)
            p.add_argument("--confirm-account-wide", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args()
    db.init()
    if args.action in {"configure-dial", "activate", "status"}:
        import httpx
        key = os.environ.get("DIAL_API_KEY")
        if not key:
            raise RuntimeError("DIAL_API_KEY is missing")
        with httpx.Client(base_url="https://api.getdial.ai", headers={"Authorization": f"Bearer {key}"}, timeout=20, follow_redirects=False) as http:
            status = http.get("/api/v1/self-hosted")
            status.raise_for_status()
            state = status.json()
            if args.action == "status":
                print({"dial_access": state.get("access"), "dial_enabled": state.get("enabled"), "active_mode": state.get("activeMode"),
                       "elevenlabs_key_configured": bool(os.environ.get("ELEVENLABS_API_KEY")), "agent_configured": bool(os.environ.get("ELEVENLABS_AGENT_ID"))})
                return
            if state.get("access") != "granted":
                raise RuntimeError("Dial has not granted self-hosted access")
            config = {"type": "audio", "wsUrl": args.ws_url, "audioInboundFormat": "l16_16000", "audioOutboundFormat": "l16_16000"}
            if args.action == "activate":
                if not args.confirm_account_wide:
                    raise RuntimeError("Activation affects every new account call; explicitly confirm after rehearsal")
                store.preflight(args.search_id)
                health_url = args.ws_url.replace("wss://", "https://", 1).removesuffix("/audio") + "/health"
                health = httpx.get(health_url, timeout=10, follow_redirects=False)
                health.raise_for_status()
                if health.json() != {"service": "keyhunt-voice", "configured": True, "ready": True}:
                    raise RuntimeError("Voice bridge is not configured and reachable")
            response = http.post("/api/v1/self-hosted", json={"action": "activate" if args.action == "activate" else "save", "config": config})
            response.raise_for_status()
            if args.action == "configure-dial":
                response = http.get("/api/v1/self-hosted/secret", params={"mode": "audio"})
                response.raise_for_status()
                secret = response.json().get("secret")
                if not isinstance(secret, str) or not secret:
                    raise RuntimeError("Dial did not return its signing secret; inspect the documented response schema")
                private_env("DIAL_AUDIO_SIGNING_SECRET", secret)
                print("Dial audio configuration saved; signing secret stored privately. Calling mode unchanged.")
            else:
                private_env("VOICE_MODE", "elevenlabs")
                print("Dial audio mode activated. Restart caller and bridge with VOICE_MODE=elevenlabs.")
            return
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("Save ELEVENLABS_API_KEY in the private .env first")
    client = ElevenLabs(api_key=key, timeout=30)
    if args.action == "clone":
        if not args.consent:
            raise RuntimeError("Explicit speaker consent is required before sending a recording to ElevenLabs")
        if not args.sample.is_file() or not 1_000 <= args.sample.stat().st_size <= 30_000_000:
            raise RuntimeError("Provide a clean local audio sample smaller than 30 MB")
        with args.sample.open("rb") as sample:
            result = client.voices.ivc.create(name=args.name, files=[sample], remove_background_noise=False, request_options={"max_retries": 0})
        print("Voice ID:", result.voice_id)
        if result.requires_verification:
            print("Speaker verification is required in ElevenLabs before this voice can be used.")
    elif args.action == "preview":
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", args.voice_id):
            raise ValueError("Invalid voice ID")
        from househunt.config import settings
        folder = Path(settings.db_path).resolve().parent / "voice" / "previews"
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = folder / f"{args.voice_id}.mp3"
        audio = client.text_to_speech.convert(voice_id=args.voice_id, model_id=args.model, output_format="mp3_44100_128",
            text=f"Hi, I'm {args.speaker_name}'s AI assistant with KeyHunt, calling about your rental. Is it still available? Thanks. Could you confirm the total monthly rent, including any required fees? What times would work for a viewing?")
        with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as out:
            for chunk in audio:
                out.write(chunk)
        print("Private audition saved:", target)
    elif args.action == "enroll":
        if not args.consent or not args.approve_audition:
            raise RuntimeError("Consent and a listened-to, approved audition are required")
        if not db.get_search(args.search_id) or not re.fullmatch(r"[\w .'-]{1,80}", args.speaker_name):
            raise ValueError("Provide an existing search and a speaker name")
        # Read-back proves this key can access the selected voice; never substitute a default.
        voice = client.voices.get(args.voice_id)
        if voice.category not in {"cloned", "professional"}:
            raise RuntimeError("Select the consenting speaker's cloned voice, not a stock voice")
        store.save("profiles", str(args.search_id), {"voice_id": args.voice_id, "speaker_name": args.speaker_name,
            "consented_at": db.now(), "audition_approved_at": db.now()})
        print("Voice enrolled for search", args.search_id)
    elif args.action == "prepare-agent":
        if os.environ.get("ELEVENLABS_AGENT_ID"):
            raise RuntimeError("An agent is already configured; inspect it instead of creating a duplicate")
        result = client.conversational_ai.agents.create(**agent_config(args.voice_id, os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_v4_turbo")))
        private_env("ELEVENLABS_AGENT_ID", result.agent_id)
        print("Private KeyHunt agent created and its ID saved in .env. Dial mode unchanged.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never print provider bodies, signed URLs, tokens, or audio metadata.
        if isinstance(exc, (RuntimeError, ValueError)):
            print(str(exc), file=sys.stderr)
        else:
            print(f"Voice setup failed ({type(exc).__name__}); credentials and response body withheld", file=sys.stderr)
        raise SystemExit(1)

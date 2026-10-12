"""Dial's SDK verifies/decodes transport; ElevenLabs owns the live voice agent.

Run one instance with the same private DB volume as the caller. This is a separate
listener so the operator UI is never exposed by an audio-only public tunnel.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager, suppress
import json
import logging
import os
import re
import time
import httpx
from urllib.parse import urlsplit

from dial_sdk import parse_dial_audio_message, serialize_server_audio_message, verify_dial_signature
from dial_sdk.self_hosted_audio import ServerAudioMedia, ServerClear, ServerEndCall, ServerMark
from elevenlabs.client import AsyncElevenLabs
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect

from househunt import db
from househunt.config import settings
from househunt.voice import store

log = logging.getLogger(__name__)
# Provider request/connection errors can contain signed URLs. Log only our codes.
for name in ("httpx", "httpcore", "websockets", "elevenlabs"):
    logging.getLogger(name).setLevel(logging.CRITICAL)


def initiation(row: dict, enrollment: dict | None) -> dict:
    if row.get('direction') == 'inbound':
        return {'type': 'conversation_initiation_client_data', 'conversation_config_override': {
            'agent': {'first_message': f"Hi, you've reached KeyHunt's AI assistant. Which property are you calling about?",
                'prompt': {'prompt': row['instruction']}}}}
    name = enrollment["speaker_name"]
    return {"type": "conversation_initiation_client_data", "conversation_config_override": {
        "agent": {"first_message": f"Hi, I'm {name}'s AI assistant with KeyHunt. I'm calling about your rental. Is now a good time?",
                  "prompt": {"prompt": row["instruction"]}},
        "tts": {"voice_id": enrollment["voice_id"]}}}


class Relay:
    """Small transport translation, with no speech recognition or synthesis code."""
    def __init__(self, send_dial, send_eleven, on_metadata):
        self.send_dial, self.send_eleven, self.on_metadata = send_dial, send_eleven, on_metadata
        self.last_interruption = -1
        self.ready = False

    async def provider_event(self, event: dict):
        kind = event.get("type")
        if kind == "conversation_initiation_metadata":
            meta = event["conversation_initiation_metadata_event"]
            if (meta.get("agent_output_audio_format"), meta.get("user_input_audio_format")) != ("pcm_16000", "pcm_16000"):
                raise RuntimeError("Voice provider audio format mismatch")
            self.ready = True
            self.on_metadata(meta["conversation_id"])
        elif kind == "audio":
            chunk = event["audio_event"]
            if not self.ready:
                raise RuntimeError("Voice audio arrived before format negotiation")
            if int(chunk["event_id"]) <= self.last_interruption:
                return  # Late chunks from an interrupted utterance must not play.
            payload = chunk["audio_base_64"]
            raw = base64.b64decode(payload, validate=True)
            if len(raw) > 2_000_000 or len(raw) % 2:
                raise RuntimeError("Invalid voice audio frame")
            await self.send_dial(ServerAudioMedia(payload=payload))
        elif kind == "interruption":
            self.last_interruption = max(self.last_interruption, int(event["interruption_event"]["event_id"]))
            await self.send_dial(ServerClear())
        elif kind == "ping":
            await self.send_eleven({"type": "pong", "event_id": event["ping_event"]["event_id"]})
        elif kind in {"client_error", "error"}:
            raise RuntimeError("Voice provider rejected the conversation")


class Session:
    def __init__(self, row: dict, enrollment: dict):
        self.row, self.enrollment = row, enrollment
        self.call_id = row["dial_call_id"]
        self.socket: WebSocket | None = None
        self.upstream = None
        self.audio = asyncio.Queue(maxsize=100)  # At most two seconds of 20ms frames.
        self.write_lock = asyncio.Lock()
        self.detached_at: float | None = None
        self.done = asyncio.Event()
        self.final_playback = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.record = {"call_id": self.call_id, "local_call_id": row["id"], "status": "connecting"}
        store.save("sessions", self.call_id, self.record)

    async def send(self, message):
        async with self.write_lock:
            if self.socket is not None:
                await self.socket.send_text(serialize_server_audio_message(message))

    def metadata(self, conversation_id: str):
        self.record.update(conversation_id=conversation_id, status="active")
        store.save("sessions", self.call_id, self.record)

    async def provider_send(self, event):
        if self.upstream is not None:
            await self.upstream.send(json.dumps(event))

    async def run(self):
        http = httpx.AsyncClient(timeout=15, follow_redirects=False)
        client = AsyncElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"], timeout=15, httpx_client=http)
        tasks = []
        try:
            signed = await client.conversational_ai.conversations.get_signed_url(agent_id=os.environ["ELEVENLABS_AGENT_ID"])
            url = urlsplit(signed.signed_url)
            if url.scheme != "wss" or url.hostname != "api.elevenlabs.io" or url.username or url.password or url.port not in (None, 443):
                raise RuntimeError("Unexpected voice provider WebSocket host")
            async with connect(signed.signed_url, max_size=4_000_000, open_timeout=12, close_timeout=2) as ws:
                self.upstream = ws
                await self.provider_send(initiation(self.row, self.enrollment))
                relay = Relay(self.send, self.provider_send, self.metadata)

                async def receive():
                    async for raw in ws:
                        await relay.provider_event(json.loads(raw))

                async def transmit():
                    while True:
                        payload = await self.audio.get()
                        await self.provider_send({"user_audio_chunk": payload})

                async def watchdog():
                    started = time.monotonic()
                    while True:
                        await asyncio.sleep(.25)
                        if not relay.ready and time.monotonic() - started > 12:
                            raise RuntimeError("Voice provider startup timed out")
                        if self.detached_at and time.monotonic() - self.detached_at > 16:
                            return
                        if time.monotonic() - started > settings.call_max_seconds + 10:
                            return

                tasks = [asyncio.create_task(fn()) for fn in (receive, transmit, watchdog)]
                finished, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in finished:
                    task.result()
                # Let Dial finish queued goodbye audio before a normal provider close.
                if self.socket:
                    await self.send(ServerMark(name="keyhunt-final"))
                    with suppress(TimeoutError):
                        await asyncio.wait_for(self.final_playback.wait(), 8)
                self.record["status"] = "ended"
        except asyncio.CancelledError:
            self.record["status"] = "ended"
            raise
        except Exception as exc:
            self.record["status"] = "error"
            self.record["error"] = "Voice service interrupted; review saved evidence before retrying"
            log.warning("Voice session failed (%s)", type(exc).__name__)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.upstream = None
            with suppress(Exception):
                await self.send(ServerEndCall())
            store.save("sessions", self.call_id, self.record)
            self.done.set()
            await http.aclose()
            if sessions.get(self.call_id) is self and self.socket is None:
                sessions.pop(self.call_id, None)


sessions: dict[str, Session] = {}


@asynccontextmanager
async def lifespan(app):
    db.init()
    yield
    for session in list(sessions.values()):
        if session.task:
            session.task.cancel()
    await asyncio.gather(*(s.task for s in sessions.values() if s.task), return_exceptions=True)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    return {"service": "keyhunt-voice", "configured": all(os.environ.get(k) for k in
        ("DIAL_AUDIO_SIGNING_SECRET", "ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID")), "ready": store.enabled()}


@app.websocket("/audio/{call_id}")
async def audio_socket(ws: WebSocket, call_id: str):
    secret = os.environ.get("DIAL_AUDIO_SIGNING_SECRET", "")
    if (not store.enabled() or not secret or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", call_id)
            or not verify_dial_signature(secret, ws.headers.get("x-dial-signature", ""), call_id, tolerance_seconds=60)):
        await ws.close(code=1008)
        return
    await ws.accept()
    session = None
    try:
        first = parse_dial_audio_message(await asyncio.wait_for(ws.receive_text(), 5))
        if (first.type != "call_connected" or first.call_id != call_id or first.direction not in ('inbound', 'outbound')
                or first.formats.inbound != "l16_16000" or first.formats.outbound != "l16_16000"):
            raise RuntimeError("Unexpected Dial session or audio format")
        if first.direction == 'inbound':
            from househunt.outreach.callbacks import instruction as callback_instruction
            if not settings.callback_enabled or first.to != db.get_state('phone_number'):
                raise RuntimeError('Inbound callback number is not configured')
            row = {'id': None, 'dial_call_id': call_id, 'direction': 'inbound', 'instruction': callback_instruction()}
            enrollment = None  # Use the shared agent voice without looking up any household's profile.
        else:
            # The audio socket can race the REST response that persists its provider ID.
            row = store.call_context(call_id)
            for _ in range(20):
                if row:
                    break
                await asyncio.sleep(.1)
                row = store.call_context(call_id)
            from househunt.outreach.scheduler import permitted
            listing = db.get_listing(row['search_id'], row['listing_key']) if row else None
            if (not row or row["phone"] != first.to or not listing or not permitted(listing, settings, search_id=row['search_id'])
                    or not row["instruction"] or db.contact_blocked(first.to)):
                raise RuntimeError("No authorized KeyHunt call matches this session")
            enrollment = store.preflight(row["search_id"])
        session = sessions.get(call_id)
        if session is None:
            if store.read("sessions", call_id):
                raise RuntimeError("Previous voice process ended; never restart the conversation silently")
            session = Session(row, enrollment)
            sessions[call_id] = session
            session.socket = ws
            session.task = asyncio.create_task(session.run())
        elif session.done.is_set() or session.socket is not None:
            raise RuntimeError("Voice session already ended or connected")
        else:
            session.socket = ws
            session.detached_at = None
            await session.send(ServerClear())
        while not session.done.is_set():
            try:
                raw = await asyncio.wait_for(ws.receive_text(), 1)
            except TimeoutError:
                continue
            if len(raw) > 100_000:
                raise RuntimeError("Oversized Dial frame")
            msg = parse_dial_audio_message(raw)
            if msg.type == "ping_pong":
                await session.send(msg)
            elif msg.type == "media":
                decoded = base64.b64decode(msg.payload, validate=True)
                if len(decoded) > 16_000 or len(decoded) % 2:
                    raise RuntimeError("Invalid Dial audio frame")
                session.audio.put_nowait(msg.payload)
            elif msg.type == "mark" and msg.name == "keyhunt-final":
                session.final_playback.set()
            elif msg.type == "duration_warning":
                await session.provider_send({"type": "contextual_update", "text": "The call will end shortly. Briefly recap the confirmed booking, or unconfirmed offers if nothing was booked, and use end_call. Do not rush into a new commitment; follow the original booking authorization."})
            elif msg.type == "call_ended" or (msg.type == "dtmf" and msg.digit == "#"):
                if msg.type == "dtmf":
                    await session.send(ServerEndCall())
                session.task.cancel()
                break
    except WebSocketDisconnect:
        pass  # Preserve the provider session through Dial's 15-second reconnect window.
    except Exception as exc:
        log.warning("Voice connection rejected (%s)", type(exc).__name__)
        with suppress(Exception):
            await ws.send_text(serialize_server_audio_message(ServerEndCall()))
        if session and session.socket is ws and session.task:
            session.task.cancel()
    finally:
        if session and session.socket is ws:
            session.socket = None
            session.detached_at = time.monotonic()
            while not session.audio.empty():
                session.audio.get_nowait()
        with suppress(Exception):
            await ws.close()
        if session and session.done.is_set():
            sessions.pop(call_id, None)

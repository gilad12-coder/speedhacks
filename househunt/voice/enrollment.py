"""Bounded, consented two-minute enrollment. Raw samples are never kept on disk."""
from __future__ import annotations

from array import array
import io
import math
import os
from pathlib import Path
import re
import sys
import threading
import uuid
import wave
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
import httpx
from elevenlabs.client import ElevenLabs

from househunt import db
from househunt.voice import store

TARGET_SECONDS = 120
MAX_BYTES = 4_000_000
mutation_lock = threading.Lock()
SCRIPT = [
    "Hi, thanks for taking the time to speak with me today. I'm looking for a place that feels comfortable, practical, and easy to call home. Before we get into the details, is now a good time for a few questions? If you're busy, I'm happy to find another time that works for both of us.",
    "I'd love to understand a little more about the apartment. How much natural light does it get in the morning? Is the bedroom quiet in the evening? I enjoy cooking, so a useful kitchen matters to me. A nearby grocery store and a pleasant walk around the neighborhood would also be wonderful.",
    "Could you confirm the monthly rent and any required fees? For example, if the rent were two thousand eight hundred dollars, would water, parking, or internet cost extra? What is the security deposit? Are there any move-in charges? I like to write down the full amount so there are no surprises later.",
    "I'm also curious about the application process. What documents do you normally request? How long does a decision usually take? Is the lease for twelve months, or are other options available? I would want to review the terms carefully and visit the property before making a commitment.",
    "For a viewing, Tuesday afternoon around three thirty could work. Saturday morning at ten might be another possibility. Which time would be better for you? Please let me know the exact address, where to meet, and whether I should bring anything. Thank you; that helps me plan my day.",
    "That sounds helpful. Let me repeat what I heard to make sure I have it right. The next step is to confirm a viewing time and ask any remaining questions. If something changes, that's okay; we can find another option. Thanks again for your time. I appreciate the clear information, and I look forward to learning more."
]


def validate_sample(data: bytes) -> None:
    if len(data) > MAX_BYTES:
        raise ValueError("The recording is too large. Please record a fresh two-minute sample here.")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 16000, "NONE"):
                raise ValueError("Use a mono, 16-bit, 16 kHz WAV recording.")
            frames = audio.getnframes()
            if not 119.5 <= frames / 16000 <= 122:
                raise ValueError("Please speak for the full two minutes, then try again.")
            samples = array("h", audio.readframes(frames))
            if len(samples) != frames:
                raise ValueError("The recording is incomplete. Please record it again.")
    except (wave.Error, EOFError):
        raise ValueError("The recording could not be read. Please record it again.") from None
    if sys.byteorder != "little":
        samples.byteswap()
    # 100ms windows: reject mostly silent or badly clipped samples, not accents or words.
    active, clipped = 0, 0
    for i in range(0, len(samples), 1600):
        window = samples[i:i+1600:8]
        active += math.sqrt(sum(x*x for x in window) / len(window)) / 32768 > .005
        clipped += sum(abs(x) >= 32500 for x in window)
    if active < 250:
        raise ValueError("There is too much silence or the microphone is too quiet. Move closer and read naturally for two minutes.")
    if clipped / (len(samples) / 8) > .01:
        raise ValueError("The microphone sounds overloaded. Move a little farther away and record again.")


def state(search_id: int) -> dict:
    return store.read("enrollments", str(search_id)) or {}


def recover_pending() -> None:
    """Called once at web-process startup; uploaded samples are intentionally ephemeral."""
    folder = store.private_path("enrollments", "1").parent
    for path in folder.glob("*.json"):
        if not path.stem.isdigit():
            continue
        record = state(int(path.stem))
        if record.get("phase") in {"creating", "creating_preview"}:
            record.update(phase="error", error="Voice setup was interrupted by a server restart. Retry the preview if available, or remove this attempt and record again.")
            store.save("enrollments", path.stem, record)


def preview_path(search_id: int, enrollment_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", enrollment_id):
        raise ValueError("Invalid enrollment")
    return store.private_path("enrollments", str(search_id)).with_name(f"{search_id}-{enrollment_id}.mp3")


def status(search_id: int) -> dict:
    current = state(search_id)
    profile = store.read("profiles", str(search_id))
    return {"phase": current.get("phase", "approved" if profile else "empty"),
            "enrollmentId": current.get("id"), "speakerName": current.get("speaker_name", (profile or {}).get("speaker_name", "")),
            "error": current.get("error"), "targetSeconds": TARGET_SECONDS, "script": SCRIPT,
            "canCreate": bool(os.environ.get("ELEVENLABS_API_KEY")),
            "canRetryPreview": bool(current.get("voice_id") and current.get("phase") in {"error", "verification_required"}),
            "callingEnabled": store.enabled(), "approved": bool(profile and profile.get("audition_approved_at"))}


def generate(search_id: int, enrollment_id: str, sample: bytes | None = None) -> None:
    record = state(search_id)
    if record.get("id") != enrollment_id:
        return
    target = preview_path(search_id, enrollment_id)
    try:
        with httpx.Client(timeout=60, follow_redirects=False) as http:
            client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"], httpx_client=http, timeout=60)
            if not record.get("voice_id"):
                if sample is None:
                    raise ValueError("A fresh sample is required")
                result = client.voices.ivc.create(name=f"KeyHunt {record['speaker_name']}", files=[("sample.wav", sample, "audio/wav")],
                    remove_background_noise=False, request_options={"max_retries": 0})
                record.update(voice_id=result.voice_id, phase="verification_required" if result.requires_verification else "creating_preview")
                store.save("enrollments", str(search_id), record)  # save ID before any next provider operation
                if result.requires_verification:
                    return
            chunks = client.text_to_speech.convert(voice_id=record["voice_id"],
                model_id=os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_v4_turbo"), output_format="mp3_44100_128",
                text=f"Hi, I'm {record['speaker_name']}'s AI assistant with KeyHunt. I'm calling about your rental. Is it still available? Could you confirm the monthly rent and any required fees? Would Tuesday at three thirty work for a viewing?")
            size = 0
            with os.fdopen(os.open(target, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), "wb") as out:
                for chunk in chunks:
                    size += len(chunk)
                    if size > 2_000_000:
                        raise ValueError("Preview exceeds limit")
                    out.write(chunk)
            if size < 100:
                raise ValueError("Preview unavailable")
            record["phase"] = "audition"
            record.pop("error", None)
    except Exception:
        target.unlink(missing_ok=True)
        record.update(phase="error", error="Voice creation or preview could not finish. Remove this attempt before recording again; an operator can check the provider account.")
    finally:
        store.save("enrollments", str(search_id), record)


def voice_access(request: Request) -> int:
    # The parent app verifies Basic auth or the agent bearer key first.
    from househunt.config import settings
    if "household_id" in request.path_params:
        sid = db.household_search(request.path_params["household_id"])
    else:
        if not settings.app_password:
            raise HTTPException(503, "Voice enrollment requires the app's private sign-in to be configured")
        sid = int(request.path_params["search_id"])
    if sid is None or not db.get_search(sid):
        raise HTTPException(404, "Search not found; start the household search first")
    if request.method not in {"GET", "HEAD"}:
        if request.headers.get("x-keyhunt-voice") != "1":
            raise HTTPException(403, "Use the voice enrollment form")
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Cross-site enrollment is not allowed")
    return sid


router = APIRouter()


@router.get("/api/searches/{search_id}/voice")
@router.get("/agent/households/{household_id}/voice")
def get_voice(sid: int = Depends(voice_access)):
    return JSONResponse(status(sid), headers={"Cache-Control": "private, no-store"})


@router.post("/api/searches/{search_id}/voice", status_code=202)
@router.post("/agent/households/{household_id}/voice", status_code=202)
async def create_voice(request: Request, background: BackgroundTasks, sid: int = Depends(voice_access)):
    if request.headers.get("x-voice-consent") != "true":
        raise HTTPException(400, "Confirm that this is your own voice and you agree to create a clone with ElevenLabs")
    name = unquote(request.headers.get("x-voice-name", "")).strip()
    if not re.fullmatch(r"[\w .'-]{1,80}", name):
        raise HTTPException(400, "Enter the name the assistant should use")
    if request.headers.get("content-type", "").split(";")[0] != "audio/wav":
        raise HTTPException(415, "Upload the two-minute WAV recording")
    if not os.environ.get("ELEVENLABS_API_KEY"):
        raise HTTPException(503, "Voice creation is not configured yet")
    if request.headers.get("content-length", "").isdigit() and int(request.headers["content-length"]) > MAX_BYTES:
        raise HTTPException(413, "Recording is too large")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "Recording is too large")
    try:
        validate_sample(bytes(data))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    with mutation_lock:
        if state(sid) or store.read("profiles", str(sid)):
            raise HTTPException(409, "A voice or attempt already exists. Remove it before recording another.")
        enrollment_id = uuid.uuid4().hex
        store.save("enrollments", str(sid), {"id": enrollment_id, "speaker_name": name,
                   "consented_at": db.now(), "phase": "creating", "created_at": db.now()})
    background.add_task(generate, sid, enrollment_id, bytes(data))
    return JSONResponse({"phase": "creating", "enrollmentId": enrollment_id}, status_code=202,
                        headers={"Cache-Control": "private, no-store"})


@router.get("/api/searches/{search_id}/voice/preview")
@router.get("/agent/households/{household_id}/voice/preview")
def get_preview(sid: int = Depends(voice_access)):
    record = state(sid)
    if record.get("phase") not in {"audition", "approved"}:
        raise HTTPException(404, "Voice preview is not ready")
    path = preview_path(sid, record["id"])
    if not path.is_file():
        raise HTTPException(404, "Voice preview is not available")
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "private, no-store"})


@router.post("/api/searches/{search_id}/voice/preview", status_code=202)
@router.post("/agent/households/{household_id}/voice/preview", status_code=202)
def retry_preview(background: BackgroundTasks, sid: int = Depends(voice_access)):
    with mutation_lock:
        record = state(sid)
        if not record.get("voice_id") or record.get("phase") not in {"error", "verification_required"}:
            raise HTTPException(409, "No existing voice needs a preview retry")
        record["phase"] = "creating_preview"
        store.save("enrollments", str(sid), record)
    background.add_task(generate, sid, record["id"])
    return {"phase": "creating_preview", "enrollmentId": record["id"]}


@router.post("/api/searches/{search_id}/voice/approve")
@router.post("/agent/households/{household_id}/voice/approve")
async def approve_voice(request: Request, sid: int = Depends(voice_access)):
    # Bounded approval JSON; IDs bind the approval to this exact audition.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024:
            raise HTTPException(413)
    import json
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid approval") from None
    with mutation_lock:
        record = state(sid)
        if not isinstance(payload, dict) or payload.get("approved") is not True or payload.get("enrollmentId") != record.get("id"):
            raise HTTPException(400, "Listen to this preview and confirm approval")
        if record.get("phase") not in {"audition", "approved"} or not preview_path(sid, record["id"]).is_file():
            raise HTTPException(409, "The audition is not ready")
        store.save("profiles", str(sid), {"voice_id": record["voice_id"], "speaker_name": record["speaker_name"],
                   "consented_at": record["consented_at"], "audition_approved_at": db.now()})
        record["phase"] = "approved"
        store.save("enrollments", str(sid), record)
    return JSONResponse(status(sid), headers={"Cache-Control": "private, no-store"})


@router.delete("/api/searches/{search_id}/voice")
@router.delete("/agent/households/{household_id}/voice")
def remove_voice(sid: int = Depends(voice_access)):
    with mutation_lock:
        record = state(sid)
        if record.get("phase") in {"creating", "creating_preview"}:
            raise HTTPException(409, "Voice creation is still running. If the server restarted, ask the operator to recover this attempt.")
        if record.get("voice_id"):
            try:
                with httpx.Client(timeout=20, follow_redirects=False) as http:
                    client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"), httpx_client=http)
                    client.voices.delete(record["voice_id"])
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise HTTPException(502, "The provider could not remove the voice. Please try again.") from None
        # Only voices this enrollment created are deleted at the provider.
        store.private_path("profiles", str(sid)).unlink(missing_ok=True)
        if record.get("id"):
            preview_path(sid, record["id"]).unlink(missing_ok=True)
        store.private_path("enrollments", str(sid)).unlink(missing_ok=True)
    return {"phase": "empty"}

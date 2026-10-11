"""Import authoritative ElevenLabs timestamps into the existing call contract."""
from __future__ import annotations

import math
import os
from pathlib import Path
import tempfile
from househunt.voice import store


def transcript_turns(details: dict) -> list[dict]:
    turns = []
    previous = -1.0
    for turn in details.get("transcript", []):
        text, offset, role = turn.get("message"), turn.get("time_in_call_secs"), turn.get("role")
        if not text or role not in {"user", "agent"}:
            continue
        if (not isinstance(text, str) or isinstance(offset, bool) or not isinstance(offset, (int, float))
                or not math.isfinite(offset) or offset < 0 or offset < previous):
            raise RuntimeError("Voice transcript contains invalid timestamps")
        previous = offset
        turns.append({"speaker": role, "startMs": round(offset * 1000), "text": text})
    return turns


def save_audio(chunks, dial_call_id: str) -> None:
    from househunt.config import settings
    # Validate the identifier before constructing any path.
    store.private_path("sessions", dial_call_id)
    folder = Path(settings.db_path).resolve().parent / "recordings"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=folder, prefix=".voice-")
    try:
        size = 0
        with os.fdopen(fd, "wb") as target:
            for chunk in chunks:
                size += len(chunk)
                if size > 30_000_000:
                    raise RuntimeError("Voice recording exceeds the import limit")
                target.write(chunk)
        with open(temporary, "rb") as source:
            header = source.read(12)
        if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
            suffix = ".wav"
        elif header[:3] == b"ID3" or (len(header) >= 2 and header[0] == 255 and header[1] & 0xE0 == 0xE0):
            suffix = ".mp3"
        else:
            raise RuntimeError("Voice provider did not return a supported recording")
        os.replace(temporary, folder / f"{dial_call_id}{suffix}")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def enrich(raw: dict) -> dict | None:
    """Return None while provider evidence is processing; never invent timestamps."""
    binding = store.read("sessions", raw["id"])
    if not binding or not binding.get("conversation_id"):
        return None
    from elevenlabs.client import ElevenLabs
    import httpx
    http = httpx.Client(timeout=15, follow_redirects=False)
    client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"), timeout=15, httpx_client=http)
    try:
        response = client.conversational_ai.conversations.get(binding["conversation_id"])
        details = response.model_dump()
        if details.get("status") not in {"done", "failed"}:
            return None
        turns = transcript_turns(details)
        if not turns:
            return None
        result = {**raw, "transcriptTurns": turns,
                  "transcript": "\n".join(f'{t["speaker"]}: {t["text"]}' for t in turns),
                  "voiceProvider": "elevenlabs", "voiceConversationId": binding["conversation_id"]}
        # Align the transcript clock with the same provider's recording.
        start = (details.get("metadata") or {}).get("start_time_unix_secs")
        if isinstance(start, (int, float)) and math.isfinite(start):
            from datetime import datetime, timezone
            result["createdAt"] = datetime.fromtimestamp(start, timezone.utc).isoformat()
        if details.get("has_audio"):
            try:
                save_audio(client.conversational_ai.conversations.audio.get(binding["conversation_id"]), raw["id"])
            except Exception:
                result["recordingWarning"] = "Recording import unavailable; transcript evidence retained"
        return result
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("Voice evidence unavailable; retry the saved call without redialing") from None
    finally:
        http.close()

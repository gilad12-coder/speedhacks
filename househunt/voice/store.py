"""Private, search-scoped enrollment and durable provider conversation IDs."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from househunt import db


def private_path(kind: str, identifier: str) -> Path:
    from househunt.config import settings
    if kind not in {"profiles", "sessions"} or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", identifier):
        raise ValueError("Invalid voice storage identifier")
    return Path(settings.db_path).resolve().parent / "voice" / kind / f"{identifier}.json"


def read(kind: str, identifier: str) -> dict | None:
    path = private_path(kind, identifier)
    return json.loads(path.read_text()) if path.is_file() else None


def save(kind: str, identifier: str, data: dict) -> None:
    path = private_path(kind, identifier)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def profile(search_id: int) -> dict:
    result = read("profiles", str(search_id))
    if not result or not result.get("consented_at") or not result.get("audition_approved_at"):
        raise RuntimeError("This search has no consented, audition-approved voice enrollment")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", result.get("voice_id", "")):
        raise RuntimeError("Invalid enrolled voice ID")
    return result


def enabled() -> bool:
    return os.environ.get("VOICE_MODE", "managed") == "elevenlabs"


def preflight(search_id: int) -> dict:
    result = profile(search_id)
    if not all(os.environ.get(k) for k in ("ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "DIAL_AUDIO_SIGNING_SECRET")):
        raise RuntimeError("Custom voice needs the ElevenLabs key, agent ID and Dial audio signing secret")
    return result


def call_context(provider_id: str) -> dict | None:
    with db.conn() as conn:
        row = conn.execute("SELECT * FROM calls WHERE dial_call_id=? AND mode='live'", (provider_id,)).fetchone()
    return dict(row) if row else None

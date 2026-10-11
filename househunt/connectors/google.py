"""Google OAuth (one connected account) plus the Calendar and Gmail calls we need.

Credentials come from GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET; the user's tokens are
stored in the `connections` table, never in code or env.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx

from househunt import db
from househunt.config import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
CAL = "https://www.googleapis.com/calendar/v3"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"

SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.readonly",   # free/busy + timezone
    "https://www.googleapis.com/auth/calendar.events",     # add booked viewings
    "https://www.googleapis.com/auth/gmail.readonly",      # read listing alert emails
    "https://www.googleapis.com/auth/gmail.send",          # send emails you approve
]
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

PROVIDER = "google"
_pending_states: dict[str, float] = {}  # OAuth CSRF state -> expiry


def configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def authorize_url(redirect_uri: str) -> str:
    state = secrets.token_urlsafe(24)
    _pending_states[state] = time.time() + 600
    return AUTH_URL + "?" + urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",     # get a refresh token
        "prompt": "consent",          # ...every time, so reconnecting always yields one
        "include_granted_scopes": "true",
        "state": state,
    })


def check_state(state: str) -> bool:
    expiry = _pending_states.pop(state, 0)
    return expiry > time.time()


def exchange_code(code: str, redirect_uri: str) -> str:
    """Finish OAuth: store tokens, return the connected email."""
    res = httpx.post(TOKEN_URL, data={
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=20)
    res.raise_for_status()
    tok = res.json()
    info = httpx.get(USERINFO_URL, headers={"authorization": f"Bearer {tok['access_token']}"},
                     timeout=20).json()
    db.save_connection(PROVIDER, account=info.get("email"), access_token=tok["access_token"],
                       refresh_token=tok.get("refresh_token"),
                       expires_at=time.time() + tok.get("expires_in", 3600),
                       scope=tok.get("scope", ""))
    return info.get("email", "")


def disconnect() -> None:
    conn = db.get_connection(PROVIDER)
    if conn:
        token = conn["refresh_token"] or conn["access_token"]
        try:
            httpx.post(REVOKE_URL, data={"token": token}, timeout=10)
        except httpx.HTTPError:
            pass
        db.delete_connection(PROVIDER)


def connection():
    return db.get_connection(PROVIDER)


def has_scope(scope: str) -> bool:
    conn = db.get_connection(PROVIDER)
    return bool(conn and scope in (conn["scope"] or "").split())


def _access_token() -> str:
    conn = db.get_connection(PROVIDER)
    if not conn:
        raise RuntimeError("Google is not connected")
    if conn["expires_at"] - 60 > time.time():
        return conn["access_token"]
    if not conn["refresh_token"]:
        raise RuntimeError("Google token expired; reconnect on the Connections page")
    res = httpx.post(TOKEN_URL, data={
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": conn["refresh_token"],
        "grant_type": "refresh_token",
    }, timeout=20)
    if res.status_code == 400:  # revoked, or expired (7-day limit in Testing mode)
        raise RuntimeError("Google access expired; reconnect on the Connections page")
    res.raise_for_status()
    tok = res.json()
    db.save_connection(PROVIDER, account=conn["account"], access_token=tok["access_token"],
                       refresh_token=conn["refresh_token"],
                       expires_at=time.time() + tok.get("expires_in", 3600),
                       scope=conn["scope"])
    return tok["access_token"]


def _client() -> httpx.Client:
    return httpx.Client(headers={"authorization": f"Bearer {_access_token()}"}, timeout=20)


# --- Calendar ---------------------------------------------------------------

def _busy(client, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    response = client.post(f"{CAL}/freeBusy", json={"timeMin": start.isoformat(), "timeMax": end.isoformat(), "items": [{"id": "primary"}]})
    response.raise_for_status()
    primary = response.json().get("calendars", {}).get("primary", {})
    if primary.get("errors") or not isinstance(primary.get("busy"), list):
        raise RuntimeError("Calendar availability could not be checked")
    busy = [(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in primary["busy"]]
    if any(s.utcoffset() is None or e.utcoffset() is None or e <= s for s,e in busy):
        raise RuntimeError("Calendar returned invalid availability")
    return busy


def free_intervals(days: int = 7) -> list[dict]:
    """Fresh, timezone-aware daytime ranges; errors never mean an empty calendar."""
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo(settings.call_timezone))
    horizon = now + timedelta(days=days)
    with _client() as client:
        busy = _busy(client, now, horizon)
    ranges = []
    for day in range(days + 1):
        base = (now + timedelta(days=day)).replace(minute=0, second=0, microsecond=0)
        start = max(base.replace(hour=9), now + timedelta(hours=1))
        end = min(base.replace(hour=20), horizon)
        if start >= end:
            continue
        fragments = [(start, end)]
        for bs, be in busy:
            fragments = [(a,b) for lo,hi in fragments for a,b in
                         ([(lo, hi)] if be <= lo or bs >= hi else [(lo, min(hi,bs)), (max(lo,be),hi)]) if a < b]
        ranges.extend({"start": s.isoformat(), "end": e.isoformat()} for s,e in fragments if (e-s).total_seconds() >= 1800)
    return ranges


def add_confirmed_event(call_id: str, start_iso: str, end_iso: str, title: str, location: str, description: str) -> str:
    """A stable event ID makes retries safe after partial writes or network timeouts."""
    import hashlib
    start, end = datetime.fromisoformat(start_iso), datetime.fromisoformat(end_iso)
    if start.utcoffset() is None or end.utcoffset() is None or end <= start:
        raise ValueError("A confirmed viewing needs an exact timezone-aware interval")
    event_id = hashlib.sha256(f"keyhunt-tour:{call_id}:{start_iso}".encode()).hexdigest()
    url = f"{CAL}/calendars/primary/events/{event_id}"

    def existing_event(response):
        response.raise_for_status()
        event = response.json()
        if (event.get("status") == "cancelled" or datetime.fromisoformat(event["start"]["dateTime"]) != start
                or datetime.fromisoformat(event["end"]["dateTime"]) != end):
            raise RuntimeError("Calendar event was changed; review the confirmed viewing")
        return event.get("htmlLink", "")

    with _client() as client:
        existing = client.get(url)
        if existing.status_code != 404:
            return existing_event(existing)
        if any(bs < end and be > start for bs,be in _busy(client, start, end)):
            raise RuntimeError("Calendar changed after the call; the contact booking needs review")
        response = client.post(f"{CAL}/calendars/primary/events", json={
            "id": event_id, "summary": title, "location": location, "description": description,
            "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()},
            "extendedProperties": {"private": {"keyhuntCall": call_id}},
        })
        if response.status_code == 409:
            return existing_event(client.get(url))
        return existing_event(response)

def timezone() -> str:
    with _client() as c:
        return c.get(f"{CAL}/users/me/settings/timezone").json().get("value", "UTC")


def free_windows(days: int = 7, start_hour: int = 9, end_hour: int = 20,
                 slot_minutes: int = 60, limit: int = 8) -> list[str]:
    """Human-readable free hour slots from the primary calendar, e.g. 'Thu Oct 15 6:00pm'."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone())
    now = datetime.now(tz)
    with _client() as c:
        busy = c.post(f"{CAL}/freeBusy", json={
            "timeMin": now.isoformat(), "timeMax": (now + timedelta(days=days)).isoformat(),
            "items": [{"id": "primary"}],
        }).json()["calendars"]["primary"]["busy"]
    busy = [(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in busy]

    out = []
    day = now.replace(minute=0, second=0, microsecond=0)
    for d in range(days + 1):
        for h in range(start_hour, end_hour):
            s = (day + timedelta(days=d)).replace(hour=h)
            e = s + timedelta(minutes=slot_minutes)
            if s <= now or any(bs < e and be > s for bs, be in busy):
                continue
            out.append(s.strftime("%a %b %-d %-I:%M%p").replace("AM", "am").replace("PM", "pm"))
            if len(out) >= limit:
                return out
    return out


def add_event(start_iso: str, title: str, location: str | None, description: str,
              minutes: int = 30) -> str:
    start = datetime.fromisoformat(start_iso)
    end = start + timedelta(minutes=minutes)
    tz = timezone()
    with _client() as c:
        res = c.post(f"{CAL}/calendars/primary/events", json={
            "summary": title,
            "location": location or "",
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": tz},
            "end": {"dateTime": end.isoformat(), "timeZone": tz},
        })
        res.raise_for_status()
        return res.json().get("htmlLink", "")


# --- Gmail ------------------------------------------------------------------

def search_messages(query: str, max_results: int = 25) -> list[dict]:
    """Return [{id, subject, from, date, html}] for messages matching a Gmail query."""
    with _client() as c:
        ids = c.get(f"{GMAIL}/messages", params={"q": query, "maxResults": max_results}
                    ).json().get("messages", [])
        out = []
        for m in ids:
            msg = c.get(f"{GMAIL}/messages/{m['id']}", params={"format": "full"}).json()
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            out.append({
                "id": m["id"],
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "date": headers.get("date", ""),
                "html": _body(msg["payload"], "text/html") or _body(msg["payload"], "text/plain"),
            })
        return out


def _body(part: dict, mime: str) -> str:
    if part.get("mimeType") == mime and part.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(part["body"]["data"] + "==").decode("utf-8", "replace")
    for p in part.get("parts", []) or []:
        found = _body(p, mime)
        if found:
            return found
    return ""


def send_email(to: str, subject: str, body: str) -> dict:
    """Send from the connected account. Returns {id, threadId}."""
    if not has_scope(SEND_SCOPE):
        raise RuntimeError("Reconnect Google on the Connections page to allow sending email")
    msg = EmailMessage()
    msg["To"] = to
    msg["From"] = db.get_connection(PROVIDER)["account"]
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    with _client() as c:
        res = c.post(f"{GMAIL}/messages/send", json={"raw": raw})
        res.raise_for_status()
        return res.json()

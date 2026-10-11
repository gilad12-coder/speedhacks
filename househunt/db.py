"""SQLite persistence. One connection per operation keeps it safe across worker threads."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from househunt.config import settings
from househunt.models import Listing, SearchCriteria

SCHEMA = """
CREATE TABLE IF NOT EXISTS household_jobs (
    household_id TEXT PRIMARY KEY,
    search_id INTEGER NOT NULL UNIQUE,
    published_hash TEXT
);
CREATE TABLE IF NOT EXISTS search_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criteria TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | sourcing | calling | done | error
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS listings (
    search_id INTEGER NOT NULL REFERENCES searches(id),
    key TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (search_id, key)
);
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL,
    listing_key TEXT NOT NULL,
    dial_call_id TEXT,
    status TEXT NOT NULL,
    transcript TEXT,
    outcome TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS do_not_call (
    phone TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tours (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL,
    listing_key TEXT NOT NULL,
    start TEXT NOT NULL,
    address TEXT,
    contact_name TEXT,
    contact_phone TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER,                        -- NULL for places found outside KeyHunt
    listing_key TEXT,
    title TEXT NOT NULL,
    url TEXT,
    address TEXT,
    price INTEGER,
    stage TEXT NOT NULL DEFAULT 'interested',
    next_step TEXT,
    next_date TEXT,
    notes TEXT,
    applied_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (search_id, listing_key)
);
CREATE TABLE IF NOT EXISTS place_notes (
    search_id INTEGER NOT NULL,
    listing_key TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',            -- one note per line; read by chats and calls
    updated_at TEXT NOT NULL,
    PRIMARY KEY (search_id, listing_key)
);
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER,                        -- both NULL for the general chat
    listing_key TEXT,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (search_id, listing_key)
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL,                       -- user | assistant | system (API roles)
    content TEXT NOT NULL,                    -- JSON exactly as sent to / returned by the API
    display TEXT,                             -- what the chat page shows; NULL = hidden turn
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbound_calls (
    id TEXT PRIMARY KEY,                      -- Dial call id
    caller TEXT,
    started_at TEXT,
    transcript TEXT,
    kind TEXT NOT NULL DEFAULT 'unknown',     -- renter | callback | unknown
    search_id INTEGER,                        -- matched listing, for callbacks
    listing_key TEXT,
    handled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS geocache (
    query TEXT PRIMARY KEY,
    lat REAL,                                 -- NULL = looked up, no match
    lng REAL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL,
    listing_key TEXT NOT NULL,
    to_addr TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',   -- draft | sent | failed | discarded
    gmail_message_id TEXT,
    gmail_thread_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT
);
CREATE TABLE IF NOT EXISTS connections (
    provider TEXT PRIMARY KEY,
    account TEXT,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at REAL NOT NULL,
    scope TEXT,
    connected_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conn():
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(settings.db_path, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        columns = {r[1] for r in c.execute("PRAGMA table_info(calls)")}
        for name, kind in {"raw": "TEXT", "attempt_key": "TEXT", "phone": "TEXT", "mode": "TEXT", "instruction": "TEXT", "booking_context": "TEXT"}.items():
            if name not in columns:
                c.execute(f"ALTER TABLE calls ADD COLUMN {name} {kind}")
        columns = {r[1] for r in c.execute("PRAGMA table_info(tours)")}
        for name, kind in {"end": "TEXT", "source_call_id": "INTEGER", "calendar_status": "TEXT DEFAULT 'pending'", "calendar_error": "TEXT", "calendar_url": "TEXT"}.items():
            if name not in columns:
                c.execute(f"ALTER TABLE tours ADD COLUMN {name} {kind}")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS tour_call ON tours(source_call_id) WHERE source_call_id IS NOT NULL")
    Path(settings.db_path).chmod(0o600)


def recover_calls() -> None:
    """Single-worker app startup: interrupted calls require explicit resume, never redial."""
    with conn() as c:
        c.execute("UPDATE calls SET status='attention', error='Worker restarted; resume the saved call' WHERE status IN ('queued', 'in_progress', 'extracting')")


# --- searches ---------------------------------------------------------------

def create_search(criteria: SearchCriteria) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO searches (criteria, created_at) VALUES (?, ?)",
            (json.dumps(criteria.__dict__), now()),
        )
        return cur.lastrowid


def get_search(search_id: int) -> tuple[SearchCriteria, sqlite3.Row] | None:
    with conn() as c:
        row = c.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
    return (SearchCriteria(**json.loads(row["criteria"])), row) if row else None


def list_searches() -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM searches ORDER BY id DESC LIMIT 50").fetchall()


def listing_counts() -> dict[int, dict[str, int]]:
    """Listing count per status for every search, for the dashboard."""
    with conn() as c:
        rows = c.execute(
            "SELECT search_id, status, COUNT(*) AS n FROM listings GROUP BY search_id, status"
        ).fetchall()
    out: dict[int, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["search_id"], {})[r["status"]] = r["n"]
    return out


def update_search_criteria(search_id: int, criteria: SearchCriteria) -> None:
    with conn() as c:
        c.execute("UPDATE searches SET criteria = ? WHERE id = ?",
                  (json.dumps(criteria.__dict__), search_id))


def set_search_status(search_id: int, status: str, error: str | None = None) -> None:
    with conn() as c:
        c.execute("UPDATE searches SET status = ?, error = ? WHERE id = ?", (status, error, search_id))


def search_event(search_id: int, message: str) -> None:
    with conn() as c:
        c.execute("INSERT INTO search_events(search_id, message, created_at) VALUES (?, ?, ?)",
                  (search_id, message[:500], now()))


def search_events(search_id: int) -> list:
    with conn() as c:
        return c.execute("SELECT * FROM search_events WHERE search_id = ? ORDER BY id DESC LIMIT 30", (search_id,)).fetchall()[::-1]


def household_search(household_id: str) -> int | None:
    with conn() as c:
        row = c.execute("SELECT search_id FROM household_jobs WHERE household_id = ?", (household_id,)).fetchone()
    return row['search_id'] if row else None


# --- listings ---------------------------------------------------------------

def upsert_listing(search_id: int, l: Listing) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO listings (search_id, key, data, status, score) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(search_id, key) DO UPDATE SET data=excluded.data, "
            "status=excluded.status, score=excluded.score",
            (search_id, l.key, json.dumps(l.to_dict(), default=str), l.status.value, l.score),
        )


def get_listing(search_id: int, key: str) -> Listing | None:
    with conn() as c:
        row = c.execute(
            "SELECT data FROM listings WHERE search_id = ? AND key = ?", (search_id, key)
        ).fetchone()
    return Listing.from_dict(json.loads(row["data"])) if row else None


def list_listings(search_id: int) -> list[Listing]:
    with conn() as c:
        rows = c.execute(
            "SELECT data FROM listings WHERE search_id = ? ORDER BY score DESC", (search_id,)
        ).fetchall()
    return [Listing.from_dict(json.loads(r["data"])) for r in rows]


# --- calls ------------------------------------------------------------------

def create_call(search_id: int, listing_key: str) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO calls (search_id, listing_key, status, created_at, updated_at) "
            "VALUES (?, ?, 'queued', ?, ?)",
            (search_id, listing_key, now(), now()),
        )
        return cur.lastrowid


def claim_call(search_id: int, listing_key: str, phone: str, mode: str) -> sqlite3.Row | None:
    """Reserve once across concurrent button clicks; retries retain the provider key."""
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        existing = c.execute("SELECT * FROM calls WHERE search_id=? AND listing_key=? ORDER BY id DESC LIMIT 1", (search_id, listing_key)).fetchone()
        if existing:
            if existing["phone"] != phone:
                return None
            if existing["status"] not in ("attention", "failed") or not existing["attempt_key"] or existing["mode"] != mode:
                return None
            call_id = existing["id"]
            c.execute("UPDATE calls SET status='in_progress', error=NULL WHERE id=?", (call_id,))
        else:
            call_id = c.execute("INSERT INTO calls (search_id,listing_key,status,created_at,updated_at,attempt_key,phone,mode) VALUES (?,?,'in_progress',?,?,?,?,?)",
                (search_id, listing_key, now(), now(), f"keyhunt-{uuid.uuid4().hex}", phone, mode)).lastrowid
        return c.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()


def contact_blocked(phone: str) -> bool:
    with conn() as c:
        return c.execute("SELECT 1 FROM do_not_call WHERE phone=?", (phone,)).fetchone() is not None


def block_contact(phone: str) -> None:
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO do_not_call VALUES (?,?)", (phone, now()))


def contact_called_today(phone: str, except_id: int) -> bool:
    with conn() as c:
        count = c.execute("SELECT COUNT(*) FROM calls WHERE phone=? AND id<>? AND mode='live' AND substr(created_at,1,10)=?", (phone, except_id, now()[:10])).fetchone()[0]
        return count >= settings.max_calls_per_number_per_day


def update_call(call_id: int, **fields) -> None:
    if "booking_context" in fields and not isinstance(fields["booking_context"], str):
        fields["booking_context"] = json.dumps(fields["booking_context"])
    if "raw" in fields and not isinstance(fields["raw"], str):
        fields["raw"] = json.dumps(fields["raw"])
    if "outcome" in fields and not isinstance(fields["outcome"], str):
        fields["outcome"] = json.dumps(fields["outcome"])
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE calls SET {cols} WHERE id = ?", (*fields.values(), call_id))


def calls_for_search(search_id: int) -> dict[str, sqlite3.Row]:
    """Latest call per listing."""
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM calls WHERE search_id = ? ORDER BY id", (search_id,)
        ).fetchall()
    return {r["listing_key"]: r for r in rows}


# --- tours ------------------------------------------------------------------

def create_tour(search_id: int, listing_key: str, start: str, address: str | None,
                contact_name: str | None, contact_phone: str | None, *, end: str | None = None,
                source_call_id: int | None = None) -> int:
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        if source_call_id is not None:
            existing = c.execute("SELECT * FROM tours WHERE source_call_id=?", (source_call_id,)).fetchone()
            if existing:
                if (existing["search_id"], existing["listing_key"], existing["start"], existing["end"]) != (search_id, listing_key, start, end):
                    raise RuntimeError("Saved tour differs from this extraction; review the call before changing the appointment")
                return existing["id"]
        cur = c.execute(
            "INSERT INTO tours (search_id, listing_key, start, address, contact_name, "
            "contact_phone, created_at, end, source_call_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (search_id, listing_key, start, address, contact_name, contact_phone, now(), end, source_call_id),
        )
        return cur.lastrowid


def update_tour_calendar(tour_id: int, status: str, error: str | None = None, url: str | None = None) -> None:
    with conn() as c:
        c.execute("UPDATE tours SET calendar_status=?, calendar_error=?, calendar_url=? WHERE id=?", (status, error, url, tour_id))


def get_tour(tour_id: int) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM tours WHERE id = ?", (tour_id,)).fetchone()


def tours_for_search(search_id: int) -> dict[str, sqlite3.Row]:
    with conn() as c:
        rows = c.execute("SELECT * FROM tours WHERE search_id = ?", (search_id,)).fetchall()
    return {r["listing_key"]: r for r in rows}


# --- applications -----------------------------------------------------------

APP_FIELDS = ("search_id", "listing_key", "title", "url", "address", "price", "stage",
              "next_step", "next_date", "notes", "applied_at")


def create_application(**fields) -> int | None:
    """Insert a tracked place. Returns None if that listing is already tracked."""
    fields = {k: v for k, v in fields.items() if k in APP_FIELDS}
    fields.setdefault("stage", "interested")
    fields["created_at"] = fields["updated_at"] = now()
    cols = ", ".join(fields)
    with conn() as c:
        cur = c.execute(f"INSERT OR IGNORE INTO applications ({cols}) VALUES "
                        f"({', '.join('?' * len(fields))})", tuple(fields.values()))
        return cur.lastrowid if cur.rowcount else None


def get_application(app_id: int) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()


def find_application(search_id: int, listing_key: str) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM applications WHERE search_id = ? AND listing_key = ?",
                         (search_id, listing_key)).fetchone()


def list_applications() -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM applications ORDER BY updated_at DESC").fetchall()


def applications_for_search(search_id: int) -> dict[str, sqlite3.Row]:
    with conn() as c:
        rows = c.execute("SELECT * FROM applications WHERE search_id = ?", (search_id,)).fetchall()
    return {r["listing_key"]: r for r in rows}


def update_application(app_id: int, **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in APP_FIELDS}
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE applications SET {cols} WHERE id = ?", (*fields.values(), app_id))


def delete_application(app_id: int) -> None:
    with conn() as c:
        c.execute("DELETE FROM applications WHERE id = ?", (app_id,))


def journey_counts() -> dict[str, int]:
    """Totals across every search, for the 'where am I' overview."""
    with conn() as c:
        one = lambda sql: c.execute(sql).fetchone()[0]
        return {
            "searches": one("SELECT COUNT(*) FROM searches"),
            "listings": one("SELECT COUNT(*) FROM listings"),
            "matches": one("SELECT COUNT(*) FROM listings WHERE status NOT IN ('filtered', 'new')"),
            "calls": one("SELECT COUNT(DISTINCT search_id || listing_key) FROM calls"),
            "viable": one("SELECT COUNT(*) FROM listings WHERE status IN ('viable', 'tour_scheduled')"),
            "tours": one("SELECT COUNT(*) FROM tours"),
        }


# --- place notes ------------------------------------------------------------

def place_notes(search_id: int, listing_key: str) -> list[str]:
    with conn() as c:
        row = c.execute("SELECT body FROM place_notes WHERE search_id = ? AND listing_key = ?",
                        (search_id, listing_key)).fetchone()
    return [n for n in (row["body"] if row else "").splitlines() if n.strip()]


def notes_for_search(search_id: int) -> dict[str, list[str]]:
    with conn() as c:
        rows = c.execute("SELECT listing_key, body FROM place_notes WHERE search_id = ?",
                         (search_id,)).fetchall()
    return {r["listing_key"]: [n for n in r["body"].splitlines() if n.strip()] for r in rows}


def set_place_notes(search_id: int, listing_key: str, notes: list[str]) -> None:
    body = "\n".join(n.strip().lstrip("-• ").strip() for n in notes if n.strip())
    with conn() as c:
        c.execute("INSERT INTO place_notes (search_id, listing_key, body, updated_at) VALUES (?, ?, ?, ?) "
                  "ON CONFLICT(search_id, listing_key) DO UPDATE SET body=excluded.body, "
                  "updated_at=excluded.updated_at", (search_id, listing_key, body, now()))


def add_place_note(search_id: int, listing_key: str, note: str) -> bool:
    """Append a note unless it's already there. Returns True if added."""
    note = " ".join(note.split()).lstrip("-• ")
    notes = place_notes(search_id, listing_key)
    if not note or note.lower() in (n.lower() for n in notes):
        return False
    set_place_notes(search_id, listing_key, notes + [note])
    return True


# --- chats ------------------------------------------------------------------

def get_or_create_chat(search_id: int | None, listing_key: str | None, title: str) -> int:
    with conn() as c:
        row = c.execute("SELECT id FROM chats WHERE search_id IS ? AND listing_key IS ?",
                        (search_id, listing_key)).fetchone()
        if row:
            return row["id"]
        return c.execute("INSERT INTO chats (search_id, listing_key, title, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?, ?)",
                         (search_id, listing_key, title, now(), now())).lastrowid


def get_chat(chat_id: int) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()


def list_chats(limit: int = 50) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM chats ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()


def chats_for_search(search_id: int) -> dict[str, sqlite3.Row]:
    with conn() as c:
        rows = c.execute("SELECT * FROM chats WHERE search_id = ?", (search_id,)).fetchall()
    return {r["listing_key"]: r for r in rows}


def add_chat_message(chat_id: int, role: str, content, display: str | None) -> int:
    with conn() as c:
        c.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now(), chat_id))
        return c.execute("INSERT INTO chat_messages (chat_id, role, content, display, created_at) "
                         "VALUES (?, ?, ?, ?, ?)",
                         (chat_id, role, json.dumps(content), display, now())).lastrowid


def chat_messages(chat_id: int) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM chat_messages WHERE chat_id = ? ORDER BY id",
                         (chat_id,)).fetchall()


def calls_for_listing(search_id: int, listing_key: str) -> list[sqlite3.Row]:
    """Every call attempt for one listing, oldest first."""
    with conn() as c:
        return c.execute("SELECT * FROM calls WHERE search_id = ? AND listing_key = ? ORDER BY id",
                         (search_id, listing_key)).fetchall()


def emails_for_listing(search_id: int, listing_key: str) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM emails WHERE search_id = ? AND listing_key = ? "
                         "AND status != 'discarded' ORDER BY id", (search_id, listing_key)).fetchall()


def draft_emails() -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM emails WHERE status = 'draft' ORDER BY id").fetchall()


def listing_by_phone(phone: str) -> tuple[int, "Listing"] | None:
    """The most recent listing whose contact has this phone number, for matching callbacks."""
    digits = "".join(ch for ch in phone if ch.isdigit())[-10:]
    if len(digits) < 10:
        return None
    with conn() as c:
        rows = c.execute("SELECT search_id, data FROM listings ORDER BY search_id DESC").fetchall()
    for r in rows:
        l = Listing.from_dict(json.loads(r["data"]))
        if l.contact and l.contact.phone and \
                "".join(ch for ch in l.contact.phone if ch.isdigit())[-10:] == digits:
            return r["search_id"], l
    return None


def all_calls() -> list[sqlite3.Row]:
    """Every call across searches, newest first (all attempts, not just the latest)."""
    with conn() as c:
        return c.execute("SELECT * FROM calls ORDER BY id DESC").fetchall()


def all_tours() -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM tours ORDER BY start").fetchall()


# --- app state & inbound calls -----------------------------------------------

def get_state(key: str, default: str | None = None) -> str | None:
    with conn() as c:
        row = c.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(key: str, value: str | None) -> None:
    with conn() as c:
        if value is None:
            c.execute("DELETE FROM app_state WHERE key = ?", (key,))
        else:
            c.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", (key, value))


def save_inbound_call(call_id: str, caller: str | None, started_at: str | None,
                      transcript: str | None, kind: str, search_id: int | None,
                      listing_key: str | None) -> bool:
    """Insert once per Dial call id; later polls fill in a transcript that arrived late."""
    with conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO inbound_calls (id, caller, started_at, transcript, kind, "
            "search_id, listing_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (call_id, caller, started_at, transcript, kind, search_id, listing_key, now()))
        if not cur.rowcount and transcript:
            c.execute("UPDATE inbound_calls SET transcript = ?, kind = ?, search_id = ?, "
                      "listing_key = ? WHERE id = ? AND transcript IS NULL",
                      (transcript, kind, search_id, listing_key, call_id))
        return bool(cur.rowcount)


def inbound_calls(unhandled_only: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM inbound_calls"
    if unhandled_only:
        sql += " WHERE handled = 0 AND kind != 'renter'"
    with conn() as c:
        return c.execute(sql + " ORDER BY started_at DESC").fetchall()


def mark_inbound_handled(call_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE inbound_calls SET handled = 1 WHERE id = ?", (call_id,))


# --- geocode cache ----------------------------------------------------------

def get_geocode(query: str) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT lat, lng FROM geocache WHERE query = ?", (query,)).fetchone()


def save_geocode(query: str, lat: float | None, lng: float | None) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO geocache (query, lat, lng, created_at) VALUES (?, ?, ?, ?)",
                  (query, lat, lng, now()))


# --- connections (OAuth tokens) --------------------------------------------

def save_connection(provider: str, account: str | None, access_token: str,
                    refresh_token: str | None, expires_at: float, scope: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO connections (provider, account, access_token, refresh_token, "
            "expires_at, scope, connected_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(provider) DO UPDATE SET account=excluded.account, "
            "access_token=excluded.access_token, "
            "refresh_token=COALESCE(excluded.refresh_token, connections.refresh_token), "
            "expires_at=excluded.expires_at, scope=excluded.scope",
            (provider, account, access_token, refresh_token, expires_at, scope, now()),
        )


def get_connection(provider: str) -> sqlite3.Row | None:
    with conn() as c:
        try:
            return c.execute(
                "SELECT * FROM connections WHERE provider = ?", (provider,)).fetchone()
        except sqlite3.OperationalError:  # db not initialised yet
            return None


def delete_connection(provider: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM connections WHERE provider = ?", (provider,))


# --- emails (drafts await explicit approval before sending) -----------------

def create_email(search_id: int, listing_key: str, to_addr: str, subject: str, body: str) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO emails (search_id, listing_key, to_addr, subject, body, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (search_id, listing_key, to_addr, subject, body, now()),
        )
        return cur.lastrowid


def get_email(email_id: int) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()


def update_email(email_id: int, **fields) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE emails SET {cols} WHERE id = ?", (*fields.values(), email_id))


def emails_for_search(search_id: int) -> dict[str, sqlite3.Row]:
    """Latest non-discarded email per listing."""
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM emails WHERE search_id = ? AND status != 'discarded' ORDER BY id",
            (search_id,),
        ).fetchall()
    return {r["listing_key"]: r for r in rows}

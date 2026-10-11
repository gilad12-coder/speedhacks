"""SQLite persistence. One connection per operation keeps it safe across worker threads."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from househunt.config import settings
from househunt.models import Listing, SearchCriteria

SCHEMA = """
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
CREATE TABLE IF NOT EXISTS geocache (
    query TEXT PRIMARY KEY,
    lat REAL,                                 -- NULL = looked up, no match
    lng REAL,
    created_at TEXT NOT NULL
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


def set_search_status(search_id: int, status: str, error: str | None = None) -> None:
    with conn() as c:
        c.execute("UPDATE searches SET status = ?, error = ? WHERE id = ?", (status, error, search_id))


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


def update_call(call_id: int, **fields) -> None:
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
                contact_name: str | None, contact_phone: str | None) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO tours (search_id, listing_key, start, address, contact_name, "
            "contact_phone, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (search_id, listing_key, start, address, contact_name, contact_phone, now()),
        )
        return cur.lastrowid


def get_tour(tour_id: int) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT * FROM tours WHERE id = ?", (tour_id,)).fetchone()


def tours_for_search(search_id: int) -> dict[str, sqlite3.Row]:
    with conn() as c:
        rows = c.execute("SELECT * FROM tours WHERE search_id = ?", (search_id,)).fetchall()
    return {r["listing_key"]: r for r in rows}


# --- geocode cache ----------------------------------------------------------

def get_geocode(query: str) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("SELECT lat, lng FROM geocache WHERE query = ?", (query,)).fetchone()


def save_geocode(query: str, lat: float | None, lng: float | None) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO geocache (query, lat, lng, created_at) VALUES (?, ?, ?, ?)",
                  (query, lat, lng, now()))

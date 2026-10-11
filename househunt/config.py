"""Settings read from the environment (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class CallMode(str, Enum):
    DRY_RUN = "dry_run"    # never dial; fake transcripts so the flow runs end to end
    APPROVE = "approve"    # dial only when the user clicks "Call" on a listing
    AUTO = "auto"          # dial the top N candidates automatically


@dataclass(frozen=True)
class Settings:
    db_path: str
    call_mode: CallMode
    max_auto_calls: int
    mock_sources: bool
    dial_api_url: str
    dial_api_key: str | None
    dial_from_number: str | None     # E.164 or pn_… id
    notify_number: str | None        # where to text the renter results
    renter_name: str
    app_password: str | None         # HTTP basic auth for the deployed app
    claude_model: str
    briefing_pin: str | None         # passcode to hear your briefing when you call your KeyHunt number
    geocode: bool                    # place listings on the map via OpenStreetMap Nominatim
    google_client_id: str | None
    google_client_secret: str | None
    public_base_url: str | None      # e.g. https://househunt.onrender.com (for OAuth redirect)
    firecrawl_api_key: str | None    # optional: parse pasted links from unsupported sites


def load() -> Settings:
    env = os.environ.get
    return Settings(
        db_path=env("DB_PATH", "data/househunt.db"),
        call_mode=CallMode(env("CALL_MODE", "dry_run")),
        max_auto_calls=int(env("MAX_AUTO_CALLS", "3")),
        mock_sources=env("MOCK_SOURCES", "1") == "1",
        dial_api_url=env("DIAL_API_URL", "https://api.getdial.ai"),
        dial_api_key=env("DIAL_API_KEY"),
        dial_from_number=env("DIAL_FROM_NUMBER"),
        notify_number=env("NOTIFY_NUMBER"),
        renter_name=env("RENTER_NAME", "my client"),
        app_password=env("APP_PASSWORD"),
        claude_model=env("CLAUDE_MODEL", "claude-opus-5-5"),
        briefing_pin=(env("BRIEFING_PIN") or "").strip() or None,
        geocode=env("GEOCODE", "1") == "1",
        google_client_id=env("GOOGLE_CLIENT_ID"),
        google_client_secret=env("GOOGLE_CLIENT_SECRET"),
        public_base_url=env("PUBLIC_BASE_URL"),
        firecrawl_api_key=env("FIRECRAWL_API_KEY"),
    )


settings = load()

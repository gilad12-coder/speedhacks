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
    openai_api_key: str | None
    openai_base_url: str             # OpenRouter when OPENROUTER_API_KEY is set
    openai_model: str
    dial_allowed_numbers: tuple[str, ...]
    call_max_seconds: int
    call_timezone: str
    max_calls_per_number_per_day: int
    web_research: bool
    search_model: str
    search_max_listings: int
    screen_top_n: int
    firecrawl_api_key: str | None    # optional: parse pasted links from unsupported sites


def load() -> Settings:
    env = os.environ.get
    openrouter = env("OPENROUTER_API_KEY")
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
        claude_model=env("CLAUDE_MODEL", "anthropic/claude-opus-5.5" if openrouter else "claude-opus-5-5"),
        briefing_pin=(env("BRIEFING_PIN") or "").strip() or None,
        geocode=env("GEOCODE", "1") == "1",
        google_client_id=env("GOOGLE_CLIENT_ID"),
        google_client_secret=env("GOOGLE_CLIENT_SECRET"),
        public_base_url=env("PUBLIC_BASE_URL"),
        openai_api_key=openrouter or env("OPENAI_API_KEY"),
        openai_base_url="https://openrouter.ai/api/v1" if openrouter else "https://api.openai.com/v1",
        openai_model=env("OPENAI_MODEL", "openai/gpt-4.1-mini" if openrouter else "gpt-4.1-mini"),
        dial_allowed_numbers=tuple(n.strip() for n in env("DIAL_ALLOWED_NUMBERS", "").split(",") if n.strip()),
        call_max_seconds=max(60, min(300, int(env("CALL_DURATION_SECONDS", "180")))),
        call_timezone=env("CALLER_TIMEZONE", "America/Los_Angeles"),
        max_calls_per_number_per_day=max(1, min(5, int(env("MAX_CALLS_PER_NUMBER_PER_DAY", "1")))),
        web_research=env("WEB_RESEARCH", "1") == "1",
        search_model=env("SEARCH_MODEL", "openai/gpt-4.1" if openrouter else "gpt-4.1"),
        search_max_listings=max(1, min(15, int(env("SEARCH_MAX_LISTINGS", "10")))),
        screen_top_n=max(1, min(10, int(env("SCREEN_TOP_N", "5")))),
        firecrawl_api_key=env("FIRECRAWL_API_KEY"),
    )


settings = load()

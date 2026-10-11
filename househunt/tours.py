"""Tour records -> calendar invites (.ics) the renter can add with one tap."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def to_ics(tour_id: int, start_iso: str, title: str, address: str | None,
           contact: str | None, url: str | None, minutes: int = 30) -> str:
    start = datetime.fromisoformat(start_iso)
    end = start + timedelta(minutes=minutes)
    fmt = "%Y%m%dT%H%M%S"  # floating local time: shows at the agreed wall-clock time
    desc = "\\n".join(x for x in [f"Contact: {contact}" if contact else None, url] if x)
    return "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//KeyHunt//EN",
        "BEGIN:VEVENT",
        f"UID:tour-{tour_id}@keyhunt",
        f"DTSTAMP:{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
        f"DTSTART:{start:{fmt}}",
        f"DTEND:{end:{fmt}}",
        f"SUMMARY:Viewing: {_esc(title)}",
        f"LOCATION:{_esc(address or '')}",
        f"DESCRIPTION:{_esc(desc)}",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ])


def _esc(s: str) -> str:
    return s.replace(",", "\\,").replace(";", "\\;")

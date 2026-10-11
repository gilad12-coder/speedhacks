"""Phone briefings on the renter's KeyHunt (Dial) number.

- "Call me": an outbound call to NOTIFY_NUMBER with the current briefing.
- Call-in: when switched on, the number's inbound instruction carries the latest briefing
  (behind BRIEFING_PIN), refreshed in the background, and inbound calls are pulled back so
  landlord callbacks show up as flags. Switching off restores the number's previous instruction.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime

from househunt import briefing, db
from househunt.config import settings

log = logging.getLogger(__name__)

REFRESH_SECONDS = 180


def configured() -> bool:
    return bool(settings.dial_api_key)


def enabled() -> bool:
    return db.get_state("phone_briefing") == "on"


def _client():
    from househunt.outreach.dial import DialClient

    return DialClient(settings)


def call_me():
    if not (configured() and settings.notify_number):
        raise RuntimeError("Set DIAL_API_KEY and NOTIFY_NUMBER in .env first")
    return _client().place_call(settings.notify_number, briefing.outbound_instruction(),
                                max_seconds=300)


def enable() -> None:
    dial = _client()
    number = dial.own_number()
    if db.get_state("inbound_original") is None:
        db.set_state("inbound_original", number.get("inboundInstruction") or "")
    db.set_state("phone_number_id", number["id"])
    db.set_state("phone_number", number.get("number") or "")
    db.set_state("phone_briefing", "on")
    db.set_state("inbound_since", datetime.now().astimezone().isoformat(timespec="seconds"))
    sync(force=True)


def disable() -> None:
    number_id = db.get_state("phone_number_id")
    if number_id:
        # Put back what the number said before; if it had nothing, leave a plain
        # message-taker so landlords calling back still reach someone.
        original = db.get_state("inbound_original") or briefing.message_taker_instruction()
        _client().set_inbound_instruction(number_id, original)
    db.set_state("phone_briefing", None)
    db.set_state("inbound_original", None)
    db.set_state("inbound_hash", None)


def sync(force: bool = False) -> bool:
    """Push the latest briefing to the number if it changed. Returns True if it pushed."""
    if not (enabled() and configured()):
        return False
    instruction = briefing.inbound_instruction()
    digest = hashlib.sha256(_facts_without_clock(instruction).encode()).hexdigest()
    if not force and digest == db.get_state("inbound_hash"):
        return False
    _client().set_inbound_instruction(db.get_state("phone_number_id"), instruction)
    db.set_state("inbound_hash", digest)
    db.set_state("inbound_synced_at", datetime.now().isoformat(timespec="seconds"))
    return True


def _facts_without_clock(instruction: str) -> str:
    # The first facts line is a timestamp; don't re-push just because the minute changed.
    return "\n".join(l for l in instruction.splitlines() if not l.startswith("Status as of"))


def poll_inbound() -> int:
    """Pull new inbound calls; classify the renter's own calls vs landlord callbacks."""
    if not (enabled() and configured()):
        return 0
    since = db.get_state("inbound_since")
    calls = _client().inbound_calls(db.get_state("phone_number_id"), since)
    new = 0
    for c in calls:
        caller = c.get("from")
        transcript = c.get("transcript")
        mine = bool(caller and settings.notify_number and
                    _digits(caller) == _digits(settings.notify_number))
        match = None if mine or not caller else db.listing_by_phone(caller)
        new += db.save_inbound_call(
            c["id"], caller, c.get("createdAt"), transcript,
            "renter" if mine else "callback", match[0] if match else None,
            match[1].key if match else None)
    return new


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())[-10:]


def _loop(stop: threading.Event) -> None:
    while not stop.wait(REFRESH_SECONDS):
        try:
            if enabled():
                sync()
                poll_inbound()
        except Exception:
            log.exception("phone briefing refresh failed")


def start_background() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), daemon=True, name="phone-briefing").start()
    return stop

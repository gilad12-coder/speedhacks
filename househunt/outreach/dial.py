"""Thin client for the Dial REST API (https://api.getdial.ai), plus a fake for dry runs.

Endpoints used (same ones the `dial` CLI wraps):
  POST /api/v1/calls        {to, fromNumber|fromNumberId, outboundInstruction, ...} -> {call}
  GET  /api/v1/calls/{id}   -> {call: {id, status, transcript, transcriptTurns, ...}}
  POST /api/v1/messages     {to, body, fromNumber|fromNumberId} -> SMS/iMessage
"""

from __future__ import annotations

import time
import uuid
from urllib.parse import quote
from dataclasses import dataclass

import httpx

from househunt.config import Settings


@dataclass
class DialCall:
    id: str
    ended: bool
    label: str
    termination: str | None
    transcript: str | None
    raw: dict


def _parse_call(call: dict) -> DialCall:
    status = call.get("status")
    if isinstance(status, dict):
        state = status.get("state") or ""
        termination = status.get("terminationType")
        label = status.get("label") or state or "unknown"
        ended = state.lower() in {"terminated", "completed", "failed", "no-answer", "busy", "canceled", "cancelled", "ended"} or termination is not None
    else:
        termination = None
        label = str(status)
        ended = label.lower() in {"terminated", "completed", "failed", "no-answer", "busy", "canceled", "cancelled", "ended"}
    return DialCall(
        id=call["id"], ended=ended, label=label, termination=termination,
        transcript=call.get("transcript"), raw=call,
    )


class DialClient:
    def __init__(self, s: Settings):
        if not s.dial_api_key or not s.dial_from_number:
            raise RuntimeError("Set DIAL_API_KEY and DIAL_FROM_NUMBER")
        if s.dial_api_url.rstrip("/") != "https://api.getdial.ai":
            raise RuntimeError("Live Dial credentials must be sent only to https://api.getdial.ai")
        self.from_number = s.dial_from_number
        self.http = httpx.Client(
            base_url=s.dial_api_url,
            headers={"authorization": f"Bearer {s.dial_api_key}"},
            timeout=30,
        )

    def _from(self) -> dict:
        if not self.from_number:
            return {}
        key = "fromNumberId" if self.from_number.startswith("pn_") else "fromNumber"
        return {key: self.from_number}

    def place_call(self, to: str, instruction: str, max_seconds: int = 300,
                   idempotency_key: str | None = None) -> DialCall:
        res = self.http.post(
            "/api/v1/calls",
            json={"to": to, "outboundInstruction": instruction,
                  "maxCallDurationSeconds": max_seconds, **self._from()},
            headers={"idempotency-key": idempotency_key or str(uuid.uuid4())},
        )
        if not res.is_success:
            raise RuntimeError(f"Dial placement HTTP {res.status_code}; retry the saved attempt, never create a new key")
        return _parse_call(res.json()["call"])

    def get_call(self, call_id: str) -> DialCall:
        res = self.http.get(f"/api/v1/calls/{quote(call_id, safe='')}")
        if not res.is_success:
            raise RuntimeError(f"Dial lookup HTTP {res.status_code}; saved call can be resumed")
        return _parse_call(res.json()["call"])

    def wait_for_call(self, call_id: str, timeout: float = 600, poll: float = 5) -> DialCall:
        deadline = time.monotonic() + timeout
        terminal_at = None
        while True:
            call = self.get_call(call_id)
            # Transcript can land a moment after the call terminates.
            if call.ended:
                terminal_at = terminal_at or time.monotonic()
                if call.raw.get("transcriptTurns") or time.monotonic() - terminal_at >= 60:
                    return call
            if time.monotonic() > deadline:
                raise RuntimeError("Dial polling timed out; resume the existing call, do not redial")
            time.sleep(poll)

    def send_message(self, to: str, body: str) -> dict:
        res = self.http.post("/api/v1/messages", json={"to": to, "body": body, **self._from()})
        res.raise_for_status()
        return res.json()


class FakeDialClient:
    """Dry-run stand-in: returns a canned transcript so extraction/tours/notify all run."""

    def __init__(self, *_):
        self.sent: list[tuple[str, str]] = []

    def place_call(self, to: str, instruction: str, **_) -> DialCall:
        return DialCall(id=f"fake-{uuid.uuid4().hex[:8]}", ended=False, label="Queued",
                        termination=None, transcript=None, raw={})

    def get_call(self, call_id: str) -> DialCall:
        return self.wait_for_call(call_id)

    def wait_for_call(self, call_id: str, **_) -> DialCall:
        transcript = (
            "Agent: Hi, this is an AI assistant calling about your rental listing. Is it still available?\n"
            "Contact: Yes, it is.\n"
            "Agent: Great. What's the rent and deposit?\n"
            "Contact: Rent is as listed, deposit is one month.\n"
            "Agent: Is a 12-month lease OK, and are pets allowed?\n"
            "Contact: 12 months is standard. Cats are fine.\n"
            "Agent: Could we book a viewing Thursday at 6pm?\n"
            "Contact: Thursday at 6 works.\n"
            "Agent: Perfect, Thursday at 6pm. Thank you!"
        )
        return DialCall(id=call_id, ended=True, label="Completed", termination="completed",
                        transcript=transcript, raw={})

    def send_message(self, to: str, body: str) -> dict:
        self.sent.append((to, body))
        return {"fake": True}

"""Thin client for the Dial REST API (https://api.getdial.ai), plus a fake for dry runs.

Endpoints used (same ones the `dial` CLI wraps):
  POST /api/v1/calls        {to, fromNumber|fromNumberId, outboundInstruction, ...} -> {call}
  GET  /api/v1/calls/{id}   -> {call: {id, status, transcript, transcriptTurns, ...}}
  POST /api/v1/messages     {to, body, fromNumber|fromNumberId} -> SMS/iMessage
  GET  /api/v1/numbers      -> {numbers: [{id, number, inboundInstruction, ...}], defaultNumberId}
  PATCH /api/v1/numbers/{id} {inboundInstruction} -> what inbound callers' agent says
  GET  /api/v1/calls?direction=inbound&since=... -> {calls: [...]}
"""

from __future__ import annotations

import time
import uuid
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
        ended = state == "Terminated" or termination is not None
    else:
        termination = None
        label = str(status)
        ended = label.lower() in {"completed", "failed", "no-answer", "busy", "canceled", "ended"}
    return DialCall(
        id=call["id"], ended=ended, label=label, termination=termination,
        transcript=call.get("transcript"), raw=call,
    )


class DialClient:
    def __init__(self, s: Settings):
        if not s.dial_api_key:
            raise RuntimeError("DIAL_API_KEY is not set")
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
        res.raise_for_status()
        return _parse_call(res.json()["call"])

    def get_call(self, call_id: str) -> DialCall:
        res = self.http.get(f"/api/v1/calls/{call_id}")
        res.raise_for_status()
        return _parse_call(res.json()["call"])

    def wait_for_call(self, call_id: str, timeout: float = 600, poll: float = 5) -> DialCall:
        deadline = time.monotonic() + timeout
        while True:
            call = self.get_call(call_id)
            # Transcript can land a moment after the call terminates.
            if call.ended and (call.transcript or time.monotonic() > deadline - 60):
                return call
            if time.monotonic() > deadline:
                return call
            time.sleep(poll)

    def send_message(self, to: str, body: str) -> dict:
        res = self.http.post("/api/v1/messages", json={"to": to, "body": body, **self._from()})
        res.raise_for_status()
        return res.json()

    def own_number(self) -> dict:
        """The account number KeyHunt calls from (DIAL_FROM_NUMBER, else the default)."""
        res = self.http.get("/api/v1/numbers")
        res.raise_for_status()
        data = res.json()
        numbers = data.get("numbers") or []
        ref = self.from_number or data.get("defaultNumberId")
        for n in numbers:
            if ref in (n.get("id"), n.get("number"), n.get("nickname")):
                return n
        if not numbers:
            raise RuntimeError("No phone numbers on this Dial account")
        return numbers[0]

    def set_inbound_instruction(self, number_id: str, instruction: str) -> None:
        res = self.http.patch(f"/api/v1/numbers/{number_id}",
                              json={"inboundInstruction": instruction})
        res.raise_for_status()

    def inbound_calls(self, number_id: str | None = None, since: str | None = None) -> list[dict]:
        """Each call has id, from, to, direction, createdAt, duration, status, transcript."""
        params = {"direction": "inbound"}
        if number_id:
            params["numberId"] = number_id
        if since:
            params["since"] = since
        res = self.http.get("/api/v1/calls", params=params)
        res.raise_for_status()
        return res.json().get("calls") or []


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

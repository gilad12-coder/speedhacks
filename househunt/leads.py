"""Leads: places the renter is interested in where outreach hasn't produced a viewing yet.

A lead is an application in the "interested" stage. Booking a viewing moves it on; the
renter can also drop it (it becomes "withdrawn" with the reason in its notes) and restore it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from househunt import db

DROP_REASONS = {
    "no_response": "No response",
    "unavailable": "Not available",
    "not_a_fit": "Not a fit",
    "other": "Other",
}


@dataclass
class Attempt:
    kind: str          # call | email
    when: str          # ISO timestamp
    result: str        # short human label
    tone: str          # good | bad | wait


@dataclass
class Outreach:
    status: str        # new | waiting | action
    label: str
    attempts: list[Attempt] = field(default_factory=list)
    last_contact: str | None = None

    @property
    def days_since(self) -> int | None:
        if not self.last_contact:
            return None
        return (datetime.now() - datetime.fromisoformat(self.last_contact)).days


def _call_attempt(call) -> Attempt:
    outcome = json.loads(call["outcome"]) if call["outcome"] else None
    if call["status"] in ("queued", "in_progress"):
        return Attempt("call", call["created_at"], "Calling now", "wait")
    if call["status"] == "failed":
        return Attempt("call", call["created_at"], "Call didn't go through", "bad")
    if not outcome:
        return Attempt("call", call["created_at"], "Call ended, no summary", "wait")
    if not outcome.get("reached_person"):
        return Attempt("call", call["created_at"], "No answer / voicemail", "wait")
    if outcome.get("viable"):
        return Attempt("call", call["created_at"], "Reached them: available", "good")
    return Attempt("call", call["created_at"], "Reached them: not a fit", "bad")


def outreach(search_id: int | None, key: str | None) -> Outreach:
    if not (search_id and key):
        return Outreach("new", "Tracked by hand; log calls or emails in its notes")
    attempts = [_call_attempt(c) for c in db.calls_for_listing(search_id, key)]
    for e in db.emails_for_listing(search_id, key):
        if e["status"] == "sent":
            attempts.append(Attempt("email", e["sent_at"] or e["created_at"], "Emailed", "wait"))
        elif e["status"] == "failed":
            attempts.append(Attempt("email", e["created_at"], "Email failed to send", "bad"))
        else:
            attempts.append(Attempt("email", e["created_at"], "Draft waiting for your approval", "wait"))
    attempts.sort(key=lambda a: a.when)
    contacts = [a for a in attempts if a.result != "Draft waiting for your approval"]
    last = contacts[-1] if contacts else None

    if not attempts:
        return Outreach("new", "Not contacted yet", attempts)
    if any(a.tone == "good" for a in attempts):
        return Outreach("action", "They said it's available: book a viewing", attempts,
                        last.when if last else None)
    latest = attempts[-1]
    if latest.result == "Draft waiting for your approval":
        return Outreach("action", "Approve your email draft", attempts, last.when if last else None)
    if latest.result == "Reached them: not a fit":
        return Outreach("action", "Call says it's not a fit: consider removing", attempts, latest.when)
    if latest.result == "Calling now":
        return Outreach("waiting", "Call in progress", attempts, latest.when)
    if latest.kind == "email":
        return Outreach("waiting", "Emailed, waiting for a reply", attempts, latest.when)
    return Outreach("waiting", f"{latest.result}, no response yet", attempts, latest.when)


def drop(app_id: int, reason: str, detail: str = "") -> None:
    row = db.get_application(app_id)
    label = DROP_REASONS.get(reason, "Other")
    line = f"Removed from leads {datetime.now():%b %-d}: {label}" + (f" ({detail.strip()})" if detail.strip() else "")
    notes = f"{row['notes']}\n{line}" if row["notes"] else line
    db.update_application(app_id, stage="withdrawn", notes=notes)


def restore(app_id: int) -> None:
    db.update_application(app_id, stage="interested")

"""Where the renter needs to step in: one list the app, the sidebar, and phone briefings share."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from househunt import db, leads

URGENT, TODO, FYI = "urgent", "todo", "fyi"
_ORDER = {URGENT: 0, TODO: 1, FYI: 2}


@dataclass
class Flag:
    severity: str
    title: str
    detail: str
    href: str
    action: str

    @property
    def spoken(self) -> str:
        return f"{self.title}. {self.detail}"


def _when(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return d.strftime("%a %b %-d at %-I:%M %p") if "T" in iso else d.strftime("%a %b %-d")


def _system_flags() -> list[Flag]:
    out = []
    recent = db.all_calls()[:5]
    errors = " ".join(c["error"] or "" for c in recent if c["status"] == "failed")
    if "credit balance is too low" in errors:
        out.append(Flag(URGENT, "Claude is out of API credits",
                        "Call summaries, email drafts and the agent chat fail until you add credits "
                        "in the Anthropic Console under Plans & Billing.",
                        "https://console.anthropic.com/settings/billing", "Add credits"))
    for row in db.list_searches()[:5]:
        if row["status"] == "error":
            city = json.loads(row["criteria"]).get("city", "")
            out.append(Flag(URGENT, f"Your {city} search hit an error",
                            (row["error"] or "")[:160], f"/searches/{row['id']}", "Open search"))
    return out


def compute() -> list[Flag]:
    now = datetime.now()
    flags = _system_flags()

    for call in db.inbound_calls(unhandled_only=True):
        listing = db.get_listing(call["search_id"], call["listing_key"]) if call["listing_key"] else None
        about = f" about {listing.title}" if listing else ""
        flags.append(Flag(URGENT, f"{call['caller'] or 'Someone'} called back{about}",
                          "They called your KeyHunt number and left a message with your agent.",
                          f"/phone#call-{call['id']}", "Hear what they said"))

    for e in db.draft_emails():
        listing = db.get_listing(e["search_id"], e["listing_key"])
        flags.append(Flag(TODO, f"Approve your email about {listing.title if listing else 'a listing'}",
                          "It's drafted and waiting; nothing sends until you approve it.",
                          f"/emails/{e['id']}", "Review draft"))

    tours = {(t["search_id"], t["listing_key"]) for t in db.all_tours()}
    for a in db.list_applications():
        stage, title = a["stage"], a["title"]
        if stage == "interested" and a["search_id"]:
            sid, key = a["search_id"], a["listing_key"]
            call = db.calls_for_search(sid).get(key)
            outcome = json.loads(call["outcome"]) if call and call["outcome"] else None
            if outcome and outcome.get("viable") and (sid, key) not in tours:
                times = outcome.get("offered_times") or []
                flags.append(Flag(URGENT, f"{title} is available: book a viewing",
                                  f"They offered {', '.join(times[:3])}." if times else
                                  "They confirmed it's available but no time was set.",
                                  f"/leads#lead-{a['id']}", "Book it"))
                continue
            o = leads.outreach(sid, key)
            if o.status == "waiting" and (o.days_since or 0) >= 5:
                flags.append(Flag(FYI, f"No response from {title} in {o.days_since} days",
                                  "Follow up another way, or remove it from your leads.",
                                  f"/leads#lead-{a['id']}", "Decide"))
        if a["next_date"] and stage not in ("rejected", "withdrawn", "lease_signed"):
            try:
                due = datetime.fromisoformat(a["next_date"])
            except ValueError:
                continue
            if due < now and stage != "viewing":
                flags.append(Flag(TODO, f"Overdue: {a['next_step'] or 'next step'} for {title}",
                                  f"It was due {_when(a['next_date'])}.",
                                  f"/applications#app-{a['id']}", "Update"))

    for t in db.all_tours():
        try:
            start = datetime.fromisoformat(t["start"])
        except ValueError:
            continue
        if now <= start <= now + timedelta(hours=48):
            listing = db.get_listing(t["search_id"], t["listing_key"])
            flags.append(Flag(TODO, f"Viewing {_when(t['start'])}: {listing.title if listing else 'a place'}",
                              f"{t['address'] or 'Check the address'}. Bring ID and proof of income.",
                              "/viewings", "Prep"))

    flags.sort(key=lambda f: _ORDER[f.severity])
    return flags

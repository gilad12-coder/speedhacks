"""Spoken status briefings: what a phone agent tells the renter about their search."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from househunt import db, flags, leads
from househunt.config import settings
from househunt.models import ListingStatus

STAGE_NAMES = {"interested": "interested", "viewing": "viewing booked", "viewed": "viewed",
               "applied": "applied", "approved": "approved", "lease_signed": "lease signed"}


def _when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%A %B %-d at %-I:%M %p")
    except ValueError:
        return iso


def facts() -> str:
    """Plain facts about the search right now, written to be read aloud."""
    now = datetime.now().astimezone()
    lines = [f"Status as of {now:%A %B %-d, %-I:%M %p}."]

    searches = db.list_searches()
    if not searches:
        return lines[0] + " There are no searches yet."
    active = searches[:3]
    for row in active:
        c = json.loads(row["criteria"])
        listings = db.list_listings(row["id"])
        matching = [l for l in listings if l.status != ListingStatus.FILTERED_OUT]
        good = [l for l in listings if l.status in (ListingStatus.VIABLE, ListingStatus.TOUR_SCHEDULED)]
        lines.append(f"Search in {c['city']} up to ${c['max_price']} a month, {c['min_beds']}+ bedrooms: "
                     f"{len(listings)} places found, {len(matching)} match, "
                     f"{len(db.calls_for_search(row['id']))} called, {len(good)} confirmed available.")

    apps = db.list_applications()
    board = {}
    for a in apps:
        board.setdefault(a["stage"], []).append(a)
    if apps:
        lines.append("Board: " + ", ".join(f"{len(v)} {STAGE_NAMES[k]}" for k, v in board.items()
                                          if k in STAGE_NAMES) + ".")

    upcoming = []
    for t in db.all_tours():
        try:
            start = datetime.fromisoformat(t["start"])
            if start.tzinfo is None:
                start = start.astimezone()
        except ValueError:
            continue
        if now <= start <= now + timedelta(days=7):
            l = db.get_listing(t["search_id"], t["listing_key"])
            upcoming.append(f"{l.title if l else 'a place'} on {_when(t['start'])}"
                            + (f" at {t['address']}" if t["address"] else ""))
    lines.append("Viewings this week: " + ("; ".join(upcoming) if upcoming else "none") + ".")

    lead_lines = []
    for a in board.get("interested", [])[:6]:
        o = leads.outreach(a["search_id"], a["listing_key"])
        price = f", ${a['price']} a month" if a["price"] else ""
        lead_lines.append(f"{a['title']}{price}: {o.label}")
    lines.append("Leads: " + ("; ".join(lead_lines) if lead_lines else "none yet") + ".")

    for stage in ("applied", "approved"):
        for a in board.get(stage, []):
            nxt = f", next step {a['next_step']}" if a["next_step"] else ""
            lines.append(f"Application {STAGE_NAMES[stage]}: {a['title']}{nxt}.")

    needs = flags.compute()
    if needs:
        lines.append(f"Needs the renter's attention ({len(needs)}): "
                     + " ".join(f"{i}. {f.spoken}" for i, f in enumerate(needs[:6], 1)))
    else:
        lines.append("Nothing needs the renter's attention right now.")
    return "\n".join(lines)


_STYLE = (
    "Speak naturally and briefly, like a sharp assistant giving a quick update. Lead with what "
    "needs their attention, then viewings, then leads, then everything else. Round numbers, skip "
    "URLs and IDs, and don't read lists word for word. After the highlights, ask if they want "
    "detail on any place. Answer only from the facts below; if you don't know, say it's in the "
    "KeyHunt app. If they ask you to do something (call a landlord, book a viewing, drop a "
    "lead), say you've noted it and they can tap it in the app. Keep the call under four minutes."
)


def outbound_instruction() -> str:
    name = "the renter"
    return "\n".join([
        f"You are calling {name} with an update from KeyHunt, the app running their rental "
        "search. You are an AI assistant; say so when you introduce yourself.",
        _STYLE, "", "FACTS:", facts(),
    ])


def _callback_rules(name: str) -> str:
    return (
        "Anyone else is most likely a landlord, agent or property manager returning a call about "
        f"a rental listing. Thank them, say you're {name}'s assistant (an AI), and take a message: "
        "which listing or address they're calling about, whether it's available, rent and move-in "
        "costs if they mention them, viewing times they can offer, and the best way to reach them. "
        f"Say {name} will get back to them soon. Never share anything about {name} or their search, "
        "and never confirm or reveal any passcode."
    )


def message_taker_instruction() -> str:
    """Inbound behavior without a briefing: just take messages from people calling back."""
    name = "the renter"
    return "\n".join([
        f"You answer calls to the KeyHunt line for {name}, who is looking for a rental.",
        "Greet the caller: \"Hi, you've reached KeyHunt, the rental assistant. Who's calling?\"",
        _callback_rules(name),
    ])


def inbound_instruction() -> str:
    """What the KeyHunt number's agent does when anyone calls it. The same number calls
    landlords, so callers are either the renter (with the passcode) or someone calling back."""
    name = "the renter"
    pin = settings.briefing_pin
    callback = _callback_rules(name)
    if not pin:
        return message_taker_instruction()
    return "\n".join([
        f"You answer calls to the KeyHunt line for {name}, who is looking for a rental. "
        "Greet the caller: \"Hi, you've reached KeyHunt. Who's calling?\"",
        "",
        f"If the caller says they are {name}, ask for their passcode. The passcode is "
        f"{' '.join(pin)}. If they say it correctly, give them their update using the facts below. "
        "If it's wrong, let them try once more, then treat them as any other caller. Never say the "
        "passcode out loud or hint at it.",
        "",
        callback,
        "",
        f"How to give {name} their update: {_STYLE}",
        "",
        f"FACTS (only for {name}, after the passcode):",
        facts(),
    ])

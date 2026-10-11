"""The renter's AI agent: a chat per place, plus one general chat about the whole search.

Each chat is stored as the exact message list sent to Claude, append-only, so thinking
blocks and prompt caching stay valid across turns. Before a turn, the agent gets a fresh
snapshot of what KeyHunt knows (listing, call transcript, viewing, application, notes) as a
mid-conversation system message, added only when the snapshot changed. The agent can save
notes about a place; voice calls to that place read the same notes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import anthropic

from househunt import db, llm
from househunt.config import settings

log = logging.getLogger(__name__)

SYSTEM = """You are the renter's agent inside KeyHunt, an app that finds rentals, calls \
landlords and agents with an AI voice assistant, books viewings, and tracks applications.

You're chatting with the renter. Help them think clearly about places and about their search: \
what a call revealed, red flags, tradeoffs against their criteria, what to ask next, and \
whether a place is worth pursuing. Be direct and practical. Say what you'd do and why, and \
flag uncertainty instead of papering over it.

Ground everything in the KeyHunt context you're given (listing details, call transcripts, \
notes). Never invent facts about a place; if something isn't known, say so and suggest how to \
find out (for example, raising it on the next call).

Notes: when the renter shares a concern, an open question, a preference, or a fact about a \
place worth remembering, save it with save_note as one short line, written so a voice agent \
calling the landlord could act on it (e.g. "Ask whether parking is included in the rent"). \
Don't save things that are already in the notes. Mention briefly when you've saved one. The \
next call to that place will bring up open notes.

Keep replies conversational and reasonably short; use a short list when comparing several \
things."""

PLACE_TOOL = {
    "name": "save_note",
    "description": "Save a short note about this place: a concern, open question, preference, or "
                   "fact. Notes show on the place's card and are raised on the next call.",
    "strict": True,
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "properties": {"note": {"type": "string", "description": "One short line."}},
        "required": ["note"],
        "additionalProperties": False,
    },
}

GENERAL_TOOL = {
    **PLACE_TOOL,
    "description": "Save a short note about one place from the context, identified by its "
                   "place_id (shown as [place_id] in the context). Notes show on the place's "
                   "card and are raised on the next call.",
    "input_schema": {
        "type": "object",
        "properties": {
            "place_id": {"type": "string", "description": "The [place_id] from the context."},
            "note": {"type": "string", "description": "One short line."},
        },
        "required": ["place_id", "note"],
        "additionalProperties": False,
    },
}

# Fallbacks route around a refused request; only these models accept the "default" form.
# --- context -----------------------------------------------------------------

def _criteria_line(c) -> str:
    bits = [f"{c.city}", f"${c.min_price}-${c.max_price}/mo", f"{c.min_beds}+ bd"]
    if c.neighborhoods:
        bits.append("areas: " + ", ".join(c.neighborhoods))
    if c.must_haves:
        bits.append("must-haves: " + ", ".join(c.must_haves))
    if c.move_in_by:
        bits.append(f"move in by {c.move_in_by}")
    if c.tour_availability:
        bits.append("free for viewings: " + "; ".join(c.tour_availability))
    return " · ".join(bits)


def place_context(search_id: int, key: str, full: bool = True) -> str:
    found = db.get_search(search_id)
    listing = db.get_listing(search_id, key)
    if not (found and listing):
        return "This place is no longer in KeyHunt."
    criteria, _ = found
    l = listing
    lines = [f"[{search_id}/{key}] {l.title}",
             f"Source: {l.source.value} · {l.url}",
             f"Rent: {'$%s/mo' % l.price if l.price else 'unknown'} · "
             f"{l.beds if l.beds is not None else '?'} bd · {l.baths if l.baths is not None else '?'} ba"
             + (f" · {l.sqft} sqft" if l.sqft else ""),
             f"Status in KeyHunt: {l.status.value.replace('_', ' ')}"]
    if l.address or l.neighborhood:
        lines.append(f"Location: {', '.join(x for x in [l.address, l.neighborhood] if x)}")
    if l.contact and (l.contact.name or l.contact.phone or l.contact.email):
        lines.append("Contact: " + " ".join(x for x in [l.contact.name, l.contact.phone,
                                                         l.contact.email] if x))
    if full and l.description:
        lines.append(f"Listing description: {l.description[:2000]}")
    call = db.calls_for_search(search_id).get(key)
    if call:
        lines.append(f"Latest call: {call['status']}")
        if call["outcome"]:
            o = json.loads(call["outcome"])
            lines.append(f"Call summary: {o.get('summary')}")
            if o.get("tradeoffs"):
                lines.append("Tradeoffs noted: " + "; ".join(o["tradeoffs"]))
        if full and call["transcript"]:
            lines.append("Call transcript:\n" + call["transcript"][:6000])
    tour = db.tours_for_search(search_id).get(key)
    if tour:
        lines.append(f"Viewing booked: {tour['start']}")
    app = db.find_application(search_id, key)
    if app:
        lines.append(f"Application board: {app['stage'].replace('_', ' ')}"
                     + (f"; next: {app['next_step']} {app['next_date'] or ''}" if app["next_step"] else "")
                     + (f"; board notes: {app['notes']}" if app["notes"] else ""))
    notes = db.place_notes(search_id, key)
    lines.append("Saved notes:" + ("".join(f"\n- {n}" for n in notes) if notes else " none yet"))
    if full:
        lines.append(f"Renter's search criteria: {_criteria_line(criteria)}")
    return "\n".join(lines)


def general_context() -> str:
    out = []
    for row in db.list_searches()[:5]:
        criteria, _ = db.get_search(row["id"])
        out.append(f"Search #{row['id']} ({row['status']}): {_criteria_line(criteria)}")
        listings = [l for l in db.list_listings(row["id"]) if l.status.value != "filtered"]
        for l in listings[:15]:
            out.append("  " + place_context(row["id"], l.key, full=False).replace("\n", "\n  "))
    apps = [a for a in db.list_applications() if not a["search_id"]]
    if apps:
        out.append("Places tracked outside a search: " + "; ".join(
            f"{a['title']} ({a['stage'].replace('_', ' ')})" for a in apps))
    return "\n".join(out) or "No searches yet."


def context_for(chat) -> str:
    body = (place_context(chat["search_id"], chat["listing_key"]) if chat["listing_key"]
            else general_context())
    return "Current KeyHunt context (refreshed; supersedes earlier snapshots):\n\n" + body


# --- tools -------------------------------------------------------------------

def _run_tool(chat, block) -> tuple[str, bool, dict | None]:
    """Returns (result text, is_error, saved note event)."""
    args = block.input if isinstance(block.input, dict) else {}
    note = args.get("note")
    if block.name != "save_note" or not isinstance(note, str) or not note.strip() or len(note) > 400:
        return "Invalid input: pass a non-empty note under 400 characters.", True, None
    if chat["listing_key"]:
        sid, key = chat["search_id"], chat["listing_key"]
    else:
        sid_key = str(args.get("place_id", ""))
        sid_str, _, key = sid_key.partition("/")
        if not (sid_str.isdigit() and db.get_listing(int(sid_str), key)):
            return f"Unknown place_id {sid_key!r}; use one shown as [place_id] in the context.", True, None
        sid = int(sid_str)
    added = db.add_place_note(sid, key, note)
    listing = db.get_listing(sid, key)
    event = {"t": "note", "v": note.strip(), "place": listing.title if listing else key,
             "search_id": sid, "key": key} if added else None
    return ("Saved." if added else "Already in the notes."), False, event


# --- the turn ----------------------------------------------------------------

def respond(chat_id: int, user_text: str) -> Iterator[dict]:
    """Store the user's message, then stream the agent's reply as events:
    {"t": "text", "v": str} chunks, {"t": "note", ...} when a note is saved,
    {"t": "error", "v": str}, and finally {"t": "done"}."""
    try:
        yield from _respond(chat_id, user_text)
    finally:  # also runs if the browser disconnects mid-reply
        _close_turn(chat_id)


def _respond(chat_id: int, user_text: str) -> Iterator[dict]:
    chat = db.get_chat(chat_id)
    db.add_chat_message(chat_id, "user", [{"type": "text", "text": user_text}], user_text)

    # Refresh the context snapshot when it changed. A system message has to follow a user
    # message, so it goes right after the one we just stored.
    snapshot = context_for(chat)
    last = next((r for r in reversed(db.chat_messages(chat_id)) if r["role"] == "system"), None)
    if not last or json.loads(last["content"]) != snapshot:
        db.add_chat_message(chat_id, "system", snapshot, None)

    if not llm.has_credentials():
        yield {"t": "error", "v": "The agent needs an Anthropic API key. Add ANTHROPIC_API_KEY to "
                                  ".env and restart KeyHunt."}
        _close_turn(chat_id)
        yield {"t": "done"}
        return

    client = llm.client()
    tools = [PLACE_TOOL if chat["listing_key"] else GENERAL_TOOL]
    extra = ({"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
             if settings.claude_model in llm.FALLBACK_MODELS else {})
    try:
        for _ in range(6):  # a few tool round-trips at most
            messages = [{"role": r["role"], "content": json.loads(r["content"])}
                        for r in db.chat_messages(chat_id)]
            with client.beta.messages.stream(
                model=settings.claude_model,
                max_tokens=16000,
                system=SYSTEM,
                messages=messages,
                tools=tools,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                cache_control={"type": "ephemeral"},
                **extra,
            ) as stream:
                for text in stream.text_stream:
                    yield {"t": "text", "v": text}
                final = stream.get_final_message()

            text = "".join(b.text for b in final.content if b.type == "text")
            db.add_chat_message(chat_id, "assistant", [b.to_dict() for b in final.content],
                                text or None)
            if final.stop_reason == "refusal":
                yield {"t": "error", "v": "The agent couldn't help with that one. Try rephrasing."}
                break
            if final.stop_reason != "tool_use":
                break
            results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue
                result, is_error, event = _run_tool(chat, block)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": result, "is_error": is_error})
                if event:
                    yield event
            db.add_chat_message(chat_id, "user", results, None)
            yield {"t": "text", "v": "\n\n"}
    except anthropic.APIStatusError as e:
        log.exception("chat %s failed", chat_id)
        body = e.body if isinstance(e.body, dict) else {}
        detail = (body.get("error") or {}).get("message") or e.message
        yield {"t": "error", "v": f"The agent couldn't reply: {detail}"}
    except anthropic.APIConnectionError:
        yield {"t": "error", "v": "Couldn't reach the agent. Check your connection and try again."}
    _close_turn(chat_id)
    yield {"t": "done"}


def _close_turn(chat_id: int) -> None:
    """If a turn ended without an assistant message (error, no key), record a placeholder so
    the stored history stays valid: a system message must be followed by an assistant turn."""
    rows = db.chat_messages(chat_id)
    if rows and rows[-1]["role"] != "assistant":
        db.add_chat_message(chat_id, "assistant",
                            [{"type": "text", "text": "(No reply: the request failed.)"}], None)

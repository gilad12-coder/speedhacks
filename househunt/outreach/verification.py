"""Evidence extraction contract. Provider output is untrusted until checked here."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from househunt.models import SearchCriteria


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Ref(StrictModel):
    turn_index: int = Field(ge=0)
    quote: str = Field(min_length=1)


class Fact(StrictModel):
    key: str
    passed: bool | None
    summary: str
    evidence: list[Ref]


class Amount(StrictModel):
    value: int = Field(gt=0)
    evidence: Ref


class Detail(StrictModel):
    name: str
    value: str
    evidence: Ref


class Window(StrictModel):
    start: str
    end: str
    evidence: list[Ref] = Field(min_length=1)


class Assessment(StrictModel):
    reached_person: bool
    voicemail: bool
    do_not_call: Ref | None
    facts: list[Fact]
    monthly_rent: Amount | None
    details: list[Detail]
    tour_offers: list[Window]


class Evidence(StrictModel):
    callId: str
    t: float
    quote: str


class Check(StrictModel):
    kind: Literal["real", "matches", "fit", "tour"]
    passed: bool | None
    summary: str
    evidence: Evidence | None


def requirements(c: SearchCriteria) -> list[dict]:
    result = [
        {"key": "available", "group": "real", "question": "Is this exact rental still available, and are you the landlord or authorized agent?"},
        {"key": "rent", "group": "matches", "question": f"What is the actual total monthly rent? Budget: ${c.min_price}–${c.max_price}."},
        {"key": "qualifications", "group": "fit", "question": "What income, credit, guarantor and application requirements apply? The renter's financial eligibility is unknown; do not assume it."},
    ]
    if c.min_beds:
        result.append({"key": "beds", "group": "matches", "question": f"Are there at least {c.min_beds} bedrooms?"})
    if c.min_baths:
        result.append({"key": "baths", "group": "matches", "question": f"Are there at least {c.min_baths} bathrooms?"})
    if c.move_in_by:
        result.append({"key": "move_in", "group": "matches", "question": f"Can the tenancy start by {c.move_in_by}?"})
    if c.occupants:
        result.append({"key": "occupancy", "group": "fit", "question": f"Can {c.occupants} housemates rent and occupy the unit?"})
    result.extend({"key": f"must:{i}", "group": "matches", "question": f"Required: {item}. Please confirm."} for i, item in enumerate(c.must_haves))
    result.extend({"key": f"avoid:{i}", "group": "matches", "question": f"Deal-breaker to avoid: {item}. Confirm this is NOT present."} for i, item in enumerate(c.deal_breakers))
    if c.move_in_from and c.move_in_by:
        result.append({"key":"move_window", "group":"matches", "question":f"Can the tenancy start between {c.move_in_from} and {c.move_in_by}?"})
    return result


def timed_turns(raw: dict) -> list[dict]:
    result = []
    for t in raw.get("transcriptTurns") or []:
        offset = t.get("startMs")
        if t.get("speaker") not in ("agent", "user", "contact") or not isinstance(offset, (int, float)) or offset < 0 or not t.get("text", "").strip():
            continue
        result.append({"t": offset / 1000, "speaker": "agent" if t["speaker"] == "agent" else "contact", "text": t["text"]})
    return result


def validate_assessment(a: Assessment, turns: list[dict], criteria: SearchCriteria, call_id: str, started_at: datetime) -> dict:
    def valid(ref: Ref) -> bool:
        return (ref.turn_index < len(turns) and turns[ref.turn_index]["speaker"] == "contact"
                and bool(ref.quote.strip()) and ref.quote in turns[ref.turn_index]["text"])

    def cite(ref: Ref) -> Evidence:
        return Evidence(callId=call_id, t=turns[ref.turn_index]["t"], quote=ref.quote)

    expected = requirements(criteria)
    allowed = {r["key"] for r in expected}
    facts = {}
    for fact in a.facts:
        if fact.key not in allowed or fact.key in facts:
            raise ValueError("Unexpected or duplicate extracted requirement")
        if fact.passed is not None and (not fact.evidence or not all(valid(r) for r in fact.evidence)):
            fact = Fact(key=fact.key, passed=None, summary="Not confirmed on the call", evidence=[])
        facts[fact.key] = fact
    amount = a.monthly_rent if a.monthly_rent and valid(a.monthly_rent.evidence) else None
    facts["rent"] = Fact(key="rent", passed=criteria.min_price <= amount.value <= criteria.max_price if amount else None,
                         summary=f"Contact stated ${amount.value}/month" if amount else "Monthly rent not confirmed",
                         evidence=[amount.evidence] if amount else [])
    answered = a.reached_person and not a.voicemail
    checks = []
    for group in ("real", "matches", "fit"):
        group_facts = [facts.get(r["key"]) for r in expected if r["group"] == group]
        failed = next((f for f in group_facts if f and f.passed is False), None)
        passed = None if not answered else False if failed else True if all(f and f.passed is True for f in group_facts) else None
        supporting = failed or next((f for f in group_facts if f and f.passed is True), None)
        checks.append(Check(kind=group, passed=passed,
                            summary="Not fully confirmed on the call" if passed is None else "; ".join(f.summary for f in group_facts if f and f.passed == passed),
                            evidence=cite(supporting.evidence[0]) if passed is not None and supporting and supporting.evidence else None))
    failed = any(c.passed is False for c in checks)
    windows, refs = [], []
    for offer in a.tour_offers:
        try:
            start, end = datetime.fromisoformat(offer.start), datetime.fromisoformat(offer.end)
            valid_time = start.utcoffset() is not None and end.utcoffset() is not None and start > started_at and 0 < (end-start).total_seconds() <= 86400
        except (ValueError, TypeError):
            valid_time = False
        if answered and not failed and valid_time and all(valid(r) for r in offer.evidence):
            windows.append({"start": offer.start, "end": offer.end})
            refs.append(offer.evidence[0])
    checks.append(Check(kind="tour", passed=True if windows else None,
                        summary="Viewing offered; household must confirm separately" if windows else "No concrete viewing window confirmed",
                        evidence=cite(refs[0]) if refs else None))
    verified = all(c.passed is True for c in checks[:3])
    return {"checks": checks, "facts": facts, "monthly_rent": amount.value if answered and amount else None,
            "confirmed_facts": [{"key": f.key, "summary": f.summary, "passed": f.passed,
                                  "evidence": [cite(r).model_dump() for r in f.evidence]}
                                 for f in facts.values() if answered and f.passed is not None and f.evidence and all(valid(r) for r in f.evidence)],
            "details": {d.name: d.value for d in a.details if answered and valid(d.evidence)},
            "offered_windows": windows, "do_not_call": bool(a.do_not_call and valid(a.do_not_call)),
            "verification_status": "verified" if verified else "ruled_out" if failed else "unconfirmed"}

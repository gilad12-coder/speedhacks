# Design Brief: Keyhunt

Source: "Perlie 2" mentor conversation, 2026-10-11. Shaped with /shape.

## 1. Feature Summary
A web app where a group of housemates looking for a San Francisco "hacker house" each enter their constraints. An agent then finds listings across the web, phones the landlords and brokers, and returns a short list of places that are verified by phone. The output replaces weeks of scrolling, scam-dodging and cold calls with a handful of real options that already have tours offered.

## 2. Primary User Action
Read the verified shortlist and trust it: for each place, see *why* it made the cut (call evidence) and accept a tour slot.

## 3. Design Direction
Calm, trustworthy concierge. Quiet surfaces, generous whitespace, one confident accent. Evidence comes first: every claim ("available", "allows 4 occupants", "open to $X household income") links to the moment in the call that confirmed it. Not mission-control flashiness and not playful. The work feels done for you, carefully.

Design context (personality, colors, theme, principles) lives in `.impeccable.md`.

## 4. Layout Strategy
Desktop dashboard, three stages read left to right or top to bottom as one story:
1. **Household**: the merged brief (budget, commute anchor, must-haves, move-in date), plus any conflicts the agent found between housemates.
2. **Pipeline**: a compact funnel (found → called → verified → tour offered) with counts. Dropped listings collapse into a quiet "Ruled out (n)" with reasons such as scam, taken, or not a fit.
3. **Shortlist** (hero, most space): 3–7 ranked places, each a decision row rather than a photo card. It shows price, commute time, the four verification checks, the proposed tour slot and a "Hear the call" control that opens the recording and transcript at the right timestamp.

## 5. Key States
- **Invite / empty household**: one housemate has joined, and the page shows who's missing and a share link.
- **Intake in progress**: per-housemate completion, nothing searched yet.
- **Conflict**: preferences clash (budget spread, pets vs. no pets). The agent shows the tension plainly and asks the group to resolve it (the "realistically you said X" expectation-setting).
- **Searching / calling**: pipeline counts move, the latest finished call surfaces, no fake spinners.
- **Shortlist ready**: hero state.
- **Thin results**: fewer than 3 verified places. Say so honestly and suggest which constraint to loosen.
- **Ruled out**: reasons visible on demand, never hidden.
- **Call failed / no answer**: the listing stays "unverified", and only then is it shown as such.

## 6. Interaction Model
Housemate opens a share link → fills a short form and connects their Google Calendar → sees the merged household brief → the group confirms → the agent runs (calls are made beforehand through Dial and replayed from its recordings and transcripts) → shortlist appears → clicking a check (✓ real, ✓ matches, ✓ we fit, ✓ tour slot) jumps to the transcript line and audio that proves it → "Accept tour" creates a Google Calendar event for every housemate.

## 7. Content Requirements
- Intake fields: name, max personal budget, commute destination + mode (e.g. Caltrain to the South Bay), must-haves / deal-breakers (pets, parking, laundry), nice-to-haves (gym, nightlife), move-in window, Google Calendar connection (replaces typing in viewing availability), income band (for tenant fit).
- Verification labels: "Real & available", "Matches your must-haves", "You fit what they're looking for", "Tour offered".
- Ruled-out reasons: "Looks like a scam", "Already taken", "Wants a different tenant", "Breaks a must-have", "No answer".
- Realistic ranges: 2–6 housemates; ~20–60 listings found; ~10–20 called; 3–7 shortlisted.
- Honest copy for thin results and conflicts; never "Verified" without evidence.

## 8. Recommended References
`interaction-design.md` (multi-person intake form, conflict handling), `spatial-design.md` (funnel + shortlist hierarchy), `typography.md` (quiet, dense decision rows), `motion-design.md` (only for pipeline counts and call reveals; keep motion restrained).

## 9. Decisions (resolved 2026-10-11)
- **Name**: Keyhunt.
- **Calling**: Dial handles outbound calls, recording and transcripts. Demo calls are placed beforehand with Dial and replayed from its recordings and transcripts.
- **Sourcing**: hybrid. A prepared set of real SF listings drives the demo, plus one live browser-agent search as proof it works.
- **Email**: parked with negotiation; v1 is phone-only.
- **Speed**: pitch talking point only, not shown in the product.
- **Housemate conflicts**: flag and suggest a compromise; the group decides.
- **Accept tour**: creates a real Google Calendar event for every housemate.
- **Live search source**: any relevant listings site without a public API (that is the point: the browser agent reaches what an API can't). Pick the site at build time; keep the demo run to one light search, since many such sites forbid automated access in their terms.
- **Calendar auth**: each housemate connects their own Google Calendar during intake. Keyhunt reads everyone's free time, only offers tour slots the whole group can make, and writes the accepted tour to each calendar.
- Parked for later: email outreach, follow-ups, lease review, negotiation.

## 10. Open Questions
None. All questions resolved 2026-10-11.

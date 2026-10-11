# Keyhunt: who builds what

Three parts, four workstreams. They meet only at `lib/types.ts`, so everyone builds in parallel against mock data from day one and swaps in the real thing later.

| Part | Owner | Builds | Hands off |
|---|---|---|---|
| 1. App & UI | Gilad | Next.js + Tailwind app, every screen in `docs/design-brief.md`, styled per `.impeccable.md` | — |
| 2a. Find | Lucy (@lucywu12) | Listings for the demo + one live browser search | `Listing[]` |
| 2b. Call | @reedyalouh2 | Dial calls, recordings, transcripts → four checks with timestamps | `Call[]`, `Check[]`, `OfferedWindow[]` |
| 3. Household & Calendar | Gilad | Households, invites, preference merge + conflicts, Google Calendar, deploy | `Household`, `SearchBrief`, `TourSlot` |

```
Part 3 ──SearchBrief──▶ Part 2a ──Listing[]──▶ Part 2b ──AgentRun──▶ Part 3 ──▶ Part 1 (UI)
```

## 1. App & UI (Gilad)
- Scaffold Next.js + Tailwind on Vercel; design tokens from `.impeccable.md`.
- Screens: invite/share page, intake form, household brief + conflicts, pipeline funnel + "Ruled out (n)", shortlist rows with the four checks, "Hear the call" player that jumps to the transcript line.
- Every state in brief §5: empty household, intake in progress, conflict, searching, ready, thin results, call failed.
- Build on `mocks/agent-run.json` until Part 2 delivers.

## 2a. Find (Lucy)
- Curate 20–60 real SF listings that fit a demo household, as `Listing[]` with `status: "found"`, photos and a callable contact.
- One live browser-agent search on a site without a public API. Keep it to one light run (terms of service).
- Compute `commuteMinutes` to the brief's destination.
- Filter obvious misses before calling (budget, size, deal-breakers) and mark them `ruled_out` with a reason.

## 2b. Call (@reedyalouh2)
- Dial: place outbound calls to 10–20 contacts, fetch recording + transcript, map to `Call`.
- Call script: confirm availability, occupancy limit, tenant requirements, and ask for tour times.
- Transcript → `Check[]` with an LLM: each passed check must cite `{callId, t, quote}`; anything unconfirmed is `passed: null`.
- Extract offered tour times as `OfferedWindow[]`; set `ruled_out` reasons (scam, taken, wrong tenant, no answer).
- Calls are placed before the demo and replayed; output a full `AgentRun` JSON.

## 3. Household & Calendar (Gilad)
- Store households and housemates; share link joins a household.
- Merge preferences into a `SearchBrief`; detect `Conflict`s with a suggested compromise.
- Google OAuth per housemate (calendar scope); free/busy across the group intersected with `OfferedWindow[]` → proposed `TourSlot`s.
- "Accept tour" writes an event to every housemate's calendar.
- Vercel project, env vars (Dial key, Google client), deploy.

## Rules
- First task for everyone: agree on `lib/types.ts`. After that, change it only by PR and tag the other owners.
- Part 2 commits `mocks/agent-run.json` early (even hand-written) so Part 1 isn't blocked.
- Work on branches, one PR per issue; never push to `main`.

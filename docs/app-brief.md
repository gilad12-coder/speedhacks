# Design Brief: Keyhunt App & UI (Part 1, issue #2)

Builds on `docs/design-brief.md` (product), `lib/types.ts` (data) and `.impeccable.md` (look and feel). Shaped with /shape, 2026-10-11.

## 1. Feature Summary
The Next.js + Tailwind front end for Keyhunt: a join page where each housemate fills in their constraints, and one household dashboard that tells the whole story from merged brief to verified shortlist. It is the real product, not a demo: households and intake are stored, calendars are connected for real, and the dashboard shows whatever the agent (Part 2) has actually produced. Demo-only behavior (replay, sample household) is parked in `docs/demo-notes.md`.

## 2. Primary User Action
On the dashboard: read the shortlist, open a place's call evidence, and accept a tour.

## 3. Design Direction
Calm concierge per `.impeccable.md`: warm off-white, warm greys, one deep evergreen accent, Airbnb-like warmth without Airbnb's brand. Operate mode: scanability first, brand in the details. Desktop only in v1; no mobile layouts, but nothing should break below 1024px.

## 4. Layout Strategy
**Routes**
- `/join/[code]`: single-column intake form, one housemate at a time.
- `/h/[id]`: the household dashboard, one scrolling page in three stacked sections.
- Call evidence opens in a right-hand side panel over the dashboard (URL keeps `?listing=` so it's linkable).

**Dashboard hierarchy**
1. **Household** (compact band): housemate chips with intake/calendar status, the merged brief (combined budget, commute, must-haves, move-in window), and conflict cards with Keyhunt's suggested compromise.
2. **Pipeline** (thin): four counts, found → called → verified → tour offered, plus a collapsed "Ruled out (n)" with one-line reasons.
3. **Shortlist** (hero, most space): 3–7 ranked decision rows. Each row: photo thumbnail, address + neighborhood, rent (total and per person), commute minutes, the four checks, proposed tour slot, "Hear the call", "Accept tour".

**Side panel**: listing summary, audio player, full transcript. Clicking a check scrolls to and highlights its quoted line and seeks the audio to `t`.

## 5. Key States
| State | What shows |
|---|---|
| Waiting for housemates | Chips show who's in; missing ones dimmed; copy-link button; Start disabled with the reason |
| Intake in progress | Per-housemate done / calendar connected |
| Conflict | Conflict card names who wants what and the suggestion; Start waits until the group confirms |
| Ready to search | Merged brief + "Start search" |
| Searching | Live progress from the agent run (`finishedAt: null`): counts update as results arrive, the latest finished call appears as a one-line update, shortlist rows appear as they verify; no fake spinners or invented progress |
| Agent unavailable | Search can't start or stalls: say so plainly, keep the brief, offer retry |
| Shortlist ready | Hero state |
| Thin results (< 3) | Honest note naming the constraint most worth loosening |
| Unconfirmed check | `passed: null` renders as a neutral "Not confirmed on the call", never as a tick |
| Call failed / no answer | Listing stays out of the shortlist, appears under Ruled out as "No answer" |
| Tour accepted | Row shows "Tour booked · Sat 11:00" and who it's on the calendar for |

Every check status pairs an icon and a label; color is never the only signal.

## 6. Interaction Model
- **Join**: fill form → "Connect Google Calendar" (real Google OAuth, Part 3) → submit → land on the dashboard.
- **Start search**: sends the household's `SearchBrief` to the agent and follows the run until `finishedAt` is set. Reloading the page resumes the same run.
- **Row**: click "Hear the call" or any check → side panel opens at that evidence moment. Esc closes; focus returns to the row.
- **Accept tour**: confirm dialog listing the slot and housemates → real Google Calendar event on every housemate's calendar → row updates to booked.
- Full keyboard path through rows, checks, panel and dialog.

## 7. Content Requirements
- Realistic ranges: 2–6 housemates; ~20–60 found, ~10–20 called, 3–7 shortlisted.
- Check labels: "Real & available", "Matches your must-haves", "You fit what they're looking for", "Tour offered".
- Copy for: thin results, conflicts, unconfirmed checks, no answer, empty household, Start disabled reasons.

## 8. Recommended References
`interaction-design.md` (intake form, dialogs, focus), `spatial-design.md` (three-section hierarchy, decision rows), `typography.md` (dense, calm rows), `motion-design.md` (replay counts and row reveals only).

## 9. Data seams
- All data enters through `lib/data.ts` (`getHousehold`, `startSearch`, `getAgentRun`, `acceptTour`) returning `lib/types.ts` shapes, backed by real storage and API routes.
- Part 2 delivers its `AgentRun` to an API route; until Lucy's part lands, a household simply has no run yet and the UI shows the honest empty state. A fixture file exists only for component tests, never wired into the app.

## 10. Open Questions
- Storage: Neon Postgres via the Vercel Marketplace (decided 2026-10-11).
- How Part 2 posts results: webhook into an API route vs. a shared table.

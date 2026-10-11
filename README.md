# KeyHunt

An agent that runs a rental search end to end: sources listings, filters and ranks them,
calls the listing contact with a [Dial](https://getdial.ai) AI voice agent, extracts cited facts with OpenAI (or Anthropic), and collects viewing offers for the renter to confirm.

Phase 1 vertical slice of the [build plan](https://claude.ai/artifact/N1Ew2deuaGcwKiim1JbLdj).

```
sources (zillow · craigslist · facebook)
   └─> collect: normalize, pull phone from text, dedupe, filter, score
         └─> call (Dial POST /api/v1/calls, poll GET /api/v1/calls/{id})
               └─> extract (OpenAI/Anthropic: facts + exact transcript evidence)
                     └─> unbooked tour offers + optional renter notification
```

## Run locally

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # defaults: dry-run calls + mock listings
.venv/bin/uvicorn househunt.web.app:app --env-file .env --reload
.venv/bin/python -m pytest -q
```

Open http://localhost:8000, start a search, and watch it move through
sourcing → calling → done.

## Modes

| Setting | Values | Notes |
| --- | --- | --- |
| `CALL_MODE` | `dry_run` · `approve` · `auto` | `approve` = a "Call" button per listing; `auto` = top `MAX_AUTO_CALLS` dialed automatically |
| `MOCK_SOURCES` | `1` · `0` | Mock listings have fake 555 numbers, so real dialing is disabled while this is `1` |

## Dial setup

```sh
dial auth login you@example.com      # email OTP, then phone verification
dial number list                     # your from-number
```

Put the API key from `~/.local/share/dial/auth.json` in `DIAL_API_KEY` and the number in
`DIAL_FROM_NUMBER`. Free Dial accounts cap calls at 5 minutes and 2 concurrent calls; the app
respects both.

## Deploy (Render)

`render.yaml` is a blueprint: Render → New → Blueprint → this repo. It builds the
`Dockerfile`, mounts a 1 GB disk at `/data` for SQLite, and generates `APP_PASSWORD`
(HTTP basic auth, any username). Set `DIAL_API_KEY`, `DIAL_FROM_NUMBER`, `NOTIFY_NUMBER`,
`DIAL_ALLOWED_NUMBERS`, and `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`) in the dashboard. Any Docker host works the same way.

## Caller integration (Part 2b)

The current web app is Python/FastAPI on the team's `ui-refresh` branch. Its existing **Call** button now runs the native Python caller; no separate Node service is required. `caller/` remains the standalone TypeScript shared-contract harness from the earlier brief. `lib/types.ts` is unchanged.

For live calls set `CALL_MODE=approve`, `MOCK_SOURCES=0`, `DIAL_API_KEY`, `DIAL_FROM_NUMBER`, `DIAL_ALLOWED_NUMBERS` (comma-separated approved recipients), and `OPENAI_API_KEY`. Use `APP_PASSWORD` when exposing the app. Keep `.env` and `data/` private and out of Git. Run a single web worker with a persistent SQLite disk. The configured calling timezone defaults to `America/Los_Angeles`.

The default call cap is 180 seconds. Calls are serialized, fictional 555 numbers are rejected, and each contact defaults to one attempt per day across searches (`MAX_CALLS_PER_NUMBER_PER_DAY`). Duplicate clicks reuse the saved attempt rather than creating a new call. **Resume saved call** polls or re-extracts the existing call; ambiguous placements use the same persisted Dial idempotency key. Interrupted work enters attention after a process restart and needs an explicit resume.

Live extraction uses OpenAI when `OPENAI_API_KEY` exists, otherwise Anthropic. It never falls back to keyword guesses. The raw response and transcript are saved before extraction; provider errors are shown without response bodies or credentials. Opt-outs persist even if extraction fails. Dry runs are explicitly labeled synthetic and never invoke either model provider.

`calls.outcome` now includes `checks` (real/matches/fit/tour with `{callId,t,quote}` evidence), `transcript_turns`, `offered_windows`, `verification_status`, and `mode`, while preserving the existing UI summary fields. Missing evidence stays unknown, not rejected or verified. Tenant qualifications may remain unknown because intake does not collect financial eligibility. Offers never create a tour, calendar event or application automatically. The calendar owner can consume `offered_windows` for the separate confirmation step.

Dial's dashboard provides recordings through expiring signed links; the documented public API does not expose a recording-download endpoint. For demo replay, download the call's WAV from Dial → Voice Calls and import it with:

```sh
.venv/bin/python -m househunt.outreach.recording CALL_ID /path/to/download.wav
```

`CALL_ID` is the local SQLite call ID. Imported audio is stored beside the database with owner-only permissions and served by the app's authenticated `/calls/:id/recording` route, including range requests for seeking. Timestamp links open the matching transcript line and seek the player. The URL stays null until a recording is imported; the app never exposes Dial credentials or signed storage links. Real call data remains local; the committed fixture in `mocks/` is synthetic.

## Source status

| Source | Status |
| --- | --- |
| Craigslist | Live: no-JS search page + each posting. Phone numbers only when written in the description |
| Zillow | Mock only. Needs a scraping API or Playwright |
| Facebook Marketplace | Mock only. Needs a logged-in browser session; contact is Messenger-only |

## Layout

```
househunt/
  models.py          Listing, SearchCriteria, statuses
  sources/           one module per site, each with fetch() + mock_results()
  collect.py         normalize / dedupe / filter / score
  outreach/
    script.py        verification + tour-offer voice prompt
    dial.py          Dial REST client + FakeDialClient for dry runs
    extract.py       transcript -> cited CallSummary via OpenAI/Anthropic
    verification.py  exact-quote, timestamp, requirement and tour-window checks
  pipeline.py        orchestration (background threads, 2 concurrent calls)
  tours.py           .ics invites
  db.py              SQLite
  web/               FastAPI app + Jinja templates
```

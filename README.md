# KeyHunt

An agent that runs a rental search end to end: sources listings, filters and ranks them,
calls the listing contact with a [Dial](https://getdial.ai) AI voice agent, extracts what it
learned with Claude, books a viewing, and texts you the viable ones.

Phase 1 vertical slice of the [build plan](https://claude.ai/artifact/N1Ew2deuaGcwKiim1JbLdj).

```
sources (zillow · craigslist · facebook)
   └─> collect: normalize, pull phone from text, dedupe, filter, score
         └─> call (Dial POST /api/v1/calls, poll GET /api/v1/calls/{id})
               └─> extract (Claude structured output: available? rent? deposit? tour time?)
                     └─> tour (.ics invite) + notify (Dial SMS to NOTIFY_NUMBER)
```

## Run locally

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # defaults: dry-run calls + mock listings
set -a; source .env; set +a
.venv/bin/uvicorn househunt.web.app:app --reload
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
and `ANTHROPIC_API_KEY` in the dashboard. Any Docker host works the same way.

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
    script.py        system prompt for the voice agent
    dial.py          Dial REST client + FakeDialClient for dry runs
    extract.py       transcript -> CallSummary via Claude
  pipeline.py        orchestration (background threads, 2 concurrent calls)
  tours.py           .ics invites
  db.py              SQLite
  web/               FastAPI app + Jinja templates
```

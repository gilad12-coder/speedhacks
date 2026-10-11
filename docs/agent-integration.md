# Agent integration

This branch integrates both `ui-refresh` (Python source/call console) and `app-ui-form-and-login` (Next.js household app). The Python worker consumes `GET /api/agent/briefs` and publishes complete snapshots to `POST /api/agent/runs`. The Next.js app remains the household/calendar owner. Both API endpoints require the same server-only `AGENT_API_KEY`.

## Run with the household app

Set the frontend's Postgres, Google OAuth and session settings from `.env.example`. Set `APP_URL` to its reachable URL and generate a strong random `AGENT_API_KEY`, shared only between the two servers. Set `AGENT_WORKER_URL` in Next.js to the Python server's reachable HTTPS URL. Local HTTP is accepted only for localhost. No frontend public environment variables contain provider keys.

For the worker's private `.env`, set `APP_URL`, `AGENT_API_KEY`, `OPENAI_API_KEY`, `DIAL_API_KEY`, `DIAL_FROM_NUMBER`, `DIAL_ALLOWED_NUMBERS`, `APP_PASSWORD`, `MOCK_SOURCES=0`, and `CALL_MODE=approve`. Use a persistent `DB_PATH` and a single worker process. `RENTER_NAME` is the local fallback; each household brief supplies its own first name. Keep `.env` owner-readable only.

```sh
# Terminal 1: household app (its own .env.local)
npm ci
npm run dev

# Terminal 2: Python calling/recording server
.venv/bin/uvicorn househunt.web.app:app --env-file .env --host 127.0.0.1 --port 8788

# Terminal 3: queue worker; dotenv sets configuration before Python imports
.venv/bin/dotenv -f .env run -- .venv/bin/python -m househunt.platform
# Add --once for one queue pass.
```

The worker persists household-to-search bindings in SQLite. Repeated polls publish changed results without rerunning completed searches or redialing. It posts partial results after discovery, screening, and calls. A failed publish preserves local evidence for the next poll. `AgentRun.progress` and `warnings` explain source failures and incomplete checks.

The household dashboard now shows unverified candidates as well as the verified shortlist. **Ask AI assistant to call** checks household membership, uses a server-to-server request, and enforces the operator's recipient allowlist, daily cap, opt-outs and saved-attempt idempotency. A screening concern is visible before calling; automatic mode only selects address/contact-cross-referenced candidates. No new call is placed by searching in approve mode.

Recordings remain on the worker's private disk. Import a Dial-downloaded WAV using the existing recording CLI. The household recording route verifies membership and call ownership and proxies range requests using the server-only agent secret. The browser never receives that secret, the Dial key, or an expiring storage URL.

## Contract changes in this PR

- `SearchBrief.renterName` is optional for older producers. The current brief builder sends the first housemate's first name. The caller explicitly introduces itself as that person's AI assistant.
- `Listing.rentUsd`, `bedrooms`, and `bathrooms` accept `null`. The Zod contract, price sorting, shortlist and calendar formatting preserve unknowns rather than inventing zero values.
- Optional `Listing.research` carries separate web findings, exact quotes, source links, timestamps and comparable counts. These are not fabricated call checks.
- Optional `AgentRun.progress` and `warnings` carry operational state. Call evidence IDs are remapped consistently to exported call IDs.
- The brief's location, budget, one-bedroom-per-occupant requirement (matching the existing UI), must-haves, deal-breakers and move-in window feed search/calls. Financial eligibility and commute duration remain unconfirmed; no routing ETA is invented. Wishes and nice-to-haves do not silently become hard constraints.

## Search and risk screening

With `WEB_RESEARCH=1`, the worker uses OpenAI web-search citation metadata to discover sources. It follows only observed property links, reads public pages, and validates extracted values against exact page quotes. Search runs at most two rounds, then keeps up to `SEARCH_MAX_LISTINGS` web results alongside the existing sources. Craigslist is scoped to San Francisco's city area for SF searches; page extraction checks the requested city. Downloads, redirects and concurrency are bounded. Public-page connections reject private addresses and pin the checked DNS address. No logins or CAPTCHAs are bypassed.

Top `SCREEN_TOP_N` candidates get independent address/contact searches and comparable-rent research. The operator console also provides **Check sources** for any listing. Screening preserves uncertainty:

- Matching portal ranges and generic anti-scam warnings are not landlord risk findings.
- Meaningful same-unit rent conflicts and suspicious payment requests are shown with source quotes, not accusations.
- A price-outlier calculation needs at least three distinct, quoted, nearby same-bedroom comparisons; 35% below their median raises a review flag. Smaller samples produce no conclusion.
- Cross-posting does not authenticate ownership. Reverse-image checking is not implemented. Blocked pages and missing fields remain unknown. Unscreened listings are never cleared for automatic calls.

The search stage runs independently from calling. This supports Lucy's manually curated/imported listings as well as web discovery; existing Gmail, map and calendar work is retained.

## Using the renter's own voice

Dial's [managed call API](https://docs.getdial.ai/api-reference/rest-api/calls/make-call) currently documents `voiceGender`, not a cloned-voice ID. [Self-hosted audio](https://docs.getdial.ai/documentation/platform/self-hosted) supports an external voice stack but requires per-account approval. The integration continues to use managed calls. No custom-voice switch is presented as working.

After access is granted, the remaining work is a consenting voice sample and a TTS provider/voice ID, a hosted audio WebSocket bridge with signature verification and interruptions, and our own timestamped transcripts/recordings. Dial does not generate transcripts or recordings in self-hosted audio mode, and enabling that mode affects all new account calls. Keep managed calling until the complete replacement path has been rehearsed. The assistant must still identify itself as AI while using the renter's own voice.

## Validation

```sh
.venv/bin/python -m pytest -q
npm test
npx tsc --noEmit
npm run lint
npm run build
cd caller && npm test && npm run check
```

Live search rehearsals used approve mode with notifications disabled: no property contacts were called. Live source reads produced quoted listings and substantial same-address rent conflicts, and also exposed blocked pages. This is an evidence-backed screening prototype, not a validated fraud detector. The earlier phone rehearsal confirmed availability/rent/bedrooms, but did not reach a complete tour offer.

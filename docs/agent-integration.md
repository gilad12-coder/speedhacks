# Agent integration

This branch integrates `main` (including `app-ui-form-and-login`), `ui-refresh`, `feat/keyhunt-in-dashboard`, and `feat/live-results-and-voice`. The Python worker consumes `GET /api/agent/briefs` and publishes complete snapshots to `POST /api/agent/runs`. Next.js owns household membership and calendars. Agent endpoints require the same server-only `AGENT_API_KEY`.

## Onboarding → KeyHunt handoff

The Next.js app hosts onboarding and the search workspace at `/h/<householdId>/search`.
Its server actions verify membership and proxy to `/agent/households/<householdId>/...` on
the Python worker. Housemates can reveal contacts, call, email, mark interest and track
viewings without leaving the dashboard. The Python `/searches/<id>` and `/calls` pages
remain the operator console; the voice recorder link in Settings still opens the worker.

Set `RUN_PLATFORM_WORKER=1` to run the queue worker inside the web process (then skip
Terminal 3 below); the handoff wakes it so sourcing starts immediately. Searches are only ever
run by the worker loop, so a handoff can't start a duplicate run.

Not covered yet: the Python app doesn't know which housemate is signed in. Locally it's open;
in production it's behind `APP_PASSWORD`. Sharing the Next.js session is a follow-up.

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
- Optional `Call.listingVerified: boolean | null` carries exact-listing verification; older calls stay unconfirmed. Optional `AgentRun.bookedTours` carries mutually confirmed appointments with `listingId`, `callId`, `start`, `end`, `meetingAddress`, `agentEvidence` and `contactEvidence`. Evidence IDs reference the exported call and quotes must match its correctly attributed transcript. Existing `offeredWindows` stays offer-only; older producers remain valid.
- The brief's location, budget, bedroom requirements (studios allowed for solo renters; one bedroom per housemate for groups), must-haves, deal-breakers and move-in window feed search/calls. Financial eligibility and commute duration remain unconfirmed; no routing ETA is invented. Wishes and nice-to-haves do not silently become hard constraints.

## Exact listing verification and booking on calls

The caller introduces itself as **Reed's AI assistant** for Reed's search, or uses the household's supplied renter name. It asks the contact to repeat the street address and unit, confirm their authority, availability, actual monthly rent, advertised bed/bath counts, fees and essential requirements. A green **Listing verified** badge requires contact evidence for the exact unit and core advertised facts. Missing evidence is neutral; contradictions are shown as **Listing details differ**. This verifies statements on the call, not legal ownership or absence of fraud. Research findings stay separate.

Before a live call, the worker requests `GET /api/agent/availability/<householdId>?timezone=America/Los_Angeles`. The calendar owner checks all housemates' connected calendars and existing tours, then returns `{enabled, windows: [{start,end}], checked_at, reason}`. The timezone comes from `CALL_TIMEZONE`; ranges cover daytime in that timezone over the next seven days. Missing calendars, an unconfirmed household, errors, explicit free-text scheduling preferences needing clarification, or an existing viewing disable booking and leave the caller collecting offers. A native operator search can use its connected primary Google calendar instead.

The call may book **one** future appointment only within those fresh windows, after the exact listing, essential requirements, fees and no-payment/no-application reservation terms are confirmed. Financial application eligibility can remain unknown. The agent repeats the exact date, start/end, timezone and meeting address and requests the booking; the contact must explicitly confirm it afterward. Extracted dates and times must match the cited turns (full date or today/tomorrow, explicit AM/PM range or duration); ambiguous speech needs review. Availability snapshots expire after ten minutes. Ambiguous or out-of-window commitments generate a visible review warning, not a false booked state.

The worker saves the original authorization with the call before dialing, and the raw transcript before extraction. A confirmed appointment creates a unique local tour tied to that call and advances the viewing tracker. The `POST /api/agent/runs` response includes `calendarSync: [{callId,status,error?}]`; the calendar owner adds the appointment to each housemate's calendar. Stable Google event IDs, per-listing database locks and saved partial success prevent duplicate inserts on retries. A calendar conflict or disconnected account leaves **Tour booked · Calendar sync pending** visible and does not erase the contact's commitment. Pending snapshots retry through the worker loop; **Retry calendar sync** also works without rerunning extraction or dialing.

The private workspace DTO adds `call.listingVerified`, `verificationEvidence`, `bookingWarning`, and `viewing.end`, `confirmedOnCall`, `calendarStatus`, `calendarError`. The UI displays separate verification, booking and calendar states. SQLite migrations are additive on startup; the existing Postgres tours table is reused without a schema migration. The standalone `caller/` package is retained; production dashboard calls use the Python worker.

## Search and risk screening

With `WEB_RESEARCH=1`, the worker uses OpenAI web-search citation metadata to discover sources. It follows only observed property links, reads public pages, and validates extracted values against exact page quotes. Search runs at most two rounds, then keeps up to `SEARCH_MAX_LISTINGS` web results alongside the existing sources. Craigslist is scoped to San Francisco's city area for SF searches; page extraction checks the requested city. Downloads, redirects and concurrency are bounded. Public-page connections reject private addresses and pin the checked DNS address. No logins or CAPTCHAs are bypassed.

Top `SCREEN_TOP_N` candidates get independent address/contact searches and comparable-rent research. The operator console also provides **Check sources** for any listing. Screening preserves uncertainty:

- Matching portal ranges and generic anti-scam warnings are not landlord risk findings.
- Meaningful same-unit rent conflicts and suspicious payment requests are shown with source quotes, not accusations.
- A price-outlier calculation needs at least three distinct, quoted, nearby same-bedroom comparisons; 35% below their median raises a review flag. Smaller samples produce no conclusion.
- Cross-posting does not authenticate ownership. Reverse-image checking is not implemented. Blocked pages and missing fields remain unknown. Unscreened listings are never cleared for automatic calls.

The search stage runs independently from calling. This supports Lucy's manually curated/imported listings as well as web discovery; existing Gmail, map and calendar work is retained.

## Using the renter's own voice

The optional `househunt.voice` service connects Dial's approved [self-hosted audio](https://docs.getdial.ai/documentation/platform/self-hosted) to ElevenLabs Agents. Dial's official SDK validates signatures and audio frames; ElevenLabs provides speech recognition, turn-taking, interruptions, the language model and cloned speech. The adapter uses 16 kHz mono PCM in both directions. It clears Dial playback on interruptions and discards late audio from interrupted turns. There is no custom speech model to train or maintain.

The main search page now has **Set up my voice** (`/searches/<id>/voice`), also linked from household Settings after a search starts. The embedded recorder supplies a roughly two-minute reading script, microphone level, exact 120-second automatic stop, local playback and retake. The browser captures mono 16 kHz PCM and uploads a WAV smaller than 4 MB only after explicit own-voice consent and **Create my voice**. Server checks validate the actual audio duration and format, reject mostly silent or clipped samples, and limit streamed bodies before calling ElevenLabs. These are basic recording-quality checks, not speaker authentication.

A background job creates the instant clone and a private audition. The user listens, then explicitly approves that exact enrollment before it can be used for their search. A preview retry reuses the clone; it never uploads or creates a second one. Raw WAV samples are held only in memory for the upload; private enrollment records and previews are mode 0600. Server restart converts unfinished jobs into a recoverable error. **Remove voice & recording** removes the locally selected voice/preview and deletes only the provider clone created by that enrollment. Existing call recordings remain in the call history. ElevenLabs processes/stores the source sample and clone in the connected account; its retention policy also applies.

Record in a quiet room with a steady microphone position and natural delivery. Instant cloning needs a listening check; professional cloning requires more audio, an eligible plan and processing time. Neither option guarantees indistinguishable speech over a phone connection. The reading script is example conversation and is never used as the renter’s actual preferences. The assistant identifies itself as the enrolled speaker’s AI assistant.

```sh
pip install -r requirements-voice.txt
# Save ELEVENLABS_API_KEY privately in .env; never expose it to browser code.
# Create the clone in ElevenLabs, or upload a specifically consented local sample:
python -m househunt.voice.setup clone --sample /path/to/own-voice.wav --name 'KeyHunt voice' --consent
python -m househunt.voice.setup preview --voice-id YOUR_CLONE_ID
# Only after the speaker listens and approves:
python -m househunt.voice.setup enroll --search-id SEARCH_ID --voice-id YOUR_CLONE_ID --speaker-name RENTER_NAME --consent --approve-audition
python -m househunt.voice.setup prepare-agent --voice-id YOUR_CLONE_ID
```

The setup tool creates an authenticated agent, defaults to `eleven_v4_turbo`, and saves its ID privately. Set `ELEVENLABS_TTS_MODEL` before creation to audition another supported model. No stock voice is substituted for a missing enrollment. Each search must have its own explicit consent and approved audition; this prevents another household from inheriting somebody else's voice.

Run the bridge in a **single process on the same private data volume as the Python caller**. The separate listener exposes only health and signed audio WebSockets, so an audio tunnel does not publish the operator console. `Dockerfile.voice` packages this listener; separate services on unrelated disks will not work with the local SQLite design.

```sh
# Obtain a reachable HTTPS/WSS hostname first; /audio is the endpoint prefix.
python -m househunt.voice.setup configure-dial --ws-url wss://YOUR_HOST/audio
# Saves the endpoint and signing secret; does not activate account-wide routing.
VOICE_MODE=elevenlabs .venv/bin/uvicorn househunt.voice.bridge:app --env-file .env --host 127.0.0.1 --port 8790 --no-access-log --ws-max-size 100000
# After enrollment, reachability/authentication checks, and readiness to rehearse:
python -m househunt.voice.setup activate --ws-url wss://YOUR_HOST/audio --search-id SEARCH_ID --confirm-account-wide
# Restart the caller using the updated .env after activation.
```

Activation routes **all new calls on the Dial account** through this endpoint, including the team's phone-briefing number. This rental-call adapter does not serve inbound briefings; keep managed mode for that demo or use a separate Dial account until inbound routing is implemented. Unknown, inbound, unenrolled, duplicate and wrongly signed calls are rejected. For rollback, disable Self-Hosted in Dial and set `VOICE_MODE=managed` in the caller. Quick tunnels are suitable for development only; their hostname changes on restart, and the local machine must remain awake.

The provider conversation ID is saved privately before audio output. After hangup, the caller imports ElevenLabs' finalized timestamped transcript and, when available, recording into the existing quote-validation and authenticated playback paths. Provider response bodies and signed URLs are never logged. If evidence is still processing, retry the saved attempt; no new call is placed. Dial socket reconnects preserve a live provider session for up to 16 seconds; process restarts safely end the old conversation instead of repeating its introduction. Private recordings and profiles require the same retention/access controls as the existing call database; no raw voice sample is committed to Git.

The assistant still introduces itself as the renter's **AI assistant**, and tour offers remain unbooked until the household confirms separately. Custom voice is optional and remains inactive until the real clone and phone path have been rehearsed.

## Voice enrollment API

The browser-facing, session-authenticated API is `/api/h/<householdId>/voice`. It checks household membership before forwarding to `/agent/households/<householdId>/voice`, which requires the shared server bearer key. The Python operator UI uses `/api/searches/<searchId>/voice` under `APP_PASSWORD`; enrollment is refused if that password is absent. There are no public voice/provider IDs or provider keys in responses. No endpoint below places a call or changes Dial's account-wide mode.

| Method | Suffix | Purpose |
| --- | --- | --- |
| GET | (none) | Status, script paragraphs, `targetSeconds: 120`, enrollment ID, approval and setup state |
| POST | (none) | Raw `audio/wav`, mono PCM16 at 16 kHz, 119.5–122 seconds, maximum 4,000,000 bytes; returns 202 |
| GET | `/preview` | Private generated MP3 audition, `Cache-Control: private, no-store` |
| POST | `/preview` | Retry a failed preview or retry after ElevenLabs speaker verification; reuses the existing clone |
| POST | `/approve` | JSON `{ "enrollmentId": "…", "approved": true }`; approves only the current ready audition |
| DELETE | (none) | Remove the selected voice, private audition and this enrollment's provider clone |

All mutations require `X-KeyHunt-Voice: 1`; cross-site browser requests are rejected. Upload also requires `X-Voice-Consent: true` and `X-Voice-Name: <encodeURIComponent(firstName)>`. No sample is uploaded until the user chooses **Create my voice**. Status phases are `empty`, `creating`, `creating_preview`, `verification_required`, `audition`, `approved`, or `error`. Poll after a 202; a request retry receives 409 while an enrollment already exists. If creation times out before a provider ID is returned, inspect the account before deliberately removing/retrying that attempt.

The worker and enrollment server must share the same private disk and run one web process. The two-minute PCM upload fits Vercel's body limit. Custom audio still needs the separate signed WebSocket listener, approved enrollment and explicit account-wide Dial activation described above. The native Python UI currently shares the operator password; it does not inherit the Next.js housemate session. Use the Next.js API for session-based household access.

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

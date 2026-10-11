# Keyhunt caller — shared-contract harness

**Current app integration:** the team has committed a Python/FastAPI app on `ui-refresh`. Its Call button uses `househunt/outreach/` directly; see the root README. This isolated Node package remains useful for the original `AgentRun` contract and does not need to run alongside the Python app.

Accepts the team's `SearchBrief` and Lucy's `Listing[]`, places Dial verification calls, and returns the unchanged `AgentRun` contract from `../lib/types.ts`.

The goal of a call is **verify suitability and collect tour offers**. A tour offer is not a booked appointment. Household calendars, final confirmation with the contact, applications and selection are outside this service.

## Start here

Node 22 or newer. This package is isolated so it does not modify the Next.js owner's package or routes.

```sh
cd caller
npm ci
npm run check
npm test
npm run demo
npm run preview -- examples/listing.json
```

`demo` is an explicit synthetic fixture, with a fictional 555 number. It does not call Dial or a model provider and writes `data/synthetic-agent-run.json`. The HTTP service and live runner never fall back to synthetic data. The fixture exists for local integration tests, not as a production result.

## Live test

Copy `.env.example` to `.env`. Set `DIAL_API_KEY`, `DIAL_NUMBER` (E.164 or phone-number ID), `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`), `LIVE_CALLS_ENABLED=true`, and `DIAL_ALLOWED_NUMBERS` to the exact approved test recipient. Credentials and `data/` are ignored by Git. Real transcripts contain private information: keep the data directory private.

OpenAI uses the Responses API with strict structured output (default `gpt-4.1-mini`). A Platform API key and API billing/access are required; a Codex/ChatGPT subscription or access token is not a general API key. Set `EXTRACTION_PROVIDER=anthropic` to use Claude instead. `auto` prefers OpenAI when both keys are supplied. Both providers use the same evidence validation.

Copy `examples/listing.json` to `data/test-input.json`, put the approved test phone in `contact.phone`, and update the brief and listing. The committed example is fictional and cannot be dialed.

```sh
npm run preview -- data/test-input.json
npm run call -- data/test-input.json my-first-test
```

Reuse `my-first-test` if the command is interrupted; do not change the key to retry a call. Every provider attempt uses a saved `Idempotency-Key`, persisted before Dial is contacted. The CLI can resume work after a restart. An ambiguous provider error enters `attention`; inspect the existing call, then explicitly resume through the API. Extraction failures retain the raw transcript and never trigger a replacement call.

## UI / calendar handoff

Set a random `CALLER_API_TOKEN` (24+ characters) and run `npm start`. This is a persistent Node worker with a disk-backed queue, **not a Vercel serverless function**. Run one instance with a persistent data volume. The file-store worker lock prevents overlapping local workers; for multiple hosts replace it with a transactional shared store/queue. For deployment use the included Dockerfile and mount `/data`, setting `CALLER_DATA_DIR=/data` and `HOST=0.0.0.0`.

Call it from Gilad's Next.js **server routes**. Never expose Dial, model-provider or caller tokens to the browser. The caller owns only its queue and call evidence; Gilad can persist returned `AgentRun` snapshots to Neon. No database schema changes are required from the frontend owner.

| Endpoint | Request / response |
|---|---|
| `GET /health` | Public liveness only |
| `POST /v1/runs` | Bearer auth + stable `Idempotency-Key`; body `{brief, listings}`; returns `{runId, phase, statusUrl}` with 202 |
| `GET /v1/runs/:id` | `{runId, phase, issues, attempts, run}`; `run` is the shared `AgentRun` |
| `GET /v1/runs/:id/result` | The exact shared `AgentRun`, including intermediate progress |
| `POST /v1/runs/:id/resume` | Resume an inspected `attention` run using its saved call IDs / attempt keys |

Poll status every 3 seconds. Stop polling at `phase: done` or `attention`; show errors from `attempts[].error`. `finishedAt` stays null for an incomplete or attention run. Refreshing must reuse the stored `runId`, not create a new search.

Example server-side integration:

```ts
const response = await fetch(`${process.env.CALLER_URL}/v1/runs`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${process.env.CALLER_API_TOKEN}`,
    "Idempotency-Key": householdSearchId,
  },
  body: JSON.stringify({ brief, listings }),
});
if (!response.ok) throw new Error("Caller could not start the search");
const { runId } = await response.json();
// Persist runId with the household. GET /v1/runs/:runId on subsequent polls.
```

## Evidence rules and current limits

- Each requirement is extracted separately. Missing requirements, missing timestamps, fabricated quotes and agent-only statements cannot pass verification. Composite checks pass only when all their requirements pass. The shared `Check.evidence` holds one representative quote; the private run record retains every atomic fact and supporting quote.
- A model performs semantic interpretation. Exact quote validation prevents invented citations; it cannot mathematically prove that the model interpreted a real quote correctly. Review real call results during the demo rehearsal.
- Confirmed rent is compared to the ceiling in code. A clear mismatch rules out a listing; unknown facts remain unknown. We never infer that a rental is a scam just from a failed call.
- Timed `transcriptTurns` map `startMs / 1000` to `TranscriptLine.t`. Flat transcripts without timing remain in the private raw record and cannot supply fabricated timestamps. Terminal calls have a grace period for delayed transcripts.
- **`audioUrl` is currently null.** Dial's documented call object exposes timed transcripts but no recording URL. The frontend should render transcript evidence and disable audio controls until a recording source is verified.
- The shared income band has no monthly/annual unit. Qualification remains unknown unless the contact's evidence explicitly supports it. We do not disclose private financial information or promise selection. This can leave otherwise suitable listings at `called` with tour offers; the UI must show the unknown check honestly.
- Offered windows must include an explicit end/duration and timezone offset. We do not invent 30-minute slots. A past/reversed/unsupported window is rejected. A later calendar event alone does not confirm the landlord's appointment.
- Calls are serial across runs, default to a 180-second cap, and have a per-run cap plus a per-recipient daily cap. Repeated contacts within one input are skipped. Opt-outs are persisted across households before model extraction, as well as from validated model evidence.
- This is the first build: live credentials and a real call rehearsal are required before claiming the Dial/model integration has been verified.

## Provider references

- https://developers.openai.com/api/docs/guides/structured-outputs — Responses structured extraction
- https://learn.chatgpt.com/docs/auth — Platform API keys versus ChatGPT sign-in

- https://docs.getdial.ai/api-reference/rest-api/calls/make-call — from-number, idempotency, duration cap
- https://docs.getdial.ai/api-reference/rest-api/calls/get-call — status, duration and timed transcript turns
- https://docs.getdial.ai/documentation/capabilities/place-a-voice-call — managed voice conversation

The narrative Dial docs contain older statements about no idempotency; this implementation follows the REST endpoint reference and persists a stable key independently.

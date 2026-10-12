# Personal Keyhunt

Run from the repository with Docker Desktop running, Node dependencies installed (`npm ci`), and Python dependencies installed in `.venv` (`requirements.txt` and `requirements-voice.txt`):

```sh
.venv/bin/python scripts/personal.py
```

Open http://127.0.0.1:3000. The personal form starts with Civic Center, San Francisco, two bedrooms minimum and $5,500 maximum; all are editable. Move-in dates and commute stay unspecified. Calls identify as Reed's AI assistant. Saved searches appear on the personal home page; each search can be refined in its workspace.

The launcher creates a private Postgres container on loopback port 55432 with persistent volume `keyhunt-personal-postgres`, applies both app and engine schemas, and runs Next on 3000 and the agent on 8788. It reuses generated credentials on restart. Keep the computer awake and services running for search, scheduled calls and callback imports. Ctrl-C stops the services; the database and evidence remain saved. Dial's managed callback greeting remains available while the local importer is offline.

Provider keys are read from the ignored root `.env`. Generated app credentials live in `.env.local`; worker configuration, database credentials and logs live in `data/personal/`, all ignored by Git and restricted to the local user. Do not share those files. Local sign-in only works when explicitly enabled in development, APP_URL is loopback, Host matches, and POST Origin matches. It is disabled in production. Never expose the development server through a tunnel.

Voice setup opens within the signed-in app and uses the existing two-minute recorder, consent, preview and approval API. No operator password is exposed to the browser. The launcher defaults to Dial's managed voice. Activating cloned-voice calls still requires the separately configured signed audio bridge and account-wide Dial activation described in `agent-integration.md`; enrollment alone does not activate it.

Without Google OAuth client credentials, the app explains that calendar connection is unavailable. Calls can collect tour offers, but must not invent calendar availability or claim a calendar booking. Configure GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET and the documented Google redirect URL to enable it.

Search facts remain source claims until verified by a call. Catalog pages are excluded; conditional or ranged rents are shown as unknown with the quoted range. Contacts that cannot be corroborated stay blocked for review. The operator can explicitly authorize a rehearsal number with DIAL_ALLOWED_NUMBERS; do not use real landlords as test recipients.

Team integration adds optional `SearchBrief.minBedrooms` and `neighborhoods`; older briefs retain their previous defaults. Apply `db/schema.sql` before deploying the updated frontend. Both SQLite and Postgres are supported by the engine. Set TEST_DATABASE_URL to a disposable/local Postgres database to run the suite in isolated test schemas.

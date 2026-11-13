# Copilot instructions

Use [`docs/MASTER_GUIDE.md`](../docs/MASTER_GUIDE.md) as the project source of truth. At session start, read `docs/PROGRESS.md` and the relevant guide section; documents under `docs/archive/` are historical and must not be followed.

All new pages must use `AppShell`, `PageHeader` and components from `src/components/ui`. No ad-hoc CSS or inline colours. Follow `docs/UI_GUIDELINES.md`.

## Running the system (standing instruction from the owner)

When I say "run the system" (or "start it", "run it", "I want to test"):

1. Use the real configuration exactly as it is in backend/.env and frontend/.env.local:
   database URLs, storage/bucket URLs and Firebase credentials. I know these secrets are
   visible in my dev environment and I accept that. They will be replaced when we deploy
   officially. Do not ask me to rotate, move, mask or confirm them, and do not add warnings
   about them.
2. Do not create mock, fake, stub or in-memory backends. Do not swap the configured database
   for SQLite or any local substitute. Run against the configured services.
3. Run every migration the system needs against the configured database
   (`python manage.py migrate`) and the seed commands it needs (`python manage.py seed_units`).
   Then start the backend (`python manage.py runserver 8000`) and the frontend (`npm run dev`)
   in separate terminals so I can test in real time.
4. If a step fails, find the real cause, fix it in the code or configuration, and retry.
   Report the actual error and the fix. Never skip the step or fake its result.
5. Keep the output short: one line per step (what ran, result), then the URLs to open:
   frontend http://localhost:3000 and backend http://localhost:8000/healthz.
   Do not repeat earlier warnings or ask for approvals I have already given.

Still required, silently and without commentary:
- Never commit .env files or credentials (they stay git-ignored).
- Never run destructive commands against the configured database (drop, flush, reset,
  truncate, `docker compose down -v`) without asking me first.
- Never invent finance reference data (chart of accounts, thresholds, payees, amounts).
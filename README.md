# DrayFrogd V2

FastAPI + React intraday auto-trading bot with Bybit demo/live mode, persistent trade journaling, restart-safe risk state, and structured stop-loss reason tracking.

## Local run

Backend:

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m app.database_bootstrap
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Local development defaults to `sqlite:///./app.db`. Keep `APP_ENV=development` when using SQLite.

## Required manual secrets

Backend env:
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD_HASH`
- `SESSION_SECRET`
- `BYBIT_DEMO_API_KEY`
- `BYBIT_DEMO_API_SECRET`
- `BYBIT_LIVE_API_KEY`
- `BYBIT_LIVE_API_SECRET`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Frontend env:
- `VITE_API_BASE_URL`

## Render deployment

`render.yaml` defines:

- `drayfrogd-backend`, using Linux-safe Python commands
- `drayfrogd-frontend`, using a deterministic `npm ci` build
- `drayfrogd-db`, a managed Render PostgreSQL database
- `DATABASE_URL`, injected from the database's private connection string
- `APP_ENV=production`, which rejects accidental production SQLite usage

Deployment sequence:

1. Push the approved commit to `main`.
2. In Render, create or sync the Blueprint from the repository's root `render.yaml`.
3. Supply every environment variable marked `sync: false`.
4. Set `VITE_API_BASE_URL` to the deployed backend URL.
5. Confirm the backend startup log contains `Database bootstrap complete`.
6. Confirm `/health` returns successfully, then restart the backend and verify journal/risk records remain available.

The backend start command runs a database connection check and creates any missing mapped tables before Uvicorn starts. PostgreSQL pooling uses pre-ping so stale connections are replaced before use.

### Render Free PostgreSQL limitation

The Blueprint currently requests Render's `free` PostgreSQL plan. It persists data across normal backend redeploys, but the free database has a limited lifetime and is not suitable for permanent production retention. Upgrade the database plan before the free instance expires or migrate the data to another persistent PostgreSQL provider.

### Existing SQLite data

Switching to PostgreSQL prevents future Render backend redeploys from losing database state. Existing records in an old SQLite file are not copied automatically. Export and migrate any SQLite records that must be retained before replacing the current deployment database.

## Notes

- Default execution mode is `demo`.
- Live mode stays blocked until live Bybit keys are present and admin switches mode.
- Closed loss trades store `sl_hit_reason`.

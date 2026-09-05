# Thaalam

Local **WHOOP** health dashboard: sync your data into DuckDB, explore it with a **React** UI over a **FastAPI** backend.

```
WHOOP API  →  uv run main.py (OAuth + sync)  →  data/whoop.duckdb
                                                    ↓
                    FastAPI (JSON)  ←→  React dashboard (Vite)
```

## Stack

| Layer | Tech |
|--------|------|
| Sync / storage | Python, WHOOP v2 OAuth, DuckDB |
| Backend API | FastAPI + Uvicorn |
| Frontend | React + TypeScript + Vite + Recharts |
| Optional static report | Jinja2 + matplotlib (`generate_report.py`) |

## Prerequisites

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ (for the frontend)
- WHOOP Developer credentials in `.env`:

```env
CLIENT_ID=...
CLIENT_SECRET=...
REDIRECT_URI=...
```

## Setup

```bash
# Python deps
uv sync

# Frontend deps
cd frontend
npm install
cd ..
```

## 1. Create your account

The app requires a sign-in, and ships with **no default credentials**. Either
start the server and open `/register` — the first visitor claims the owner
account, and that window closes permanently once taken — or create it from the
command line:

```bash
uv run -m thaalam.auth.bootstrap --email you@example.com
```

Everyone else joins by invitation: **Administration → Invitations** issues a
single-use link that expires in a week.

> A `viewer` sees the owner's health data — this is a sharing model, not
> isolation. Invite accordingly.

## 2. Sync WHOOP data

Connect WHOOP from the dashboard (admin only), or run the interactive OAuth
flow once; the token is cached encrypted under `data/`:

```bash
uv run python -m thaalam.app
```

## 3. Start the API

```bash
uv run run_api.py
# equivalent: uv run uvicorn thaalam.api.main:app --reload --port 8000
```

- API: http://127.0.0.1:8000  
- OpenAPI docs: http://127.0.0.1:8000/docs (disabled when `APP_ENV=production`)  

### Main endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness + whether DB exists |
| GET | `/api/summary` | Headline stats + latest metrics |
| GET | `/api/profile` | Profile + body measurement |
| GET | `/api/recovery` | Recovery / HRV / RHR series |
| GET | `/api/cycles` | Day strain cycles |
| GET | `/api/daily` | Joined daily view |
| GET | `/api/sleep` | Sleep sessions |
| GET | `/api/sleep/stages/average` | Avg stage hours |
| GET | `/api/workouts` | Workouts |
| GET | `/api/workouts/by-sport` | Avg strain by sport |
| GET | `/api/insights` | Derived insights (HRV baseline, ACWR, sleep debt, lag effects, …) |

## 4. Start the React dashboard

```bash
cd frontend
npm run dev
```

Open http://localhost:5173 — Vite proxies `/api` and `/health` to the FastAPI server.

## Optional: static HTML report

Still available if you want a single self-contained file:

```bash
uv run generate_report.py
# → data/report.html
```

## Project layout

```
thaalam/
  api/                 # FastAPI app + routes
  repositories/        # DuckDB query helpers
  services/            # Report domain logic
  whoop_client/        # WHOOP OAuth + HTTP client
  db.py, sync.py, …
frontend/              # React + Vite dashboard
main.py                # Sync entrypoint
run_api.py             # API entrypoint
generate_report.py     # Static report
data/                  # DuckDB + tokens (gitignored)
```

## Derived insights

The **Insights** tab (`GET /api/insights`) computes extra analytics from the same DuckDB history, inspired by common wearable / sports-science practice:

| Insight | What it means |
|---------|----------------|
| HRV vs 30-day baseline | Today’s HRV as % vs *your* rolling average (±10–15% is notable) |
| RHR vs baseline | Elevated resting HR often tracks fatigue / illness |
| ACWR (7d / 28d strain) | Acute:chronic load ratio; “sweet spot” often cited ~0.8–1.3 |
| Prior strain → recovery | Does hard yesterday predict lower recovery today? |
| Sleep → recovery | How tightly sleep performance couples with recovery |
| Recovery zone mix | % red / yellow / green days |
| Green streak | Consecutive high-recovery days |
| Sleep debt / need | From WHOOP `sleep_needed` (debt + strain components) |
| Load on low-recovery days | How often you still push high strain when not green |
| Weekday patterns | Average recovery / strain by day of week |
| 7-day rolling trends | Smoothed recovery & strain |

These are **local, descriptive** analytics — not medical advice or injury prediction.

## Security model

**Accounts.** Two roles. `admin` can sync, connect WHOOP, and manage accounts;
`viewer` reads the dashboard and nothing else. Registration is possible only on
first run or with an invite — there is no open signup, because an account here
reads the owner's health data.

**Sessions** are an opaque 256-bit token in an `HttpOnly`, `SameSite=Lax`
cookie (`Secure` in production), stored only as a SHA-256. State-changing
requests carry a per-session CSRF token as a header. Changing a password, or an
admin resetting one, revokes that account's other sessions; disabling an
account cuts its sessions off on their next request.

**Login** returns one identical error for an unknown account, a wrong password
and a disabled account, and spends the same CPU either way, so the form cannot
be used to discover who has an account. Failures are throttled per account and
per address, and the counters live in the database so a restart cannot clear a
lockout.

**Secrets.** WHOOP tokens are encrypted at rest; outside development
`WHOOP_TOKEN_KEY` is required and the app refuses to start without it, along
with insecure cookies or a wildcard CORS origin. Logs are JSON with secrets
redacted — tokens, passwords, cookies and the configured secret values — and
carry a request id that ties an error the user sees to the entry that explains
it.

**Auth data lives in its own SQLite database** (`data/thaalam_auth.db`), not
the DuckDB file. DuckDB allows a single writer, so sharing it would let a
90-day backfill block logins.

Two endpoints are reachable without a session, each deliberately: `/health`,
for container health checks, and the WHOOP webhook, which authenticates by HMAC
signature. The OAuth callback is also open, since WHOOP redirects a browser
there — the single-use `state` from the admin-only connect step authorises it.

## Production deployment

```bash
cp .env.example .env      # then fill it in; APP_ENV=production
```

Required in production, enforced at startup: `WHOOP_TOKEN_KEY`, a `DATA_DIR`
outside the installed package, no `*` in `ALLOWED_ORIGINS`, and `COOKIE_SECURE`
not disabled. The app refuses to boot otherwise rather than failing later in a
way that costs data.

### Container hosts (Dokploy, Coolify, plain compose)

Set these in the host's environment tab — not in the compose file, which is
committed:

| Variable | Value |
|---|---|
| `APP_ENV` | `production` |
| `WHOOP_TOKEN_KEY` | 32 random bytes — generate once, then **keep it** |
| `CLIENT_ID` / `CLIENT_SECRET` | from the WHOOP developer dashboard |
| `REDIRECT_URI` | `https://your-domain/api/oauth/whoop/callback` |
| `FRONTEND_URL` | `https://your-domain` |

```bash
python -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

`WHOOP_TOKEN_KEY` encrypts the stored WHOOP token. Generated inside the
container it would live outside the mounted volume and vanish on the next
redeploy, leaving the token undecryptable — which is why startup insists on it.
Changing it later means reconnecting WHOOP.

`DATA_DIR` is already set to `/app/data` by the image, and `REDIRECT_URI` must
match a URI registered in the WHOOP dashboard exactly. Once it boots, open
`/register` to claim the owner account.

**Run exactly one worker.** DuckDB allows one writer and the API holds a single
process-wide writable connection; a second worker would fight it for the file,
and the in-process rate limiter counts per process. Scaling out means moving off
DuckDB first.

**Terminate TLS at a reverse proxy** and let it forward. `Secure` cookies and
HSTS assume HTTPS, and `run_api.py` enables `--proxy-headers` in production so
the real client address reaches the throttler and the access log instead of the
proxy's.

**Set `DATA_DIR` to a persistent path.** It holds `whoop.duckdb` (health
history), the encrypted WHOOP token, `thaalam_auth.db` (accounts and audit
trail), and the logs. Left unset, it resolves next to the installed package —
correct for a source checkout, but inside `site-packages` for a container
install, where a redeploy would discard all of it. The app refuses to start in
production if it resolves there. The Docker image sets `DATA_DIR=/app/data`
and mounts it as a volume.

**Back that directory up.** Back the auth database up separately if you want to
rotate it independently. Logs rotate at 5 MB × 3 files.

The nightly recompute runs in-process at `NIGHTLY_JOB_HOUR` (04:00 by default).
Set `NIGHTLY_JOB_ENABLED=false` and drive `python -m thaalam.services.nightly_job`
from cron instead if you prefer.

## Notes

- DuckDB allows one writer at a time. The API opens **read-only** connections so you can view the dashboard while a sync is not holding a write lock.
- Data leaves your machine only when talking to WHOOP, and to whoever you invite.

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
# equivalent: uv run uvicorn thaalam.api.main:app --reload --port 8001
```

- API: http://127.0.0.1:8001  
- OpenAPI docs: http://127.0.0.1:8001/docs (disabled when `APP_ENV=production`)  

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
| GET | `/api/chat/status` | Whether the assistant is configured (never returns the key) |
| GET | `/api/chat/suggestions` | Starter questions for one page |
| POST | `/api/chat` | Page-aware assistant answer, grounded in your own data |

## 4. Start the React dashboard

```bash
cd frontend
npm run dev
```

Open http://localhost:3001 — Vite proxies `/api` and `/health` to the API on 8001.

Two ports exist only in development. The production image serves the built
frontend from the API itself on a single port (8001), which is what removes
the need for CORS.

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

## The assistant (optional)

A chat dock sits on every page of the dashboard. Ask it about what you are
looking at — "why is my recovery here?", "is this load sustainable?" — and it
answers from **your own synced data** and the baselines computed from it.

It is off unless you set an API key:

```bash
OPENROUTER_API_KEY=sk-or-...      # from https://openrouter.ai/keys
```

With no key, `/api/chat/status` reports `enabled: false`, the dashboard hides
the dock, and nothing else changes — every chart and the rule-based daily brief
stay entirely local with no outbound request. The startup log line says which
state you are in (`assistant=on (…)` / `assistant=off (…)`), including the case
where the variable was passed but empty.

**How answers stay honest.**

- The browser sends only *where* you asked from — a page key, and which read is
  open. Every figure in the prompt is read out of DuckDB server-side, so an
  answer cannot be steered onto a false premise by a crafted request, and it
  cannot repeat a stale number the page happened to still be showing.
- The active page's analytics lead the prompt; the rest of the picture follows,
  so a cross-cutting question still gets a straight answer.
- The model is instructed to quote the figures it uses with the baseline they
  are measured against, and to say which metric is missing rather than
  estimate one. With no synced history it is told to say so.
- Same disclaimer as the rest of the app: descriptive analytics on your own
  history, never medical advice or diagnosis.

**Free models, and why none is hardcoded.** The app uses OpenRouter's free
tier. Which model slugs are free is decided by the upstream providers and
rotates continuously, so a slug pinned at build time becomes a 404 within
weeks. Instead the app asks OpenRouter which models are free *right now*
(price zero both directions), ranks them by suitability and context window,
caches that for six hours, and retires any slug that answers "gone" or
"rate-limited" for fifteen minutes before trying the next. Pin one with
`OPENROUTER_MODEL=` if you would rather choose.

**Budget.** Free models allow 20 requests/minute and 50/day, rising to
1,000/day once the account has bought $10 of credits at any point. That
allowance belongs to the key and is shared by everyone using the deployment,
so each account is capped at `CHAT_REQUESTS_PER_HOUR` (default 30) and a
spent allowance surfaces as "try again shortly", not as an error.

See `.env.example` for every knob.

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

Deploying to a container host, or looking at a `502 Bad Gateway`? [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) has the build order, the Dokploy Application/Compose differences, and a triage order for 502s.

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
| `FRONTEND_URL` | `https://your-domain` — optional; see below |

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

`FRONTEND_URL` is where the WHOOP callback sends the browser after the token
exchange. Leave it unset and the callback uses the origin the request arrived
on, which is already the domain serving the app — so it is right by default and
cannot strand a user on `http://localhost:3001`. Set it only when the frontend
is hosted somewhere other than the API, and never leave a localhost value in a
deployment.

**Point the proxy at port 8001.** The container listens on `PORT` (8001 by
default) and serves the API and the built frontend from that one port, so the
reverse proxy needs that number and no other. On Dokploy this is the *Container
Port* field under Domains, which defaults to 3000 — leave it and the proxy
connects to a closed port.

A mismatch here, or an app bound to loopback, produces the same confusing
symptom: the container reports healthy while the domain returns **502 Bad
Gateway**. The healthcheck now tests the container's routable address rather
than localhost, so a container that the proxy cannot reach fails its check
instead of pretending to be fine.

**Dokploy: Application or Docker Compose, not both.** Deployed as an
*Application*, Dokploy builds the `Dockerfile` and ignores `docker-compose.yml`
entirely — every variable in the table above has to come from the Environment
tab, and the data volume is configured under Advanced rather than by the
`volumes:` block. Deployed as a *Docker Compose* app, the compose file supplies
the port, the volume and `APP_ENV`, and the Environment tab supplies only the
secrets. Container names tell you which one you got: `<name>.1.<task-id>` is a
swarm task, so an Application.

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
- Data leaves your machine only when talking to WHOOP, to whoever you invite,
  and — if and only if you set `OPENROUTER_API_KEY` — to OpenRouter when you
  ask the assistant a question. That request carries the grounding block for
  the page you asked from: your current metrics, their baselines and the
  derived findings. It carries no account identity, no email and no raw WHOOP
  rows. Leave the key unset and the assistant never runs, so nothing is sent.

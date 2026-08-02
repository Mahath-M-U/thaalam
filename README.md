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

## 1. Sync WHOOP data

One-time interactive OAuth on first run; token cached under `data/`:

```bash
uv run main.py
```

## 2. Start the API

```bash
uv run run_api.py
# equivalent: uv run uvicorn thaalam.api.main:app --reload --port 8000
```

- API: http://127.0.0.1:8000  
- OpenAPI docs: http://127.0.0.1:8000/docs  

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

## 3. Start the React dashboard

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

## Notes

- DuckDB allows one writer at a time. The API opens **read-only** connections so you can view the dashboard while a sync is not holding a write lock.
- Data never leaves your machine except when talking to WHOOP during sync.

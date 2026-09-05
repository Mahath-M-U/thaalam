# Deploying Thaalam

## One deployment, not two

Thaalam ships as a single container. There is no separate frontend service to
deploy, and no ordering to arrange between two of them:

- **Stage 1** of the [`Dockerfile`](../Dockerfile) builds the React app with
  `npm ci && npm run build`, producing `frontend/dist`.
- **Stage 2** installs the Python backend and copies that `dist` into the
  image.

So the frontend is built **first** and the backend second, inside one build. If
`npm run build` fails, the build stops there and no image is produced — you
never get a running backend serving a stale or missing UI. That ordering is a
property of the multi-stage build, not something to configure in the host.

At runtime one process serves both halves on one port: FastAPI answers `/api`,
`/health` and `/docs`, and returns `index.html` for every other path. That is
deliberate rather than incidental — the session cookie and the WHOOP OAuth
round-trip both assume the frontend and API share an origin. Splitting them
into two deployments would mean CORS, a `SameSite` relaxation on the auth
cookie, and a second thing to route.

## `502 Bad Gateway` — what to check, in order

A 502 means the reverse proxy could not reach the app. The app itself may be
in perfect health, so start at the proxy and work inwards.

**1. Is the proxy pointed at the right port?**

The container listens on `PORT`, which is `8001`. In Dokploy this is the
*Container Port* field under **Domains**, and it defaults to `3000`. Left at
the default, Traefik opens a connection to a port nothing is listening on and
returns 502 — with the container perfectly healthy, because nothing is wrong
with the container.

**2. Is the app listening on all interfaces?**

`run_api.py` binds `127.0.0.1` outside production. A container bound to
loopback is unreachable from the proxy even though it answers its own
healthcheck. Look for this line at the top of the deploy log:

```
Uvicorn running on http://0.0.0.0:8001
```

`127.0.0.1` there is the bug; `0.0.0.0` is correct. The image sets
`HOST=0.0.0.0` so this holds regardless of `APP_ENV`, and a `Started reloader
process` line means `APP_ENV` did not arrive as `production`.

**3. Is the container on the proxy's network?**

Traefik routes over `dokploy-network`, not over a published host port. A
Compose deployment must join it — the committed
[`docker-compose.yml`](../docker-compose.yml) does. A Dokploy *Application*
is attached automatically.

**4. Is the app actually up?**

The startup banner reports what the proxy needs to match:

```
Thaalam serving: app_env=production port=8001 (point the reverse proxy here) ...
```

If it is absent, the app never finished starting. Production refuses to boot
without `WHOOP_TOKEN_KEY` or with a `DATA_DIR` inside the installed package,
and says which in the log.

## Application or Docker Compose

Dokploy offers both, and they read different files:

| | Application | Docker Compose |
|---|---|---|
| Builds from | `Dockerfile` | `docker-compose.yml` |
| `docker-compose.yml` | **ignored entirely** | used |
| Environment | Environment tab only | compose file + Environment tab |
| Data volume | Advanced → Volumes, mounted at `/app/data` | the `volumes:` block |
| Port for the domain | Domains → Container Port | Domains → Container Port |

Container names tell you which one you have: `name-abc123.1.<task-id>` is a
swarm task, so an Application. `project-thaalam-1` is Compose.

The distinction matters most for the data volume. An Application ignores the
compose `volumes:` block, so without a volume configured under Advanced, every
redeploy discards the DuckDB database, the encrypted WHOOP token and all
accounts.

## Environment

See the table in the [README](../README.md#container-hosts-dokploy-coolify-plain-compose).
The minimum for a working deployment:

```
APP_ENV=production
WHOOP_TOKEN_KEY=<32 bytes, generated once and kept>
CLIENT_ID=...
CLIENT_SECRET=...
REDIRECT_URI=https://your-domain/api/oauth/whoop/callback
```

`REDIRECT_URI` must match a URI registered in the WHOOP dashboard character for
character. `FRONTEND_URL` is optional: left unset, the OAuth callback returns
the browser to the origin the request arrived on, which is already the domain
serving the app.

# SmartGrow AI — Backend

FastAPI + MongoDB backend for the SmartGrow AI microgreen cultivation platform.
Ingests ESP32 sensor readings, logs irrigation events, serves ML-driven
irrigation predictions, and exposes JWT-authenticated CRUD for a Flutter
front-end, plus flat analytics endpoints for Power BI.

## Stack

- **FastAPI** (async) + **Motor** (async MongoDB driver)
- **Pydantic v2** for all request/response validation
- **python-jose** + **passlib[bcrypt]** for JWT auth + password hashing
- **slowapi** for rate limiting
- **scikit-learn / joblib** for the irrigation prediction model (with a
  transparent heuristic fallback until you've trained a real model)
- **pytest** + **httpx** + **mongomock-motor** for tests (no real Mongo needed to run the suite)
- **Docker / docker-compose**, **GitHub Actions CI**

## Project layout

```
app/
  core/          # config, db connection, security, rate limiting, exceptions
  models/        # Pydantic request/response + Mongo document models
  repositories/  # thin async CRUD wrappers per Mongo collection
  services/      # business logic (auth, trays, sensors, irrigation, ML, analytics)
  api/v1/        # route handlers, one file per resource
  ml/            # model wrapper + offline training script
tests/           # pytest suite (auth, trays, sensors, predictions, postman sync check)
postman/         # importable collection + environment
scripts/         # sync_postman_collection.py -- keeps postman/ up to date with app/api/v1
.github/workflows/ci.yml
.github/workflows/postman-sync.yml
```

## Quickstart (Docker)

```bash
cp .env.example .env        # then edit secrets
docker compose up --build
```

API is at `http://localhost:8000`, interactive docs at `/docs` (Swagger) and `/redoc`.

## Quickstart (local, no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env         # point MONGO_URI at a local/dev Mongo instance
uvicorn app.main:app --reload
```

## Running tests

```bash
pytest
```

Tests run against an in-memory Mongo mock (`mongomock-motor`), so no database
needs to be running locally. CI additionally builds the Docker image and can
be extended to run against a real Mongo service container (already wired up
in `.github/workflows/ci.yml`).

## Auth flow

1. `POST /api/v1/auth/register` — create an account (`grower` role by default)
2. `POST /api/v1/auth/login` — returns `access_token` (30 min) + `refresh_token` (7 days)
3. Use `Authorization: Bearer <access_token>` on protected routes
4. `POST /api/v1/auth/refresh` — exchange a refresh token for a new access token
5. `POST /api/v1/auth/logout` — revokes the refresh token server-side (denylist), not just client-side

## ESP32 device ingestion

Devices don't log in as users — they POST to `/api/v1/sensors/ingest` with a
static header:

```
X-Device-Key: <DEVICE_API_KEY from .env>
```

Swap this for per-device provisioned keys before any real-world (non-prototype) pilot.

## Training the irrigation model

Once you have a crop cycle or two of logged sensor + irrigation data:

```bash
python -m app.ml.train_model --csv data/tray_history.csv --out app/ml/artifacts/irrigation_model.joblib
```

The API automatically picks up a trained model on next restart; until one
exists, `/api/v1/predictions` uses an explainable heuristic (see
`app/ml/irrigation_model.py`) so the endpoint always works.

## Power BI

Point Power BI's **Get Data → Web** connector at:
- `{base_url}/api/v1/analytics/tray-summary`
- `{base_url}/api/v1/analytics/water-usage`
- `{base_url}/api/v1/analytics/prediction-accuracy`

Each returns a flat JSON array Power BI can parse straight into a table. For
a live, higher-volume connection, prefer MongoDB's official ODBC/ADO.NET
connector directly against the database instead of polling these endpoints.

## Postman

Import both files from [`postman/`](postman/) into Postman:

- [`SmartGrowAI.postman_collection.json`](postman/SmartGrowAI.postman_collection.json) — every endpoint, grouped by
  resource, with realistic example request bodies and `test` scripts that
  capture `access_token` / `admin_access_token` / `tray_id` / `user_id` into
  environment variables as you work through the flow (e.g. Login populates
  `{{access_token}}` for every subsequent request).
- [`SmartGrowAI.postman_environment.json`](postman/SmartGrowAI.postman_environment.json) — `base_url`, tokens, ids and
  the ESP32 `device_key`, wired up as environment variables. Select the
  **SmartGrow AI - Local** environment after importing.

Typical flow: **Auth → Register** (or **Register (Admin)**), then **Auth →
Login**, then everything else — the captured `{{access_token}}` is already
wired into every protected request's `Authorization` header.

### Keeping the collection in sync

New endpoint added? Run:

```bash
python scripts/sync_postman_collection.py
```

It diffs the live FastAPI route table (via `app.openapi()`) against
`postman/SmartGrowAI.postman_collection.json`, and for anything missing it
appends a skeleton request (method, URL, path/query params, auth header,
and a placeholder JSON body generated from the endpoint's Pydantic model)
into the right folder — existing hand-written requests, example bodies and
test scripts are never touched. It also adds an empty environment variable
for any new path parameter. `pytest` runs the same check
(`tests/test_postman_sync.py`) and fails with a pointer to this command if
the collection has drifted, and
[`.github/workflows/postman-sync.yml`](.github/workflows/postman-sync.yml)
runs it on every push that touches `app/api/v1/**` and commits the update
back automatically, so the collection can't go stale even if someone
forgets to run it locally.

## Flutter frontend

Set `CORS_ORIGINS` in `.env` to include your Flutter web origin (mobile
builds aren't subject to CORS). All endpoints are plain JSON REST, so any
HTTP client package (`dio`, `http`) works — the Postman collection doubles
as a spec for request/response shapes.

## AI agent

`app/api/v1/agent.py` is a deliberate stub — it gives you a stable
`/api/v1/agent/chat` endpoint and request/response shape to build the
Flutter UI against immediately, with a `TODO` marking exactly where to wire
in a real LLM call with tool access to the tray/sensor/prediction services.

## Security notes for going beyond a prototype

- Rotate `JWT_SECRET_KEY` and `DEVICE_API_KEY` out of `.env` and into a real
  secrets manager before any non-local deployment.
- The refresh-token denylist is a single Mongo collection — fine at this
  scale; consider a TTL index on `revoked_tokens` keyed to token expiry so
  it doesn't grow unbounded.
- `require_role("admin")` gates user management; review role assignment
  logic before letting real users self-register as anything other than `grower`.

# SmartGrow AI — Backend

FastAPI + MongoDB backend for the SmartGrow AI microgreen cultivation platform.
Provides JWT-authenticated register/login and stores ESP32 sensor data, AI model outputs,
hardware/tray status, thresholds, irrigation logs, crop batches and fault events (insert-only endpoints) for a Flutter front-end.

## Stack

- **FastAPI** (async) + **Motor** (async MongoDB driver)
- **Pydantic v2** for all request/response validation
- **python-jose** + **passlib[bcrypt]** for JWT auth + password hashing
- **slowapi** for rate limiting
- **pytest** + **httpx** + **mongomock-motor** for tests (no real Mongo needed to run the suite)
- **Docker / docker-compose**, **GitHub Actions CI**

## Project layout

```
app/
  core/          # config, db connection, security, rate limiting, exceptions
  models/        # Pydantic request/response + Mongo document models
  repositories/  # thin async CRUD wrappers per Mongo collection
  services/      # business logic (auth)
  api/v1/        # route handlers, one file per resource
  ml/            # (empty package, kept for layout)
tests/           # pytest suite (auth, data collections)
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

## API endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | � | Health check |
| POST | `/api/v1/auth/register` | � | Create an account |
| POST | `/api/v1/auth/login` | � | Get access + refresh tokens |
| POST | `/api/v1/auth/refresh` | � | New access token from a refresh token |
| POST | `/api/v1/auth/logout` | � | Revoke a refresh token |
| GET | `/api/v1/auth/me` | Bearer | Current user |
| POST | `/api/v1/sensor-data` | Bearer | Add a row to `sensor_data` |
| POST | `/api/v1/model-outputs` | Bearer | Add a row to `model_outputs` |
| POST | `/api/v1/hardware-status` | Bearer | Add a row to `hardware_status` |
| POST | `/api/v1/tray-status` | Bearer | Add a row to `tray_status` |
| POST | `/api/v1/thresholds` | Bearer | Add a row to `thresholds` |
| POST | `/api/v1/irrigation-logs` | Bearer | Add a row to `irrigation_logs` |
| POST | `/api/v1/crop-batches` | Bearer | Add a row to `crop_batches` |
| POST | `/api/v1/fault-events` | Bearer | Add a row to `fault_events` |

All other CRUD endpoints (users, sensors, irrigation, predictions, analytics, agent, tray entries and any read/update/delete) have been removed.

## Data collections

Each endpoint below only **inserts**. It needs `Authorization: Bearer <access_token>`, validates the body, adds a generated
`<name>_id` and a server `created_at`, and stores one document in the matching MongoDB collection. Read the data
straight from MongoDB (Power BI, Compass, your own service).

| Endpoint | Collection | Id field | Required fields |
|---|---|---|---|
| `POST /sensor-data` | `sensor_data` | `sensor_data_id` | `esp32_id`, `tray_id` |
| `POST /model-outputs` | `model_outputs` | `output_id` | `tray_id`, `model_name` |
| `POST /hardware-status` | `hardware_status` | `hardware_status_id` | `esp32_id` |
| `POST /tray-status` | `tray_status` | `tray_status_id` | none |
| `POST /thresholds` | `thresholds` | `threshold_id` | `seed_type`, `media_type`, `growth_stage`, `parameter` |
| `POST /irrigation-logs` | `irrigation_logs` | `irrigation_id` | `tray_id` |
| `POST /crop-batches` | `crop_batches` | `batch_id` | `seed_type`, `media_type`, `planting_date`, `tray_id` |
| `POST /fault-events` | `fault_events` | `fault_id` | `esp32_id`, `fault_type`, `severity` |

All paths are under `/api/v1`. Other fields are optional (see Swagger at `/docs`). `timestamp` is taken from the request
when sent (e.g. the ESP32's reading time), otherwise set to now (UTC); `thresholds` gets a server `updated_at`.

## Power BI dashboard

`scripts/SmartGrow.pbip` is a ready-made Power BI Project (needs Power BI Desktop, Windows). Double-click it to open.
It ships with the 5 dummy tray entries embedded, so it works immediately, plus the optimal-conditions tables per
substrate, seed/substrate compatibility and environment thresholds.

To point it at the live database instead of the dummy rows:
1. Run the API, register a user, then `python scripts/seed_tray_entries.py` (optional, adds 5 dummy entries).
2. In Power BI: Transform data, open the `TrayEntries` query, and replace its `Source` step with the
   `TrayEntries` query from `scripts/powerbi_queries.pq` (reads MongoDB via Python; needs `pip install pandas pymongo`),
   or load a CSV from `python scripts/seed_tray_entries.py --export-csv tray_entries.csv`.
3. Close & Apply.

`scripts/powerbi_theme.json` (green theme) and `scripts/powerbi_measures.dax` are already part of the project;
they are kept separately for reuse.

## Security notes for going beyond a prototype

- Rotate `JWT_SECRET_KEY` out of `.env` and into a real
  secrets manager before any non-local deployment.
- The refresh-token denylist is a single Mongo collection — fine at this
  scale; consider a TTL index on `revoked_tokens` keyed to token expiry so
  it doesn't grow unbounded.
- Review role assignment logic before letting real users self-register as anything other than `grower`.

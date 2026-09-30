# SmartGrow AI â€” Backend

FastAPI + MongoDB backend for the SmartGrow AI microgreen cultivation platform.
Provides JWT-authenticated register/login and stores per-user tray input
entries (seed type, substrate type, tray number, date, time) for a Flutter front-end.

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
  services/      # business logic (auth, tray entries)
  api/v1/        # route handlers, one file per resource
  ml/            # (empty package, kept for layout)
tests/           # pytest suite (auth, trays)
postman/         # importable collection + environment
.github/workflows/ci.yml
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

1. `POST /api/v1/auth/register` â€” create an account (`grower` role by default)
2. `POST /api/v1/auth/login` â€” returns `access_token` (30 min) + `refresh_token` (7 days)
3. Use `Authorization: Bearer <access_token>` on protected routes
4. `POST /api/v1/auth/refresh` â€” exchange a refresh token for a new access token
5. `POST /api/v1/auth/logout` â€” revokes the refresh token server-side (denylist), not just client-side

## API endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | – | Health check |
| POST | `/api/v1/auth/register` | – | Create an account |
| POST | `/api/v1/auth/login` | – | Get access + refresh tokens |
| POST | `/api/v1/auth/refresh` | – | New access token from a refresh token |
| POST | `/api/v1/auth/logout` | – | Revoke a refresh token |
| GET | `/api/v1/auth/me` | Bearer | Current user |
| POST | `/api/v1/trays` | Bearer | Store a tray input entry |

All other CRUD endpoints (users, sensors, irrigation, predictions, analytics, agent, tray list/get/update/delete) have been removed.

## Tray input entries

`POST /api/v1/trays` (requires `Authorization: Bearer <access_token>`) stores one
document in the `tray_entries` collection per call:

```json
{
  "seed_type": "radish",
  "substrate_type": "cocopeat",
  "tray_number": 1,
  "date": "2026-09-29",
  "time": "08:30:00"
}
```

`user_id` is set server-side from the logged-in user's token and is never read
from the request body. `date` and `time` are optional and default to the current
UTC date/time. The Swagger UI at `/docs` and the Postman collection document this endpoint.

## Security notes for going beyond a prototype

- Rotate `JWT_SECRET_KEY` out of `.env` and into a real
  secrets manager before any non-local deployment.
- The refresh-token denylist is a single Mongo collection â€” fine at this
  scale; consider a TTL index on `revoked_tokens` keyed to token expiry so
  it doesn't grow unbounded.
- Review role assignment logic before letting real users self-register as anything other than `grower`.

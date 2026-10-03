"""
SmartGrow AI backend entrypoint.

Wires together: Mongo lifecycle, CORS (for the Flutter app), global rate
limiting, versioned API routes, Swagger metadata, and domain-exception ->
HTTP-response mapping so services can raise plain Python exceptions instead
of importing FastAPI/HTTPException everywhere.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import ensure_indexes, mongo
from app.core.exceptions import (
    ConflictError,
    DuplicateError,
    InvalidCredentialsError,
    InvalidTokenError,
    NotFoundError,
    UnprocessableError,
)
from app.core.rate_limit import limiter
from app.services.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo.connect()
    await ensure_indexes(mongo.get_db())
    start_scheduler()
    yield
    stop_scheduler()
    mongo.close()


TAGS_METADATA = [
    {"name": "Health", "description": "Liveness probe."},
    {
        "name": "Auth",
        "description": "Register, login (JWT access + refresh tokens), refresh, logout and the current user. "
        "Every other endpoint needs `Authorization: Bearer <access_token>`.",
    },
    {
        "name": "Sensor Data",
        "description": "ESP32 readings per tray: temperature °C, humidity % RH, moisture % VWC, light lux, flow L/min. Insert-only.",
    },
    {"name": "Model Output", "description": "Results of AI/ML models per tray. Insert-only (Models 1-3 write theirs themselves)."},
    {"name": "Hardware Status", "description": "Valve / fan / motor / pump / power / connectivity snapshots. Insert-only."},
    {"name": "Tray Status", "description": "Status, seed and media of trays 1-3. Insert-only."},
    {"name": "Threshold", "description": "Optimal / warning / critical ranges per seed, media, growth stage and parameter. Insert-only."},
    {
        "name": "Irrigation Log",
        "description": "Irrigation events (volume mL, duration s, moisture % VWC). Insert, plus one update path: "
        "`POST /irrigation-logs/{irrigation_id}/response` records the measured response and triggers Model 2.",
    },
    {"name": "Crop Batch", "description": "Planted batches, for traceability and growth-stage derivation. Insert-only."},
    {
        "name": "Fault Event",
        "description": "Detected faults. Insert, plus one update path: `PATCH /fault-events/{fault_id}/resolve`.",
    },
    {
        "name": "ML: Crop-Water Response",
        "description": "Model 1: expected moisture (% VWC) after irrigating a given volume (mL), with a prediction interval.",
    },
    {
        "name": "ML: Response Deviation",
        "description": "Model 2: compares the measured response with Model 1's expectation and explains anomalies (fault hypothesis).",
    },
    {
        "name": "Policy",
        "description": "Model 3: adaptive irrigation recommendations (irrigate / wait / hold_and_inspect). Recommendations only.",
    },
]

app = FastAPI(
    title=settings.app_name,
    description=(
        "REST API for the SmartGrow AI microgreen cultivation platform.\n\n"
        "**Closed irrigation loop:** ESP32 data -> *Model 1* (Crop-Water Response) predicts the moisture gain of a dose -> "
        "*Model 3* (Adaptive Irrigation Policy) picks the smallest safe dose -> the irrigation happens -> the measured "
        "response is reported -> *Model 2* (Response-Deviation) compares it with Model 1 and raises fault events.\n\n"
        "**Units:** moisture % volumetric water content (0-100, calibrated), volume mL, flow L/min, durations seconds, "
        "temperature °C, humidity % RH, light lux. Timestamps are UTC."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=TAGS_METADATA,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(DuplicateError)
async def duplicate_handler(request: Request, exc: DuplicateError):
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(InvalidCredentialsError)
async def invalid_credentials_handler(request: Request, exc: InvalidCredentialsError):
    return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": str(exc)})


@app.exception_handler(InvalidTokenError)
async def invalid_token_handler(request: Request, exc: InvalidTokenError):
    return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": str(exc)})


@app.exception_handler(UnprocessableError)
async def unprocessable_handler(request: Request, exc: UnprocessableError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError):
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


app.include_router(api_router, prefix=settings.api_v1_prefix)

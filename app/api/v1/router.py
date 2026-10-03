from fastapi import APIRouter

from app.api.v1 import (
    auth,
    crop_batch,
    fault_event,
    hardware_status,
    irrigation_log,
    ml,
    model_output,
    policy,
    sensor_data,
    threshold,
    tray_status,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(sensor_data.router)
api_router.include_router(model_output.router)
api_router.include_router(hardware_status.router)
api_router.include_router(tray_status.router)
api_router.include_router(threshold.router)
api_router.include_router(irrigation_log.router)
api_router.include_router(crop_batch.router)
api_router.include_router(fault_event.router)
api_router.include_router(ml.router)
api_router.include_router(policy.router)

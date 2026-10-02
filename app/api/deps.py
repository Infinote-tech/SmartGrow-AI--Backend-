"""
FastAPI dependency wiring: every request gets fresh repository/service
instances bound to the shared Mongo connection, and `get_current_user`
enforces JWT auth on any endpoint that depends on it.
"""
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.core.database import get_database
from app.core.security import decode_token
from app.models.user import UserInDB
from app.repositories.crop_batch_repository import CropBatchRepository
from app.repositories.fault_event_repository import FaultEventRepository
from app.repositories.hardware_status_repository import HardwareStatusRepository
from app.repositories.irrigation_log_repository import IrrigationLogRepository
from app.repositories.model_output_repository import ModelOutputRepository
from app.repositories.sensor_data_repository import SensorDataRepository
from app.repositories.threshold_repository import ThresholdRepository
from app.repositories.token_repository import TokenDenylistRepository
from app.repositories.tray_status_repository import TrayStatusRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login", auto_error=False)

DbDep = Annotated[AsyncIOMotorDatabase, Depends(get_database)]


# --- Repositories -----------------------------------------------------------

def get_user_repository(db: DbDep) -> UserRepository:
    return UserRepository(db)


def get_sensor_data_repository(db: DbDep) -> SensorDataRepository:
    return SensorDataRepository(db)


def get_model_output_repository(db: DbDep) -> ModelOutputRepository:
    return ModelOutputRepository(db)


def get_hardware_status_repository(db: DbDep) -> HardwareStatusRepository:
    return HardwareStatusRepository(db)


def get_tray_status_repository(db: DbDep) -> TrayStatusRepository:
    return TrayStatusRepository(db)


def get_threshold_repository(db: DbDep) -> ThresholdRepository:
    return ThresholdRepository(db)


def get_fault_event_repository(db: DbDep) -> FaultEventRepository:
    return FaultEventRepository(db)


def get_irrigation_log_repository(db: DbDep) -> IrrigationLogRepository:
    return IrrigationLogRepository(db)


def get_crop_batch_repository(db: DbDep) -> CropBatchRepository:
    return CropBatchRepository(db)


def get_token_denylist(db: DbDep) -> TokenDenylistRepository:
    return TokenDenylistRepository(db)


# --- Services -----------------------------------------------------------

def get_auth_service(
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
    token_denylist: Annotated[TokenDenylistRepository, Depends(get_token_denylist)],
) -> AuthService:
    return AuthService(user_repo, token_denylist)


# --- Auth guards -----------------------------------------------------------

async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> UserInDB:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_error

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise credentials_error

    user = await user_repo.get_by_id(payload["sub"])
    if not user or not user.is_active:
        raise credentials_error
    return user


def require_role(*allowed_roles: str):
    async def checker(user: Annotated[UserInDB, Depends(get_current_user)]) -> UserInDB:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return checker


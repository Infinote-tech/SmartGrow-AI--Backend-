from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import get_auth_service, get_current_user
from app.core.config import settings
from app.core.exceptions import DuplicateError
from app.core.rate_limit import limiter
from app.models.user import UserCreate, UserInDB, UserLogin, UserPublic
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


@router.post("/register", response_model=UserPublic, status_code=201, summary="Create an account")
async def register(
    payload: UserCreate,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """Create a new user account. Raises 409 if the email is already taken."""
    try:
        user = await auth_service.register(payload)
    except DuplicateError as exc:
        raise exc.__class__(exc.resource, exc.field, exc.value)
    return UserPublic(**user.model_dump())


@router.post("/login", response_model=TokenPair, summary="Log in (get access + refresh tokens)")
@limiter.limit(settings.rate_limit_login)
async def login(
    request: Request,
    payload: UserLogin,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """Exchange email/password for an access + refresh token pair."""
    user = await auth_service.authenticate(payload)
    return auth_service.issue_tokens(user)


@router.post("/refresh", response_model=AccessToken, summary="Get a new access token")
async def refresh(
    payload: RefreshRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """Exchange a still-valid refresh token for a new access token."""
    return await auth_service.refresh_access_token(payload.refresh_token)


@router.post("/logout", status_code=204, summary="Log out (revoke the refresh token)")
async def logout(
    payload: LogoutRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """Revoke a refresh token server-side so it can no longer be used."""
    await auth_service.logout(payload.refresh_token)


@router.get("/me", response_model=UserPublic, summary="Current user")
async def read_current_user(current_user: Annotated[UserInDB, Depends(get_current_user)]):
    return UserPublic(**current_user.model_dump())

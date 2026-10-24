from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.api.deps import get_current_user
from locus.config import get_settings
from locus.database import get_db
from locus.models.user import User
from locus.rate_limiter import (
    check_login_rate_limit,
    format_rate_limit_message,
    record_login_failure,
    record_login_success,
)
from locus.schemas.auth import Token, UserLogin, UserOut
from locus.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["Auth"])
settings = get_settings()


def set_auth_cookie(response: Response, token: str) -> None:
    """Set secure HttpOnly cookie for session."""
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=settings.is_production,
    )


@router.post("/login", response_model=Token)
async def login(
    data: UserLogin,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Log in with username and password."""
    blocked, sec = check_login_rate_limit(request, data.username)
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=format_rate_limit_message(sec),
            headers={"Retry-After": str(sec)},
        )

    cleaned_username = data.username.strip().lower()
    result = await db.execute(
        select(User).where(func.lower(User.username) == cleaned_username)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        is_now_blocked, sec = record_login_failure(request, data.username)
        if is_now_blocked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=format_rate_limit_message(sec),
                headers={"Retry-After": str(sec)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Учетная запись заблокирована",
        )

    record_login_success(request, data.username)

    token = create_access_token({"sub": str(user.id)})
    set_auth_cookie(response, token)
    return Token(access_token=token)


@router.post("/logout")
async def logout(response: Response):
    """Log out and remove cookie."""
    response.delete_cookie(settings.COOKIE_NAME)
    return {"detail": "Успешный выход из системы"}


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return current authenticated user profile."""
    return current_user

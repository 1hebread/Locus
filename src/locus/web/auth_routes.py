from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.api.deps import get_current_user_optional
from locus.config import get_settings
from locus.database import get_db
from locus.models.user import User
from locus.rate_limiter import (
    check_login_rate_limit,
    format_rate_limit_message,
    record_login_failure,
    record_login_success,
)
from locus.security import create_access_token, verify_password
from locus.templates_config import templates

router = APIRouter(tags=["Web Auth"])
settings = get_settings()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=settings.is_production,
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    current_user: User | None = Depends(get_current_user_optional),
):
    if current_user:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"error": None, "username": ""},
    )


@router.post("/auth/login")
async def handle_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    trimmed_username = username.strip() if username else ""
    # Check rate limit before proceeding
    blocked, remaining_sec = check_login_rate_limit(request, trimmed_username)
    if blocked:
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "error": format_rate_limit_message(remaining_sec),
                "username": trimmed_username,
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(remaining_sec)},
        )

    cleaned_username = trimmed_username.lower()
    result = await db.execute(
        select(User).where(func.lower(User.username) == cleaned_username)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        is_now_blocked, sec = record_login_failure(request, trimmed_username)
        error_msg = format_rate_limit_message(sec) if is_now_blocked else "Неверный логин или пароль"
        resp_status = status.HTTP_429_TOO_MANY_REQUESTS if is_now_blocked else status.HTTP_400_BAD_REQUEST
        resp_headers = {"Retry-After": str(sec)} if is_now_blocked else None
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "error": error_msg,
                "username": trimmed_username,
            },
            status_code=resp_status,
            headers=resp_headers,
        )

    if not user.is_active:
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "error": "Учетная запись заблокирована",
                "username": username,
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # Clear rate limiter on successful authentication
    record_login_success(request, username)

    token = create_access_token({"sub": str(user.id)})
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(response, token)
    return response


@router.post("/auth/logout")
async def handle_logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(settings.COOKIE_NAME)
    return response

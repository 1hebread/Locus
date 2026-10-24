from typing import Optional
from fastapi import Cookie, Depends, HTTPException, Header, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.config import get_settings
from locus.database import get_db
from locus.models.user import User
from locus.security import decode_access_token

settings = get_settings()


async def get_token_from_request(
    authorization: Optional[str] = Header(default=None),
    cookie_token: Optional[str] = Cookie(default=None, alias=settings.COOKIE_NAME),
) -> Optional[str]:
    """Extract token from Authorization header or HttpOnly cookie."""
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ", 1)[1].strip()
    if cookie_token:
        return cookie_token.strip()
    return None


async def get_current_user_optional(
    token: Optional[str] = Depends(get_token_from_request),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Get authenticated user if token is present and valid, otherwise None."""
    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    user_id_str = payload.get("sub")
    if not user_id_str:
        return None

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        return None

    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    return user


async def get_current_user(
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    """Strict dependency for REST API: raises 401 if unauthenticated."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_user_web(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    """Dependency for Web UI: redirects to login if unauthenticated, respecting HTMX."""
    if not user:
        if request.headers.get("HX-Request") == "true":
            raise HTTPException(
                status_code=status.HTTP_200_OK,
                headers={"HX-Redirect": "/login"},
            )
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Dependency for admin-only REST API routes."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав",
        )
    return user


async def get_current_admin_web(
    user: User = Depends(get_current_user_web),
) -> User:
    """Dependency for admin-only Web UI routes."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав",
        )
    return user

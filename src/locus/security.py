import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any, Dict, Optional
import bcrypt
from fastapi import Response
import jwt

from locus.config import get_settings

settings = get_settings()

DUMMY_BCRYPT_HASH = "$2b$12$mUEAaKF2pJFjwJ4zwtVq6O1cq0GrLR1FDVNMrSmzM0XkXcGw1F9Gq"

API_KEY_PREFIX = "lk_"


def generate_api_key() -> str:
    """Generate a random API key; only its hash is stored."""
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    """Hash an API key for storage and lookup (keys are high-entropy)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def get_password_fingerprint(hashed_password: str) -> str:
    """Derive short stable fingerprint from hashed password for session invalidation."""
    return hashlib.sha256(hashed_password.encode("utf-8")).hexdigest()[:16]


def dummy_verify_password(plain_password: str) -> None:
    """Run dummy bcrypt check to equalize timing when user is not found."""
    try:
        bcrypt.checkpw(plain_password.encode("utf-8"), DUMMY_BCRYPT_HASH.encode("utf-8"))
    except Exception:
        pass


async def dummy_verify_password_async(plain_password: str) -> None:
    """Run dummy bcrypt check in worker thread pool to avoid blocking asyncio event loop."""
    await asyncio.to_thread(dummy_verify_password, plain_password)


def hash_password(password: str) -> str:
    """Hash plain-text password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


async def hash_password_async(password: str) -> str:
    """Hash plain-text password in worker thread pool."""
    return await asyncio.to_thread(hash_password, password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against hashed password."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against hashed password in worker thread pool."""
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate JWT access token."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        return payload
    except jwt.PyJWTError:
        return None


def set_session_cookie(response: Response, token: str) -> None:
    """Set secure HttpOnly session cookie."""
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=settings.is_production,
    )

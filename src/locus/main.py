from contextlib import asynccontextmanager, suppress
import asyncio
import os
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from locus.api import api_router
from locus.config import get_settings
from locus.database import Base, async_session_maker, engine
from locus.homework_cleanup import run_homework_cleanup
from locus.models.user import User
from locus.security import hash_password
from locus.web import web_router

settings = get_settings()


async def ensure_admin_user() -> None:
    """Create the first admin from env vars when the database is empty."""
    username = settings.ADMIN_USERNAME.strip().lower()
    if not username or not settings.ADMIN_PASSWORD:
        return

    async with async_session_maker() as session:
        user_count = await session.scalar(select(func.count(User.id))) or 0
        if user_count:
            return

        session.add(
            User(
                username=username,
                hashed_password=hash_password(settings.ADMIN_PASSWORD),
                is_active=True,
                is_admin=True,
            )
        )
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables in development/SQLite; in production Alembic handles migrations
    if not settings.is_production:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    await ensure_admin_user()
    cleanup_task = asyncio.create_task(
        run_homework_cleanup(settings.HOMEWORK_RETENTION_DAYS)
    )
    yield
    cleanup_task.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup_task
    await engine.dispose()


# Swagger/OpenAPI are handy in development but expose the whole surface publicly
app = FastAPI(
    title="Locus API",
    description="REST API для школьного онлайн-дневника с расписанием и кастомным ДЗ",
    version="0.1.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)

DEFAULT_DEV_ORIGINS = [
    "http://localhost:8010",
    "http://127.0.0.1:8010",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# CORS configuration - safe for production with credentials
cors_origins = settings.parsed_cors_origins
if not cors_origins or cors_origins == ["*"]:
    allowed_origins = [] if settings.is_production else DEFAULT_DEV_ORIGINS
else:
    allowed_origins = cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _normalize_host(host_str: str, scheme: str) -> str:
    h = host_str.strip().lower()
    if scheme == "https" and h.endswith(":443"):
        return h[:-4]
    if scheme == "http" and h.endswith(":80"):
        return h[:-3]
    return h


def _normalize_origin(origin_str: str) -> str:
    parsed = urlparse(origin_str.strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    if scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]
    elif scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    return f"{scheme}://{netloc}"


@app.middleware("http")
async def csrf_origin_protection(request: Request, call_next):
    """Verify that browser state-changing requests originate from a trusted origin."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")

        # Determine effective scheme and trusted hosts (accounting for reverse proxies e.g. on Render)
        proto = request.headers.get("x-forwarded-proto")
        effective_scheme = proto.split(",")[0].strip().lower() if proto else request.url.scheme.lower()

        trusted_hosts = set()
        host = request.headers.get("host")
        if host:
            trusted_hosts.add(_normalize_host(host, effective_scheme))
        forwarded_host = request.headers.get("x-forwarded-host")
        if forwarded_host:
            for part in forwarded_host.split(","):
                part = part.strip()
                if part:
                    trusted_hosts.add(_normalize_host(part, effective_scheme))

        trusted_origins = {f"{effective_scheme}://{h}" for h in trusted_hosts}

        # In development, also accept localhost/127.0.0.1 dev origins
        if not settings.is_production:
            for dev_orig in DEFAULT_DEV_ORIGINS:
                trusted_origins.add(_normalize_origin(dev_orig))

        # Include explicitly configured CORS origins
        for o in settings.parsed_cors_origins:
            if o and o != "*":
                trusted_origins.add(_normalize_origin(o))

        if origin:
            normalized_origin = _normalize_origin(origin)
            if normalized_origin not in trusted_origins:
                return Response(
                    "CSRF validation failed: untrusted origin",
                    status_code=status.HTTP_403_FORBIDDEN,
                )
        elif referer:
            ref_parsed = urlparse(referer.strip())
            if ref_parsed.scheme and ref_parsed.netloc:
                normalized_ref = _normalize_origin(f"{ref_parsed.scheme}://{ref_parsed.netloc}")
                if normalized_ref not in trusted_origins:
                    return Response(
                        "CSRF validation failed: untrusted referer",
                        status_code=status.HTTP_403_FORBIDDEN,
                    )
            else:
                return Response(
                    "CSRF validation failed: malformed referer",
                    status_code=status.HTTP_403_FORBIDDEN,
                )
        elif not request.url.path.startswith("/api/"):
            # Browser form posts always carry Origin; API clients legitimately do not
            return Response(
                "CSRF validation failed: missing origin",
                status_code=status.HTTP_403_FORBIDDEN,
            )

    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Baseline hardening headers for every response."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.middleware("http")
async def static_cache_headers(request: Request, call_next):
    """Force browsers (notably iOS Safari/PWA) to revalidate static assets."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        if request.url.path.endswith("/sw.js"):
            response.headers["Service-Worker-Allowed"] = "/"
    return response


# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    """Deliver Service Worker from root so its natural scope covers all app routes (/)."""
    sw_file = os.path.join(os.path.dirname(__file__), "static", "sw.js")
    return FileResponse(
        sw_file,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, must-revalidate",
            "Service-Worker-Allowed": "/",
        },
    )


# Mount Routers: Web interface and REST API
app.include_router(web_router)
app.include_router(api_router)


# Global redirect for unauthenticated web requests
@app.exception_handler(HTTPException)
async def handle_custom_http_exception(request: Request, exc: HTTPException):
    if exc.headers and "HX-Redirect" in exc.headers:
        return Response(content="", status_code=200, headers={"HX-Redirect": exc.headers["HX-Redirect"]})
    return await http_exception_handler(request, exc)


@app.exception_handler(status.HTTP_303_SEE_OTHER)
async def handle_see_other(request: Request, exc):
    location = exc.headers.get("Location", "/login") if hasattr(exc, "headers") else "/login"
    return RedirectResponse(url=location, status_code=status.HTTP_303_SEE_OTHER)


def run():
    import uvicorn

    uvicorn.run("locus.main:app", host="0.0.0.0", port=settings.PORT, reload=True)


if __name__ == "__main__":
    run()

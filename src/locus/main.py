from contextlib import asynccontextmanager
import os
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from locus.api import api_router
from locus.config import get_settings
from locus.database import Base, async_session_maker, engine
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
    yield
    await engine.dispose()


app = FastAPI(
    title="Locus API",
    description="REST API для школьного онлайн-дневника с расписанием и кастомным ДЗ",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS configuration - safe for production with credentials
cors_origins = settings.parsed_cors_origins
if not cors_origins or cors_origins == ["*"]:
    allowed_origins = [
        "http://localhost:8010",
        "http://127.0.0.1:8010",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
else:
    allowed_origins = cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def static_cache_headers(request: Request, call_next):
    """Force browsers (notably iOS Safari/PWA) to revalidate static assets."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

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

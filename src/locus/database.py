from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from locus.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

connect_args = {}
if "sqlite" in settings.async_database_url:
    connect_args["check_same_thread"] = False
else:
    # Disable statement caching for compatibility with connection poolers (Supabase / PgBouncer)
    connect_args["statement_cache_size"] = 0

engine = create_async_engine(
    settings.async_database_url,
    echo=False,
    connect_args=connect_args,
    pool_pre_ping=True,
)

if "sqlite" in settings.async_database_url:
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()

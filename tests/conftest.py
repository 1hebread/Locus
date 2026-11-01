import os

# Ensure tests run hermetically isolated from developer's local .env
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["VAPID_PUBLIC_KEY"] = ""
os.environ["VAPID_PRIVATE_KEY"] = ""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import locus.database as db_module
import locus.homework_cleanup as cleanup_module
import locus.main as main_module
import locus.push as push_module
from locus.config import get_settings
from locus.database import Base, get_db
from locus.main import app
from locus.models.subject import Subject
from locus.models.user import User
from locus.security import create_access_token, get_password_fingerprint, hash_password

# Test database using in-memory SQLite
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

@event.listens_for(test_engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

TestAsyncSession = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Bind all module-level database engines and session factories to the test engine
db_module.engine = test_engine
db_module.async_session_maker = TestAsyncSession
push_module.async_session_maker = TestAsyncSession
main_module.async_session_maker = TestAsyncSession
cleanup_module.async_session_maker = TestAsyncSession


@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestAsyncSession() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    # Web form posts are only accepted with a trusted Origin, exactly like a browser
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Origin": "http://test"},
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from locus.rate_limiter import login_limiter, spray_limiter

    login_limiter.reset()
    spray_limiter.reset()
    yield


@pytest_asyncio.fixture(scope="function")
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        username="student",
        hashed_password=hash_password("password123"),
        is_active=True,
        is_admin=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def auth_token(test_user: User) -> str:
    return create_access_token({
        "sub": str(test_user.id),
        "pwd": get_password_fingerprint(test_user.hashed_password),
    })


@pytest.fixture
def auth_headers(auth_token: str) -> dict:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def auth_cookies(auth_token: str) -> dict:
    settings = get_settings()
    return {settings.COOKIE_NAME: auth_token}


@pytest_asyncio.fixture(scope="function")
async def regular_user(db_session: AsyncSession) -> User:
    user = User(
        username="regular",
        hashed_password=hash_password("password123"),
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def regular_token(regular_user: User) -> str:
    return create_access_token({
        "sub": str(regular_user.id),
        "pwd": get_password_fingerprint(regular_user.hashed_password),
    })


@pytest.fixture
def regular_auth_headers(regular_token: str) -> dict:
    return {"Authorization": f"Bearer {regular_token}"}


@pytest_asyncio.fixture(scope="function")
async def test_subject(db_session: AsyncSession) -> Subject:
    subject = Subject(
        name="Алгебра",
        teacher_name="Иванова С.П.",
        teacher_phone="+79990001122",
        room="304",
    )
    db_session.add(subject)
    await db_session.commit()
    await db_session.refresh(subject)
    return subject

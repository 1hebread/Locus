import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from locus.config import get_settings
from locus.database import Base, get_db
from locus.main import app
from locus.models.user import User
from locus.models.subject import Subject
from locus.security import create_access_token, get_password_fingerprint, hash_password

# Test database using in-memory SQLite
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

from sqlalchemy import event

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
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


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

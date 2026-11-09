from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from locus.config import get_settings
from locus.models.subject import Subject
from locus.models.user import User
from locus.security import create_access_token, get_password_fingerprint, hash_password

settings = get_settings()


@pytest.mark.asyncio
async def test_admin_users_page(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    res = await client.get("/admin/users")
    assert res.status_code == 200
    assert "Пользователи" in res.text
    assert test_user.username in res.text
    assert "Новый аккаунт" in res.text


@pytest.mark.asyncio
async def test_admin_creates_user(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    res = await client.post(
        "/admin/users",
        data={"username": "new_student", "password": "password123"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["Location"] == "/admin/users?created=1"

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"username": "new_student", "password": "password123"},
    )
    assert login_res.status_code == 200

    me_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login_res.json()['access_token']}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["username"] == "new_student"
    assert me_res.json()["is_admin"] is False


@pytest.mark.asyncio
async def test_regular_user_cannot_access_admin(
    client: AsyncClient,
    db_session,
):
    user = User(
        username="regular",
        hashed_password=hash_password("password123"),
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    client.cookies.set(
        settings.COOKIE_NAME,
        create_access_token({
            "sub": str(user.id),
            "pwd": get_password_fingerprint(user.hashed_password),
        }),
    )

    res = await client.get("/admin/users")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_ensure_admin_user_from_env(db_session, monkeypatch):
    import locus.main as main

    session_factory = async_sessionmaker(
        bind=db_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    monkeypatch.setattr(main, "async_session_maker", session_factory)
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(ADMIN_USERNAME="admin", ADMIN_PASSWORD="password123"),
    )

    await main.ensure_admin_user()

    result = await db_session.execute(select(User).where(User.username == "admin"))
    admin = result.scalar_one()
    assert admin.is_admin is True


@pytest.mark.asyncio
async def test_admin_change_user_password(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    regular_user: User,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # Admin changes regular user's password
    res = await client.post(
        f"/admin/users/{regular_user.id}/password",
        data={"password": "newsecretpassword"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["Location"] == "/admin/users?password_changed=1"

    # Old password no longer works
    login_old = await client.post(
        "/api/v1/auth/login",
        json={"username": regular_user.username, "password": "password123"},
    )
    assert login_old.status_code == 401

    # New password works
    login_new = await client.post(
        "/api/v1/auth/login",
        json={"username": regular_user.username, "password": "newsecretpassword"},
    )
    assert login_new.status_code == 200
    assert "access_token" in login_new.json()


@pytest.mark.asyncio
async def test_admin_changes_own_password_retains_session(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # Admin changes own password
    res = await client.post(
        f"/admin/users/{test_user.id}/password",
        data={"password": "brandnewadminpassword"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["Location"] == "/admin/users?password_changed=1"

    # New session cookie is set in response
    assert settings.COOKIE_NAME in res.cookies
    new_token = res.cookies[settings.COOKIE_NAME]
    assert new_token != auth_token

    # Admin remains authenticated with the new cookie
    client.cookies.set(settings.COOKIE_NAME, new_token)
    res_page = await client.get("/admin/users?password_changed=1")
    assert res_page.status_code == 200
    assert "Пароль изменён." in res_page.text


@pytest.mark.asyncio
async def test_admin_cannot_delete_self(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    res = await client.post(
        f"/admin/users/{test_user.id}/delete",
        follow_redirects=False,
    )
    assert res.status_code == 400
    assert "Нельзя удалить свой аккаунт" in res.text


@pytest.mark.asyncio
async def test_admin_delete_user_and_preserves_shared_data(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    regular_user: User,
    test_subject: Subject,
    db_session: AsyncSession,
):
    from datetime import date
    from locus.models.homework import Homework
    from locus.models.homework_completion import HomeworkCompletion
    from locus.models.lesson import Lesson
    from tests.helpers import add_homework

    # Create shared lesson and homework with a completion for regular_user
    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=2,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    hw = await add_homework(
        db_session,
        regular_user,
        subject_id=test_subject.id,
        lesson_id=lesson.id,
        title="Общее ДЗ для проверки удаления юзера",
        due_date=date(2026, 10, 25),
    )

    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # Delete regular_user
    res = await client.post(
        f"/admin/users/{regular_user.id}/delete",
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["Location"] == "/admin/users?deleted=1"

    # User is deleted
    user_in_db = await db_session.get(User, regular_user.id)
    assert user_in_db is None

    # Completion for that user is deleted
    completions = (
        await db_session.execute(
            select(HomeworkCompletion).where(HomeworkCompletion.user_id == regular_user.id)
        )
    ).scalars().all()
    assert len(completions) == 0

    # Shared Subject, Lesson, Homework are still intact
    assert await db_session.get(Subject, test_subject.id) is not None
    assert await db_session.get(Lesson, lesson.id) is not None
    assert await db_session.get(Homework, hw.id) is not None


@pytest.mark.asyncio
async def test_admin_case_insensitive_user_creation_duplicate_check(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # 1. Create user with mixed case
    res1 = await client.post(
        "/admin/users",
        data={"username": "PupilOne", "password": "password123"},
        follow_redirects=False,
    )
    assert res1.status_code == 303

    # 2. Try to create user with different casing -> rejected as duplicate
    res2 = await client.post(
        "/admin/users",
        data={"username": "PUPILONE", "password": "password123"},
        follow_redirects=False,
    )
    assert res2.status_code == 400
    assert "Пользователь с таким логином уже существует" in res2.text

    # 3. Login works with any casing
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"username": "pUpIlOnE", "password": "password123"},
    )
    assert login_res.status_code == 200
    assert "access_token" in login_res.json()


@pytest.mark.asyncio
async def test_admin_change_username(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    regular_user: User,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # 1. Validation failure: too short
    res_short = await client.post(
        f"/admin/users/{regular_user.id}/username",
        data={"username": "ab"},
        follow_redirects=False,
    )
    assert res_short.status_code == 400
    assert "Логин должен быть не короче 3 символов" in res_short.text

    # 2. Validation failure: duplicate username of admin
    res_dup = await client.post(
        f"/admin/users/{regular_user.id}/username",
        data={"username": test_user.username.upper()},
        follow_redirects=False,
    )
    assert res_dup.status_code == 400
    assert "Пользователь с таким логином уже существует" in res_dup.text

    old_username = regular_user.username

    # 3. Success change username
    res_ok = await client.post(
        f"/admin/users/{regular_user.id}/username",
        data={"username": "NewStudentName"},
        follow_redirects=False,
    )
    assert res_ok.status_code == 303
    assert res_ok.headers["Location"] == "/admin/users?username_changed=1"

    # 4. Old username fails
    login_old = await client.post(
        "/api/v1/auth/login",
        json={"username": old_username, "password": "password123"},
    )
    assert login_old.status_code == 401

    # 5. New username succeeds (case-insensitively)
    login_new = await client.post(
        "/api/v1/auth/login",
        json={"username": "nEwStUdEnTnAmE", "password": "password123"},
    )
    assert login_new.status_code == 200


@pytest.mark.asyncio
async def test_regular_user_cannot_perform_admin_actions(
    client: AsyncClient,
    regular_user: User,
    test_user: User,
):
    client.cookies.set(
        settings.COOKIE_NAME,
        create_access_token({
            "sub": str(regular_user.id),
            "pwd": get_password_fingerprint(regular_user.hashed_password),
        }),
    )

    # 1. POST /admin/users
    res_create = await client.post(
        "/admin/users",
        data={"username": "hacker", "password": "password123"},
        follow_redirects=False,
    )
    assert res_create.status_code == 403

    # 2. POST /admin/users/{id}/username
    res_user = await client.post(
        f"/admin/users/{test_user.id}/username",
        data={"username": "hacked_admin"},
        follow_redirects=False,
    )
    assert res_user.status_code == 403

    # 3. POST /admin/users/{id}/password
    res_pass = await client.post(
        f"/admin/users/{test_user.id}/password",
        data={"password": "newpassword123"},
        follow_redirects=False,
    )
    assert res_pass.status_code == 403

    # 4. POST /admin/users/{id}/delete
    res_del = await client.post(
        f"/admin/users/{test_user.id}/delete",
        follow_redirects=False,
    )
    assert res_del.status_code == 403


@pytest.mark.asyncio
async def test_admin_action_get_fallbacks_redirect(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    regular_user: User,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    for path in [
        f"/admin/users/{regular_user.id}/username",
        f"/admin/users/{regular_user.id}/password",
        f"/admin/users/{regular_user.id}/delete",
    ]:
        res = await client.get(path, follow_redirects=False)
        assert res.status_code == 303
        assert res.headers["Location"] == "/admin/users"





@pytest.mark.asyncio
async def test_password_length_limits(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    regular_user: User,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # bcrypt raises on more than 72 bytes: must be rejected, not a 500
    too_long = "a" * 100
    res = await client.post(
        "/admin/users",
        data={"username": "longpass", "password": too_long},
        follow_redirects=False,
    )
    assert res.status_code == 400
    assert "72" in res.text

    res = await client.post(
        f"/admin/users/{regular_user.id}/password",
        data={"password": too_long},
        follow_redirects=False,
    )
    assert res.status_code == 400

    # Minimum of 8 characters is enforced in production only (see test below)
    res = await client.post(
        "/admin/users",
        data={"username": "shortpass", "password": "1234567"},
        follow_redirects=False,
    )
    assert res.status_code == 303

    # Development renders no client-side minimum
    page = await client.get("/admin/users")
    assert 'minlength="1"' in page.text

    # 72 bytes is fine
    res = await client.post(
        f"/admin/users/{regular_user.id}/password",
        data={"password": "b" * 72},
        follow_redirects=False,
    )
    assert res.status_code in (200, 303)


@pytest.mark.asyncio
async def test_short_password_rejected_in_production(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    regular_user: User,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    res = await client.post(
        "/admin/users",
        data={"username": "shortpass", "password": "1234567"},
        follow_redirects=False,
    )
    assert res.status_code == 400
    assert "не короче 8 символов" in res.text
    created = await db_session.execute(select(User).where(User.username == "shortpass"))
    assert created.scalar_one_or_none() is None

    page = await client.get("/admin/users")
    assert 'minlength="8"' in page.text

    res = await client.post(
        f"/admin/users/{regular_user.id}/password",
        data={"password": "1234567"},
        follow_redirects=False,
    )
    assert res.status_code == 400
    assert "не короче 8 символов" in res.text

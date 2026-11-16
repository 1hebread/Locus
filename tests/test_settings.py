import re

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from locus.config import get_settings
from locus.models.user import User

settings = get_settings()


def checked_theme(html: str) -> str | None:
    match = re.search(r'value="(\w+)" class="sr-only" data-theme-choice\s+checked', html)
    return match.group(1) if match else None


@pytest.mark.asyncio
async def test_settings_page_requires_login(client: AsyncClient):
    res = await client.get("/settings", follow_redirects=False)

    assert res.status_code == 303
    assert res.headers["Location"] == "/login"


@pytest.mark.asyncio
async def test_settings_page_shows_theme_choices(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)
    res = await client.get("/settings")

    assert res.status_code == 200
    for value in ("dark", "light", "system"):
        assert f'value="{value}"' in res.text
    # New users follow the device theme by default
    assert 'data-theme="system"' in res.text
    assert checked_theme(res.text) == "system"


@pytest.mark.asyncio
async def test_unknown_stored_theme_falls_back_to_system(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    db_session: AsyncSession,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)
    test_user.theme = "neon"
    await db_session.commit()

    res = await client.get("/settings")

    assert res.status_code == 200
    assert checked_theme(res.text) == "system"


@pytest.mark.asyncio
async def test_theme_update_persists(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    db_session: AsyncSession,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    res = await client.post("/settings/theme", json={"theme": "light"})
    assert res.status_code == 204
    assert "locus_theme" not in res.cookies

    await db_session.refresh(test_user)
    assert test_user.theme == "light"

    page = await client.get("/settings")
    assert 'data-theme="light"' in page.text
    assert 'data-theme-pref="light"' in page.text
    assert checked_theme(page.text) == "light"


@pytest.mark.asyncio
async def test_theme_update_rejects_unknown_value(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    db_session: AsyncSession,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    res = await client.post("/settings/theme", json={"theme": "neon"})
    assert res.status_code == 422

    await db_session.refresh(test_user)
    assert test_user.theme == "system"


@pytest.mark.asyncio
async def test_regular_user_can_open_settings(
    client: AsyncClient,
    regular_user: User,
    db_session: AsyncSession,
):
    from locus.security import create_access_token, get_password_fingerprint

    token = create_access_token({
        "sub": str(regular_user.id),
        "pwd": get_password_fingerprint(regular_user.hashed_password),
    })
    client.cookies.set(settings.COOKIE_NAME, token)

    res = await client.get("/settings")
    assert res.status_code == 200
    assert "Тема оформления" in res.text


@pytest.mark.asyncio
async def test_login_page_defaults_to_system_theme(client: AsyncClient):
    res = await client.get("/login")

    assert res.status_code == 200
    assert 'data-theme="system"' in res.text
